"""/api/geodata — geographic datasets and 2D water-domain meshes (FASE 10.5)."""
import json
import uuid

import numpy as np
from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import String, cast

from app.extensions import db
from app.geodata import service
from app.geodata.models import GEO_KINDS, GeoDataset
from app.geodata.readers import GeoReadError

bp = Blueprint('geodata', __name__)


def _get(dataset_id) -> GeoDataset | None:
    return db.session.get(GeoDataset, dataset_id)


@bp.route('', methods=['POST'])
def upload():
    """multipart: file, kind (coastline|bathymetry|zones|points|forcing), optional name, project_id, crs (EPSG / WKT
    when the file does not say), convention (bathymetry: auto|depth|elevation), time_unit (forcing: s|min|h|d).
    Same content + kind + options → the existing dataset (200, deduplicated)."""
    f = request.files.get('file')
    if f is None or not f.filename:
        return jsonify({'error': "Falta el archivo 'file'"}), 400
    kind = request.form.get('kind', '')
    params = {k: request.form.get(k) for k in ('crs', 'convention', 'time_unit')}
    try:
        ds, created = service.import_dataset(f, kind, request.form.get('name'), params,
                                             request.form.get('project_id') or None)
    except (GeoReadError, ValueError) as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'dataset': ds.to_dict(), 'deduplicated': not created}), 201 if created else 200


@bp.route('', methods=['GET'])
def list_datasets():
    q = GeoDataset.query
    if kind := request.args.get('kind'):
        if kind not in GEO_KINDS:
            return jsonify({'error': f'kind ∈ {", ".join(GEO_KINDS)}'}), 400
        q = q.filter_by(kind=kind)
    if pid := request.args.get('project_id'):
        q = q.filter_by(project_id=pid)
    return jsonify({'datasets': [d.to_dict() for d in q.order_by(GeoDataset.created_at.desc()).all()]})


@bp.route('/<uuid:dataset_id>', methods=['GET'])
def get_dataset(dataset_id):
    ds = _get(dataset_id)
    if ds is None:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify({'dataset': ds.to_dict()})


@bp.route('/<uuid:dataset_id>/geojson', methods=['GET'])
def dataset_geojson(dataset_id):
    ds = _get(dataset_id)
    if ds is None:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify(service.geojson(ds))


@bp.route('/<uuid:dataset_id>/preview.png', methods=['GET'])
def preview(dataset_id):
    ds = _get(dataset_id)
    if ds is None or not ds.preview_uri:
        return jsonify({'error': 'Sin vista previa'}), 404
    return send_file(service.abs_path(ds.preview_uri), mimetype='image/png', max_age=3600)


@bp.route('/<uuid:dataset_id>/series', methods=['GET'])
def series(dataset_id):
    """Forcing as a curve for the chart: series as stored (≤ 2000 points), harmonics synthesised over
    ?days= (default 3) at ?dt_min= (default 10)."""
    ds = _get(dataset_id)
    if ds is None or ds.kind != 'forcing':
        return jsonify({'error': 'No es un forzamiento'}), 404
    d = service.load(ds)
    if d['kind'] == 'harmonics':
        from app.geodata.forcing import tide
        days = min(float(request.args.get('days', 3)), 60.0)
        dt = max(float(request.args.get('dt_min', 10)), 1.0) * 60
        t = np.arange(0, days * 86400 + dt / 2, dt)
        return jsonify({'kind': 'harmonics', 't': t.tolist(),
                        'columns': {'eta_m': np.round(tide(t, d['constituents'], d['z0']), 4).tolist()}})
    idx = np.arange(len(d['t']))
    if len(idx) > 2000:
        idx = np.linspace(0, len(idx) - 1, 2000).astype(int)
    return jsonify({'kind': 'series', 't0': d['t0'], 't': d['t'][idx].tolist(),
                    'columns': {k: [None if not np.isfinite(x) else float(x) for x in v[idx]]
                                for k, v in d['columns'].items()}})


