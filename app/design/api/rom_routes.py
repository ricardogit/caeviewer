"""Design ROM API — POD-Galerkin reduced models and real-time evaluation (FASE 5).

A ROM is a SimulationRun with purpose='rom' (rom_id = run id). Build runs on the job queue
('rom.build'); evaluation runs in the web process from an in-memory cache, over REST or the
socket.io event ``rom_evaluate`` (with ack) used by the ROM explorer sliders.
"""
from __future__ import annotations

import json
import logging

import numpy as np
from flask import Blueprint, Response, jsonify, request

from app.extensions import db

logger = logging.getLogger(__name__)
bp = Blueprint('design_rom', __name__)


@bp.route('/status', methods=['GET'])
def status():
    from app.design.services.rom.pod import ROMSettings
    return jsonify({'module': 'design.rom', 'status': 'ok', 'method': 'POD-Galerkin',
                    'parameters': ['E', 'nu', 'rho', 'load_<i>'], 'defaults': ROMSettings().to_dict()}), 200


def _rom_run(rom_id):
    from app.design.models.simulation import SimulationRun
    run = db.session.get(SimulationRun, rom_id)
    if run is None or 'rom' not in (run.solver_config or {}):
        return None
    return run


def _load(rom_id):
    """(run, rom arrays) with the ROM loaded in the process cache, or (run, None)."""
    import os
    from app.design.services.rom.online_solver import online_solver
    from app.design.services.rom.runner import rom_path
    run = _rom_run(rom_id)
    if run is None or run.status != 'done':
        return run, None
    path = rom_path(rom_id)
    if not os.path.exists(path):
        return run, None
    return run, online_solver().load_rom(str(rom_id), path)


@bp.route('/<string:graph_id>/parameters', methods=['GET'])
def graph_parameters(graph_id):
    """Parameters the study offers (nominal values, units, suggested ranges)."""
    from app.design.services.graph_to_solver_spec import graph_to_solver_spec, GraphSpecError
    from app.design.services.rom.pod import describe_parameters
    try:
        spec = graph_to_solver_spec(graph_id)
    except GraphSpecError as e:
        return jsonify({'error': str(e), 'kind': 'graph_spec'}), 422
    return jsonify({'graph_id': graph_id, 'parameters': describe_parameters(spec)}), 200


@bp.route('/<string:graph_id>/build', methods=['POST'])
def build_rom(graph_id):
    """Build a ROM. Body: { parameter_space: {E: [min, max], load_0: [...], ...},
    n_snapshots, energy_threshold, n_test, tier, (mesh_source/mesh_params/bcs/loads overrides) }.
    Missing parameter_space → the suggested defaults (loads ±50 %, E ±20 %)."""
    from app.design.models.graph import DesignGraph
    from app.design.api.solver_routes import prepare_spec, _create_and_enqueue
    from app.design.services.rom.pod import ROMSettings, ROMError, describe_parameters

    graph = db.session.get(DesignGraph, graph_id)
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404
    body = request.get_json(silent=True) or {}
    keys = set(ROMSettings.__dataclass_fields__)
    try:
        settings = ROMSettings.from_dict({k: body[k] for k in keys if k in body})
    except (ROMError, TypeError, ValueError) as e:
        return jsonify({'error': str(e), 'kind': 'settings'}), 422
    data = {k: v for k, v in body.items() if k not in keys and k != 'parameter_space'}
    data, err = prepare_spec(graph_id, data)
    if err:
        return err
    if not data.get('loads') or not data.get('bcs'):
        return jsonify({'error': 'El estudio necesita al menos una restricción y una carga.', 'kind': 'graph_spec'}), 422
    available = {p['key']: p for p in describe_parameters(data)}
    space = body.get('parameter_space') or {k: p['default_range'] for k, p in available.items() if p['default_on']}
    unknown = [k for k in space if k not in available]
    if unknown:
        return jsonify({'error': f"Parámetros desconocidos: {', '.join(unknown)}", 'available': list(available)}), 422
    data['rom'] = {'method': 'pod', 'parameter_space': {k: [float(v[0]), float(v[1])] for k, v in space.items()},
                   'settings': settings.to_dict()}
    data['graph_id'] = graph_id
    run, job = _create_and_enqueue(graph, data, purpose='rom')
    return jsonify({'rom_id': str(run.id), 'run_id': str(run.id), 'job_id': str(job.id), 'hash': run.hash,
                    'status': 'queued', 'parameter_space': data['rom']['parameter_space']}), 202


