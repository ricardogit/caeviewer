"""Design Solver API — launch FEM simulations, stream progress via WebSocket.

FASE 2 full implementation.
"""
from __future__ import annotations
import logging
import uuid as _uuid

from flask import Blueprint, jsonify, request, current_app
from app.extensions import db, socketio

logger = logging.getLogger(__name__)
bp = Blueprint('design_solver', __name__)


# ── Status ────────────────────────────────────────────────────────────────────

@bp.route('/status', methods=['GET'])
def status():
    from app.design.services.fem.solver import TIER_LIMITS
    return jsonify({
        'module': 'design.solver',
        'status': 'ok',
        'tier_limits': TIER_LIMITS,
        'supported_physics': ['structural', 'thermal'],
        'supported_elements': ['T4', 'T3'],
    }), 200


# ── Launch simulation ─────────────────────────────────────────────────────────

@bp.route('/<string:graph_id>/run', methods=['POST'])
def run_simulation(graph_id):
    """Launch an async FEM simulation for the given graph.

    Body (all optional except mesh spec):
    {
        "physics":     ["structural"],
        "tier":        1,
        "tolerance":   1e-8,
        "max_iterations": 1000,
        "mesh_source": "cantilever" | "inline" | "cae_mesh" | "graph",
        "mesh_params": { "length":0.05, "width":0.01, "height":0.01, "n_along_length":12 },
        "material":    { "type":"linear_elastic_isotropic", "E":210e9, "nu":0.3, "rho":7800 },
        "bcs":  [{"node_set":"fixed", "dofs":[0,1,2], "values":[0,0,0]}],
        "loads":[{"node_set":"tip",   "force":[0,-1000,0]}]
    }

    Si material/bcs/loads faltan, se leen del grafo.

    Returns: { run_id, hash }
    WebSocket room = run_id  →  events: solver_progress, solver_done, solver_error
    """
    from app.design.models.graph import DesignGraph
    from app.design.models.simulation import SimulationRun
    from app.design.services.traceability.hasher import SimulationHasher
    from app.design.services.graph_to_solver_spec import graph_to_solver_spec

    try:
        # Validate graph exists
        graph = DesignGraph.query.filter_by(id=graph_id).first()
        if not graph:
            logger.warning(f"Graph {graph_id} not found")
            return jsonify({'error': 'Graph not found', 'graph_id': graph_id}), 404

        # Parse request body
        try:
            data = request.get_json(silent=True) or {}
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({'error': 'Invalid JSON in request body'}), 400

        # Validate tier if provided
        if 'tier' in data:
            try:
                tier = int(data['tier'])
                if tier not in (0, 1, 2, 3):
                    return jsonify({'error': 'Tier must be 0-3', 'got': tier}), 422
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid tier: {e}")
                return jsonify({'error': 'Tier must be integer 0-3'}), 422

        # Read spec from graph if needed
        if 'material' not in data or 'bcs' not in data or 'loads' not in data:
            try:
                graph_spec = graph_to_solver_spec(graph_id)
                # Merge: request body values have priority
                if 'material' not in data:
                    data['material'] = graph_spec.get('material', data.get('material'))
                if 'bcs' not in data:
                    data['bcs'] = graph_spec.get('bcs', data.get('bcs', []))
                if 'loads' not in data:
                    data['loads'] = graph_spec.get('loads', data.get('loads', []))
                if 'mesh_source' not in data and 'mesh_source' in graph_spec:
                    data['mesh_source'] = graph_spec['mesh_source']
                if 'mesh_id' not in data and 'mesh_id' in graph_spec:
                    data['mesh_id'] = graph_spec['mesh_id']
                if 'tier' not in data and 'tier' in graph_spec:
                    data['tier'] = graph_spec['tier']
            except Exception as e:
                logger.warning(f"Could not read graph spec for {graph_id}: {e}")
                # Fallback to request body defaults

        # Validate required parameters
        if not data.get('material'):
            data['material'] = {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800}
        if not data.get('bcs'):
            logger.warning(f"No boundary conditions for run {graph_id}")
        if not data.get('loads'):
            logger.warning(f"No loads for run {graph_id}")

        # Compute run hash
        run_id = _uuid.uuid4()
        hasher = SimulationHasher()
        try:
            run_hash = hasher.compute_hash(
                graph_state={'graph_id': graph_id, 'version': graph.version},
                solver_config={k: v for k, v in data.items()
                               if k not in ('nodes', 'elements')},
                mesh_stats={},
            )
        except Exception as e:
            logger.error(f"Failed to compute run hash: {e}")
            run_hash = 'unknown'

        # Inject graph_id into spec
        spec = dict(data)
        spec['graph_id'] = graph_id

        # Create SimulationRun record
        try:
            run = SimulationRun(
                id=run_id,
                graph_id=graph_id,
                graph_version=graph.version,
                hash=run_hash,
                status='queued',
                tier=int(data.get('tier', 1)),
                physics=data.get('physics', ['structural']),
                solver_config={k: v for k, v in data.items()
                               if k not in ('nodes', 'elements')},
            )
            db.session.add(run)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to create SimulationRun record: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to create simulation record', 'detail': str(e)}), 500

        # Enqueue on the 'solve' queue; a worker process (python -m app.jobs.worker
        # --queues solve) runs FEMKernel.solve_async and its socket events are
        # forwarded to room=run_id by the web-side job listener.
        from app.jobs import enqueue
        job = enqueue('fem.solve', {'run_id': str(run_id), 'spec': spec},
                      simulation_run_id=run_id)

        logger.info(f"Launched simulation run {run_id} for graph {graph_id}")
        return jsonify({
            'run_id': str(run_id),
            'hash': run_hash[:16] if run_hash != 'unknown' else run_hash,
            'status': 'queued',
            'graph_id': graph_id,
            'job_id': str(job.id),
        }), 202

    except Exception as e:
        logger.error(f"Unexpected error in run_simulation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500


# ── Run status & results ──────────────────────────────────────────────────────

@bp.route('/<string:run_id>/status', methods=['GET'])
def run_status(run_id):
    """Get status of a simulation run."""
    try:
        from app.design.models.simulation import SimulationRun
        run = SimulationRun.query.filter_by(id=run_id).first()
        if not run:
            logger.warning(f"Run {run_id} not found")
            return jsonify({'error': 'Run not found', 'run_id': run_id}), 404

        return jsonify({
            'run_id': str(run.id),
            'status': run.status,
            'graph_id': str(run.graph_id),
            'tier': run.tier,
            'converged': run.converged,
            'n_iterations': run.n_iterations,
            'final_residual': run.final_residual,
            'wall_time_s': run.wall_time,
            'created_at': run.created_at.isoformat(),
        }), 200
    except Exception as e:
        logger.error(f"Error getting run status {run_id}: {e}")
        return jsonify({'error': 'Failed to get run status', 'detail': str(e)}), 500


@bp.route('/<string:run_id>/results', methods=['GET'])
def run_results(run_id):
    """Return field summary and metadata for a completed run."""
    try:
        from app.design.models.simulation import SimulationRun
        run = SimulationRun.query.filter_by(id=run_id).first()
        if not run:
            logger.warning(f"Run {run_id} not found")
            return jsonify({'error': 'Run not found', 'run_id': run_id}), 404

        if run.status == 'queued' or run.status == 'running':
            logger.info(f"Run {run_id} still in progress (status={run.status})")
            return jsonify({
                'error': 'Run not complete',
                'run_id': str(run.id),
                'status': run.status,
                'message': f'Run is still {run.status}. Check back later.',
            }), 202  # Accepted but not ready

        if run.status == 'failed':
            logger.warning(f"Run {run_id} failed")
            return jsonify({
                'run_id': str(run.id),
                'status': 'failed',
                'error_message': run.error_message or 'Unknown error',
                'wall_time_s': run.wall_time,
            }), 200  # Return 200 with failed status

        result_path = str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver'))
        h5_path = f"{result_path}/{run_id}.h5"

        fields = []
        summary = {}
        try:
            import h5py
            import os
            if not os.path.exists(h5_path):
                logger.error(f"Results file not found: {h5_path}")
                return jsonify({
                    'error': 'Results file not found',
                    'run_id': str(run.id),
                    'expected_path': h5_path,
                }), 500

            with h5py.File(h5_path, 'r') as f:
                if 'fields' not in f:
                    logger.warning(f"No fields in HDF5 for run {run_id}")
                else:
                    for fname in f['fields']:
                        try:
                            ds = f[f'fields/{fname}/step_0']
                            arr = ds[:]
                            flat = arr.flatten()
                            fields.append({
                                'name': fname,
                                'type': 'nodal' if fname in ('displacement', 'displacement_magnitude', 'von_mises_nodal') else 'elemental',
                                'components': arr.shape[1] if arr.ndim > 1 else 1,
                                'data_min': float(flat.min()),
                                'data_max': float(flat.max()),
                            })
                        except Exception as e:
                            logger.warning(f"Could not read field {fname}: {e}")
                if 'attributes' in f:
                    summary = dict(f.attrs)
        except Exception as e:
            logger.error(f"Could not read HDF5 results for run {run_id}: {e}")
            # Return partial results with warning
            return jsonify({
                'run_id': str(run.id),
                'status': run.status,
                'converged': run.converged,
                'wall_time_s': run.wall_time,
                'n_iterations': run.n_iterations,
                'final_residual': run.final_residual,
                'mesh_stats': run.mesh_stats,
                'fields': fields,
                'summary': summary,
                'warning': f'Could not fully read results file: {str(e)}',
            }), 200

        return jsonify({
            'run_id': str(run.id),
            'status': run.status,
            'converged': run.converged,
            'wall_time_s': run.wall_time,
            'n_iterations': run.n_iterations,
            'final_residual': run.final_residual,
            'mesh_stats': run.mesh_stats,
            'fields': fields,
            'summary': summary,
        }), 200

    except Exception as e:
        logger.error(f"Error getting results for run {run_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get results', 'detail': str(e)}), 500


@bp.route('/<string:run_id>/field/<string:field_name>', methods=['GET'])
def get_field(run_id, field_name):
    """Return field values for rendering (matches CAEViewer format)."""
    step = int(request.args.get('step', 0))
    result_path = str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver'))
    h5_path = f"{result_path}/{run_id}.h5"

    try:
        import h5py
        with h5py.File(h5_path, 'r') as f:
            ds_path = f'fields/{field_name}/step_{step}'
            if ds_path not in f:
                return jsonify({'error': f"Field '{field_name}' step {step} not found"}), 404
            values = f[ds_path][:].tolist()
            flat = f[ds_path][:].flatten()
            data_min = float(flat.min())
            data_max = float(flat.max())

        return jsonify({
            'run_id': run_id,
            'field_name': field_name,
            'step': step,
            'values': values,
            'data_min': data_min,
            'data_max': data_max,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<string:run_id>/cancel', methods=['POST'])
def cancel_run(run_id):
    from app.design.models.simulation import SimulationRun
    run = SimulationRun.query.filter_by(id=run_id).first()
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    if run.status in ('queued', 'running'):
        from app.jobs.models import Job
        from app.jobs import request_cancel
        for job in Job.query.filter(Job.simulation_run_id == run.id,
                                    Job.status.in_(('queued', 'running'))).all():
            request_cancel(job.id)
        run.status = 'cancelled'
        db.session.commit()
        socketio.emit('solver_error', {'run_id': run_id, 'message': 'Cancelled by user'},
                      room=run_id)
    return jsonify({'run_id': run_id, 'status': run.status}), 200


# ── Adaptive meshing ──────────────────────────────────────────────────────────

@bp.route('/<string:graph_id>/run-adaptive', methods=['POST'])
def run_adaptive(graph_id):
    """Launch adaptive-mesh FEM simulation loop (FASE 3).

    Body (all optional):
    {
        "physics":     ["structural"],
        "tier":        1,
        "tolerance":   1e-8,
        "max_iterations": 1000,
        "material":    { "type":"linear_elastic_isotropic", "E":210e9, "nu":0.3, "rho":7800 },
        "bcs":  [{"node_set":"fixed", "dofs":[0,1,2], "values":[0,0,0]}],
        "loads":[{"node_set":"tip",   "force":[0,-1000,0]}],
        "max_cycles": 5,
        "target_error": 0.05,
        "refinement_fraction": 0.2
    }

    Returns: { run_id, hash, status } (synchronous in FASE 3)
    """
    from app.design.models.graph import DesignGraph
    from app.design.models.simulation import SimulationRun
    from app.design.services.traceability.hasher import SimulationHasher
    from app.design.services.fem.kernel import FEMKernel

    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}

    run_id = _uuid.uuid4()
    hasher = SimulationHasher()
    run_hash = hasher.compute_hash(
        graph_state={'graph_id': graph_id, 'version': graph.version},
        solver_config={k: v for k, v in data.items() if k not in ('nodes', 'elements')},
        mesh_stats={},
    )

    spec = dict(data)
    spec['graph_id'] = graph_id
    spec['mesh_source'] = spec.get('mesh_source', 'cantilever')
    spec['mesh_params'] = spec.get('mesh_params', {'length': 0.05, 'width': 0.01, 'height': 0.01, 'n_along_length': 10})

    run = SimulationRun(
        id=run_id,
        graph_id=graph_id,
        graph_version=graph.version,
        hash=run_hash,
        status='running',
        tier=int(data.get('tier', 1)),
        physics=data.get('physics', ['structural']),
        solver_config={k: v for k, v in data.items() if k not in ('nodes', 'elements')},
    )
    db.session.add(run)
    db.session.commit()

    try:
        kernel = FEMKernel()
        result = kernel.solve_adaptive_sync(
            solver_spec=spec,
            max_cycles=int(data.get('max_cycles', 5)),
            target_error=float(data.get('target_error', 0.05)),
            refinement_fraction=float(data.get('refinement_fraction', 0.2))
        )

        # Update run with results
        s = result['summary']
        run.status = 'done'
        run.converged = s.get('converged', False)
        run.n_iterations = s.get('n_iterations', 0)
        run.final_residual = s.get('final_residual')
        run.wall_time = s.get('wall_time_s', 0)
        run.mesh_stats = {
            'n_nodes': s.get('n_nodes'),
            'n_elements': s.get('n_elements'),
            'tier': s.get('tier'),
            'adaptive_cycles': len(result.get('adaptive_log', [])),
        }
        if 'adaptive_log' in result:
            run.adaptive_log = result['adaptive_log']
        db.session.commit()

        return jsonify({
            'run_id': str(run_id),
            'hash': run_hash[:16],
            'status': 'done',
            'graph_id': graph_id,
            'summary': s,
            'adaptive_log': result.get('adaptive_log', []),
        }), 200

    except Exception as exc:
        logger.error(f"Adaptive solve failed: {exc}", exc_info=True)
        run.status = 'failed'
        db.session.commit()
        return jsonify({'error': str(exc), 'run_id': str(run_id)}), 500


@bp.route('/<string:run_id>/convergence', methods=['GET'])
def convergence_log(run_id):
    from app.design.models.simulation import SimulationRun
    run = SimulationRun.query.filter_by(id=run_id).first()
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    return jsonify({
        'run_id': str(run.id),
        'convergence_log': run.convergence_log or [],
    }), 200


# ── Cantilever validation test ────────────────────────────────────────────────

@bp.route('/test/cantilever', methods=['GET'])
def test_cantilever():
    """Run the canonical cantilever beam validation synchronously.

    Compares FEM tip deflection with Euler-Bernoulli analytical solution.
    Hito FASE 2: error < 5% for T4 mesh.

    Query params:
        length:  [m]  default 0.05
        width:   [m]  default 0.01
        height:  [m]  default 0.01
        E:       [Pa] default 210e9
        nu:            default 0.3
        force_y: [N]  default 1000 (applied in -Y direction at tip)
        n_div:         default 12 (elements along length)
    """
    from app.design.services.fem.kernel import FEMKernel
    import time

    L  = float(request.args.get('length',  0.050))
    W  = float(request.args.get('width',   0.010))
    H  = float(request.args.get('height',  0.010))
    E  = float(request.args.get('E',       210e9))
    nu = float(request.args.get('nu',      0.3))
    Fy = float(request.args.get('force_y', 1000.0))
    nd = int(request.args.get('n_div',     12))

    spec = {
        'physics': ['structural'],
        'mesh_source': 'cantilever',
        'mesh_params': {'length': L, 'width': W, 'height': H, 'n_along_length': nd},
        'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu, 'rho': 7800.0},
        'bcs':  [{'node_set': 'fixed', 'dofs': [0, 1, 2], 'values': [0.0, 0.0, 0.0]}],
        'loads': [{'node_set': 'tip', 'force': [0.0, -Fy, 0.0]}],
    }

    t0 = time.perf_counter()
    try:
        kernel = FEMKernel()
        result = kernel.solve_sync(spec)
        s = result['summary']

        analytical = FEMKernel.cantilever_analytical(E, nu, L, W, H, Fy)

        fem_tip_mm = s['max_displacement_mm']
        ana_tip_mm = analytical['tip_deflection_mm']
        rel_err_pct = abs(fem_tip_mm - ana_tip_mm) / ana_tip_mm * 100.0

        return jsonify({
            'status': 'ok',
            'fem': {
                'tip_deflection_mm': fem_tip_mm,
                'max_von_mises_mpa': s['max_von_mises_mpa'],
                'n_nodes': s['n_nodes'],
                'n_elements': s['n_elements'],
                'tier': s['tier'],
                'converged': s['converged'],
                'solver': s['solver_method'],
                'wall_time_s': s['wall_time_s'],
            },
            'analytical': {
                'tip_deflection_mm': ana_tip_mm,
                'max_bending_stress_mpa': analytical['max_bending_stress_mpa'],
                'I_m4': analytical['I_m4'],
            },
            'validation': {
                'relative_error_pct': round(rel_err_pct, 3),
                'pass_5pct': rel_err_pct <= 5.0,
                'pass_1pct': rel_err_pct <= 1.0,
            },
            'params': {'L': L, 'W': W, 'H': H, 'E': E, 'nu': nu, 'F': Fy, 'n_div': nd},
        }), 200

    except Exception as exc:
        logger.error(f"Cantilever test failed: {exc}", exc_info=True)
        return jsonify({'error': str(exc)}), 500
