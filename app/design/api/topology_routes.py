"""Design Topology API — SIMP (+ AM overhang filter) and level-set topology optimization (FASE 4).

The optimization settings live in the graph: an OPTIMIZATION node (created on the first run)
stores them, and the extracted optimum comes back as a GEOMETRY node produced by it.
Runs are SimulationRun rows with purpose='topology' (hash, lineage, reports: FASE 7).
"""
from __future__ import annotations

import io
import logging

import numpy as np
from flask import Blueprint, jsonify, request, send_file

from app.extensions import db

logger = logging.getLogger(__name__)
bp = Blueprint('design_topology', __name__)

SETTING_KEYS = ('volume_fraction', 'p_penalization', 'filter_radius', 'filter_factor', 'max_iter', 'tol',
                'move', 'emin_ratio', 'projection', 'beta_max', 'keep_bc_load_solid',
                'am_constraint', 'build_direction', 'max_overhang_angle')
LEVELSET_KEYS = ('volume_fraction', 'tau', 'dt', 'max_iter', 'ramp_iter', 'band', 'emin_ratio',
                 'tol_compliance', 'keep_bc_load_solid')
METHOD_KEYS = {'simp': SETTING_KEYS, 'levelset': LEVELSET_KEYS}


@bp.route('/status', methods=['GET'])
def status():
    from app.design.services.topology.simp import SIMPSettings, MAX_ELEMENTS
    from app.design.services.topology.levelset import LevelSetSettings
    return jsonify({
        'module': 'design.topology', 'status': 'ok',
        'methods_available': ['simp', 'levelset'],
        'am_constraints': True,
        'defaults': {**SIMPSettings().to_dict(), 'am_constraint': False, 'build_direction': [0.0, 0.0, 1.0],
                     'max_overhang_angle': 45.0},
        'defaults_levelset': LevelSetSettings().to_dict(),
        'max_elements': MAX_ELEMENTS,
    }), 200


def _optimization_node(graph_id):
    from app.design.models.graph import DesignNode
    return (DesignNode.query.filter_by(graph_id=graph_id, node_type='OPTIMIZATION')
            .order_by(DesignNode.created_at).first())


def _save_settings_node(graph_id, settings: dict, method: str = 'simp'):
    """Persist the settings used in the graph's OPTIMIZATION node (create it if needed)."""
    from app.design.models.graph import DesignNode
    from app.design.services.graph_service import DesignGraphService
    svc = DesignGraphService()
    node = _optimization_node(graph_id)
    props = {'method': method, **{k: settings.get(k) for k in METHOD_KEYS[method] if k in settings}}
    if node is None:
        geo = (DesignNode.query.filter_by(graph_id=graph_id, node_type='GEOMETRY')
               .order_by(DesignNode.created_at).first())
        node = svc.add_node(graph_id, 'OPTIMIZATION', 'Optimización topológica', props,
                            pos_x=(geo.pos_x + 260) if geo else 0.0, pos_y=(geo.pos_y - 120) if geo else 0.0)
        if geo is not None:
            svc.add_edge(graph_id, node.id, geo.id, 'DEPENDS_ON')
    else:
        node.properties = {**(node.properties or {}), **props}
        db.session.commit()
    return node


@bp.route('/<string:graph_id>/run-simp', methods=['POST'])
def run_simp(graph_id):
    """Launch SIMP on the graph's study (geometry/material/BC/loads from the graph).

    Body (all optional): { volume_fraction, p_penalization, filter_radius, max_iter, tol, move,
    emin_ratio, projection, beta_max, keep_bc_load_solid, am_constraint, build_direction,
    max_overhang_angle, tier, mesh_size_mm,
    mesh_source/mesh_params/bcs/loads (to override the graph, e.g. the 'plate' hito) }.
    Defaults come from the graph's OPTIMIZATION node, then SIMPSettings.
    Socket room=run_id: topology_progress, topology_snapshot, topology_done, topology_error.
    """
    return _launch(graph_id, 'simp')


@bp.route('/<string:graph_id>/run-levelset', methods=['POST'])
def run_levelset(graph_id):
    """Launch the reaction-diffusion level-set optimizer (same study input as run-simp).

    Body (all optional): { volume_fraction, tau, dt, max_iter, ramp_iter, band, emin_ratio,
    tol_compliance, keep_bc_load_solid, tier, mesh_size_mm, mesh_source/mesh_params/bcs/loads }.
    """
    return _launch(graph_id, 'levelset')