@bp.route('/<string:graph_id>/list', methods=['GET'])
def list_roms(graph_id):
    from app.design.models.simulation import SimulationRun
    runs = (SimulationRun.query.filter(SimulationRun.graph_id == graph_id, SimulationRun.purpose == 'rom')
            .order_by(SimulationRun.created_at.desc()).limit(50).all())
    out = []
    for r in runs:
        s = r.summary or {}
        out.append({'rom_id': str(r.id), 'status': r.status, 'hash': r.hash,
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                    'parameter_space': ((r.solver_config or {}).get('rom') or {}).get('parameter_space'),
                    'n_modes': s.get('n_modes'), 'n_snapshots': s.get('n_snapshots'),
                    'validation_max_error_u': s.get('validation_max_error_u'),
                    'validation_max_error_vm': s.get('validation_max_error_vm'),
                    'n_nodes': s.get('n_nodes'), 'element_type': s.get('element_type'),
                    'build_s': s.get('build_s'), 'error': (r.mesh_stats or {}).get('error')})
    return jsonify({'roms': out}), 200


@bp.route('/<string:rom_id>', methods=['GET'])
def rom_info(rom_id):
    """Metadata for the explorer: parameters (with ranges), modes, validation."""
    run, rom = _load(rom_id)
    if run is None:
        return jsonify({'error': 'ROM not found'}), 404
    s = run.summary or {}
    space = ((run.solver_config or {}).get('rom') or {}).get('parameter_space') or {}
    params = []
    if rom is not None:
        for p in rom['params']:
            params.append({**p, 'range': space.get(p['key']), 'variable': p['key'] in space})
    return jsonify({'rom_id': rom_id, 'graph_id': str(run.graph_id), 'status': run.status, 'hash': run.hash,
                    'parameters': params, 'parameter_space': space,
                    'summary': {k: v for k, v in s.items() if k != 'singular_values'},
                    'singular_values': s.get('singular_values'), 'error': (run.mesh_stats or {}).get('error')}), 200


@bp.route('/<string:rom_id>/pack', methods=['GET'])
def rom_pack(rom_id):
    """Binary surface pack for the client-side field reconstruction.

    Layout: uint32 header length, UTF-8 JSON header, zero padding to 4 bytes, then the arrays
    listed in header['arrays'] ({name, dtype, shape, offset}) relative to the data start.
    Coordinates in mm; surf_phi in m per unit reduced coordinate.
    """
    run, rom = _load(rom_id)
    if rom is None:
        return jsonify({'error': 'ROM not available'}), 404
    arrays = [('xyz', (rom['surf_xyz'] * 1000.0).astype(np.float32)),
              ('tris', rom['surf_tris'].astype(np.uint32)),
              ('phi', rom['surf_phi'].astype(np.float32)),          # (n_s, 3, r)
              ('strain', rom['surf_strain'].astype(np.float32))]    # (n_s, 6, r)
    from app.design.services.binpack import pack_arrays
    body = pack_arrays({'rom_id': rom_id, 'r': int(rom['r'])}, arrays)
    return Response(body, mimetype='application/octet-stream',
                    headers={'Cache-Control': 'private, max-age=3600'})


def evaluate(rom_id: str, params: dict) -> tuple[dict, int]:
    from app.design.services.rom.online_solver import online_solver
    from app.design.services.rom.pod import ROMError
    solver = online_solver()
    if solver.get(rom_id) is None:
        run, rom = _load(rom_id)
        if rom is None:
            return {'error': 'ROM no disponible' if run else 'ROM not found'}, 404
    try:
        return solver.evaluate(rom_id, params or {}), 200
    except (ROMError, ValueError, np.linalg.LinAlgError) as e:
        return {'error': str(e)}, 422


@bp.route('/<string:rom_id>/evaluate', methods=['POST'])
def evaluate_rom(rom_id):
    """Body: { params: {E: 140e9, load_0: 450} } → reduced coefficients + key results."""
    out, code = evaluate(rom_id, (request.get_json(silent=True) or {}).get('params') or {})
    return jsonify(out), code


