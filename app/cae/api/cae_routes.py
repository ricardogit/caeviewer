"""CAE Mesh API Routes."""
import os
import logging
from flask import Blueprint, jsonify, request, current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.cae.models import CAEMesh, CAEField

# ---------------------------------------------------------------------------
# Simple in-process mesh cache keyed by (file_path, mtime).
# Evicts the oldest entry when capacity is reached.
# Each Flask worker process has its own cache — that's intentional.
# ---------------------------------------------------------------------------
_mesh_cache: dict = {}
_CACHE_CAPACITY = 8


def _get_mesh_cached(file_path: str) -> dict:
    mtime = os.path.getmtime(file_path)
    key = (file_path, mtime)
    if key not in _mesh_cache:
        if len(_mesh_cache) >= _CACHE_CAPACITY:
            _mesh_cache.pop(next(iter(_mesh_cache)))
        from app.cae.services.mesh_parser import parse_mesh
        _mesh_cache[key] = parse_mesh(file_path)
    return _mesh_cache[key]

logger = logging.getLogger(__name__)
bp = Blueprint('cae_api', __name__)

ALLOWED_MESH_EXTENSIONS = {
    '.vtu', '.vtk', '.pvtu',    # VTK / ParaView
    '.inp',                      # Abaqus
    '.bdf', '.nas', '.dat',      # Nastran / ANSYS
    '.msh',                      # GMSH
    '.med',                      # Salome MED
    '.exo', '.e',                # Exodus II
    '.cdb',                      # ANSYS CDB
    '.xdmf', '.xmf',             # XDMF
}


