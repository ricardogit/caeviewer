"""Uncertainty-propagation job (FASE 6): spec → evaluator (ROM or full) → Monte Carlo → files.

Runs are SimulationRun(purpose='uncertainty') with the setup under spec['uncertainty']:
  {distributions: {key: {mean, std}}, n_samples, confidence, seed, failure: {yield_mean, yield_std},
   method: 'rom'|'full', rom_id, rom_hash, material_id}
Files: SOLVER_DATA_DIR/uncertainty/<run_id>/result.npz (surface fields + samples).
Socket events (room = run_id): uncertainty_progress | uncertainty_done | uncertainty_error.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np


def run_dir(run_id) -> Path:
    from flask import current_app
    return Path(str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver'))) / 'uncertainty' / str(run_id)


def result_path(run_id) -> str:
    return str(run_dir(run_id) / 'result.npz')


def sample_cap(method: str, tier: int) -> int:
    from app.design.services.material.uncertainty import TIER_MC_SAMPLES, MAX_ROM_SAMPLES
    return MAX_ROM_SAMPLES if method == 'rom' else TIER_MC_SAMPLES.get(int(tier), 100)


def make_evaluator(spec: dict, kernel=None, progress=None, check_cancel=None):
    """Evaluator for spec['uncertainty'] (ROM from its file, or full solves on the study mesh)."""
    from app.design.services.material.uncertainty import ROMEvaluator, FullEvaluator, UncertaintyError
    cfg = spec['uncertainty']
    if cfg.get('method') == 'rom':
        from app.design.services.rom.online_solver import online_solver
        from app.design.services.rom.runner import rom_path
        path = rom_path(cfg['rom_id'])
        if not os.path.exists(path):
            raise UncertaintyError('El ROM indicado no tiene archivo (¿borrado o sin terminar?).')
        return ROMEvaluator(online_solver().load_rom(str(cfg['rom_id']), path)), None
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.solver import check_tier_limits
    from app.design.services.rom.pod import PODROMBuilder
    kernel = kernel or FEMKernel()
    mesh, meta = kernel._build_mesh(spec, progress=progress)
    tier = int(spec.get('tier', mesh.estimate_tier()))
    check_tier_limits(mesh.n_nodes, mesh.n_elements, mesh.n_dof_structural, tier)
    # the builder is used only for its affine full-order operators; the box is informative
    space = {}
    for k, d in cfg['distributions'].items():
        m, s = float(d['mean']), float(d.get('std') or 0)
        if s > 0:
            lo, hi = m - 4 * s, m + 4 * s
            if k == 'nu':
                lo, hi = max(lo, 0.0), min(hi, 0.499)
            elif k in ('E', 'rho'):
                lo = max(lo, 1e-6 * m)
            space[k] = [lo, hi]
    if not space:
        raise UncertaintyError('Ninguna variable aleatoria con desviación > 0.')
    b = PODROMBuilder(mesh, spec, space, {'n_snapshots': 2, 'n_test': 0}, check_cancel=check_cancel)
    return FullEvaluator(b), mesh


def run_uncertainty(ctx, run_id: str, spec: dict) -> dict:
    from app.extensions import db
    from app.design.models.simulation import SimulationRun
    from app.design.services.fem.kernel import FEMKernel, _json_safe
    from app.design.services.material.uncertainty import UncertaintyPropagator
    from app.design.services.traceability.hasher import array_hash

    kernel = FEMKernel()
    room = str(run_id)
    t0 = time.perf_counter()

    def emit(event, data):
        ctx.emit_socket(event, {'run_id': room, **data}, room)

    def progress(pct, msg):
        ctx.progress(pct, msg, force=True)
        emit('uncertainty_progress', {'percent': round(pct, 1), 'status': msg})

    kernel._update_run(run_id, 'running')
    kernel._record_fingerprint(run_id, spec)
    try:
        cfg = spec['uncertainty']
        progress(1, 'Preparando evaluador (ROM)' if cfg.get('method') == 'rom' else 'Mallando y ensamblando')
        evaluator, mesh = make_evaluator(spec, kernel, progress=lambda m: progress(1, m),
                                         check_cancel=ctx.check_cancel)
        prop = UncertaintyPropagator(progress=lambda p, m: progress(3 + 0.95 * p, m), check_cancel=ctx.check_cancel)
        out = prop.propagate_monte_carlo(evaluator, cfg['distributions'], int(cfg['n_samples']),
                                         float(cfg.get('confidence', 0.95)), int(cfg.get('seed', 0)),
                                         cfg.get('failure'))
        res, surf, smp = out['result'], out['surface'], out['samples']
        d = run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'result.tmp.npz'
        np.savez(tmp, **{f'surf_{k}': v for k, v in surf.items()},
                 sample_keys=np.array(smp['keys']), X=smp['X'], max_vm=smp['max_vm'], max_u=smp['max_u'])
        os.replace(tmp, d / 'result.npz')
        summary = {
            'kind': 'uncertainty', **res,
            'n_surface_nodes': int(len(surf['xyz'])),
            'result_hash': array_hash(np.column_stack([smp['max_vm'], smp['max_u']])),
            'converged': True,
            'wall_time_s': round(time.perf_counter() - t0, 2),
        }
        if mesh is not None:
            summary.update(n_nodes=mesh.n_nodes, n_elements=mesh.n_elements, element_type=mesh.element_type)
        # flat keys used by history / reports
        summary['max_von_mises_mean_mpa'] = res['max_von_mises']['mean'] / 1e6
        summary['max_von_mises_ci_high_mpa'] = res['max_von_mises']['ci_high'] / 1e6
        summary['max_displacement_mean_mm'] = res['max_displacement']['mean'] * 1e3
        if 'reliability' in res:
            summary['p_failure'] = res['reliability']['p_failure']
            summary['beta'] = res['reliability']['beta_cornell']
        summary = _json_safe(summary)
        run = db.session.get(SimulationRun, run_id)
        if run is not None:
            run.status = 'done'
            run.converged = True
            run.wall_time = summary['wall_time_s']
            run.summary = summary
            run.result_hash = summary['result_hash']
            run.result_ref = str(d)
            db.session.commit()
        emit('uncertainty_done', {k: summary[k] for k in ('max_von_mises_mean_mpa', 'max_displacement_mean_mm',
                                                          'wall_time_s', 'n_samples', 'method') if k in summary})
        ctx.progress(100, f"Monte Carlo listo: {cfg['n_samples']} muestras ({res['method']})", force=True)
        return {'run_id': room, 'n_samples': int(cfg['n_samples']), 'method': res['method']}
    except Exception as e:
        from app.jobs.handlers import JobCancelled
        db.session.rollback()
        status = 'cancelled' if isinstance(e, JobCancelled) else 'failed'
        kernel._update_run(run_id, status, error=None if status == 'cancelled' else str(e))
        emit('uncertainty_error', {'message': 'Cancelado' if status == 'cancelled' else str(e)})
        raise