@bp.route('/<uuid:dataset_id>/depth', methods=['POST'])
def sample_depth(dataset_id):
    """{points: [[lon, lat]…]} → depth [m] (null outside the data)."""
    ds = _get(dataset_id)
    if ds is None or ds.kind != 'bathymetry':
        return jsonify({'error': 'No es una batimetría'}), 404
    from app.geodata.readers import DepthSampler
    pts = np.asarray((request.get_json(silent=True) or {}).get('points') or [], float).reshape(-1, 2)
    z = DepthSampler([service.load(ds)])(pts[:, 0], pts[:, 1]) if len(pts) else np.zeros(0)
    return jsonify({'depth': [None if not np.isfinite(v) else float(v) for v in z]})


@bp.route('/<uuid:dataset_id>', methods=['DELETE'])
def delete_dataset(dataset_id):
    """409 when a study node references the dataset (its id appears in a node's properties)."""
    from app.design.models.graph import DesignNode
    ds = _get(dataset_id)
    if ds is None:
        return jsonify({'error': 'No encontrado'}), 404
    used = DesignNode.query.filter(cast(DesignNode.properties, String).like(f'%{ds.id}%')).count()
    if used:
        return jsonify({'error': f'«{ds.name}» lo usa {used} nodo(s) de estudio.'}), 409
    import shutil
    shutil.rmtree(service.data_dir() / 'geodata' / str(ds.id), ignore_errors=True)
    if GeoDataset.query.filter(GeoDataset.sha256 == ds.sha256, GeoDataset.id != ds.id).count() == 0:
        try:
            service.abs_path(ds.file_uri).unlink(missing_ok=True)
        except ValueError:
            pass
    db.session.delete(ds)
    db.session.commit()
    return jsonify({'deleted': str(dataset_id)})


# ── 2D mesh ───────────────────────────────────────────────────────────────────

def _domain_spec(body: dict) -> dict:
    keys = ('domain', 'segments', 'segment_labels', 'epsg', 'mesh', 'points', 'land_datasets',
            'bathymetry_datasets', 'zone_dataset', 'points_datasets')
    spec = {k: body.get(k) for k in keys if body.get(k) not in (None, '', [])}
    if not spec.get('domain'):
        raise ValueError('Falta el polígono del dominio.')
    from app.geodata.mesh2d import params_of
    params_of(spec.get('mesh'))          # validate early (400 instead of a failed job)
    return spec


@bp.route('/mesh', methods=['POST'])
def mesh():
    """Body = domain_2d spec. Cached mesh → 200 {key, cached}; else 202 {key, job_id} (job geo.mesh2d)."""
    from app.jobs import enqueue
    try:
        spec = _domain_spec(request.get_json(silent=True) or {})
        inp = service.mesh_inputs(spec)
    except (ValueError, GeoReadError) as e:
        return jsonify({'error': str(e)}), 400
    key = inp['key']
    if service.mesh_path(key).exists():
        return jsonify({'key': key, 'cached': True}), 200
    job = enqueue('geo.mesh2d', {'spec': spec, 'key': key})
    return jsonify({'key': key, 'job_id': str(job.id), 'cached': False}), 202


@bp.route('/mesh/<key>', methods=['GET'])
def get_mesh(key):
    """Mesh for the map (lon/lat nodes, triangles, depth, boundaries, stats); ?format=npz downloads the cache."""
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        return jsonify({'error': 'Clave inválida'}), 400
    path = service.mesh_path(key)
    if not path.exists():
        return jsonify({'error': 'Malla no generada'}), 404
    if request.args.get('format') == 'npz':
        return send_file(path, mimetype='application/octet-stream', as_attachment=True,
                         download_name=f'malla2d_{key[:10]}.npz')
    from app.geodata.mesh2d import Mesh2D
    return jsonify(service.mesh_json(Mesh2D.from_bytes(path.read_bytes())))


@bp.route('/utm', methods=['GET'])
def utm():
    """?lon=&lat= → automatic UTM EPSG of the point."""
    from app.geodata.crs import utm_epsg
    try:
        return jsonify({'epsg': utm_epsg(float(request.args['lon']), float(request.args['lat']))})
    except (KeyError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