def _allowed(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_MESH_EXTENSIONS


@bp.route('/meshes', methods=['GET'])
def list_meshes():
    """List all uploaded CAE meshes."""
    meshes = CAEMesh.query.order_by(CAEMesh.created_at.desc()).all()
    return jsonify({
        'meshes': [{
            'id': str(m.id),
            'original_filename': m.original_filename,
            'file_format': m.file_format,
            'node_count': m.node_count,
            'element_count': m.element_count,
            'element_types': m.element_types,
            'field_names': m.field_names or [],
            'created_at': m.created_at.isoformat() if m.created_at else None,
        } for m in meshes],
        'total': len(meshes),
    }), 200


@bp.route('/meshes/upload', methods=['POST'])
def upload_mesh():
    """Upload a CAE mesh file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400
    if not _allowed(file.filename):
        exts = ', '.join(sorted(ALLOWED_MESH_EXTENSIONS))
        return jsonify({'error': f'Unsupported format. Allowed: {exts}'}), 400

    filename = secure_filename(file.filename)
    upload_folder = os.path.join(str(current_app.config.get('UPLOAD_FOLDER', 'data/uploads')), 'cae')
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)

    ext = os.path.splitext(filename)[1].lower().lstrip('.')

    try:
        from app.cae.services.mesh_parser import parse_mesh, get_field_range
        mesh_data = parse_mesh(file_path)

        mesh = CAEMesh(
            filename=filename,
            original_filename=file.filename,
            file_path=file_path,
            file_format=ext,
            node_count=mesh_data['node_count'],
            element_count=mesh_data['element_count'],
            element_types=mesh_data['element_types'],
            node_sets=mesh_data['node_sets'],
            element_sets=mesh_data['element_sets'],
            field_names=mesh_data['field_names'],
            time_steps=mesh_data['time_steps'],
            bounding_box=mesh_data['bounding_box'],
            description=request.form.get('description', ''),
        )
        db.session.add(mesh)
        db.session.flush()  # get mesh.id

        # Store field metadata
        for fname in mesh_data.get('field_names', []):
            is_nodal = fname in mesh_data['node_fields']
            raw = (mesh_data['node_fields'] if is_nodal else mesh_data['element_fields'])[fname]
            step0 = raw.get('0', [])
            fmin, fmax = get_field_range(step0)
            ncomp = len(step0[0]) if step0 and isinstance(step0[0], list) else 1
            field = CAEField(
                mesh_id=mesh.id,
                name=fname,
                field_type='nodal' if is_nodal else 'elemental',
                components=ncomp,
                time_step=0.0,
                data_min=fmin,
                data_max=fmax,
            )
            db.session.add(field)

        db.session.commit()
        parse_status = 'done'

    except Exception as e:
        logger.warning(f"Mesh parse failed for {filename}: {e}")
        db.session.rollback()
        # Still register the file even if parsing failed
        mesh = CAEMesh(
            filename=filename,
            original_filename=file.filename,
            file_path=file_path,
            file_format=ext,
        )
        db.session.add(mesh)
        db.session.commit()
        parse_status = f'failed: {e}'
        mesh_data = {}

    return jsonify({
        'success': True,
        'mesh_id': str(mesh.id),
        'filename': filename,
        'node_count': mesh_data.get('node_count'),
        'element_count': mesh_data.get('element_count'),
        'field_names': mesh_data.get('field_names', []),
        'parse_status': parse_status,
    }), 201


@bp.route('/meshes/<string:mesh_id>', methods=['GET'])
def get_mesh(mesh_id):
    """Return mesh geometry (nodes + elements). Paginated for large meshes."""
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    try:
        mesh_data = _get_mesh_cached(mesh.file_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'mesh_id': mesh_id,
        'nodes': mesh_data['nodes'],
        'elements': mesh_data['elements'],
        'surface_triangles': mesh_data.get('surface_triangles', []),
        'node_sets': mesh_data['node_sets'],
        'element_sets': mesh_data['element_sets'],
        'bounding_box': mesh_data['bounding_box'],
        'node_count': mesh_data['node_count'],
        'element_count': mesh_data['element_count'],
        'surface_triangle_count': mesh_data.get('surface_triangle_count', 0),
        'time_steps': mesh_data.get('time_steps', [0]),
    }), 200


@bp.route('/meshes/<string:mesh_id>/fields', methods=['GET'])
def list_fields(mesh_id):
    """List fields available for a mesh."""
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    fields = CAEField.query.filter_by(mesh_id=mesh_id).all()
    return jsonify({
        'mesh_id': mesh_id,
        'fields': [{
            'id': str(f.id),
            'name': f.name,
            'field_type': f.field_type,
            'components': f.components,
            'component_names': f.component_names,
            'time_step': f.time_step,
            'data_min': f.data_min,
            'data_max': f.data_max,
        } for f in fields],
    }), 200


@bp.route('/meshes/<string:mesh_id>/field/<string:field_name>', methods=['GET'])
def get_field_data(mesh_id, field_name):
    """Return field values for coloring the mesh."""
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    step = request.args.get('step', '0')

    try:
        from app.cae.services.mesh_parser import get_field_range
        mesh_data = _get_mesh_cached(mesh.file_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if field_name in mesh_data['node_fields']:
        raw = mesh_data['node_fields'][field_name]
        field_type = 'nodal'
    elif field_name in mesh_data['element_fields']:
        raw = mesh_data['element_fields'][field_name]
        field_type = 'elemental'
    else:
        return jsonify({'error': f'Field "{field_name}" not found'}), 404

    values = raw.get(step, raw.get('0', []))
    fmin, fmax = get_field_range(values)

    return jsonify({
        'mesh_id': mesh_id,
        'field_name': field_name,
        'field_type': field_type,
        'step': step,
        'values': values,
        'data_min': fmin,
        'data_max': fmax,
    }), 200


@bp.route('/meshes/<string:mesh_id>/download', methods=['GET'])
def download_mesh(mesh_id):
    """Serve the original mesh file as an attachment."""
    from flask import send_file
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404
    if not os.path.exists(mesh.file_path):
        return jsonify({'error': 'File not found on disk'}), 404
    return send_file(mesh.file_path, as_attachment=True, download_name=mesh.original_filename)


@bp.route('/meshes/<string:mesh_id>', methods=['DELETE'])
def delete_mesh(mesh_id):
    """Delete a CAE mesh and its file."""
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    if mesh.file_path and os.path.exists(mesh.file_path):
        try:
            os.remove(mesh.file_path)
        except Exception as e:
            logger.warning(f"Could not delete mesh file: {e}")

    db.session.delete(mesh)
    db.session.commit()
    return jsonify({'success': True}), 200


@bp.route('/status', methods=['GET'])
def cae_status():
    """CAE subsystem status."""
    try:
        import meshio
        meshio_version = meshio.__version__
        meshio_ok = True
    except ImportError:
        meshio_version = None
        meshio_ok = False

    return jsonify({
        'status': 'ok',
        'meshio_available': meshio_ok,
        'meshio_version': meshio_version,
        'supported_formats': sorted(ALLOWED_MESH_EXTENSIONS),
    }), 200
