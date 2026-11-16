"""Import, storage and loading of geographic datasets; inputs of the 2D mesher (FASE 10.5)."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
from flask import current_app

from app.extensions import db
from app.geodata import readers as rd
from app.geodata.models import GEO_KINDS, GeoDataset

MAX_BYTES = 200 * 1024 * 1024
PREVIEW_PX = 1024


def data_dir() -> Path:
    return Path(current_app.config['DATA_DIR'])


def abs_path(rel: str) -> Path:
    p = (data_dir() / rel).resolve()
    if data_dir().resolve() not in p.parents:
        raise ValueError(f'URI fuera de DATA_DIR: {rel}')
    return p


def _write(rel: str, data: bytes) -> str:
    p = data_dir() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return rel


# ── Import ────────────────────────────────────────────────────────────────────

def parse(kind: str, data: bytes, filename: str, params: dict) -> dict:
    crs = params.get('crs') or None
    if kind in ('coastline', 'zones'):
        d = rd.read_vector(data, filename, crs)
        if kind == 'coastline' and not any(f['geometry'].geom_type in ('Polygon', 'MultiPolygon') for f in d['features']):
            raise rd.GeoReadError('La línea de costa debe darse como polígonos de tierra (el agua es el dominio menos '
                                  'la tierra); este archivo solo tiene líneas o puntos.')
        if kind == 'zones' and not any(f['geometry'].geom_type in ('Polygon', 'MultiPolygon') for f in d['features']):
            raise rd.GeoReadError('Las zonas deben ser polígonos.')
        return d
    if kind == 'bathymetry':
        return rd.read_bathymetry(data, filename, crs, params.get('convention') or 'auto')
    if kind == 'points':
        return rd.read_points(data, filename, crs)
    if kind == 'forcing':
        return rd.read_forcing(data, filename, params.get('time_unit') or 's')
    raise rd.GeoReadError(f'Tipo de dato desconocido «{kind}» ({", ".join(GEO_KINDS)}).')


def _bbox_lonlat(d: dict):
    from app.geodata.crs import WGS84, transform
    if d['kind'] == 'vector':
        from shapely.ops import unary_union
        b = unary_union([f['geometry'] for f in d['features']]).bounds
        return [float(v) for v in b]
    if d['kind'] in ('grid', 'scatter'):
        if d['kind'] == 'grid':
            X, Y = np.meshgrid([d['x'][0], d['x'][-1]], [d['y'][0], d['y'][-1]])
            X, Y = X.ravel(), Y.ravel()
        else:
            X, Y = d['x'], d['y']
        lon, lat = transform(X, Y, d['crs'], WGS84)
        return [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())]
    return None


def _summary(d: dict) -> dict:
    from app.geodata.forcing import summary as fsum
    if d['kind'] == 'vector':
        types = {}
        for f in d['features']:
            types[f['geometry'].geom_type] = types.get(f['geometry'].geom_type, 0) + 1
        keys = sorted({k for f in d['features'] for k in f['props']})
        return {'kind': 'vector', 'n_features': len(d['features']), 'geometry_types': types, 'attributes': keys[:30]}
    if d['kind'] in ('grid', 'scatter'):
        z = np.asarray(d['z'], float)
        out = {'kind': d['kind'], 'crs': d['crs'], 'convention': d.get('convention'),
               'depth_min_m': float(np.nanmin(z)), 'depth_max_m': float(np.nanmax(z)),
               'n_valid': int(np.isfinite(z).sum())}
        if d['kind'] == 'grid':
            out.update(nx=len(d['x']), ny=len(d['y']), dx=float(abs(d['x'][1] - d['x'][0])) if len(d['x']) > 1 else None,
                       dy=float(abs(d['y'][1] - d['y'][0])) if len(d['y']) > 1 else None)
        else:
            out['n_points'] = int(len(z))
        return out
    return fsum(d)


def _normalised_bytes(d: dict) -> tuple[bytes, str]:
    if d['kind'] == 'vector':
        from shapely.geometry import mapping
        fc = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': mapping(f['geometry']),
             'properties': {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                            for k, v in f['props'].items()}} for f in d['features']]}
        return json.dumps(fc).encode(), '.geojson'
    if d['kind'] == 'harmonics':
        return json.dumps(d).encode(), '.json'
    buf = io.BytesIO()
    if d['kind'] == 'series':
        np.savez_compressed(buf, t=d['t'], meta=np.frombuffer(json.dumps({'t0': d['t0'], 'columns': list(d['columns'])})
                                                               .encode(), np.uint8),
                            **{f'c{i}': v for i, v in enumerate(d['columns'].values())})
    else:
        np.savez_compressed(buf, x=d['x'], y=d['y'], z=d['z'],
                            meta=np.frombuffer(json.dumps({'kind': d['kind'], 'crs': d['crs'],
                                                           'convention': d.get('convention')}).encode(), np.uint8))
    return buf.getvalue(), '.npz'


def depth_png(d: dict) -> bytes | None:
    """Colour image of a bathymetry grid (north up, ≤ PREVIEW_PX), transparent where no data / land."""
    if d['kind'] != 'grid':
        return None
    from PIL import Image
    z = np.asarray(d['z'], float)[::-1]                       # rows north → south
    step = max(1, int(np.ceil(max(z.shape) / PREVIEW_PX)))
    z = z[::step, ::step]
    ok = np.isfinite(z) & (z > 0)
    zmax = float(np.nanmax(z[ok])) if ok.any() else 1.0
    t = np.clip(np.sqrt(np.where(ok, z, 0) / zmax), 0, 1)
    shallow, deep = np.array([198, 233, 247]), np.array([8, 48, 107])
    rgb = (shallow[None, None] * (1 - t[..., None]) + deep[None, None] * t[..., None]).astype(np.uint8)
    a = np.where(ok, 200, 0).astype(np.uint8)
    img = Image.fromarray(np.dstack([rgb, a]), 'RGBA')
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def import_dataset(file_storage, kind: str, name: str | None, params: dict, project_id=None) -> tuple[GeoDataset, bool]:
    """Read, validate and store an upload. Returns (dataset, created); the same content with the same kind and
    import options returns the existing row."""
    filename = file_storage.filename or 'datos'
    data = file_storage.read()
    if not data:
        raise rd.GeoReadError('Archivo vacío.')
    if len(data) > MAX_BYTES:
        raise rd.GeoReadError(f'Archivo demasiado grande (> {MAX_BYTES // 2**20} MB).')
    params = {k: v for k, v in (params or {}).items() if v not in (None, '')}
    if kind not in GEO_KINDS:
        raise rd.GeoReadError(f'Tipo de dato desconocido «{kind}» ({", ".join(GEO_KINDS)}).')
    sha = hashlib.sha256(data).hexdigest()
    for ds in GeoDataset.query.filter_by(sha256=sha, kind=kind).all():
        if (ds.params or {}) == params:
            return ds, False
    d = parse(kind, data, filename, params)
    ext = Path(filename).suffix.lower()[:16]
    rel = f'geodata/files/{sha[:2]}/{sha}{ext}'
    if not (data_dir() / rel).exists():
        _write(rel, data)
    ds = GeoDataset(name=(name or Path(filename).stem)[:255], kind=kind, fmt=ext.lstrip('.'),
                    original_filename=filename[:500], file_uri=rel, sha256=sha, size_bytes=len(data), params=params,
                    source_crs=d.get('source_crs') or d.get('crs'), bbox=_bbox_lonlat(d), summary=_summary(d),
                    project_id=project_id)
    db.session.add(ds)
    db.session.flush()
    blob, pext = _normalised_bytes(d)
    ds.processed_uri = _write(f'geodata/{ds.id}/data{pext}', blob)
    png = depth_png(d) if kind == 'bathymetry' else None
    if png:
        ds.preview_uri = _write(f'geodata/{ds.id}/preview.png', png)
        if d['kind'] == 'grid':
            ds.summary = {**ds.summary, 'preview_bounds': ds.bbox}
    db.session.commit()
    return ds, True


# ── Loading ──────────────────────────────────────────────────────────────────

def load(ds: GeoDataset) -> dict:
    """Normalised data of a stored dataset (the form readers return)."""
    blob = abs_path(ds.processed_uri).read_bytes()
    if ds.processed_uri.endswith('.geojson'):
        from shapely.geometry import shape
        fc = json.loads(blob)
        return {'kind': 'vector', 'features': [{'geometry': shape(f['geometry']), 'props': f['properties'] or {}}
                                               for f in fc['features']]}
    if ds.processed_uri.endswith('.json'):
        return json.loads(blob)
    z = np.load(io.BytesIO(blob))
    meta = json.loads(bytes(z['meta']).decode())
    if 't' in z.files:
        return {'kind': 'series', 't': z['t'], 't0': meta['t0'],
                'columns': {name: z[f'c{i}'] for i, name in enumerate(meta['columns'])}}
    return {'kind': meta['kind'], 'x': z['x'], 'y': z['y'], 'z': z['z'], 'crs': meta['crs'],
            'convention': meta.get('convention')}


def geojson(ds: GeoDataset, max_points: int = 5000) -> dict:
    """Map layer: vectors as stored; soundings as (subsampled) points with the depth; grids as their bbox."""
    if ds.processed_uri.endswith('.geojson'):
        return json.loads(abs_path(ds.processed_uri).read_bytes())
    if ds.kind == 'bathymetry':
        d = load(ds)
        if d['kind'] == 'scatter':
            from app.geodata.crs import WGS84, transform
            idx = np.arange(len(d['z']))
            if len(idx) > max_points:
                idx = np.linspace(0, len(idx) - 1, max_points).astype(int)
            lon, lat = transform(d['x'][idx], d['y'][idx], d['crs'], WGS84)
            return {'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [float(a), float(b)]},
                 'properties': {'depth': float(z)}} for a, b, z in zip(lon, lat, d['z'][idx])]}
    if ds.bbox:
        w, s, e, n = ds.bbox
        return {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'bbox': True},
                'geometry': {'type': 'Polygon', 'coordinates': [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}]}
    return {'type': 'FeatureCollection', 'features': []}


def get_datasets(ids, kind: str | None = None) -> list[GeoDataset]:
    import uuid as _uuid
    out = []
    for i in ids or []:
        try:
            ds = db.session.get(GeoDataset, _uuid.UUID(str(i)))
        except ValueError:
            ds = None
        if ds is None:
            raise ValueError(f'Conjunto de datos geográficos {i} inexistente.')
        if kind and ds.kind != kind:
            raise ValueError(f'«{ds.name}» es de tipo {ds.kind}, se esperaba {kind}.')
        out.append(ds)
    return out


def dataset_identity(ds: GeoDataset) -> dict:
    """What the hash of a study sees of a dataset: content + import options (not its id or name)."""
    return {'sha256': ds.sha256, 'kind': ds.kind, 'params': ds.params or {}}


# ── 2D mesh inputs ────────────────────────────────────────────────────────────

def mesh_inputs(spec: dict) -> dict:
    """Resolve a domain_2d spec (dataset ids) into the mesher inputs + the content key."""
    from app.geodata.mesh2d import mesh_key
    from app.geodata.readers import DepthSampler
    land_ds = get_datasets(spec.get('land_datasets'), 'coastline')
    bat_ds = get_datasets(spec.get('bathymetry_datasets'), 'bathymetry')
    zone_ds = get_datasets([spec['zone_dataset']] if spec.get('zone_dataset') else [], 'zones')
    pt_ds = get_datasets(spec.get('points_datasets'), 'points')
    land = [f['geometry'] for ds in land_ds for f in load(ds)['features']
            if f['geometry'].geom_type in ('Polygon', 'MultiPolygon')]
    sampler = DepthSampler([load(ds) for ds in bat_ds]) if bat_ds else None
    zones = [f for ds in zone_ds for f in load(ds)['features'] if f['geometry'].geom_type in ('Polygon', 'MultiPolygon')]
    size = (spec.get('mesh') or {}).get('poi_size')
    pts = [{'label': f['props'].get('name') or f'P{i + 1}', 'lon': f['geometry'].x, 'lat': f['geometry'].y,
            'size': size} for ds in pt_ds for i, f in enumerate(load(ds)['features'])]
    hashes = [f'{role}:{ds.sha256}:{json.dumps(ds.params or {}, sort_keys=True)}'
              for role, group in (('land', land_ds), ('bathy', bat_ds), ('zones', zone_ds), ('points', pt_ds))
              for ds in group]
    return {'land': land, 'depth_sampler': sampler, 'zones': zones, 'points': pts, 'key': mesh_key(spec, hashes)}


def mesh_path(key: str) -> Path:
    return data_dir() / 'geodata' / 'meshes' / f'{key}.npz'


def mesh_json(mesh) -> dict:
    """Mesh for the map: lon/lat nodes (7 decimals ≈ 1 cm), triangles, depth, boundary edges by id, zones."""
    ll = np.round(mesh.lonlat(), 7)
    return {'key': mesh.key, 'nodes': ll.tolist(), 'tris': mesh.tris.tolist(),
            'depth': [None if not np.isfinite(z) else round(float(z), 3) for z in mesh.depth],   # no NaN in JSON
            'zone': mesh.zone.tolist(),
            'boundary': {k: v.tolist() for k, v in mesh.boundary.items()}, 'boundary_info': mesh.boundary_info,
            'zones': mesh.zones, 'stats': mesh.stats}
