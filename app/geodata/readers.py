"""Readers of geographic files → normalised datasets (no GDAL: pyproj, shapely, pyshp, tifffile, h5py, scipy).

Normalised forms (``kind`` of the result):
  vector   {'features': [{'geometry': shapely geometry in lon/lat, 'props': {...}}]}   coastlines (land polygons),
           zones (polygons + attributes, e.g. Manning n), points (discharge / sampling sites)
  grid     {'x': (nx,), 'y': (ny,) increasing, 'z': (ny, nx) depth [m, positive down], 'crs'}   GeoTIFF, NetCDF
  scatter  {'x', 'y', 'z' (depth), 'crs'}                                                    XYZ soundings
  series   {'t': seconds from t0, 't0': ISO or None, 'columns': {name: values}}            tide gauge, wind, river
  harmonics {'constituents': [{'name', 'amplitude' [m], 'phase' [deg]}], 'z0'}             tidal constants
Bathymetry convention: ``depth`` (positive down) or ``elevation`` (negative below the datum, GEBCO); ``auto``
picks elevation when most values are negative. Depth is what is stored.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

import numpy as np

from app.geodata.crs import WGS84, is_geographic, map_geometry, parse_crs, transform

VECTOR_EXT = ('.geojson', '.json', '.kml', '.zip', '.shp')
GRID_EXT = ('.tif', '.tiff', '.nc', '.nc4', '.grd')
XYZ_EXT = ('.xyz', '.csv', '.txt', '.dat')


class GeoReadError(ValueError):
    pass


# ── Vector ────────────────────────────────────────────────────────────────────

def _reproject_geom(geom, src: str):
    if src == WGS84:
        return geom
    return map_geometry(geom, lambda x, y: transform(x, y, src, WGS84))


def read_geojson(data: bytes, crs: str | None = None) -> dict:
    from shapely.geometry import shape
    try:
        obj = json.loads(data.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise GeoReadError(f'GeoJSON inválido: {e}')
    src = crs
    if src is None:
        name = ((obj.get('crs') or {}).get('properties') or {}).get('name')
        src = parse_crs(name) if name else WGS84
    feats = obj.get('features') if obj.get('type') == 'FeatureCollection' else \
        [obj] if obj.get('type') == 'Feature' else [{'type': 'Feature', 'geometry': obj, 'properties': {}}]
    out = []
    for f in feats or []:
        if not f.get('geometry'):
            continue
        try:
            g = shape(f['geometry'])
        except Exception as e:
            raise GeoReadError(f'Geometría GeoJSON inválida: {e}')
        out.append({'geometry': _reproject_geom(g, src), 'props': f.get('properties') or {}})
    if not out:
        raise GeoReadError('El GeoJSON no contiene geometrías.')
    return {'kind': 'vector', 'features': out, 'source_crs': src}


def _kml_coords(text: str) -> list:
    pts = []
    for tok in (text or '').split():
        parts = tok.split(',')
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def read_kml(data: bytes) -> dict:
    """KML Placemarks (Polygon with inner boundaries, LineString, Point, MultiGeometry); always WGS84."""
    from shapely.geometry import LineString, Point, Polygon
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise GeoReadError(f'KML inválido: {e}')

    def local(tag):
        return tag.rsplit('}', 1)[-1]

    out = []
    for pm in root.iter():
        if local(pm.tag) != 'Placemark':
            continue
        props = {}
        for ch in pm:
            if local(ch.tag) in ('name', 'description') and ch.text:
                props[local(ch.tag)] = ch.text.strip()
        for d in pm.iter():
            if local(d.tag) in ('Data', 'SimpleData'):
                val = d.text if local(d.tag) == 'SimpleData' else next(
                    (v.text for v in d if local(v.tag) == 'value'), None)
                if d.get('name'):
                    props[d.get('name')] = val
        for g in pm.iter():
            t = local(g.tag)
            if t == 'Polygon':
                outer, inner = None, []
                for b in g:
                    ring = next((c for c in b.iter() if local(c.tag) == 'coordinates'), None)
                    if ring is None:
                        continue
                    if local(b.tag) == 'outerBoundaryIs':
                        outer = _kml_coords(ring.text)
                    elif local(b.tag) == 'innerBoundaryIs':
                        inner.append(_kml_coords(ring.text))
                if outer and len(outer) >= 3:
                    out.append({'geometry': Polygon(outer, inner), 'props': dict(props)})
            elif t == 'LineString':
                c = next((c for c in g if local(c.tag) == 'coordinates'), None)
                pts = _kml_coords(c.text if c is not None else '')
                if len(pts) >= 2:
                    out.append({'geometry': LineString(pts), 'props': dict(props)})
            elif t == 'Point':
                c = next((c for c in g if local(c.tag) == 'coordinates'), None)
                pts = _kml_coords(c.text if c is not None else '')
                if pts:
                    out.append({'geometry': Point(pts[0]), 'props': dict(props)})
    if not out:
        raise GeoReadError('El KML no contiene Placemarks con geometría.')
    return {'kind': 'vector', 'features': out, 'source_crs': WGS84}


def read_shapefile_zip(data: bytes, crs: str | None = None) -> dict:
    """Zipped shapefile (.shp + .shx + .dbf [+ .prj]); the .prj gives the CRS unless ``crs`` overrides it."""
    import shapefile
    from shapely.geometry import shape
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise GeoReadError('El .zip no es válido.')
    names = {n.lower(): n for n in z.namelist() if not n.endswith('/')}
    shp = next((n for n in names if n.endswith('.shp')), None)
    if not shp:
        raise GeoReadError('El .zip no contiene un .shp.')
    base = shp[:-4]

    def part(ext):
        n = names.get(base + ext)
        return io.BytesIO(z.read(n)) if n else None
    if part('.dbf') is None:
        raise GeoReadError('Al shapefile le falta el .dbf.')
    src = crs
    if src is None:
        prj = part('.prj')
        src = parse_crs(prj.read().decode('latin-1')) if prj else WGS84
    r = shapefile.Reader(shp=part('.shp'), shx=part('.shx'), dbf=part('.dbf'))
    fields = [f[0] for f in r.fields[1:]]
    out = []
    for sr in r.iterShapeRecords():
        gi = sr.shape.__geo_interface__
        if not gi.get('coordinates'):
            continue
        g = shape(gi)
        if not g.is_valid:
            g = g.buffer(0)
        out.append({'geometry': _reproject_geom(g, src), 'props': dict(zip(fields, list(sr.record)))})
    if not out:
        raise GeoReadError('El shapefile no contiene geometrías.')
    return {'kind': 'vector', 'features': out, 'source_crs': src}


def read_vector(data: bytes, filename: str, crs: str | None = None) -> dict:
    ext = '.' + filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext in ('.geojson', '.json'):
        return read_geojson(data, crs)
    if ext == '.kml':
        return read_kml(data)
    if ext == '.zip':
        return read_shapefile_zip(data, crs)
    if ext == '.shp':
        raise GeoReadError('Suba el shapefile comprimido en un .zip con .shp, .shx, .dbf y .prj.')
    raise GeoReadError(f'Formato vectorial no soportado «{ext}» (GeoJSON, KML, shapefile en .zip).')


# ── Bathymetry ────────────────────────────────────────────────────────────────

def _to_depth(z: np.ndarray, convention: str) -> tuple[np.ndarray, str]:
    if convention not in ('auto', 'depth', 'elevation'):
        raise GeoReadError(f'Convención de batimetría desconocida «{convention}» (depth | elevation | auto).')
    if convention == 'auto':
        finite = z[np.isfinite(z)]
        convention = 'elevation' if finite.size and np.mean(finite < 0) > 0.5 else 'depth'
    return (-z if convention == 'elevation' else z), convention


def _regular(y, z, axis):
    """Make a coordinate axis increasing (flip z accordingly)."""
    if len(y) > 1 and y[1] < y[0]:
        return y[::-1], np.flip(z, axis=axis)
    return y, z


def read_geotiff(data: bytes, crs: str | None = None) -> dict:
    import tifffile
    try:
        tf = tifffile.TiffFile(io.BytesIO(data))
    except Exception as e:
        raise GeoReadError(f'GeoTIFF ilegible: {e}')
    with tf:
        page = tf.pages[0]
        z = page.asarray().astype(float)
        if z.ndim == 3:
            z = z[..., 0] if z.shape[-1] < z.shape[0] else z[0]
        tags = {t.code: t.value for t in page.tags.values()}
    scale, tie = tags.get(33550), tags.get(33922)
    if scale is None or tie is None:
        if 34264 in tags:
            raise GeoReadError('GeoTIFF con matriz de transformación (rotado): no soportado; exporte sin rotación.')
        raise GeoReadError('El TIFF no tiene georreferencia (ModelPixelScale / ModelTiepoint).')
    keys = {}
    gk = tags.get(34735)
    if gk is not None:
        gk = list(gk)
        for i in range(gk[3]):
            k, loc, cnt, val = gk[4 + 4 * i: 8 + 4 * i]
            if loc == 0:
                keys[k] = val
    src = crs or (f'EPSG:{keys[3072]}' if keys.get(3072) not in (None, 32767) else
                  f'EPSG:{keys[2048]}' if keys.get(2048) not in (None, 32767) else None)
    if src is None:
        raise GeoReadError('El GeoTIFF no declara su sistema de coordenadas: indíquelo (p. ej. EPSG:4326).')
    sx, sy = float(scale[0]), float(scale[1])
    i0, j0, x0, y0 = float(tie[0]), float(tie[1]), float(tie[3]), float(tie[4])
    ny, nx = z.shape
    half = 0.5 if keys.get(1025, 1) == 1 else 0.0           # PixelIsArea: tie point at the pixel corner
    x = x0 + (np.arange(nx) - i0 + half) * sx
    y = y0 - (np.arange(ny) - j0 + half) * sy                # rows go down
    nod = tags.get(42113)
    if nod is not None:
        try:
            z[z == float(str(nod).strip('\x00'))] = np.nan
        except ValueError:
            pass
    y, z = _regular(y, z, 0)
    return {'kind': 'grid', 'x': x, 'y': y, 'z': z, 'crs': parse_crs(src)}


_LON = ('lon', 'longitude', 'x', 'nav_lon')
_LAT = ('lat', 'latitude', 'y', 'nav_lat')
_Z = ('elevation', 'z', 'depth', 'bathymetry', 'band1', 'topo', 'height')


def _pick(names, options):
    low = {n.lower(): n for n in names}
    return next((low[o] for o in options if o in low), None)


def read_netcdf(data: bytes, crs: str | None = None) -> dict:
    """NetCDF-4 (HDF5, via h5py) or classic (scipy): 1-D lon/lat (or x/y) axes + a 2-D variable (GEBCO style)."""
    if data[:4] == b'\x89HDF':
        import h5py
        f = h5py.File(io.BytesIO(data), 'r')
        names = [k for k in f.keys() if isinstance(f[k], h5py.Dataset)]

        def get(n):
            ds = f[n]
            a = ds[...].astype(float)
            fill = ds.attrs.get('_FillValue')
            if fill is not None:
                a[a == float(np.ravel(fill)[0])] = np.nan
            return a
    elif data[:3] == b'CDF':
        from scipy.io import netcdf_file
        f = netcdf_file(io.BytesIO(data), 'r', mmap=False)
        names = list(f.variables)

        def get(n):
            v = f.variables[n]
            a = np.array(v.data, dtype=float)
            fill = getattr(v, '_FillValue', None)
            if fill is not None:
                a[a == float(fill)] = np.nan
            return a
    else:
        raise GeoReadError('Archivo NetCDF no reconocido (ni NetCDF-4/HDF5 ni NetCDF clásico).')
    nx_, ny_, nz_ = _pick(names, _LON), _pick(names, _LAT), _pick(names, _Z)
    if not (nx_ and ny_ and nz_):
        raise GeoReadError(f'NetCDF sin ejes lon/lat (o x/y) y variable de elevación; variables: {", ".join(names)}.')
    x, y, z = get(nx_), get(ny_), get(nz_)
    if x.ndim != 1 or y.ndim != 1 or z.ndim != 2:
        raise GeoReadError('NetCDF: se esperan ejes 1-D y una variable 2-D (rejilla regular).')
    if z.shape == (len(x), len(y)):
        z = z.T
    if z.shape != (len(y), len(x)):
        raise GeoReadError(f'NetCDF: la variable {nz_} tiene forma {z.shape}, ejes {len(y)}×{len(x)}.')
    y, z = _regular(y, z, 0)
    x, z = _regular(x, z, 1)
    src = crs or (WGS84 if nx_.lower() in ('lon', 'longitude', 'nav_lon') else None)
    if src is None:
        raise GeoReadError('NetCDF con ejes x/y: indique su sistema de coordenadas (EPSG).')
    return {'kind': 'grid', 'x': x, 'y': y, 'z': z, 'crs': parse_crs(src), 'variable': nz_}


def read_xyz(data: bytes, crs: str | None = None) -> dict:
    """Soundings: three numeric columns x y z (whitespace, comma or semicolon; header lines skipped)."""
    rows = []
    for line in data.decode('utf-8-sig', errors='replace').splitlines():
        parts = [p for p in re.split(r'[\s,;]+', line.strip()) if p]
        if len(parts) < 3:
            continue
        try:
            rows.append([float(p) for p in parts[:3]])
        except ValueError:
            continue
    if len(rows) < 3:
        raise GeoReadError('XYZ: se necesitan al menos 3 filas numéricas x y z.')
    a = np.asarray(rows)
    if crs is None:
        if np.all(np.abs(a[:, 0]) <= 180) and np.all(np.abs(a[:, 1]) <= 90):
            crs = WGS84
        else:
            raise GeoReadError('XYZ en coordenadas proyectadas: indique su sistema de coordenadas (EPSG).')
    return {'kind': 'scatter', 'x': a[:, 0], 'y': a[:, 1], 'z': a[:, 2], 'crs': parse_crs(crs)}


def read_bathymetry(data: bytes, filename: str, crs: str | None = None, convention: str = 'auto') -> dict:
    ext = '.' + filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext in ('.tif', '.tiff'):
        d = read_geotiff(data, crs)
    elif ext in ('.nc', '.nc4', '.grd'):
        d = read_netcdf(data, crs)
    elif ext in XYZ_EXT:
        d = read_xyz(data, crs)
    else:
        raise GeoReadError(f'Formato de batimetría no soportado «{ext}» (GeoTIFF, NetCDF, XYZ).')
    d['z'], d['convention'] = _to_depth(np.asarray(d['z'], float), convention)
    if not np.isfinite(d['z']).any():
        raise GeoReadError('La batimetría no tiene valores válidos.')
    return d


# ── Points and forcings ───────────────────────────────────────────────────────

def read_points(data: bytes, filename: str, crs: str | None = None) -> dict:
    """Points from GeoJSON / KML / shapefile or a CSV with name, lon (x), lat (y)[, value…] columns."""
    from shapely.geometry import Point
    ext = '.' + filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext not in ('.csv', '.txt'):
        v = read_vector(data, filename, crs)
        pts = [f for f in v['features'] if f['geometry'].geom_type == 'Point']
        if not pts:
            raise GeoReadError('El archivo no contiene puntos.')
        return {'kind': 'vector', 'features': pts, 'source_crs': v['source_crs']}
    text = data.decode('utf-8-sig', errors='replace')
    sep = ';' if text.count(';') > text.count(',') else ','
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = [h.strip().lower() for h in lines[0].split(sep)]
    ix = next((i for i, h in enumerate(head) if h in ('lon', 'longitude', 'longitud', 'x', 'este')), None)
    iy = next((i for i, h in enumerate(head) if h in ('lat', 'latitude', 'latitud', 'y', 'norte')), None)
    iname = next((i for i, h in enumerate(head) if h in ('name', 'nombre', 'label', 'id', 'punto')), None)
    if ix is None or iy is None:
        raise GeoReadError('CSV de puntos: cabecera con columnas lon/lat (o x/y) y opcionalmente nombre.')
    src = parse_crs(crs) if crs else WGS84
    out = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(sep)]
        try:
            x, y = float(parts[ix].replace(',', '.')) if sep == ';' else float(parts[ix]), \
                float(parts[iy].replace(',', '.')) if sep == ';' else float(parts[iy])
        except (ValueError, IndexError):
            continue
        lon, lat = transform([x], [y], src, WGS84)
        props = {head[i]: parts[i] for i in range(min(len(head), len(parts))) if i not in (ix, iy)}
        if iname is not None:
            props['name'] = parts[iname]
        out.append({'geometry': Point(float(lon[0]), float(lat[0])), 'props': props})
    if not out:
        raise GeoReadError('CSV de puntos sin filas válidas.')
    return {'kind': 'vector', 'features': out, 'source_crs': src}


def _parse_time(tok: str):
    try:
        return float(tok), None
    except ValueError:
        pass
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M',
                '%d/%m/%Y %H:%M:%S', '%Y-%m-%d'):
        try:
            return None, datetime.strptime(tok.replace('Z', ''), fmt)
        except ValueError:
            continue
    raise GeoReadError(f'Tiempo no reconocido «{tok}» (segundos o fecha ISO).')


def read_forcing(data: bytes, filename: str, time_unit: str = 's') -> dict:
    """Forcing CSV: either a time series (first column time — seconds/hours… or ISO dates — then one or more value
    columns: level [m], wind u/v [m/s], discharge [m³/s]…) or a table of tidal constants
    (constituent, amplitude [m], phase [deg]; optional row Z0)."""
    text = data.decode('utf-8-sig', errors='replace')
    sep = ';' if text.count(';') > text.count(',') else ','
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith('#')]
    if len(lines) < 2:
        raise GeoReadError('CSV de forzamiento vacío.')
    head = [h.strip() for h in lines[0].split(sep)]
    low = [h.lower() for h in head]
    num = (lambda s: float(s.replace(',', '.'))) if sep == ';' else float
    if low[0] in ('constituent', 'constituyente', 'componente', 'onda'):
        from app.geodata.forcing import CONSTITUENTS
        ia = next((i for i, h in enumerate(low) if h.startswith('amp')), 1)
        ip = next((i for i, h in enumerate(low) if h.startswith(('phase', 'fase', 'g'))), 2)
        cons, z0 = [], 0.0
        for ln in lines[1:]:
            p = [s.strip() for s in ln.split(sep)]
            name = p[0]
            if name.upper() == 'Z0':
                z0 = num(p[ia])
                continue
            key = next((k for k in CONSTITUENTS if k.upper() == name.upper()), None)
            if key is None:
                raise GeoReadError(f'Constituyente de marea desconocido «{name}» ({", ".join(CONSTITUENTS)}).')
            cons.append({'name': key, 'amplitude': num(p[ia]), 'phase': num(p[ip])})
        if not cons:
            raise GeoReadError('Tabla de armónicos sin constituyentes.')
        return {'kind': 'harmonics', 'constituents': cons, 'z0': z0}
    scale = {'s': 1.0, 'min': 60.0, 'h': 3600.0, 'd': 86400.0}.get(time_unit)
    if scale is None:
        raise GeoReadError(f'Unidad de tiempo «{time_unit}» no reconocida (s, min, h, d).')
    ts, cols, t0 = [], {h: [] for h in head[1:]}, None
    for ln in lines[1:]:
        p = [s.strip() for s in ln.split(sep)]
        if len(p) < 2:
            continue
        sec, dt = _parse_time(p[0])
        if dt is not None:
            t0 = t0 or dt
            sec = (dt - t0).total_seconds()
        else:
            sec *= scale
        ts.append(sec)
        for h, v in zip(head[1:], p[1:]):
            cols[h].append(num(v) if v not in ('', 'NaN', 'nan') else np.nan)
    t = np.asarray(ts)
    if len(t) < 2 or np.any(np.diff(t) <= 0):
        raise GeoReadError('Serie temporal: al menos 2 filas con tiempos crecientes.')
    return {'kind': 'series', 't': t, 't0': t0.isoformat() if t0 else None,
            'columns': {h: np.asarray(v, float) for h, v in cols.items() if len(v) == len(t)}}


# ── Sampling ──────────────────────────────────────────────────────────────────

class DepthSampler:
    """Depth at lon/lat from one or more bathymetry datasets (first that has a finite value wins: a detailed chart
    over GEBCO). Grids: bilinear in their own CRS; soundings: linear on their Delaunay triangulation (in a local
    metric frame: x·cos(lat0) for geographic soundings), outside the hull the next dataset, or the nearest
    sounding when it is the last one."""

    def __init__(self, datasets: list[dict]):
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator, RegularGridInterpolator
        self.parts = []
        for d in datasets:
            if d['kind'] == 'grid':
                f = RegularGridInterpolator((d['y'], d['x']), d['z'], bounds_error=False, fill_value=np.nan)
                self.parts.append({'kind': 'grid', 'crs': d['crs'], 'f': f})
            else:
                x, y = np.asarray(d['x'], float), np.asarray(d['y'], float)
                cx = float(np.cos(np.radians(y.mean()))) if is_geographic(d['crs']) else 1.0
                pts = np.column_stack([x * cx, y])
                self.parts.append({'kind': 'scatter', 'crs': d['crs'], 'cx': cx,
                                   'f': LinearNDInterpolator(pts, d['z']), 'near': NearestNDInterpolator(pts, d['z'])})

    def __call__(self, lon, lat) -> np.ndarray:
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        out = np.full(lon.shape, np.nan)
        for k, p in enumerate(self.parts):
            todo = ~np.isfinite(out)
            if not todo.any():
                break
            x, y = transform(lon[todo], lat[todo], WGS84, p['crs'])
            if p['kind'] == 'grid':
                out[todo] = p['f'](np.column_stack([y, x]))
            else:
                q = np.column_stack([x * p['cx'], y])
                v = p['f'](q)
                miss = ~np.isfinite(v)
                if miss.any() and k == len(self.parts) - 1:      # nearest only for the last (lowest priority) set
                    v[miss] = p['near'](q[miss])
                out[todo] = v
        return out
