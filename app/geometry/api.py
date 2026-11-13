"""/api/geometry — versioned STEP geometry with persistent entity IDs (Fase 1b)."""
import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app.extensions import db
from app.geometry.models import Geometry, GeometryEntity
from app.geometry.storage import store_step_upload
from app.jobs import enqueue

bp = Blueprint('geometry', __name__)


def _enqueue_import(geo: Geometry):
    job = enqueue('geometry.import', {'geometry_id': str(geo.id)}, commit=False)
    geo.import_job_id = job.id
    geo.status, geo.error = 'pending', None
    db.session.commit()
    return job


@bp.route('', methods=['POST'])
def upload():
    """multipart: file (STEP), optional: name, project_id, parent_id (new version of that lineage).

    Same content as the latest version of the lineage -> no new version (200, deduplicated).
    """
    f = request.files.get('file')
    if f is None or not f.filename:
        return jsonify({'error': "Falta el archivo 'file'"}), 400
    try:
        rel, sha, size = store_step_upload(f)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    parent = None
    if parent_id := request.form.get('parent_id'):
        parent = db.session.get(Geometry, parent_id)
        if parent is None:
            return jsonify({'error': 'parent_id no existe'}), 404
        latest = (Geometry.query.filter_by(lineage_id=parent.lineage_id)
                  .order_by(Geometry.version.desc()).first())
        if latest.sha256 == sha:
            return jsonify({'geometry': latest.to_dict(), 'deduplicated': True}), 200
        parent = latest     # new versions always chain off the newest one

    geo = Geometry(
        lineage_id=parent.lineage_id if parent else uuid.uuid4(),
        version=(parent.version + 1) if parent else 1,
        parent_id=parent.id if parent else None,
        project_id=request.form.get('project_id') or (parent.project_id if parent else None),
        name=request.form.get('name') or (parent.name if parent else f.filename.rsplit('.', 1)[0]),
        original_filename=f.filename, file_uri=rel, sha256=sha, size_bytes=size, units='mm',
        status='pending', meta={},
    )
    db.session.add(geo)
    db.session.flush()
    job = _enqueue_import(geo)
    return jsonify({'geometry': geo.to_dict(), 'job_id': str(job.id)}), 202


@bp.route('', methods=['GET'])
def list_geometries():
    """Latest version of each lineage (``all_versions=1`` for every row)."""
    q = Geometry.query
    if pid := request.args.get('project_id'):
        q = q.filter(Geometry.project_id == pid)
    if request.args.get('all_versions') not in ('1', 'true'):
        latest = (db.session.query(Geometry.lineage_id, func.max(Geometry.version).label('v'))
                  .group_by(Geometry.lineage_id).subquery())
        q = q.join(latest, (Geometry.lineage_id == latest.c.lineage_id) & (Geometry.version == latest.c.v))
    rows = q.order_by(Geometry.created_at.desc()).limit(min(int(request.args.get('limit', 100)), 500)).all()
    return jsonify({'geometries': [g.to_dict() for g in rows]})


@bp.route('/<uuid:geometry_id>', methods=['GET'])
def get_geometry(geometry_id):
    g = db.session.get(Geometry, geometry_id)
    if g is None:
        return jsonify({'error': 'Geometry not found'}), 404
    return jsonify(g.to_dict())


@bp.route('/<uuid:geometry_id>/versions', methods=['GET'])
def versions(geometry_id):
    g = db.session.get(Geometry, geometry_id)
    if g is None:
        return jsonify({'error': 'Geometry not found'}), 404
    rows = Geometry.query.filter_by(lineage_id=g.lineage_id).order_by(Geometry.version).all()
    return jsonify({'lineage_id': str(g.lineage_id), 'versions': [r.to_dict() for r in rows]})


@bp.route('/<uuid:geometry_id>/entities', methods=['GET'])
def entities(geometry_id):
    """Entity table. ?type=face|solid (default face)."""
    g = db.session.get(Geometry, geometry_id)
    if g is None:
        return jsonify({'error': 'Geometry not found'}), 404
    etype = request.args.get('type', 'face')
    rows = (GeometryEntity.query.filter_by(geometry_id=g.id, entity_type=etype)
            .order_by(GeometryEntity.entity_index).all())
    return jsonify({'geometry_id': str(g.id), 'status': g.status, 'type': etype,
                    'entities': [e.to_dict() for e in rows]})


@bp.route('/<uuid:geometry_id>/remap', methods=['GET'])
def remap(geometry_id):
    """Face correspondence with the previous version (what a BC on face X becomes)."""
    g = db.session.get(Geometry, geometry_id)
    if g is None:
        return jsonify({'error': 'Geometry not found'}), 404
    if not g.parent_id:
        return jsonify({'error': 'Es la versión 1; no hay versión anterior'}), 400
    parent_alias = db.aliased(GeometryEntity)
    rows = (db.session.query(GeometryEntity.id, GeometryEntity.entity_index, GeometryEntity.match_kind,
                             parent_alias.id, parent_alias.entity_index)
            .outerjoin(parent_alias, GeometryEntity.parent_entity_id == parent_alias.id)
            .filter(GeometryEntity.geometry_id == g.id, GeometryEntity.entity_type == 'face')
            .order_by(GeometryEntity.entity_index).all())
    return jsonify({
        'geometry_id': str(g.id), 'parent_id': str(g.parent_id),
        'summary': (g.meta or {}).get('remap'),
        'faces': [{'id': str(i), 'index': idx, 'match_kind': mk,
                   'parent_entity_id': str(pid) if pid else None, 'parent_index': pidx}
                  for i, idx, mk, pid, pidx in rows],
    })


@bp.route('/<uuid:geometry_id>/reimport', methods=['POST'])
def reimport(geometry_id):
    """Re-run geometry.import on the same file (determinism check; entity UUIDs are kept)."""
    g = db.session.get(Geometry, geometry_id)
    if g is None:
        return jsonify({'error': 'Geometry not found'}), 404
    if g.status in ('pending', 'processing'):
        return jsonify({'error': f'Importación en curso ({g.status})'}), 409
    job = _enqueue_import(g)
    return jsonify({'geometry': g.to_dict(), 'job_id': str(job.id)}), 202
