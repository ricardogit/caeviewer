"""ROM build job ('rom.build'): spec → mesh → snapshots → POD → rom.npz (FASE 5).

Files: ``SOLVER_DATA_DIR/rom/<run_id>/rom.npz``. The ROM is a SimulationRun with
purpose='rom' (hash over the study + parameter space + settings: FASE 7).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def rom_dir(run_id) -> Path:
    from flask import current_app
    return Path(str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver'))) / 'rom' / str(run_id)


def rom_path(run_id) -> str:
    return str(rom_dir(run_id) / 'rom.npz')


def run_rom_build(ctx, run_id: str, spec: dict) -> dict:
    from app.extensions import db
    from app.design.models.simulation import SimulationRun
    from app.design.services.fem.kernel import FEMKernel, _json_safe
    from app.design.services.fem.solver import check_tier_limits
    from app.design.services.traceability.hasher import mesh_hash, array_hash
    from app.design.services.rom.pod import PODROMBuilder, ROMSettings

    kernel = FEMKernel()
    room = str(run_id)
    t0 = time.perf_counter()

    def emit(event, data):
        ctx.emit_socket(event, {'run_id': room, **data}, room)

    def progress(pct, msg):
        ctx.progress(pct, msg, force=True)
        emit('rom_build_progress', {'percent': round(pct, 1), 'status': msg})

    kernel._update_run(run_id, 'running')
    kernel._record_fingerprint(run_id, spec)
    try:
        cfg = spec.get('rom') or {}
        settings = ROMSettings.from_dict(cfg.get('settings'))
        progress(1, 'Mallando')
        mesh, meta = kernel._build_mesh(spec, progress=lambda m: progress(1, m))
        tier = int(spec.get('tier', mesh.estimate_tier()))
        check_tier_limits(mesh.n_nodes, mesh.n_elements, mesh.n_dof_structural, tier)
        builder = PODROMBuilder(mesh, spec, cfg.get('parameter_space') or {}, settings,
                                progress=progress, check_cancel=ctx.check_cancel)
        rom = builder.build()
        val = rom.pop('validation')
        samples = rom.pop('samples')
        summary = {
            'kind': 'rom', 'method': 'POD-Galerkin (afín en λ, μ y cargas)',
            'element_type': mesh.element_type, 'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements,
            'n_dof': mesh.n_dof_structural, 'tier': tier,
            'n_snapshots': settings.n_snapshots, 'n_modes': int(rom['r']),
            'energy_captured': float(rom['energy'][int(rom['r']) - 1]),
            'singular_values': [float(x) for x in rom['singular_values'][:60]],
            'parameter_space': builder.space,
            'validation': val,
            'validation_max_error_u': max((v['error_u'] for v in val), default=None),
            'validation_max_error_vm': max((v['error_max_vm'] for v in val), default=None),
            'n_surface_nodes': int(len(rom['surf_nodes'])),
            'build_s': round(rom.pop('build_s'), 2),
            'settings': settings.to_dict(),
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(rom['Phi']),
            'converged': True,
        }
        if meta:
            summary['mesh'] = {k: v for k, v in meta.items() if k not in ('attempts', 'bridge')}
        d = rom_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        meta_json = json.dumps(_json_safe({k: summary[k] for k in (
            'n_modes', 'energy_captured', 'validation_max_error_u', 'validation_max_error_vm', 'n_snapshots',
            'element_type', 'n_nodes', 'n_elements')} | {'samples': samples}))
        tmp = d / 'rom.tmp.npz'
        np.savez(tmp, **rom, meta_json=np.array(meta_json))
        os.replace(tmp, d / 'rom.npz')
        summary['wall_time_s'] = round(time.perf_counter() - t0, 2)
        summary['file_mb'] = round((d / 'rom.npz').stat().st_size / 1e6, 1)
        run = db.session.get(SimulationRun, run_id)
        if run is not None:
            run.status = 'done'
            run.converged = True
            run.wall_time = summary['wall_time_s']
            run.summary = _json_safe(summary)
            run.mesh_hash, run.result_hash = summary['mesh_hash'], summary['result_hash']
            run.result_ref = str(d)
            run.mesh_stats = {'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements,
                              'n_dof': mesh.n_dof_structural, 'element_type': mesh.element_type, 'tier': tier}
            db.session.commit()
        emit('rom_build_done', _json_safe({k: v for k, v in summary.items() if k not in ('validation', 'settings')}))
        ctx.progress(100, f"ROM listo: {summary['n_modes']} modos, error validación "
                          f"{summary['validation_max_error_u']}", force=True)
        return {'run_id': room, 'n_modes': summary['n_modes'], 'build_s': summary['build_s']}
    except Exception as e:
        from app.jobs.handlers import JobCancelled
        db.session.rollback()
        status = 'cancelled' if isinstance(e, JobCancelled) else 'failed'
        kernel._update_run(run_id, status, error=None if status == 'cancelled' else str(e))
        emit('rom_build_error', {'message': 'Cancelado' if status == 'cancelled' else str(e)})
        raise