def _launch(graph_id, method):
    from app.design.models.graph import DesignGraph
    from app.design.api.solver_routes import prepare_spec, _create_and_enqueue
    from app.design.services.topology.simp import SIMPSettings, TopologyError
    from app.design.services.topology.levelset import LevelSetSettings
    keys = METHOD_KEYS[method]

    graph = db.session.get(DesignGraph, graph_id)
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404
    body = request.get_json(silent=True) or {}
    node = _optimization_node(graph_id)
    props = (node.properties or {}) if node else {}
    same = props.get('method', 'simp') == method          # a node saved by the other method only shares the volume
    raw = {**{k: v for k, v in props.items() if k in keys and (same or k == 'volume_fraction')},
           **{k: body[k] for k in keys if k in body}}
    try:
        settings = (LevelSetSettings if method == 'levelset' else SIMPSettings).from_dict(raw)
    except (TopologyError, TypeError, ValueError) as e:
        return jsonify({'error': str(e), 'kind': 'settings'}), 422
    if any(ld.get('gravity') is not None for ld in body.get('loads', [])):
        return jsonify({'error': 'La gravedad no está soportada en optimización topológica'}), 422

    data = {k: v for k, v in body.items() if k not in SETTING_KEYS and k not in LEVELSET_KEYS
            and k != 'mesh_size_mm'}

    def adjust(d):
        mp = dict(d.get('mesh_params') or {})
        mp['order'] = 1                            # SIMP runs on linear tets
        if body.get('mesh_size_mm'):
            mp['mesh_size'] = float(body['mesh_size_mm'])
        d['mesh_params'] = mp

    data, err = prepare_spec(graph_id, data, adjust=adjust)
    if err:
        return err
    if any('gravity' in ld for ld in data.get('loads', [])):
        return jsonify({'error': 'Quita la carga de gravedad: depende de la densidad y no está soportada '
                                 'en optimización topológica.', 'kind': 'graph_spec'}), 422
    if not data.get('loads') or not data.get('bcs'):
        return jsonify({'error': 'El estudio necesita al menos una restricción y una carga.',
                        'kind': 'graph_spec'}), 422
    data['topology'] = {**settings.to_dict(), 'method': method}
    data['graph_id'] = graph_id
    _save_settings_node(graph_id, settings.to_dict(), method)
    run, job = _create_and_enqueue(graph, data, purpose='topology')
    return jsonify({'run_id': str(run.id), 'job_id': str(job.id), 'hash': run.hash, 'status': 'queued',
                    'settings': data['topology'], 'parent_run_id': str(run.parent_run_id) if run.parent_run_id else None,
                    'parameter_delta': run.parameter_delta or {}}), 202


def _run_or_404(run_id):
    from app.design.models.simulation import SimulationRun
    run = db.session.get(SimulationRun, run_id)
    if run is None or not (run.solver_config or {}).get('topology'):
        return None
    return run


@bp.route('/<string:run_id>/state', methods=['GET'])
def run_state(run_id):
    """Status, settings, summary and compliance history (from the latest snapshot while running)."""
    from app.design.services.topology.runner import load_state
    run = _run_or_404(run_id)
    if run is None:
        return jsonify({'error': 'Topology run not found'}), 404
    st = load_state(run_id) or {}
    return jsonify({
        'run_id': run_id, 'graph_id': str(run.graph_id), 'status': run.status, 'hash': run.hash,
        'settings': (run.solver_config or {}).get('topology'), 'summary': run.summary or {},
        'error': (run.mesh_stats or {}).get('error'),
        'iteration': int(st['iteration']) if 'iteration' in st else None,
        'source': st.get('source'), 'history': st.get('history', []),
        'n_elements': int(len(st['elements'])) if 'elements' in st else None,
    }), 200


@bp.route('/<string:run_id>/densities', methods=['GET'])
def get_densities(run_id):
    """Element density field ρ̄ (0 = void, 1 = solid). ?which=auto|latest|final"""
    from app.design.services.topology.runner import load_state
    if _run_or_404(run_id) is None:
        return jsonify({'error': 'Topology run not found'}), 404
    st = load_state(run_id, request.args.get('which', 'auto'))
    if not st or 'densities' not in st:
        return jsonify({'error': 'Sin densidades todavía'}), 404
    return jsonify({'run_id': run_id, 'iteration': int(st['iteration']), 'source': st['source'],
                    'densities': np.round(st['densities'].astype(float), 4).tolist()}), 200


def _iso(run_id, threshold: float, which: str):
    """Iso-surface (cached per threshold for final results)."""
    from app.design.services.topology.runner import load_state, run_dir
    from app.design.services.topology.isosurface import extract_isosurface
    st = load_state(run_id, which)
    if not st or 'densities' not in st:
        return None, None
    cache = run_dir(run_id) / f'iso_{int(round(threshold * 1000)):04d}.npz'
    if st['source'] == 'result' and cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}, st
    surf = extract_isosurface(st['nodes'], st['elements'], st['densities'].astype(float), threshold)
    surf = {'vertices': surf['vertices'], 'faces': surf['faces'], 'nodal_density': surf['nodal_density'],
            'volume': np.float64(surf['volume']), 'area': np.float64(surf['area'])}
    if st['source'] == 'result':
        np.savez(cache, **surf)
    return surf, st