def _spec_with_params(run, q: dict) -> dict:
    """Base spec of the ROM with the parameter values applied (for a full verification run)."""
    spec = {k: v for k, v in (run.solver_config or {}).items() if k != 'rom'}
    mat = dict(spec.get('material') or {})
    for k in ('E', 'nu', 'rho'):
        if k in q:
            mat[k] = float(q[k])
    spec['material'] = mat
    from app.design.services.rom.pod import describe_parameters
    params = {p['key']: p for p in describe_parameters(run.solver_config)}
    loads = []
    for i, ld in enumerate(spec.get('loads') or []):
        ld = dict(ld)
        key = f'load_{i}'
        if key in q and params.get(key, {}).get('nominal'):
            f = float(q[key]) / params[key]['nominal']
            for k in ('force', 'force_per_node', 'gravity'):
                if k in ld:
                    ld[k] = [f * float(c) for c in ld[k]]
            if 'pressure' in ld:
                ld['pressure'] = f * float(ld['pressure'])
        loads.append(ld)
    spec['loads'] = loads
    return spec


@bp.route('/<string:rom_id>/full-run', methods=['POST'])
def full_run(rom_id):
    """Launch the full FEM simulation at the explorer's parameters (to verify the ROM)."""
    from app.design.models.graph import DesignGraph
    from app.design.api.solver_routes import _create_and_enqueue
    run, rom = _load(rom_id)
    if rom is None:
        return jsonify({'error': 'ROM not available'}), 404
    q = {p['key']: float(((request.get_json(silent=True) or {}).get('params') or {}).get(p['key'], p['nominal']))
         for p in rom['params']}
    spec = _spec_with_params(run, q)
    spec['graph_id'] = str(run.graph_id)
    graph = db.session.get(DesignGraph, run.graph_id)
    new, job = _create_and_enqueue(graph, spec, purpose='run', parent=run)
    return jsonify({'run_id': str(new.id), 'job_id': str(job.id), 'params': q}), 202


@bp.route('/<string:rom_id>/compare/<string:run_id>', methods=['GET'])
def compare(rom_id, run_id):
    """ROM vs full run at the same parameters: displacement field error and max values."""
    import h5py
    from flask import current_app
    from app.design.models.simulation import SimulationRun
    from app.design.services.rom.online_solver import online_solver
    run, rom = _load(rom_id)
    full = db.session.get(SimulationRun, run_id)
    if rom is None or full is None:
        return jsonify({'error': 'not found'}), 404
    if full.status != 'done':
        return jsonify({'status': full.status}), 202
    cfg = full.solver_config or {}
    mat = cfg.get('material') or {}
    params = {p['key']: p for p in rom['params']}
    q = {'E': float(mat.get('E')), 'nu': float(mat.get('nu'))}
    if 'rho' in params:
        q['rho'] = float(mat.get('rho', params['rho']['nominal']))
    for i, ld in enumerate(cfg.get('loads') or []):
        key = f'load_{i}'
        if key in params:
            if 'pressure' in ld:
                q[key] = abs(float(ld['pressure']))
            else:
                vec = ld.get('force', ld.get('force_per_node', ld.get('gravity')))
                q[key] = float(np.linalg.norm(vec))
    ev = online_solver().evaluate(rom_id, q)
    path = f"{current_app.config.get('SOLVER_DATA_DIR', 'data/solver')}/{run_id}.h5"
    with h5py.File(path, 'r') as f:
        u_fom = f['fields/displacement/step_0'][:].ravel()
    if len(u_fom) != rom['Phi'].shape[0]:
        return jsonify({'error': 'La simulación completa usó otra malla: no es comparable'}), 409
    u_rom = rom['Phi'] @ np.asarray(ev['coefficients'])
    err = float(np.linalg.norm(u_rom - u_fom) / max(np.linalg.norm(u_fom), 1e-300))
    s = full.summary or {}
    return jsonify({'rom_id': rom_id, 'run_id': run_id, 'params': q, 'error_u': err,
                    'rom': {'max_displacement_mm': ev['max_displacement_mm'], 'max_von_mises_mpa': ev['max_von_mises_mpa'],
                            'response_ms': ev['response_ms']},
                    'full': {'max_displacement_mm': s.get('max_displacement_mm'),
                             'max_von_mises_mpa': s.get('max_von_mises_mpa'), 'wall_time_s': full.wall_time}}), 200


def register_socket_handlers(socketio):
    """``rom_evaluate`` with ack: {rom_id, params, seq} → evaluate() result (+ seq)."""
    @socketio.on('rom_evaluate')
    def _rom_evaluate(data):
        data = data or {}
        out, code = evaluate(str(data.get('rom_id')), data.get('params') or {})
        out['seq'] = data.get('seq')
        if code != 200:
            out['status'] = code
        return out
