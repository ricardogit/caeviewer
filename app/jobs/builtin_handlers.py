"""Built-in job handlers. Imported lazily by handlers.get_handler()."""
import platform
import socket
import time

from app.jobs.handlers import handler, JobCancelled, SocketIOProxy


@handler('dummy', queue='default', api_enqueueable=True)
def dummy(ctx, payload):
    """Fase 0 smoke test: N steps of sleep with progress, optional forced failure."""
    steps = max(1, min(int(payload.get('steps', 10)), 600))
    delay = max(0.0, min(float(payload.get('delay_s', 0.5)), 10.0))
    for i in range(steps):
        ctx.check_cancel()
        time.sleep(delay)
        ctx.progress(100.0 * (i + 1) / steps, f"Paso {i + 1}/{steps}", force=True)
        if payload.get('fail_at') == i + 1:
            raise RuntimeError(f"Fallo forzado en el paso {i + 1}")
    return {
        'steps': steps,
        'host': socket.gethostname(),
        'platform': platform.platform(),
        'python': platform.python_version(),
    }


@handler('fem.solve', queue='solve')
def fem_solve(ctx, payload):
    """Native FEMKernel solve for a SimulationRun (replaces the in-process thread)."""
    from flask import current_app
    from app.design.services.fem.kernel import FEMKernel
    from app.design.models.simulation import SimulationRun
    from app.extensions import db

    run_id = payload['run_id']
    spec = payload['spec']
    kernel = FEMKernel()
    proxy = SocketIOProxy(ctx)
    kernel.solve_async(app=current_app._get_current_object(), run_id=run_id,
                       solver_spec=spec, socketio=proxy)

    db.session.expire_all()
    run = db.session.get(SimulationRun, run_id)
    if ctx.cancelled:
        if run is not None:
            run.status = 'cancelled'
            db.session.commit()
        raise JobCancelled()
    if run is None:
        raise RuntimeError(f"SimulationRun {run_id} disappeared during solve")
    if run.status != 'done':
        # solve_async swallows exceptions after emitting solver_error; surface them on the job.
        raise RuntimeError(proxy.last_error or f"Solver terminó con estado '{run.status}'")
    return {'run_id': run_id, 'status': run.status, 'wall_time': run.wall_time,
            'converged': run.converged, 'n_iterations': run.n_iterations}


@handler('topology.simp', queue='solve')
def topology_simp(ctx, payload):
    """FASE 4: SIMP topology optimization for a SimulationRun (purpose='topology')."""
    from app.design.services.topology.runner import run_topology
    return run_topology(ctx, payload['run_id'], payload['spec'])