@bp.route('/<string:run_id>/isosurface', methods=['GET'])
def get_isosurface(run_id):
    """Iso-surface ρ = threshold. ?threshold=0.5&which=auto&format=json|stl|glb[&download=1]
    JSON/exports in millimetres."""
    if _run_or_404(run_id) is None:
        return jsonify({'error': 'Topology run not found'}), 404
    thr = float(request.args.get('threshold', 0.5))
    if not 0.05 <= thr <= 0.95:
        return jsonify({'error': 'threshold debe estar entre 0.05 y 0.95'}), 422
    surf, st = _iso(run_id, thr, request.args.get('which', 'auto'))
    if surf is None:
        return jsonify({'error': 'Sin densidades todavía'}), 404
    fmt = request.args.get('format', 'json')
    V = surf['vertices'] * 1000.0
    if fmt in ('stl', 'glb'):
        import trimesh
        tm = trimesh.Trimesh(vertices=V, faces=surf['faces'], process=True)
        buf = io.BytesIO(tm.export(file_type=fmt))
        return send_file(buf, mimetype='model/stl' if fmt == 'stl' else 'model/gltf-binary',
                         as_attachment=bool(request.args.get('download')),
                         download_name=f'topologia_{run_id[:8]}_t{int(thr * 100):02d}.{fmt}')
    nodes = st['nodes'] * 1000.0
    return jsonify({
        'run_id': run_id, 'threshold': thr, 'iteration': int(st['iteration']), 'source': st['source'],
        'units': 'mm',
        'positions': np.round(V, 4).ravel().astype(float).tolist(),
        'indices': surf['faces'].ravel().astype(int).tolist(),
        'density': np.round(surf['nodal_density'], 3).astype(float).tolist(),
        'volume_mm3': float(surf['volume']) * 1e9, 'area_mm2': float(surf['area']) * 1e6,
        'bbox': np.concatenate([nodes.min(0), nodes.max(0)]).round(4).tolist(),
    }), 200


@bp.route('/<string:run_id>/domain', methods=['GET'])
def get_domain(run_id):
    """Boundary of the design domain (ghost display), mm, plus passive-solid boundary."""
    from app.design.services.topology.runner import load_state
    from app.design.services.fem import tet_batch as tb
    if _run_or_404(run_id) is None:
        return jsonify({'error': 'Topology run not found'}), 404
    st = load_state(run_id, 'latest')
    if not st or 'elements' not in st:
        return jsonify({'error': 'Malla todavía no disponible'}), 404
    faces = tb.boundary_faces(st['elements'])
    used = np.unique(faces)
    remap = -np.ones(len(st['nodes']), np.int64)
    remap[used] = np.arange(len(used))
    return jsonify({'positions': np.round(st['nodes'][used] * 1000.0, 4).ravel().astype(float).tolist(),
                    'indices': remap[faces].ravel().astype(int).tolist(), 'units': 'mm'}), 200


@bp.route('/<string:run_id>/extract-mesh', methods=['POST'])
def extract_mesh(run_id):
    """Save the optimum (iso-surface STL, mm) and add it to the graph as a GEOMETRY node
    produced by the OPTIMIZATION node. Body: { threshold: 0.5 }"""
    from app.design.services.topology.runner import run_dir
    from app.design.services.graph_service import DesignGraphService
    run = _run_or_404(run_id)
    if run is None:
        return jsonify({'error': 'Topology run not found'}), 404
    if run.status != 'done':
        return jsonify({'error': 'La optimización no ha terminado'}), 409
    thr = float((request.get_json(silent=True) or {}).get('threshold', 0.5))
    surf, _ = _iso(run_id, thr, 'final')
    if surf is None:
        return jsonify({'error': 'Sin resultado final'}), 404
    import trimesh
    tm = trimesh.Trimesh(vertices=surf['vertices'] * 1000.0, faces=surf['faces'], process=True)
    path = run_dir(run_id) / f'design_t{int(round(thr * 100)):02d}.stl'
    tm.export(str(path))
    svc = DesignGraphService()
    opt = _optimization_node(run.graph_id)
    props = {
        'source': 'topology', 'topology_run_id': run_id, 'threshold': thr,
        'base_geometry_id': (run.solver_config or {}).get('geometry_id'),
        'stl_path': str(path), 'volume_mm3': float(tm.volume), 'area_mm2': float(tm.area),
        'n_triangles': int(len(tm.faces)), 'watertight': bool(tm.is_watertight),
        'volume_fraction': (run.summary or {}).get('volume_fraction_bw'),
    }
    node = svc.add_node(str(run.graph_id), 'GEOMETRY', f'Diseño óptimo ({int(thr * 100)} %)', props,
                        pos_x=(opt.pos_x + 260) if opt else 0.0, pos_y=opt.pos_y if opt else 0.0)
    if opt is not None:
        svc.add_edge(str(run.graph_id), opt.id, node.id, 'PRODUCES')
    return jsonify({'node_id': str(node.id), 'properties': props,
                    'download_url': f'/api/design/topology/{run_id}/isosurface?threshold={thr}&format=stl&download=1'}), 201
