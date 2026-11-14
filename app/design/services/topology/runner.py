"""Topology-optimization job: spec → mesh → SIMP → files + SimulationRun (FASE 4).

Files under ``SOLVER_DATA_DIR/topology/<run_id>/``:
  mesh.npz    nodes [m], T4 elements, passive masks (written once, before the first iteration)
  latest.npz  last density snapshot + history (rewritten atomically while running)
  result.npz  final x, densities, u, history
  iso_<t>.npz cached iso-surfaces per threshold
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def run_dir(run_id) -> Path:
    from flask import current_app
    base = current_app.config.get('SOLVER_DATA_DIR', 'data/solver')
    return Path(str(base)) / 'topology' / str(run_id)


def result_path(run_id) -> str:
    return str(run_dir(run_id) / 'result.npz')


def _atomic_savez(path: Path, **arrays):
    tmp = path.with_name(path.stem + '.tmp.npz')
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def load_state(run_id, which: str = 'auto') -> dict | None:
    """Mesh + densities of a run: 'final', 'latest' or 'auto' (final if present)."""
    d = run_dir(run_id)
    mesh_p = d / 'mesh.npz'
    if not mesh_p.exists():
        return None
    with np.load(mesh_p, allow_pickle=False) as z:
        out = {k: z[k] for k in z.files}
    src = None
    if which in ('final', 'auto') and (d / 'result.npz').exists():
        src = d / 'result.npz'
    elif which in ('latest', 'auto') and (d / 'latest.npz').exists():
        src = d / 'latest.npz'
    if src is None:
        return out
    with np.load(src, allow_pickle=False) as z:
        out.update({k: z[k] for k in z.files})
    out['source'] = src.stem
    out['history'] = json.loads(str(out['history'])) if 'history' in out else []
    return out


def _printability(opt, r, settings) -> dict:
    """AM metrics of the final 0/1 design: unsupported volume (sharp printing recursion) and
    down-facing overhang area of the iso-surface, for the build direction of the run (or +Z)."""
    from app.design.services.topology.am_constraints import AMConstraints, overhang_area_fraction
    from app.design.services.topology.isosurface import extract_isosurface
    try:
        b = list(getattr(settings, 'build_direction', None) or [0.0, 0.0, 1.0])
        ang = float(getattr(settings, 'max_overhang_angle', 45.0) or 45.0)
        am = opt.am if getattr(opt, 'am', None) is not None else \
            AMConstraints(opt.centroids, opt.vol, opt.h_mean, b, ang)
        bw = (r['densities'] >= 0.5).astype(float)
        surf = extract_isosurface(opt.mesh.nodes, opt.mesh.elements, r['densities'])
        oh = overhang_area_fraction(surf['vertices'], surf['faces'], b, ang, plate_tol=opt.h_mean)
        return {'am': {'constrained': bool(getattr(settings, 'am_constraint', False)), 'build_direction': b,
                       'max_overhang_angle': ang, 'unsupported_volume_fraction': am.unsupported_fraction(bw),
                       'overhang_area_fraction': oh['overhang_fraction']}}
    except Exception as e:                                    # metrics must never fail a finished run
        logger.warning('AM metrics failed: %s', e)
        return {}


def run_topology(ctx, run_id: str, spec: dict) -> dict:
    """Job body for 'topology.simp' (SIMP, optionally with the AM overhang filter, or level set:
    ``spec['topology']['method']``)."""
    from app.extensions import db
    from app.design.models.simulation import SimulationRun
    from app.design.services.fem.kernel import FEMKernel, _json_safe
    from app.design.services.fem.constitutive import build_material
    from app.design.services.fem.solver import check_tier_limits
    from app.design.services.traceability.hasher import mesh_hash, array_hash
    from app.design.services.topology.simp import SIMPOptimizer, SIMPSettings
    from app.design.services.topology.levelset import LevelSetOptimizer, LevelSetSettings

    kernel = FEMKernel()
    room = str(run_id)
    t0 = time.perf_counter()

    def emit(event, data):
        ctx.emit_socket(event, {'run_id': room, **data}, room)

    kernel._update_run(run_id, 'running')
    kernel._record_fingerprint(run_id, spec)
    try:
        method = (spec.get('topology') or {}).get('method', 'simp')
        if method == 'levelset':
            settings = LevelSetSettings.from_dict(spec.get('topology'))
        else:
            settings = SIMPSettings.from_dict(spec.get('topology'))
        mspec = dict(spec)
        mspec['mesh_params'] = {**(spec.get('mesh_params') or {}), 'order': 1}
        ctx.progress(1, 'Mallando dominio de diseño', force=True)
        emit('topology_progress', {'status': 'mesh', 'iter': 0, 'percent': 1})
        mesh, meta = kernel._build_mesh(mspec, progress=lambda m: ctx.progress(2, m))
        tier = int(spec.get('tier', mesh.estimate_tier()))
        check_tier_limits(mesh.n_nodes, mesh.n_elements, mesh.n_dof_structural, tier)
        D = build_material(spec.get('material') or {}).get_D_matrix()
        d = run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        history: list = []

        def progress(h):
            ctx.check_cancel()
            history.append(h)
            pct = 5 + 90 * h['iter'] / settings.max_iter
            extra = f"β={h['beta']}" if h.get('beta') is not None else f"V={h['volume_fraction']:.3f}"
            ctx.progress(pct, f"iter {h['iter']} · C={h['compliance']:.4g} · Δ={h['change']:.3f} · {extra}")
            emit('topology_progress', {**h, 'percent': round(pct, 1), 'status': 'running',
                                       'max_iter': settings.max_iter})

        def snapshot(it, rho):
            _atomic_savez(d / 'latest.npz', iteration=np.int64(it), densities=rho.astype(np.float32),
                          history=np.array(json.dumps(history)))
            emit('topology_snapshot', {'iter': it})

        Opt = LevelSetOptimizer if method == 'levelset' else SIMPOptimizer
        opt = Opt(mesh, D, spec.get('loads', []), spec.get('bcs', []), settings,
                  progress=progress, snapshot=snapshot, check_cancel=ctx.check_cancel)
        m4 = opt.mesh
        _atomic_savez(d / 'mesh.npz', nodes=m4.nodes, elements=m4.elements,
                      passive_solid=opt.passive_solid, passive_void=opt.passive_void,
                      design=opt.design, volumes=opt.vol)
        emit('topology_progress', {'status': 'optimizing', 'iter': 0, 'percent': 5,
                                   'n_elements': m4.n_elements, 'n_design': int(opt.design.sum()),
                                   'filter_radius': getattr(settings, 'filter_radius', None),
                                   'method': method})
        r = opt.run()
        _atomic_savez(d / 'result.npz', iteration=np.int64(r['n_iterations']), x=r['x'],
                      densities=r['densities'], u=r['u'], history=np.array(json.dumps(r['history'])))
        summary = {
            'kind': 'topology', 'method': 'Level set' if method == 'levelset' else 'SIMP',
            'element_type': 'T4', 'n_nodes': m4.n_nodes, 'n_elements': m4.n_elements,
            'n_dof': m4.n_dof_structural, 'tier': tier,
            'converged': r['converged'], 'n_iterations': r['n_iterations'],
            'compliance_initial': r['compliance_initial'], 'compliance': r['compliance'],
            'compliance_bw': r['compliance_bw'],
            'compliance_reduction': (1 - r['compliance_bw'] / r['compliance_initial'])
            if r['compliance_initial'] else None,
            'volume_fraction': r['volume_fraction'], 'volume_fraction_bw': r['volume_fraction_bw'],
            'volume_fraction_target': settings.volume_fraction,
            'grayness': r['grayness'], 'filter_radius_m': r['filter_radius'],
            'beta_final': r['beta_final'], 'n_design': r['n_design'],
            'n_passive_solid': r['n_passive_solid'], 'n_passive_void': r['n_passive_void'],
            'max_displacement_mm': float(np.linalg.norm(r['u'].reshape(-1, 3), axis=1).max() * 1000),
            'settings': settings.to_dict(),
            'mesh_hash': mesh_hash(m4.nodes, m4.elements),
            'result_hash': array_hash(r['densities']),
            'wall_time_s': round(time.perf_counter() - t0, 3),
        }
        summary.update(_printability(opt, r, settings))
        if meta:
            summary['mesh'] = {k: v for k, v in meta.items() if k not in ('attempts', 'bridge')}
        run = db.session.get(SimulationRun, run_id)
        if run is not None:
            run.status = 'done'
            run.converged = r['converged']
            run.n_iterations = r['n_iterations']
            run.wall_time = summary['wall_time_s']
            run.summary = _json_safe(summary)
            run.mesh_hash, run.result_hash = summary['mesh_hash'], summary['result_hash']
            run.result_ref = str(d)
            run.mesh_stats = {'n_nodes': m4.n_nodes, 'n_elements': m4.n_elements, 'n_dof': m4.n_dof_structural,
                              'element_type': 'T4', 'tier': tier}
            run.convergence_log = [[h['iter'], h['compliance'], h['wall_time']] for h in r['history']]
            db.session.commit()
        emit('topology_done', _json_safe({k: v for k, v in summary.items() if k != 'settings'}))
        ctx.progress(100, f"Listo: C {r['compliance_initial']:.3g} → {r['compliance_bw']:.3g}", force=True)
        return {'run_id': room, 'converged': r['converged'], 'n_iterations': r['n_iterations'],
                'compliance_bw': r['compliance_bw']}
    except Exception as e:
        from app.jobs.handlers import JobCancelled
        db.session.rollback()
        status = 'cancelled' if isinstance(e, JobCancelled) else 'failed'
        kernel._update_run(run_id, status, error=None if status == 'cancelled' else str(e))
        emit('topology_error', {'message': 'Cancelado' if status == 'cancelled' else str(e)})
        raise
