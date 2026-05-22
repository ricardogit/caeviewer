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
    '.k', '.key',                # LS-DYNA keyword (single file)
    '.zip',                      # LS-DYNA multi-file assembly (ZIP)
}


def _allowed(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_MESH_EXTENSIONS


def _find_lsdyna_master(directory: str):
    """
    Find the LS-DYNA master keyword file inside an extracted ZIP directory.

    The master is the file that *contains* *INCLUDE directives but is not
    itself referenced by any other file.  Falls back to the largest .k/.key
    file at the root level.
    """
    import glob

    # Collect all .k / .key files (root first, then subdirectories)
    kfiles = (
        glob.glob(os.path.join(directory, '*.k')) +
        glob.glob(os.path.join(directory, '*.key')) +
        glob.glob(os.path.join(directory, '**', '*.k'),  recursive=True) +
        glob.glob(os.path.join(directory, '**', '*.key'), recursive=True)
    )
    seen: set = set()
    kfiles = [f for f in kfiles
              if not (os.path.abspath(f) in seen or seen.add(os.path.abspath(f)))]

    if not kfiles:
        return None
    if len(kfiles) == 1:
        return kfiles[0]

    # Find which files are referenced via *INCLUDE in others
    included: set = set()
    for kf in kfiles:
        try:
            with open(kf, 'r', errors='ignore') as fh:
                next_is_filename = False
                for line in fh:
                    stripped = line.strip()
                    if stripped.upper().startswith('*INCLUDE'):
                        next_is_filename = True
                        continue
                    if next_is_filename:
                        if stripped and not stripped.startswith('$'):
                            candidate = os.path.normpath(
                                os.path.join(os.path.dirname(kf), stripped)
                            )
                            included.add(candidate)
                        next_is_filename = False
        except OSError:
            pass

    kfiles_abs = [os.path.abspath(f) for f in kfiles]
    masters = [f for f in kfiles_abs if f not in included]

    if masters:
        root = os.path.abspath(directory)
        root_masters = [f for f in masters if os.path.dirname(f) == root]
        return root_masters[0] if root_masters else masters[0]

    # Last resort: largest file at root level
    root_files = [f for f in kfiles_abs
                  if os.path.dirname(f) == os.path.abspath(directory)]
    candidates = root_files or kfiles_abs
    return max(candidates, key=os.path.getsize)


@bp.route('/meshes', methods=['GET'])
def list_meshes():
    """List all uploaded CAE meshes."""
    from app.cae.services.mesh_parser import recommend_solvers
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
            'recommended_solvers': recommend_solvers(m.element_types or {})[:3],
        } for m in meshes],
        'total': len(meshes),
    }), 200


