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
        'supported_elements': ['T4', 'T10', 'T3'],
        'mesh_sources': ['geometry', 'cantilever', 'cae_mesh', 'inline'],
    }), 200


PHYSICS_LABELS = {
    ('structural',): 'Estructural 3D (elástico lineal)',
    ('thermal',): 'Térmico estacionario 3D (conducción)',
    ('structural', 'thermal'): 'Termo-mecánico 3D (térmico → estructural)',
}


def prepare_spec(graph_id: str, data: dict, adjust=None, allow_thermal: bool = False):
    """Merge the graph's solver spec under the request body, validate tier and check tier
    limits (413) before anything is enqueued. ``adjust(data)`` runs before the size check
    (e.g. topology forces linear elements). Returns (spec, None) or (None, (response, code)).
    Topology / ROM / uncertainty are structural only: thermal studies get a clear 422.
    """
    from app.design.services.graph_to_solver_spec import graph_to_solver_spec
    # Validate tier if provided
    if 'tier' in data:
        try:
            tier = int(data['tier'])
            if tier not in (0, 1, 2, 3):
                return None, (jsonify({'error': 'Tier must be 0-3', 'got': tier}), 422)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid tier: {e}")
            return None, (jsonify({'error': 'Tier must be integer 0-3'}), 422)

    # Read spec from graph if needed (request body values have priority)
    if 'material' not in data or 'bcs' not in data or 'loads' not in data:
        from app.design.services.graph_to_solver_spec import GraphSpecError
        try:
            graph_spec = graph_to_solver_spec(graph_id)
        except GraphSpecError as e:
            return None, (jsonify({'error': str(e), 'kind': 'graph_spec'}), 422)
        except Exception as e:
            logger.warning(f"Could not read graph spec for {graph_id}: {e}", exc_info=True)
            graph_spec = {}
        body_mesh = 'mesh_source' in data
        for k, v in graph_spec.items():
            if k in ('mesh_params', 'mesh_id', 'geometry_id') and body_mesh:
                continue        # the body chose its own mesh; don't mix in the graph's
            data.setdefault(k, v)

    if not allow_thermal and 'thermal' in (data.get('physics') or []):
        return None, (jsonify({'error': 'Esta herramienta solo admite estudios estructurales; el estudio '
                                        'tiene condiciones térmicas (usa Simular).',
                               'kind': 'physics_unsupported', 'physics': data.get('physics')}), 422)
    if adjust:
        adjust(data)
        adjust = None
    # Tier limits before enqueueing (plan: reject with 413). Exact when the mesh
    # is known/cached, otherwise a pre-meshing estimate; the worker re-checks exactly.
    from app.design.services.fem.sizing import estimate_problem_size
    from app.design.services.fem.solver import TIER_LIMITS, check_tier_limits, TierLimitExceeded
    try:
        size = estimate_problem_size(data)
    except Exception as e:
        logger.warning(f"Size estimate failed for graph {graph_id}: {e}")
        size = None
    if size:
        # no declared tier = auto (smallest that fits), so only the absolute limit applies
        tier_req = int(data['tier']) if 'tier' in data else 3
        try:
            check_tier_limits(size['n_nodes'], size['n_elements'], size['n_dof'], tier_req)
        except TierLimitExceeded as e:
            return None, (jsonify({**e.to_dict(), 'tier': tier_req, 'size': size,
                            'limits': TIER_LIMITS[tier_req],
                            'message': ('Tamaño estimado' if size.get('estimated') else 'Tamaño')
                            + f" fuera del Tier {tier_req}: " + '; '.join(e.violations)}), 413)

    # Validate required parameters
    if not data.get('material'):
        data['material'] = {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800}
    if not data.get('bcs'):
        logger.warning(f"No boundary conditions for run {graph_id}")
    if not data.get('loads'):
        logger.warning(f"No loads for run {graph_id}")
    return data, None


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

        data, err = prepare_spec(graph_id, data, allow_thermal=True)
        if err:
            return err

        spec = dict(data)
        spec['graph_id'] = graph_id
        try:
            run, job = _create_and_enqueue(graph, spec, purpose='run')
        except Exception as e:
            logger.error(f"Failed to create SimulationRun record: {e}", exc_info=True)
            db.session.rollback()
            return jsonify({'error': 'Failed to create simulation record', 'detail': str(e)}), 500

        logger.info(f"Launched simulation run {run.id} for graph {graph_id}")
        return jsonify({
            'run_id': str(run.id),
            'hash': run.hash,
            'status': 'queued',
            'graph_id': graph_id,
            'job_id': str(job.id),
            'parent_run_id': str(run.parent_run_id) if run.parent_run_id else None,
            'parameter_delta': run.parameter_delta or {},
        }), 202

    except Exception as e:
        logger.error(f"Unexpected error in run_simulation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500


def _create_and_enqueue(graph, spec: dict, purpose: str = 'run', parent=None):
    """Create the SimulationRun (hash, canonical inputs, lineage) and enqueue fem.solve.

    Lineage (FASE 7): a normal run's parent is the latest finished run of the same graph (or of
    its earlier versions, FASE 9) and
    ``parameter_delta`` lists what changed in the canonical inputs; a reproduction's parent is
    the run being reproduced.
    """
    from app.design.models.simulation import SimulationRun
    from app.design.services.traceability.hasher import fingerprint, parameter_delta, provenance
    from app.jobs import enqueue

    fp = fingerprint(spec)
    if parent is None and purpose in ('run', 'topology', 'rom', 'uncertainty'):
        # the previous finished run of this version, else of the earlier versions (FASE 9 tree)
        g, seen = graph, set()
        while g is not None and parent is None and g.id not in seen:
            seen.add(g.id)
            parent = (SimulationRun.query
                      .filter(SimulationRun.graph_id == g.id, SimulationRun.status == 'done',
                              SimulationRun.purpose == purpose)
                      .order_by(SimulationRun.created_at.desc()).first())
            g = db.session.get(type(graph), g.parent_id) if g.parent_id else None
    run = SimulationRun(
        id=_uuid.uuid4(),
        graph_id=graph.id,
        graph_version=graph.version,
        hash=fp['hash'],
        purpose=purpose,
        inputs=fp['inputs'],
        environment=fp['environment'],
        provenance=provenance(),
        status='queued',
        tier=int(spec.get('tier', 1)),
        physics=spec.get('physics', ['structural']),
        solver_config={k: v for k, v in spec.items() if k not in ('nodes', 'elements', 'graph_id')},
        parent_run_id=parent.id if parent is not None else None,
        parameter_delta=(parameter_delta(parent.inputs, fp['inputs'])
                         if parent is not None and parent.inputs is not None else {}),
    )
    db.session.add(run)
    db.session.commit()
    # Enqueue on the 'solve' queue; a worker process (python -m app.jobs.worker --queues solve)
    # runs FEMKernel.solve_async and its socket events are forwarded to room=run_id.
    kind = ('uncertainty.mc' if 'uncertainty' in spec else 'topology.simp' if 'topology' in spec
            else 'rom.build' if 'rom' in spec else 'fem.solve')
    job = enqueue(kind, {'run_id': str(run.id), 'spec': spec}, simulation_run_id=run.id)
    return run, job


# ── Traceability (FASE 7) ─────────────────────────────────────────────────────

@bp.route('/runs', methods=['GET'])
def list_runs():
    """Simulation history. Query: graph_id, hash, limit (default 50)."""
    from app.design.models.simulation import SimulationRun
    q = SimulationRun.query
    if request.args.get('graph_id'):
        q = q.filter(SimulationRun.graph_id == request.args['graph_id'])
    if request.args.get('hash'):
        q = q.filter(SimulationRun.hash == request.args['hash'])
    limit = max(1, min(int(request.args.get('limit', 50)), 500))
    runs = q.order_by(SimulationRun.created_at.desc()).limit(limit).all()
    items = [r.to_history_dict() for r in runs]
    counts = {}
    for it in items:
        counts[it['hash']] = counts.get(it['hash'], 0) + 1
    for it in items:
        it['same_hash_runs'] = counts[it['hash']]
    return jsonify({'runs': items, 'count': len(items)}), 200


def _load_h5_arrays(run_id, names=('displacement', 'von_mises_nodal')):
    import os
    import h5py
    import numpy as np
    from app.design.services.topology.runner import result_path
    topo = result_path(run_id)
    if os.path.exists(topo):                      # topology run: compare densities + displacement
        with np.load(topo, allow_pickle=False) as z:
            return {'displacement': z['u'], 'von_mises_nodal': z['densities']}
    path = f"{current_app.config.get('SOLVER_DATA_DIR', 'data/solver')}/{run_id}.h5"
    out = {}
    with h5py.File(path, 'r') as f:
        for n in names:
            ds = f'fields/{n}/step_0'
            if ds in f:
                out[n] = np.asarray(f[ds][:], dtype=float)
    return out


def _delta(a, b):
    from app.design.services.traceability.hasher import parameter_delta
    return parameter_delta(a, b) if a is not None and b is not None else {}


def _compare_runs(run, ref) -> dict:
    """Reproducibility of ``run`` against ``ref``: hashes and max field differences."""
    import numpy as np
    from app.design.services.traceability.hasher import environment_diff
    out = {
        'run_id': str(run.id), 'reference_run_id': str(ref.id),
        'status': run.status, 'reference_status': ref.status,
        'same_hash': run.hash == ref.hash,
        'same_mesh': bool(run.mesh_hash) and run.mesh_hash == ref.mesh_hash,
        'bitwise_identical': bool(run.result_hash) and run.result_hash == ref.result_hash,
        'environment_diff': environment_diff(ref.environment or {}, run.environment or {}),
        'input_diff': _delta(ref.inputs, run.inputs),
        'max_rel_diff_displacement': None, 'max_rel_diff_von_mises': None,
    }
    if run.status == 'done' and ref.status == 'done' and out['same_mesh']:
        try:
            a, b = _load_h5_arrays(run.id), _load_h5_arrays(ref.id)
            for key, name in (('max_rel_diff_displacement', 'displacement'),
                              ('max_rel_diff_von_mises', 'von_mises_nodal')):
                if name in a and name in b and a[name].shape == b[name].shape:
                    scale = max(float(np.abs(b[name]).max()), 1e-300)
                    out[key] = float(np.abs(a[name] - b[name]).max() / scale)
        except Exception as e:
            out['warning'] = f'No se pudieron comparar los campos: {e}'
    out['reproduced'] = bool(out['same_hash'] and (out['bitwise_identical'] or (
        out['max_rel_diff_displacement'] is not None and out['max_rel_diff_displacement'] < 1e-9)))
    return out


@bp.route('/<string:run_id>/reproducibility', methods=['GET'])
def reproducibility(run_id):
    """Compare a run with ?against=<run_id> (default: its parent)."""
    from app.design.models.simulation import SimulationRun
    run = db.session.get(SimulationRun, run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    ref_id = request.args.get('against') or run.parent_run_id
    ref = db.session.get(SimulationRun, ref_id) if ref_id else None
    if not ref:
        return jsonify({'error': 'No reference run (use ?against=<run_id>)'}), 404
    return jsonify(_compare_runs(run, ref)), 200


@bp.route('/<string:run_id>/report', methods=['GET'])
def run_report(run_id):
    """Run report. ?format=markdown (default) | jsonld; ?download=1 as attachment."""
    from flask import Response
    from app.design.models.simulation import SimulationRun
    from app.design.services.traceability.reporter import AutoReporter
    run = db.session.get(SimulationRun, run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    fmt = request.args.get('format', 'markdown').lower()
    reporter = AutoReporter(base_url=request.host_url.rstrip('/'))
    if fmt == 'jsonld':
        body = jsonify(reporter.generate_jsonld(run))
        body.mimetype = 'application/ld+json'
        if request.args.get('download'):
            body.headers['Content-Disposition'] = f'attachment; filename=run_{run.hash[:12]}.jsonld'
        return body, 200
    repro = None
    if run.purpose == 'reproduce' and run.parent_run_id:
        ref = db.session.get(SimulationRun, run.parent_run_id)
        if ref:
            repro = _compare_runs(run, ref)
    md = reporter.generate_markdown(run, reproducibility=repro)
    headers = {}
    if request.args.get('download'):
        headers['Content-Disposition'] = f'attachment; filename=run_{run.hash[:12]}.md'
    return Response(md, mimetype='text/markdown', headers=headers)


@bp.route('/<string:run_id>/reproduce', methods=['POST'])
def reproduce_run(run_id):
    """Re-run exactly the stored spec of a run.

    Rejects with 409 if the numerical environment differs from the recorded one (the result
    would not be comparable), unless the body has {"force": true}.
    """
    from app.design.models.graph import DesignGraph
    from app.design.models.simulation import SimulationRun
    from app.design.services.traceability.hasher import environment_diff
    run = db.session.get(SimulationRun, run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    if run.purpose == 'adaptive':
        return jsonify({'error': 'Las corridas adaptativas no se pueden reproducir todavía'}), 422
    if run.status != 'done':
        return jsonify({'error': 'Solo se reproducen corridas completadas'}), 422
    if run.solver_config is None or run.inputs is None:
        return jsonify({'error': 'Corrida anterior a FASE 7: no guarda sus entradas canónicas'}), 422
    # a reproduction of a reproduction is compared against the original
    original = run
    if run.purpose == 'reproduce' and run.parent_run_id:
        original = db.session.get(SimulationRun, run.parent_run_id) or run
    body = request.get_json(silent=True) or {}
    diff = environment_diff(original.environment or {})
    if diff and not body.get('force'):
        return jsonify({'error': 'EnvironmentMismatch',
                        'message': 'El entorno numérico actual difiere del registrado; el resultado '
                                   'puede no ser idéntico.',
                        'environment_diff': diff}), 409
    graph = db.session.get(DesignGraph, run.graph_id)
    if graph is None:
        return jsonify({'error': 'Graph not found'}), 404
    spec = dict(original.solver_config or {})
    spec['graph_id'] = str(original.graph_id)
    new, job = _create_and_enqueue(graph, spec, purpose='reproduce', parent=original)
    return jsonify({'run_id': str(new.id), 'job_id': str(job.id), 'hash': new.hash,
                    'same_hash': new.hash == original.hash, 'reproduces': str(original.id),
                    'environment_diff': diff, 'status': 'queued'}), 202


@bp.route('/environment', methods=['GET'])
def current_environment():
    """Numerical environment of this process (what a new run would hash)."""
    from app.design.services.traceability.hasher import numerical_environment
    return jsonify(numerical_environment()), 200


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
            'hash': run.hash,
            'purpose': run.purpose,
            'mesh_hash': run.mesh_hash,
            'result_hash': run.result_hash,
            'parent_run_id': str(run.parent_run_id) if run.parent_run_id else None,
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
            err = (run.mesh_stats or {}).get('error')
            if not err:
                from app.jobs.models import Job
                job = Job.query.filter_by(simulation_run_id=run.id).order_by(Job.created_at.desc()).first()
                err = job.error if job else None
            return jsonify({
                'run_id': str(run.id),
                'status': 'failed',
                'error_message': err or 'Unknown error',
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
                if 'summary_json' in f.attrs:
                    import json as _json
                    summary = _json.loads(f.attrs['summary_json'])
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
    from app.design.services.traceability.hasher import fingerprint, provenance
    from app.design.services.fem.kernel import FEMKernel

    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        return jsonify({'error': 'Graph not found'}), 404

    data = request.get_json(silent=True) or {}
    if 'thermal' in (data.get('physics') or []):
        return jsonify({'error': 'El refinamiento adaptativo solo admite análisis estructural.',
                        'kind': 'physics_unsupported'}), 422

    run_id = _uuid.uuid4()
    spec = dict(data)
    spec['graph_id'] = graph_id
    spec['mesh_source'] = spec.get('mesh_source', 'cantilever')
    spec['mesh_params'] = spec.get('mesh_params', {'length': 0.05, 'width': 0.01, 'height': 0.01, 'n_along_length': 10})
    fp = fingerprint(spec, adaptive={'max_cycles': int(data.get('max_cycles', 5)),
                                     'target_error': float(data.get('target_error', 0.05)),
                                     'refinement_fraction': float(data.get('refinement_fraction', 0.2))})
    run_hash = fp['hash']

    run = SimulationRun(
        id=run_id,
        graph_id=graph_id,
        graph_version=graph.version,
        hash=run_hash,
        purpose='adaptive',
        inputs=fp['inputs'],
        environment=fp['environment'],
        provenance=provenance(),
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
        from app.design.services.fem.kernel import _json_safe
        run.summary = _json_safe({k: v for k, v in s.items() if k != 'convergence_log'})
        db.session.commit()

        return jsonify({
            'run_id': str(run_id),
            'hash': run_hash,
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
    """Canonical cantilever validation (synchronous).

    Tip deflection = mean uy over the tip face, compared with Euler-Bernoulli and
    Timoshenko (shear coefficient k = 10(1+ν)/(12+11ν), rectangular section).
    FASE 2 hito: T10 within ±1 % of Timoshenko on a slender beam (L/h ≥ 10); on
    stubby beams the fully clamped face stiffens the 3D model by ~1-2 % (Poisson
    restraint), which neither beam theory captures.

    Query params: length/width/height [m] (0.2/0.01/0.01), E [Pa], nu, force_y [N]
    (applied in -Y at the tip face), n_div (20), order (1 = T4, 2 = T10; default 2).
    """
    from app.design.services.fem.kernel import FEMKernel
    import numpy as np

    L  = float(request.args.get('length',  0.200))
    W  = float(request.args.get('width',   0.010))
    H  = float(request.args.get('height',  0.010))
    E  = float(request.args.get('E',       210e9))
    nu = float(request.args.get('nu',      0.3))
    Fy = float(request.args.get('force_y', 1000.0))
    nd = int(request.args.get('n_div',     20))
    order = int(request.args.get('order',  2))
    if order not in (1, 2):
        return jsonify({'error': 'order debe ser 1 (T4) o 2 (T10)'}), 400

    spec = {
        'physics': ['structural'],
        'mesh_source': 'cantilever',
        'mesh_params': {'length': L, 'width': W, 'height': H, 'n_along_length': nd, 'order': order},
        'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu, 'rho': 7800.0},
        'bcs':  [{'face_set': 'fixed', 'dofs': [0, 1, 2], 'values': [0.0, 0.0, 0.0]}],
        'loads': [{'face_set': 'tip', 'force': [0.0, -Fy, 0.0]}],
    }

    try:
        result = FEMKernel().solve_sync(spec)
        s = result['summary']
        mesh = result['mesh']
        tip_nodes = np.unique(mesh.face_sets['tip'])
        uy = np.asarray(result['displacement'])[tip_nodes, 1]
        fem_tip_mm = float(-uy.mean() * 1000.0)

        ana = FEMKernel.cantilever_analytical(E, nu, L, W, H, Fy)
        G = E / (2.0 * (1.0 + nu))
        k = 10.0 * (1.0 + nu) / (12.0 + 11.0 * nu)
        timo_mm = (ana['tip_deflection_m'] + Fy * L / (k * G * W * H)) * 1000.0
        err_eb = (fem_tip_mm - ana['tip_deflection_mm']) / ana['tip_deflection_mm'] * 100.0
        err_ti = (fem_tip_mm - timo_mm) / timo_mm * 100.0

        return jsonify({
            'status': 'ok',
            'fem': {
                'tip_deflection_mm': round(fem_tip_mm, 6),
                'element_type': s['element_type'],
                'max_von_mises_mpa': s['max_von_mises_mpa'],
                'n_nodes': s['n_nodes'],
                'n_elements': s['n_elements'],
                'tier': s['tier'],
                'converged': s['converged'],
                'solver': s['solver_method'],
                'wall_time_s': s['wall_time_s'],
                'equilibrium_error': s['equilibrium_error'],
            },
            'analytical': {
                'tip_deflection_mm': ana['tip_deflection_mm'],
                'timoshenko_tip_deflection_mm': round(timo_mm, 6),
                'max_bending_stress_mpa': ana['max_bending_stress_mpa'],
                'I_m4': ana['I_m4'],
                'slenderness': round(L / H, 2),
            },
            'validation': {
                'reference': 'timoshenko',
                'relative_error_pct': round(err_ti, 3),
                'relative_error_eb_pct': round(err_eb, 3),
                'pass_5pct': abs(err_ti) <= 5.0,
                'pass_1pct': abs(err_ti) <= 1.0,
            },
            'params': {'L': L, 'W': W, 'H': H, 'E': E, 'nu': nu, 'F': Fy, 'n_div': nd, 'order': order},
        }), 200

    except Exception as exc:
        logger.error(f"Cantilever test failed: {exc}", exc_info=True)
        return jsonify({'error': str(exc)}), 500


# ── FASE 9: unified workspace ────────────────────────────────────────────────

@bp.route('/<string:run_id>/surface', methods=['GET'])
def run_surface(run_id):
    """Binary surface pack of a finished run for the Results viewer (binpack layout):
    xyz [mm] float32 (n,3) · tris uint32 (m,3) · u [mm] float32 (n,3) · vm [MPa] float32 (n,)
    over the surface nodes only (indices compacted)."""
    import json
    import os
    import h5py
    import numpy as np
    from flask import Response
    from app.design.models.simulation import SimulationRun
    from app.design.services.binpack import pack_arrays
    try:
        import uuid as _u
        run = SimulationRun.query.filter_by(id=_u.UUID(run_id)).first()
    except ValueError:
        run = None
    if run is None:
        return jsonify({'error': 'Run not found'}), 404
    if run.status != 'done':
        return jsonify({'error': f'El run no ha terminado ({run.status}).', 'status': run.status}), 409
    path = os.path.join(str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver')), f'{run.id}.h5')
    if not os.path.exists(path):
        return jsonify({'error': 'Este run no tiene campos 3D (archivo de resultados no encontrado).'}), 404
    with h5py.File(path, 'r') as f:
        has_u = 'fields/displacement/step_0' in f
        has_t = 'fields/temperature/step_0' in f
        if 'surface_triangles' not in f or not (has_u or has_t):
            return jsonify({'error': 'El run no tiene superficie ni campos guardados.'}), 404
        X = f['nodes'][:]
        tris = np.asarray(f['surface_triangles'][:], np.int64)
        U = f['fields/displacement/step_0'][:] if has_u else np.zeros((len(X), 3))
        vm = f['fields/von_mises_nodal/step_0'][:] if 'fields/von_mises_nodal/step_0' in f else np.zeros(len(X))
        T = f['fields/temperature/step_0'][:] if has_t else None
        Q = f['fields/heat_flux_nodal/step_0'][:] if 'fields/heat_flux_nodal/step_0' in f else None
        summary = {}
        if 'summary_json' in f.attrs:
            summary = json.loads(f.attrs['summary_json'])
    used, inv = np.unique(tris.ravel(), return_inverse=True)
    t = inv.reshape(-1, 3).astype(np.uint32)
    xyz = (X[used] * 1000.0).astype(np.float32)
    u = (U[used] * 1000.0).astype(np.float32)
    v = (np.asarray(vm, float)[used] / 1e6).astype(np.float32)
    umag_all = np.linalg.norm(U, axis=1)
    fields = (['u', 'vm'] if has_u else []) + (['T', 'q'] if has_t else [])
    header = {
        'run_id': str(run.id), 'graph_id': str(run.graph_id), 'purpose': run.purpose,
        'created_at': run.created_at.isoformat() if run.created_at else None,
        'units': {'xyz': 'mm', 'u': 'mm', 'vm': 'MPa', **({'T': '°C', 'q': 'W/m²'} if has_t else {})},
        'fields': fields, 'physics': summary.get('physics') or ['structural'],
        'n_surface_nodes': int(len(used)), 'n_triangles': int(len(t)),
        'max_u_mm': float(umag_all.max() * 1000.0), 'max_vm_mpa': float(np.max(vm) / 1e6) if len(vm) else 0.0,
        'bbox_mm': [xyz.min(0).tolist(), xyz.max(0).tolist()],
        'summary': summary, 'material': ((run.solver_config or {}).get('material') or {}),
    }
    arrays = [('xyz', xyz), ('tris', t), ('u', u), ('vm', v)]
    if has_t:
        header['min_T'], header['max_T'] = float(T.min()), float(T.max())
        arrays.append(('T', np.asarray(T, float)[used].astype(np.float32)))
        qm = np.linalg.norm(Q, axis=1) if Q is not None else np.zeros(len(X))
        header['max_q'] = float(qm.max()) if len(qm) else 0.0
        arrays.append(('q', qm[used].astype(np.float32)))
    body = pack_arrays(header, arrays)
    return Response(body, mimetype='application/octet-stream',
                    headers={'Cache-Control': 'private, max-age=3600'})


@bp.route('/<string:graph_id>/preflight', methods=['GET'])
def preflight(graph_id):
    """Everything the workspace shows about a study before simulating (plan §9.4): graph
    completeness, physics, problem size and the smallest tier that fits vs the declared one,
    confidence factor from validated similar cases, and the latest run."""
    from app.design.models.graph import DesignGraph
    from app.design.models.simulation import SimulationRun
    from app.design.services.graph_service import DesignGraphService
    from app.design.services.graph_to_solver_spec import graph_to_solver_spec, GraphSpecError
    from app.design.services.fem.sizing import estimate_problem_size
    from app.design.services.fem.solver import TIER_LIMITS
    try:
        import uuid as _u
        g = DesignGraph.query.filter_by(id=_u.UUID(graph_id)).first()
    except ValueError:
        g = None
    if g is None:
        return jsonify({'error': 'Graph not found'}), 404
    issues = DesignGraphService().validate_completeness(graph_id)
    out = {'graph_id': graph_id, 'name': g.name, 'version': g.version, 'status': g.status,
           'issues': issues, 'ready': not any(i['severity'] == 'error' for i in issues),
           'physics': ['structural'], 'physics_label': 'Estructural 3D (elástico lineal)',
           'size': None, 'tier_declared': None, 'tier_needed': None, 'tier_ok': None,
           'confidence': None, 'latest_run': None}
    try:
        spec = graph_to_solver_spec(graph_id)
        out['physics'] = sorted(spec.get('physics') or ['structural'])
        out['physics_label'] = PHYSICS_LABELS.get(tuple(out['physics']), ' + '.join(out['physics']))
        out['tier_declared'] = int(spec.get('tier', g.tier if g.tier is not None else 1))
        out['mesh_source'] = spec.get('mesh_source')
        size = estimate_problem_size(spec)
        if size:
            out['size'] = size
            need = next((t for t in sorted(TIER_LIMITS) if size['n_dof'] <= TIER_LIMITS[t]['max_dof']
                         and size['n_nodes'] <= TIER_LIMITS[t]['max_nodes']
                         and size['n_elements'] <= TIER_LIMITS[t]['max_elements']), None)
            out['tier_needed'] = need
            out['tier_ok'] = need is not None and need <= out['tier_declared']
    except GraphSpecError as e:
        out['issues'] = issues + [{'severity': 'error', 'message': str(e), 'node_id': None}]
        out['ready'] = False
    except Exception as e:                                         # size estimate is best-effort
        logger.warning(f'preflight size estimate failed for {graph_id}: {e}')
    try:
        from app.design.services.validation.correlator import SimulationCorrelator
        sc = SimulationCorrelator()
        similar = sc.find_similar_runs(graph_id, top_k=5)
        out['confidence'] = {'factor': sc.compute_confidence_factor(similar), 'n_similar': len(similar)}
    except Exception as e:
        logger.info(f'preflight confidence unavailable for {graph_id}: {e}')
    run = (SimulationRun.query.filter(SimulationRun.graph_id == g.id,
                                      SimulationRun.purpose.in_(('run', 'reproduce', 'adaptive')))
           .order_by(SimulationRun.created_at.desc()).first())
    if run is not None:
        out['latest_run'] = run.to_history_dict()
    return jsonify(out), 200