@bp.route('/meshes/upload', methods=['POST'])
def upload_mesh():
    """Upload a CAE mesh file (single file or ZIP for LS-DYNA assemblies)."""
    import uuid as _uuid
    import zipfile
    import shutil

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

    raw_ext = os.path.splitext(filename)[1].lower()

    # ── ZIP assembly (LS-DYNA multi-file) ─────────────────────────────────────
    if raw_ext == '.zip':
        zip_path  = os.path.join(upload_folder, filename)
        assy_dir  = os.path.join(upload_folder, f'assy_{_uuid.uuid4().hex}')
        file.save(zip_path)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(assy_dir)
        except Exception as exc:
            shutil.rmtree(assy_dir, ignore_errors=True)
            os.remove(zip_path)
            return jsonify({'error': f'ZIP inválido: {exc}'}), 400
        os.remove(zip_path)

        master = _find_lsdyna_master(assy_dir)
        if not master:
            shutil.rmtree(assy_dir, ignore_errors=True)
            return jsonify({'error': 'No se encontró archivo .k o .key en el ZIP'}), 400

        file_path       = master
        ext             = 'k'
        original_filename = file.filename

    # ── Single file ───────────────────────────────────────────────────────────
    else:
        file_path         = os.path.join(upload_folder, filename)
        file.save(file_path)
        ext               = raw_ext.lstrip('.')
        original_filename = file.filename

    # ── Parse ─────────────────────────────────────────────────────────────────
    base_name = os.path.basename(file_path)
    try:
        from app.cae.services.mesh_parser import parse_mesh, get_field_range
        mesh_data = parse_mesh(file_path)

        mesh = CAEMesh(
            filename=base_name,
            original_filename=original_filename,
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
        db.session.flush()

        for fname in mesh_data.get('field_names', []):
            is_nodal = fname in mesh_data['node_fields']
            raw = (mesh_data['node_fields'] if is_nodal else mesh_data['element_fields'])[fname]
            step0 = raw.get('0', [])
            fmin, fmax = get_field_range(step0)
            ncomp = len(step0[0]) if step0 and isinstance(step0[0], list) else 1
            db.session.add(CAEField(
                mesh_id=mesh.id,
                name=fname,
                field_type='nodal' if is_nodal else 'elemental',
                components=ncomp,
                time_step=0.0,
                data_min=fmin,
                data_max=fmax,
            ))

        db.session.commit()
        parse_status = 'done'

    except Exception as e:
        logger.warning(f"Mesh parse failed for {base_name}: {e}")
        db.session.rollback()
        mesh = CAEMesh(
            filename=base_name,
            original_filename=original_filename,
            file_path=file_path,
            file_format=ext,
        )
        db.session.add(mesh)
        db.session.commit()
        parse_status = f'failed: {e}'
        mesh_data = {}

    return jsonify({
        'success':       True,
        'mesh_id':       str(mesh.id),
        'filename':      base_name,
        'node_count':    mesh_data.get('node_count'),
        'element_count': mesh_data.get('element_count'),
        'field_names':   mesh_data.get('field_names', []),
        'parse_status':  parse_status,
    }), 201


def _compact_surface(nodes: list, surface_triangles: list):
    """
    Return (compact_nodes, remapped_tris, node_map) where:
      compact_nodes  — only the nodes referenced by surface_triangles
      remapped_tris  — triangle indices into compact_nodes
      node_map       — node_map[compact_idx] = original_idx (for field lookups)

    Reduces the GET /meshes/<id> response 3-4x for dense solid meshes where
    interior nodes are never referenced by surface triangles.
    """
    seen: dict = {}
    node_map: list = []
    for tri in surface_triangles:
        for idx in tri:
            if idx not in seen:
                seen[idx] = len(node_map)
                node_map.append(idx)
    compact_nodes = [nodes[i] for i in node_map]
    remapped = [[seen[idx] for idx in tri] for tri in surface_triangles]
    return compact_nodes, remapped, node_map


@bp.route('/meshes/<string:mesh_id>', methods=['GET'])
def get_mesh(mesh_id):
    """Return mesh geometry (surface nodes + triangles). Compact: interior nodes excluded."""
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    try:
        mesh_data = _get_mesh_cached(mesh.file_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    surface_tris = mesh_data.get('surface_triangles', [])
    compact_nodes, remapped_tris, node_map = _compact_surface(
        mesh_data['nodes'], surface_tris
    )

    return jsonify({
        'mesh_id': mesh_id,
        'nodes': compact_nodes,
        'node_map': node_map,
        'element_types': mesh_data['element_types'],
        'surface_triangles': remapped_tris,
        'node_sets': mesh_data['node_sets'],
        'element_sets': mesh_data['element_sets'],
        'bounding_box': mesh_data['bounding_box'],
        'node_count': mesh_data['node_count'],
        'element_count': mesh_data['element_count'],
        'surface_triangle_count': len(remapped_tris),
        'time_steps': mesh_data.get('time_steps', [0]),
        'recommended_solvers': mesh_data.get('recommended_solvers', []),
        'quality': mesh_data.get('quality', {}),
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
    """Delete a CAE mesh and its file (or entire assy_* directory for ZIP assemblies)."""
    import shutil
    mesh = CAEMesh.query.filter_by(id=mesh_id).first()
    if not mesh:
        return jsonify({'error': 'Mesh not found'}), 404

    if mesh.file_path:
        parent = os.path.dirname(mesh.file_path)
        if os.path.basename(parent).startswith('assy_') and os.path.isdir(parent):
            try:
                shutil.rmtree(parent)
            except Exception as e:
                logger.warning(f"Could not delete assembly directory: {e}")
        elif os.path.exists(mesh.file_path):
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
