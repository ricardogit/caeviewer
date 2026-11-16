"""FEM Kernel — orchestrates the complete simulation pipeline.

FASE 2 full implementation:
  1. Build FEMMesh from spec (inline / cantilever / graph / cae mesh / CAD geometry)
  2. Build constitutive model and D matrix
  3. Assemble K, F
  4. Apply BCs
  5. Check tier limits
  6. Dispatch to solver
  7. Compute post-processing (displacement, stress, von Mises)
  8. Save results to HDF5
  9. Update SimulationRun DB record
  10. Emit WebSocket events
"""
from __future__ import annotations
import logging
import os
import time

import numpy as np

from app.design.services.fem import tet_batch as tb
from app.design.services.fem import thermal as th
from app.design.services.fem.assembler import (assemble_K, assemble_F, apply_bcs, dirichlet,
                                               reduce_system, resolve_free_faces)
from app.design.services.fem.constitutive import (build_material, ElastoplasticVonMises, conductivity,
                                                  thermal_expansion, HyperelasticNeoHookean,
                                                  ViscoelasticMaxwell, Piezoelectric, ThermoPiezoelectric,
                                                  NewtonianFluid, LinearMagnetic)
from app.design.services.fem.mesh import FEMMesh
from app.design.services.fem.solver import (FEMSolverDispatcher, check_tier_limits, TierLimitExceeded,
                                            rigid_body_modes)
from app.design.services.fem.error_estimator import zz_estimate, mark_dorfler
from app.design.services.fem.mesh_adaptivity import refine_mesh
from app.design.services.traceability.hasher import mesh_hash, array_hash

logger = logging.getLogger(__name__)


class FEMKernel:
    """Orchestrates the full FEM pipeline from spec dict to results."""

    # ── Public async entry point ───────────────────────────────────────────────

    def solve_async(self, app, run_id: str, solver_spec: dict, socketio):
        """Called in a background thread by flask-socketio.start_background_task."""
        with app.app_context():
            self._update_run(run_id, 'running')
            self._record_fingerprint(run_id, solver_spec)
            socketio.emit('solver_progress',
                          {'run_id': run_id, 'iter': 0, 'status': 'starting',
                           'residual': None, 'wall_time': 0, 'percent': 0},
                          room=run_id)
            try:
                result = self._solve(run_id, solver_spec, socketio)
                self._save_results(run_id, result, app)
                self._update_run(run_id, 'done', result)
                self._update_result_nodes(run_id, result, solver_spec)
                socketio.emit('solver_done', {
                    'run_id': run_id,
                    **result['summary'],
                }, room=run_id)
            except TierLimitExceeded as e:
                self._update_run(run_id, 'failed', error=str(e))
                socketio.emit('solver_error', {'run_id': run_id,
                                               'message': str(e),
                                               'suggested_tier': e.suggested_tier},
                              room=run_id)
            except Exception as exc:
                logger.error(f"Solver error run={run_id}: {exc}", exc_info=True)
                self._update_run(run_id, 'failed', error=str(exc))
                socketio.emit('solver_error', {'run_id': run_id, 'message': str(exc)},
                              room=run_id)

    def solve_adaptive_async(self, app, run_id: str, solver_spec: dict, socketio):
        """Adaptive loop of a queued run (job ``fem.adaptive``): one ``adaptive_progress`` event per cycle
        (plus ``solver_progress`` with a status line), results saved like a plain run (last mesh)."""
        settings = solver_spec.get('adaptive') or {}
        n_max = int(settings.get('max_cycles', self.ADAPTIVE_DEFAULTS['max_cycles']))
        with app.app_context():
            self._update_run(run_id, 'running')
            self._record_fingerprint(run_id, solver_spec)
            t0 = time.perf_counter()

            def progress(entry):
                socketio.emit('adaptive_progress', {'run_id': run_id, **entry}, room=run_id)
                socketio.emit('solver_progress', {
                    'run_id': run_id, 'iter': entry['cycle'], 'residual': None,
                    'percent': min(95, int(100 * (entry['cycle'] + 1) / n_max)),
                    'wall_time': time.perf_counter() - t0,
                    'status': (f"Ciclo {entry['cycle'] + 1}/{n_max} | {entry['n_nodes']:,} nodos | "
                               f"error {100 * entry['global_error']:.2f} %")}, room=run_id)
            try:
                result = self.solve_adaptive(solver_spec, settings, progress=progress)
                self._save_results(run_id, result, app)
                self._update_run(run_id, 'done', result)
                self._update_result_nodes(run_id, result, solver_spec)
                socketio.emit('solver_done', {'run_id': run_id, **result['summary'],
                                              'adaptive_log': result['adaptive_log']}, room=run_id)
            except TierLimitExceeded as e:
                self._update_run(run_id, 'failed', error=str(e))
                socketio.emit('solver_error', {'run_id': run_id, 'message': str(e),
                                               'suggested_tier': e.suggested_tier}, room=run_id)
            except Exception as exc:
                logger.error(f"Adaptive solver error run={run_id}: {exc}", exc_info=True)
                self._update_run(run_id, 'failed', error=str(exc))
                socketio.emit('solver_error', {'run_id': run_id, 'message': str(exc)}, room=run_id)

    # ── Synchronous solve (also used by the test endpoint) ────────────────────

    def solve_sync(self, solver_spec: dict) -> dict:
        """Run the solver synchronously and return the result dict."""
        return self._solve(run_id=None, solver_spec=solver_spec, socketio=None)

    # ── Adaptive refinement solve (FASE 3) ─────────────────────────────────────

    ADAPTIVE_DEFAULTS = {'target_error': 0.05, 'max_cycles': 5, 'theta': 0.5}

    def solve_adaptive(self, solver_spec: dict, settings: dict | None = None, progress=None,
                       run_id=None, socketio=None) -> dict:
        """Solve → ZZ estimate → Dörfler marking → conforming bisection, until the relative energy-norm
        error estimate is below ``target_error`` or ``max_cycles`` solves were done.

        Linear elastic structural only (T4 or T10; T10 meshes keep curved mid nodes, see refine_mesh).
        The next mesh must fit the run's tier: otherwise the loop stops with the last solution
        (``stopped: 'tier'``). ``progress(entry)`` is called after every cycle. The returned result is the
        last solve plus ``adaptive_log`` (one entry per cycle) and ``summary['adaptive']``.
        """
        st = {**self.ADAPTIVE_DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None}}
        target, max_cycles, theta = float(st['target_error']), int(st['max_cycles']), float(st['theta'])
        mat_spec = solver_spec.get('material') or {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}
        D = build_material(mat_spec).get_D_matrix()
        log, mesh, stopped, result, meta0 = [], None, None, None, None
        t0 = time.perf_counter()
        for cycle in range(max_cycles):
            result = self._solve(run_id, solver_spec, socketio, mesh=mesh)
            mesh = result['mesh']
            if meta0 is None:
                meta0 = result['summary'].get('mesh')
            u = np.asarray(result['displacement'], dtype=np.float64).ravel()
            est = zz_estimate(mesh.nodes, mesh.elements, u, D)
            eta = est['relative_error']
            converged = eta < target
            entry = {
                'cycle': cycle, 'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements,
                'n_dof': mesh.n_dof_structural, 'element_type': mesh.element_type,
                'global_error': eta, 'error_energy': est['error_energy'],
                'solution_energy': est['solution_energy'],
                'max_displacement_mm': result['summary']['max_displacement_mm'],
                'max_von_mises_mpa': result['summary']['max_von_mises_mpa'],
                'wall_time_s': round(time.perf_counter() - t0, 3),
            }
            if not converged and cycle < max_cycles - 1:
                marked = mark_dorfler(est['eta2'], theta)
                entry['n_marked'] = int(marked.sum())
                names = sorted(set(mesh.node_sets) | set(mesh.face_sets))
                nodes, elements, node_sets, face_sets = refine_mesh(
                    mesh.nodes, mesh.elements, marked, {k: mesh.node_sets[k] for k in names})
                face_sets = {k: v for k, v in face_sets.items() if k in mesh.face_sets}
                tier = int(solver_spec.get('tier', mesh.estimate_tier()))
                try:
                    check_tier_limits(len(nodes), len(elements), 3 * len(nodes), tier)
                except TierLimitExceeded:
                    stopped = 'tier'
            log.append(entry)
            logger.info('Adaptive cycle %d: %d nodes, eta=%.4f', cycle, mesh.n_nodes, eta)
            if progress:
                progress(entry)
            if converged or stopped or cycle == max_cycles - 1:
                if not converged and not stopped:
                    stopped = 'max_cycles'
                break
            mesh = FEMMesh(nodes, elements, node_sets=node_sets, face_sets=face_sets, mids_known=True)
        result['adaptive_log'] = log
        s = result['summary']
        s['adaptive'] = {'target_error': target, 'max_cycles': max_cycles, 'theta': theta,
                         'cycles': len(log), 'final_error': log[-1]['global_error'],
                         'converged': log[-1]['global_error'] < target, 'stopped': stopped,
                         'initial_mesh': meta0}
        s['n_nodes'], s['n_elements'] = mesh.n_nodes, mesh.n_elements
        return result

    def solve_adaptive_sync(self, solver_spec: dict, max_cycles: int = 5, target_error: float = 0.05,
                            theta: float = 0.5) -> dict:
        """Backward-compatible wrapper of ``solve_adaptive``."""
        return self.solve_adaptive(solver_spec, {'max_cycles': max_cycles, 'target_error': target_error,
                                                 'theta': theta})

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def _emit(self, socketio, run_id, pct, status, t_start, **extra):
        if socketio and run_id:
            socketio.emit('solver_progress', {
                'run_id': run_id, 'iter': extra.pop('iter', 0), 'percent': pct, 'status': status,
                'wall_time': time.perf_counter() - t_start, **extra,
            }, room=run_id)

    def _solve(self, run_id, solver_spec: dict, socketio, mesh: FEMMesh | None = None) -> dict:
        """``mesh``: an already built mesh (adaptive cycles) instead of the spec's mesh source."""
        t_start = time.perf_counter()

        # 1. Build mesh
        if mesh is None:
            self._emit(socketio, run_id, 2, 'building mesh', t_start)
            mesh, mesh_meta = self._build_mesh(solver_spec, progress=lambda m: self._emit(
                socketio, run_id, 3, m, t_start))
        else:
            mesh_meta = {}

        # 2. Tier check (exact, after meshing)
        tier = int(solver_spec.get('tier', mesh.estimate_tier()))
        check_tier_limits(mesh.n_nodes, mesh.n_elements, mesh.n_dof_structural, tier)

        # 3. Material / constitutive model
        mat_spec = solver_spec.get('material', {
            'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800.0
        })
        physics = set(solver_spec.get('physics') or ['structural'])
        all_bcs = solver_spec.get('bcs', [])
        all_loads = solver_spec.get('loads', [])
        resolve_free_faces(mesh, all_bcs + all_loads)
        self._emit(socketio, run_id, 5, f'mesh built: {mesh.n_nodes:,} nodes, '
                   f'{mesh.n_elements:,} {mesh.element_type} elements', t_start)

        # 3a. Species transport (FASE 10.1): advection–diffusion–reaction on a given velocity field
        if 'transport' in physics:
            return self._solve_transport(mesh, mesh_meta, mat_spec, solver_spec, all_bcs, all_loads, tier,
                                         socketio, run_id, t_start)

        # 3b. Thermal field (FASE 2 multiphysics): steady conduction, then one-way coupling
        T = thermal = None
        if 'thermal' in physics and mat_spec.get('type') == 'piezoelectric':
            raise ValueError('Para acoplar temperatura con piezoelectricidad usa el material '
                             'termo-piezoeléctrico (α y coeficiente piroeléctrico p3).')
        if 'thermal' in physics:
            T, thermal = self._solve_thermal(mesh, mat_spec, [b for b in all_bcs if th.is_thermal_bc(b)],
                                             [ld for ld in all_loads if th.is_thermal_load(ld)], tier,
                                             float(solver_spec.get('tolerance', 1e-8)))
            self._emit(socketio, run_id, 20 if 'structural' in physics else 90,
                       f"thermal solved: T {thermal['min_temperature']:.4g} .. "
                       f"{thermal['max_temperature']:.4g}", t_start)
            if 'structural' not in physics and 'piezoelectric' not in physics:
                return self._thermal_only_results(mesh, mesh_meta, T, thermal, tier, t_start)

        material = build_material(mat_spec)
        D = material.get_D_matrix()
        is_linear = material.is_linear()
        if isinstance(material, ElastoplasticVonMises):          # FASE 2.5: J2 plasticity, Newton-Raphson
            return self._solve_plastic(mesh, mesh_meta, material, mat_spec, solver_spec, all_bcs, all_loads,
                                       T, thermal, tier, socketio, run_id, t_start)
        if isinstance(material, HyperelasticNeoHookean):         # large deformations, total Lagrangian
            if T is not None:
                raise ValueError('El material Neo-Hookean (grandes deformaciones) no admite el acoplamiento '
                                 'térmico todavía: quita las condiciones térmicas o usa un material elástico.')
            return self._solve_hyperelastic(mesh, mesh_meta, material, mat_spec, solver_spec, all_bcs,
                                            all_loads, tier, socketio, run_id, t_start)
        if isinstance(material, Piezoelectric):                   # coupled u + φ (+ one-way thermal)
            if T is not None and not isinstance(material, ThermoPiezoelectric):
                raise ValueError('Para acoplar temperatura con piezoelectricidad usa el material '
                                 'termo-piezoeléctrico (α y coeficiente piroeléctrico p3).')
            if isinstance(material, ThermoPiezoelectric) and T is None:
                raise ValueError('Material termo-piezoeléctrico sin campo de temperatura: agrega condiciones '
                                 'térmicas (temperatura impuesta, flujo, convección o fuente).')
            return self._solve_piezo(mesh, mesh_meta, material, mat_spec, solver_spec, all_bcs, all_loads,
                                     tier, socketio, run_id, t_start, T=T, thermal=thermal)
        if isinstance(material, NewtonianFluid):                  # steady Stokes flow (velocity + pressure)
            if T is not None:
                raise ValueError('El fluido newtoniano no admite condiciones térmicas todavía.')
            return self._solve_fluid(mesh, mesh_meta, material, solver_spec, all_bcs, all_loads, tier,
                                     socketio, run_id, t_start)
        if isinstance(material, LinearMagnetic):                  # magnetostatics, scalar potential
            if T is not None:
                raise ValueError('El material magnético no admite condiciones térmicas todavía.')
            return self._solve_magnetic(mesh, mesh_meta, material, all_bcs, all_loads, tier,
                                        socketio, run_id, t_start)
        if isinstance(material, ViscoelasticMaxwell):             # time stepping (creep / relaxation)
            if T is not None:
                raise ValueError('El material viscoelástico no admite el acoplamiento térmico todavía: quita '
                                 'las condiciones térmicas o usa un material elástico.')
            return self._solve_viscoelastic(mesh, mesh_meta, material, mat_spec, solver_spec, all_bcs,
                                            all_loads, tier, socketio, run_id, t_start)

        # 4. Assemble K and F
        logger.info(f"Assembling K ({mesh.n_dof_structural:,} DOF, {mesh.element_type})...")
        t_asm = time.perf_counter()
        K = assemble_K(mesh, D)
        bcs = [b for b in all_bcs if not th.is_thermal_bc(b)]
        rho = float(mat_spec.get('rho', 0.0) or 0.0)
        loads = [({**ld, 'density': ld.get('density', rho)} if 'gravity' in ld else ld)
                 for ld in all_loads if not th.is_thermal_load(ld)]
        load_info: list = []
        F = assemble_F(mesh, loads, load_info)
        eps0 = None
        if T is not None:
            alpha = thermal_expansion(mat_spec)
            T_ref = float(mat_spec.get('T_ref') or 0.0)
            F = F + th.thermal_load(mesh, D, T, alpha, T_ref)
            eps0 = lambda p: th.thermal_strain_at(mesh.elements, T, alpha, T_ref, p)  # noqa: E731
            load_info.append({'index': len(load_info), 'label': 'dilatación térmica',
                              'kind': 'thermal_strain', 'alpha': np.asarray(alpha).tolist(), 'T_ref': T_ref})
        t_asm = time.perf_counter() - t_asm
        self._emit(socketio, run_id, 30, 'assembly complete, applying BCs', t_start)

        # 5-6. BCs + solve
        solver = FEMSolverDispatcher()
        tol = float(solver_spec.get('tolerance', 1e-8))
        max_iter = solver_spec.get('max_iterations')

        def progress_cb(it, res):
            pct = min(95, 35 + int(55 * min(1.0, np.log10(max(res, 1e-300)) / np.log10(tol)))) \
                if res > 0 else 95
            self._emit(socketio, run_id, pct, f'CG iter {it}', t_start, iter=it, residual=res)

        dofs, vals = dirichlet(mesh, bcs)
        if not len(dofs):
            raise ValueError('Sin condiciones de frontera: el sistema es singular (movimiento de '
                             'cuerpo rígido). Agrega al menos un nodo BC.')
        if is_linear:
            Kf, rhs, free = reduce_system(K, F, dofs, vals)
            B = rigid_body_modes(mesh.nodes)[free]
            uf, solve_info = solver.solve_linear(Kf, rhs, tier=tier, tol=tol,
                                                 max_iter=int(max_iter) if max_iter else None,
                                                 progress_cb=progress_cb, near_nullspace=B)
            u = np.zeros(mesh.n_dof_structural)
            u[free] = uf
            u[dofs] = vals
        else:
            Kp, Fp = apply_bcs(K, F, bcs, mesh)
            u, solve_info = solver.solve(Kp, Fp, tier=tier, is_linear=False, tol=tol,
                                         max_iter=int(max_iter or 50), progress_cb=progress_cb)
        if not solve_info.get('converged', False):
            logger.warning('Solver did not converge: %s', solve_info)

        # equilibrium check: reactions at constrained DOFs must balance the applied loads
        R = K @ u - F
        reaction = [float(R[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)]
        applied = [float(F[c::3].sum()) for c in range(3)]
        scale = max(1e-30, float(np.abs(applied).max()), float(np.abs(reaction).max()))
        if T is not None:      # the thermal load is self-equilibrated: compare with its gross size
            scale = max(scale, max(float(np.abs(F[c::3]).sum()) for c in range(3)))
        equilibrium_error = float(np.abs(np.add(reaction, applied)).max() / scale)
        solve_info['assembly_s'] = round(t_asm, 3)

        logger.info(f"Solve done: {solve_info['method']}, converged={solve_info['converged']}, "
                    f"wall={solve_info['wall_time']:.2f}s, equilibrium={equilibrium_error:.2e}")

        # 7. Post-processing
        results = self._postprocess(mesh, D, u, solve_info, t_start, eps0=eps0)
        results['mesh'] = mesh
        s = results['summary']
        if T is not None:
            results['temperature'] = T.tolist()
            results['heat_flux_nodal'] = thermal.pop('heat_flux_nodal')
            s['thermal'] = thermal
            s['max_temperature'] = thermal['max_temperature']
            s['min_temperature'] = thermal['min_temperature']
            s['max_heat_flux_w_m2'] = thermal['max_heat_flux_w_m2']
            s['physics'] = sorted(physics)
        s.update({
            'element_type': mesh.element_type,
            'applied_load_N': applied,
            'reaction_N': reaction,
            'equilibrium_error': equilibrium_error,
            'loads': load_info,
            'n_constrained_dofs': int(len(dofs)),
            'tier': tier,
            # FASE 7: exact-bytes fingerprints (equal result_hash = bitwise identical result)
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(u if T is None else np.concatenate([u, T])),
        })
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return results

    # ── Material non-linearity (FASE 2.5) ─────────────────────────────────────

    def _solve_plastic(self, mesh, mesh_meta, material, mat_spec, spec, all_bcs, all_loads,
                       T, thermal, tier, socketio, run_id, t_start) -> dict:
        from app.design.services.fem import plasticity as pl
        j2 = material.j2
        bcs = [b for b in all_bcs if not th.is_thermal_bc(b)]
        rho = float(mat_spec.get('rho', 0.0) or 0.0)
        loads = [({**ld, 'density': ld.get('density', rho)} if 'gravity' in ld else ld)
                 for ld in all_loads if not th.is_thermal_load(ld)]
        load_info: list = []
        F = assemble_F(mesh, loads, load_info)
        dofs, vals = dirichlet(mesh, bcs)
        if not len(dofs):
            raise ValueError('Sin condiciones de frontera: el sistema es singular (movimiento de '
                             'cuerpo rígido). Agrega al menos un nodo BC.')
        eps0_gp = None
        if T is not None:
            alpha = thermal_expansion(mat_spec)
            T_ref = float(mat_spec.get('T_ref') or 0.0)
            pts, _ = pl.gauss_points(mesh.element_type)
            eps0_gp = np.stack([th.thermal_strain_at(mesh.elements, T, alpha, T_ref, p) for p in pts], axis=1)
            load_info.append({'index': len(load_info), 'label': 'dilatación térmica',
                              'kind': 'thermal_strain', 'alpha': np.asarray(alpha).tolist(), 'T_ref': T_ref})
        load_path = [float(x) for x in (spec.get('load_path') or [1.0])]
        n_steps = int(spec.get('n_load_steps') or 10)

        def progress(it, res, lam):
            pct = 30 + int(60 * min(1.0, abs(lam) / max(abs(x) for x in load_path)))
            self._emit(socketio, run_id, pct, f'NR it {it} · λ = {lam:.3f}', t_start, iter=it, residual=res)

        self._emit(socketio, run_id, 30, f'elastoplástico: {len(load_path)} tramo(s) × {n_steps} pasos', t_start)
        r = pl.solve_plastic(mesh, j2, F, dofs, vals, load_path=load_path, n_steps=n_steps,
                             tol=float(spec.get('nl_tolerance') or 1e-8), max_iter=int(spec.get('nl_max_iter') or 25),
                             eps0_gp=eps0_gp, tier=tier, near_nullspace=rigid_body_modes(mesh.nodes),
                             progress_cb=progress)
        u, lam, info = r['u'], r['load_factor'], r['info']
        op = r['operator']
        sig_gp, ep_gp = r['sigma_gp'], r['ep_gp']
        f_int, _ = op.internal_force_and_tangent(sig_gp, None, mesh.n_dof_structural, need_K=False)
        Rf = f_int - lam * F
        reaction = [float(Rf[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)]
        applied = [float(lam * F[c::3].sum()) for c in range(3)]
        scale = max(1e-30, float(np.abs(applied).max()), float(np.abs(reaction).max()))
        if T is not None:
            scale = max(scale, max(float(np.abs(f_int[c::3]).sum()) for c in range(3)))
        equilibrium_error = float(np.abs(np.add(reaction, applied)).max() / scale)

        disp = u.reshape(-1, 3)
        dmag = np.linalg.norm(disp, axis=1)
        el_sigma = sig_gp.mean(axis=1)
        el_vm = tb.von_mises_v(el_sigma)
        nodal_sigma = pl.gp_to_nodal(mesh.n_nodes, mesh.elements, sig_gp)
        node_vm = tb.von_mises_v(nodal_sigma)
        ep_nodal = np.maximum(pl.gp_to_nodal(mesh.n_nodes, mesh.elements, ep_gp[:, :, None])[:, 0], 0.0)
        ep_el = ep_gp.mean(axis=1)
        vol = op.wdet.sum(axis=1)
        plastic_vol = float(vol[(ep_gp > 0).any(axis=1)].sum() / vol.sum())
        s = {
            'max_displacement_m': float(dmag.max()), 'max_displacement_mm': round(float(dmag.max()) * 1000, 6),
            'max_von_mises_pa': float(el_vm.max()), 'max_von_mises_mpa': round(float(el_vm.max()) / 1e6, 4),
            'max_von_mises_nodal_mpa': round(float(node_vm.max()) / 1e6, 4),
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_dof_structural,
            'element_type': mesh.element_type, 'tier': tier,
            'converged': info['converged'], 'n_iterations': info['n_iterations'],
            'final_residual': info['final_residual'], 'solver_method': info['method'],
            'wall_time_s': round(time.perf_counter() - t_start, 3),
            'applied_load_N': applied, 'reaction_N': reaction, 'equilibrium_error': equilibrium_error,
            'loads': load_info, 'n_constrained_dofs': int(len(dofs)),
            'material_model': 'elastoplastic_vonmises',
            'plasticity': {**j2.to_dict(), 'load_factor': lam, 'load_path': load_path,
                           'limit_load_reached': info['limit_load_reached'], 'n_steps': info['n_steps'],
                           'cutbacks': info['cutbacks'], 'max_equivalent_plastic_strain': float(ep_gp.max()),
                           'plastic_volume_fraction': plastic_vol,
                           'curve': [{k: v for k, v in c.items()} for c in r['curve']]},
            'max_equivalent_plastic_strain': float(ep_gp.max()),
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(u if T is None else np.concatenate([u, T])),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        results = {
            'displacement': disp.tolist(), 'displacement_magnitude': dmag.tolist(),
            'von_mises_elemental': el_vm.tolist(), 'von_mises_nodal': node_vm.tolist(),
            'sigma_elemental': el_sigma.tolist(), 'equivalent_plastic_strain': ep_nodal.tolist(),
            'equivalent_plastic_strain_elemental': ep_el.tolist(),
            'solve_info': info, 'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }
        if T is not None:
            results['temperature'] = T.tolist()
            results['heat_flux_nodal'] = thermal.pop('heat_flux_nodal')
            s.update(thermal=thermal, max_temperature=thermal['max_temperature'],
                     min_temperature=thermal['min_temperature'], max_heat_flux_w_m2=thermal['max_heat_flux_w_m2'],
                     physics=['structural', 'thermal'])
        logger.info('Plastic solve: λ=%.4f, %d NR iterations, %d steps, %d cutbacks, εp max %.3e',
                    lam, info['n_iterations'], info['n_steps'], info['cutbacks'], float(ep_gp.max()))
        return results

    # ── Hyperelastic (Neo-Hookean, large deformations) ───────────────────────

    def _solve_hyperelastic(self, mesh, mesh_meta, material, mat_spec, spec, all_bcs, all_loads,
                            tier, socketio, run_id, t_start) -> dict:
        from app.design.services.fem import hyperelastic as he
        from app.design.services.fem import plasticity as pl
        nh = material.nh
        rho = float(mat_spec.get('rho', 0.0) or 0.0)
        loads = [({**ld, 'density': ld.get('density', rho)} if 'gravity' in ld else ld) for ld in all_loads]
        load_info: list = []
        F = assemble_F(mesh, loads, load_info)                   # dead loads on the reference configuration
        dofs, vals = dirichlet(mesh, all_bcs)
        if not len(dofs):
            raise ValueError('Sin condiciones de frontera: el sistema es singular (movimiento de '
                             'cuerpo rígido). Agrega al menos un nodo BC.')
        n_steps = int(spec.get('n_load_steps') or 10)

        def progress(it, res, lam):
            self._emit(socketio, run_id, 30 + int(60 * min(1.0, lam)), f'NR it {it} · λ = {lam:.3f}', t_start,
                       iter=it, residual=res)

        self._emit(socketio, run_id, 30, f'Neo-Hookean: {n_steps} pasos de carga', t_start)
        r = he.solve_hyperelastic(mesh, nh, F, dofs, vals, n_steps=n_steps,
                                  tol=float(spec.get('nl_tolerance') or 1e-8),
                                  max_iter=int(spec.get('nl_max_iter') or 30), tier=tier,
                                  near_nullspace=rigid_body_modes(mesh.nodes), progress_cb=progress)
        u, lam, info, f_int = r['u'], r['load_factor'], r['info'], r['f_int']
        m, g = r['S_gp'].shape[:2]
        sig_gp = he.cauchy(r['F_gp'].reshape(-1, 3, 3), r['S_gp'].reshape(-1, 3, 3)).reshape(m, g, 6)
        Rf = f_int - lam * F
        reaction = [float(Rf[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)]
        applied = [float(lam * F[c::3].sum()) for c in range(3)]
        scale = max(1e-30, float(np.abs(applied).max()), float(np.abs(reaction).max()))
        equilibrium_error = float(np.abs(np.add(reaction, applied)).max() / scale)
        # Green-Lagrange strain → max principal (stretch measure for the results)
        Fg = r['F_gp'].reshape(-1, 3, 3)
        Egl = 0.5 * (np.einsum('nki,nkj->nij', Fg, Fg) - np.eye(3))
        e_max = float(np.abs(np.linalg.eigvalsh(Egl)).max()) if len(Egl) else 0.0

        disp = u.reshape(-1, 3)
        dmag = np.linalg.norm(disp, axis=1)
        el_sigma = sig_gp.mean(axis=1)
        el_vm = tb.von_mises_v(el_sigma)
        nodal_sigma = pl.gp_to_nodal(mesh.n_nodes, mesh.elements, sig_gp)
        node_vm = tb.von_mises_v(nodal_sigma)
        s = {
            'max_displacement_m': float(dmag.max()), 'max_displacement_mm': round(float(dmag.max()) * 1000, 6),
            'max_von_mises_pa': float(el_vm.max()), 'max_von_mises_mpa': round(float(el_vm.max()) / 1e6, 4),
            'max_von_mises_nodal_mpa': round(float(node_vm.max()) / 1e6, 4),
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_dof_structural,
            'element_type': mesh.element_type, 'tier': tier,
            'converged': info['converged'], 'n_iterations': info['n_iterations'],
            'final_residual': info['final_residual'], 'solver_method': info['method'],
            'wall_time_s': round(time.perf_counter() - t_start, 3),
            'applied_load_N': applied, 'reaction_N': reaction, 'equilibrium_error': equilibrium_error,
            'loads': load_info, 'n_constrained_dofs': int(len(dofs)),
            'material_model': 'hyperelastic_neohookean',
            'hyperelastic': {**nh.to_dict(), 'load_factor': lam, 'n_steps': info['n_steps'],
                             'cutbacks': info['cutbacks'], 'stopped_early': info['stopped_early'],
                             'min_J': r['min_J'], 'max_green_strain': e_max, 'dead_loads': True,
                             'curve': r['curve']},
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(u),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        logger.info('Neo-Hookean solve: λ=%.4f, %d NR iterations, %d steps, %d cutbacks, min J %.4f',
                    lam, info['n_iterations'], info['n_steps'], info['cutbacks'], r['min_J'])
        return {
            'displacement': disp.tolist(), 'displacement_magnitude': dmag.tolist(),
            'von_mises_elemental': el_vm.tolist(), 'von_mises_nodal': node_vm.tolist(),
            'sigma_elemental': el_sigma.tolist(), 'solve_info': info,
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Piezoelectric (coupled displacement + electric potential) ───────────

    PIEZO_MAX_DOF = 400_000           # sparse direct solve of the indefinite coupled system

    def _solve_piezo(self, mesh, mesh_meta, material, mat_spec, spec, all_bcs, all_loads,
                     tier, socketio, run_id, t_start, T=None, thermal=None) -> dict:
        import scipy.sparse as sp
        from scipy.sparse.linalg import spsolve
        from app.design.services.fem import piezo as pz
        pm = material.pm
        n = mesh.n_nodes
        n_dof = 4 * n
        if n_dof > self.PIEZO_MAX_DOF:
            raise ValueError(f'Piezoeléctrico: {n_dof:,} incógnitas (u + φ) superan el límite del solver directo '
                             f'({self.PIEZO_MAX_DOF:,}); usa una malla más gruesa.')
        mech_bcs = [b for b in all_bcs if 'voltage' not in b and not th.is_thermal_bc(b)]
        mech_loads = [ld for ld in all_loads if 'surface_charge' not in ld and not th.is_thermal_load(ld)]
        rho = float(mat_spec.get('rho', 0.0) or 0.0)
        mech_loads = [({**ld, 'density': ld.get('density', rho)} if 'gravity' in ld else ld) for ld in mech_loads]
        load_info: list = []
        F = assemble_F(mesh, mech_loads, load_info)
        Q = pz.charge_vector(mesh, all_loads, load_info)
        udofs, uvals = dirichlet(mesh, mech_bcs) if mech_bcs else (np.zeros(0, np.int64), np.zeros(0))
        vnodes, vvals, groups = pz.voltage_dirichlet(mesh, all_bcs)
        if not len(udofs):
            raise ValueError('Piezoeléctrico: faltan apoyos mecánicos (movimiento de cuerpo rígido).')
        if not len(vnodes):
            raise ValueError('Piezoeléctrico: define al menos un electrodo con potencial impuesto (p. ej. 0 V).')
        self._emit(socketio, run_id, 20, f'ensamblando u + φ ({n_dof:,} incógnitas)', t_start)
        K, Kuu, Kuf, Kff = pz.assemble(mesh, pm)
        tp = None
        if T is not None:                       # thermo-piezo: thermal strain load and pyroelectric charge
            F = F + th.thermal_load(mesh, pm.C, T, material.alpha, material.T_ref)
            Q = Q + pz.pyro_vector(mesh, material.p_global, T, material.T_ref)
            tp = (T, material.alpha, material.T_ref, material.p_global)
        rhs = np.concatenate([F, -Q])
        dofs = np.concatenate([udofs, 3 * n + vnodes])
        vals = np.concatenate([uvals, vvals])
        x = np.zeros(n_dof)
        x[dofs] = vals
        mask = np.ones(n_dof, bool)
        mask[dofs] = False
        free = np.flatnonzero(mask)
        self._emit(socketio, run_id, 50, 'resolviendo el sistema acoplado (directo)', t_start)
        # symmetric diagonal scaling: stiffness ~1e11 vs permittivity ~1e-8 would cost ~8 digits in the LU
        Kf = K[free][:, free].tocsc()
        sc = 1.0 / np.sqrt(np.abs(Kf.diagonal()))
        Ds = sp.diags(sc)
        y = spsolve((Ds @ Kf @ Ds).tocsc(), sc * (rhs[free] - K[free][:, dofs] @ vals))
        x[free] = sc * y
        u, phi = x[:3 * n], x[3 * n:]
        R = K @ x - rhs
        resid = float(np.linalg.norm(R[free]) / max(np.linalg.norm(rhs), np.linalg.norm(R[dofs]), 1e-30))
        reaction = [float(R[:3 * n][c::3][udofs[udofs % 3 == c] // 3].sum()) for c in range(3)]
        applied = [float(F[c::3].sum()) for c in range(3)]
        scale = max(1e-30, float(np.abs(applied).max()), float(np.abs(reaction).max()))
        electrodes = [{'label': bc.get('label'), 'voltage_V': float(bc['voltage']),
                       'charge_C': float(-R[3 * n + nodes].sum()), 'n_nodes': int(len(nodes))}
                      for bc, nodes in groups]
        post = pz.postprocess(mesh, pm, u, phi, thermal=tp)
        el_vm = tb.von_mises_v(post['sigma_gp'].mean(axis=1))
        node_vm = tb.von_mises_v(post['sigma_nodal'])
        Emag = np.linalg.norm(post['E_nodal'], axis=1)
        disp = u.reshape(-1, 3)
        dmag = np.linalg.norm(disp, axis=1)
        d = pm.d_matrix()
        s = {
            'physics': ['thermal', 'piezoelectric'] if T is not None else ['piezoelectric'],
            'max_displacement_m': float(dmag.max()), 'max_displacement_mm': round(float(dmag.max()) * 1000, 6),
            'max_von_mises_pa': float(el_vm.max()), 'max_von_mises_mpa': round(float(el_vm.max()) / 1e6, 4),
            'max_von_mises_nodal_mpa': round(float(node_vm.max()) / 1e6, 4),
            'n_nodes': n, 'n_elements': mesh.n_elements, 'n_dof': n_dof, 'element_type': mesh.element_type,
            'tier': tier, 'converged': bool(resid < 1e-8), 'n_iterations': 1, 'final_residual': resid,
            'solver_method': 'direct_coupled', 'wall_time_s': round(time.perf_counter() - t_start, 3),
            'applied_load_N': applied, 'reaction_N': reaction,
            'equilibrium_error': float(np.abs(np.add(reaction, applied)).max() / scale)
            if max(np.abs(applied).max(), np.abs(reaction).max()) > 0 else 0.0,
            'loads': load_info, 'n_constrained_dofs': int(len(dofs)), 'material_model': 'piezoelectric',
            'piezo': {'electrodes': electrodes, 'min_potential_V': float(phi.min()), 'max_potential_V': float(phi.max()),
                      'max_field_V_m': float(Emag.max()),
                      'd_pC_N': {'d31': d[2, 0] * 1e12, 'd33': d[2, 2] * 1e12, 'd15': d[0, 5] * 1e12}
                      if np.allclose(pm.R, np.eye(3)) else None},
            'extra_fields': [{'key': 'phi', 'label': 'Potencial eléctrico', 'unit': 'V'},
                             {'key': 'Emag', 'label': '|E| campo eléctrico', 'unit': 'kV/mm'}]
            + ([{'key': 'T', 'label': 'Temperatura', 'unit': '°C'}] if T is not None else []),
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(x),
        }
        if T is not None:
            s['thermal'] = {k: v for k, v in thermal.items() if k != 'heat_flux_nodal'}
            s['max_temperature'], s['min_temperature'] = float(T.max()), float(T.min())
            s['material_model'] = 'thermopiezoelectric'
            s['piezo']['p3_C_m2K'] = material.p3
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'displacement': disp.tolist(), 'displacement_magnitude': dmag.tolist(),
            'von_mises_elemental': el_vm.tolist(), 'von_mises_nodal': node_vm.tolist(),
            'sigma_elemental': post['sigma_gp'].mean(axis=1).tolist(), 'potential': phi,
            'extra_fields': {'phi': phi, 'Emag': Emag / 1e6, **({'T': T} if T is not None else {})},
            'solve_info': {'method': 'direct_coupled', 'converged': s['converged'], 'final_residual': resid},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Newtonian fluid (steady Stokes, Taylor-Hood) ─────────────────────────

    FLUID_MAX_DOF = 400_000           # sparse direct solve of the saddle-point system

    def _solve_fluid(self, mesh, mesh_meta, material, spec, all_bcs, all_loads, tier,
                     socketio, run_id, t_start) -> dict:
        from app.design.services.fem import stokes as st
        fm = material.fm
        n = mesh.n_nodes
        n_dof = 3 * n + len(np.unique(mesh.elements[:, :4]))
        if mesh.element_type != 'T10':
            raise ValueError('Fluido: hace falta malla cuadrática T10 (elementos Taylor-Hood P2-P1).')
        if n_dof > self.FLUID_MAX_DOF:
            raise ValueError(f'Fluido: {n_dof:,} incógnitas (velocidad + presión) superan el límite del solver '
                             f'directo ({self.FLUID_MAX_DOF:,}); usa una malla más gruesa.')
        loads = [({**ld, 'density': ld.get('density', fm.rho)} if 'gravity' in ld else ld) for ld in all_loads]
        load_info: list = []
        F = assemble_F(mesh, loads, load_info)
        dofs, vals = dirichlet(mesh, all_bcs) if all_bcs else (np.zeros(0, np.int64), np.zeros(0))
        if not len(dofs):
            raise ValueError('Fluido: faltan condiciones de velocidad (paredes sin deslizamiento, entrada …).')
        if fm.inertia:
            self._emit(socketio, run_id, 30, f'Navier-Stokes: Stokes inicial + Picard/Newton ({n_dof:,} incógnitas)',
                       t_start)

            def prog(it, msg):
                self._emit(socketio, run_id, min(30 + 3 * it, 90), msg, t_start)
            body = np.zeros(3)                       # uniform body force density for the SUPG residual
            for ld in loads:
                if 'gravity' in ld:
                    body += float(ld.get('density', 0.0)) * np.asarray(ld['gravity'], float)
                elif 'body_force' in ld:
                    body += np.asarray(ld['body_force'], float)
            v, p, info = st.solve_ns(mesh, fm, F, dofs, vals, progress=prog, stabilization=fm.stabilization,
                                     body=body)
        else:
            self._emit(socketio, run_id, 30, f'Stokes: resolviendo velocidad + presión ({n_dof:,} incógnitas)',
                       t_start)
            v, p, info = st.solve(mesh, fm, F, dofs, vals)
        vmag = np.linalg.norm(v, axis=1)
        flows, seen = [], set()
        for e in all_bcs + all_loads:
            fs = e.get('face_set')
            key = repr(fs)
            if fs is None or key in seen:
                continue
            seen.add(key)
            q, area = st.flow_rate(mesh, v, fs)
            flows.append({'face_set': fs if isinstance(fs, str) else f'{len(fs)} caras', 'label': e.get('label'),
                          'flow_m3_s': q, 'area_m2': area})
        net, _ = st.flow_rate(mesh, v, '@all')
        q_scale = max([abs(f['flow_m3_s']) for f in flows] + [1e-300])
        ext = mesh.nodes.max(0) - mesh.nodes.min(0)
        Lc = float(ext[ext > 0].min()) if np.any(ext > 0) else 0.0
        Re = fm.rho * float(vmag.max()) * Lc / fm.mu
        R = info['reaction']
        wall = [float(-R[dofs[dofs % 3 == c]].sum()) for c in range(3)]
        resid = info['residual']
        s = {
            'physics': ['fluid'],
            'n_nodes': n, 'n_elements': mesh.n_elements, 'n_dof': info['n_dof'], 'element_type': mesh.element_type,
            'tier': tier, 'converged': bool(resid < 1e-8), 'final_residual': resid,
            'n_iterations': info['navier_stokes']['iterations'] if fm.inertia else 1,
            'solver_method': 'newton_picard_saddle_point' if fm.inertia else 'direct_saddle_point',
            'wall_time_s': round(time.perf_counter() - t_start, 3),
            'loads': load_info, 'n_constrained_dofs': int(len(dofs)), 'material_model': 'newtonian_fluid',
            'fluid': {'mu': fm.mu, 'rho': fm.rho, 'max_velocity_m_s': float(vmag.max()),
                      'min_pressure_pa': float(p.min()), 'max_pressure_pa': float(p.max()),
                      'flow_rates': flows, 'mass_balance_error': abs(net) / q_scale if flows else abs(net),
                      'reynolds': Re, 'length_scale_m': Lc, 'pressure_pinned': info['pressure_pinned'],
                      'wall_force_N': wall,
                      'max_shear_rate_1_s': st.velocity_gradient_max(mesh, v)},
            'extra_fields': [{'key': 'vmag', 'label': '|v| velocidad', 'unit': 'mm/s'},
                             {'key': 'vx', 'label': 'vx', 'unit': 'mm/s'},
                             {'key': 'vy', 'label': 'vy', 'unit': 'mm/s'},
                             {'key': 'vz', 'label': 'vz', 'unit': 'mm/s'},
                             {'key': 'p', 'label': 'Presión', 'unit': 'Pa'}],
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(np.concatenate([v.ravel(), p])),
        }
        s['fluid']['model'] = 'navier_stokes' if fm.inertia else 'stokes'
        warnings = []
        if fm.inertia:
            ns = info['navier_stokes']
            Re_h = st.element_reynolds_max(mesh, v, fm)
            s['fluid']['navier_stokes'] = {k: ns[k] for k in ('iterations', 'picard_iterations', 'newton_iterations',
                                                              'continuation_steps', 'newton_residuals')}
            s['fluid']['navier_stokes']['element_reynolds_max'] = Re_h
            s['fluid']['navier_stokes']['stabilization'] = fm.stabilization
            s['fluid']['navier_stokes']['curve'] = [{'it': i + 1, 'lambda': h['lambda'], 'mode': h['mode'],
                                                     'residual': h['residual']} for i, h in enumerate(ns['history'])]
            if Re > 2000:
                warnings.append(f'Re ≈ {Re:.3g}: por encima de ~2000 el flujo suele ser turbulento o no estacionario; '
                                'este modelo laminar estacionario no lo representa.')
            if Re_h > 100 and not fm.stabilization:
                warnings.append(f'Reynolds de elemento máx. ≈ {Re_h:.3g} (> 100): sin estabilización la solución puede '
                                'oscilar entre nodos; active la estabilización SUPG o refine la malla donde la velocidad es alta.')
        elif Re > 1.0:
            warnings.append(f'Re ≈ {Re:.3g} > 1: el modelo de Stokes (flujo lento) desprecia la inercia; '
                            'el resultado no es fiable a este Reynolds. Active Navier-Stokes en el material.')
        if warnings:
            s['warnings'] = warnings
        if mesh_meta:
            s['mesh'] = {k: val for k, val in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'velocity': v, 'pressure': p,
            'extra_fields': {'vmag': vmag * 1e3, 'vx': v[:, 0] * 1e3, 'vy': v[:, 1] * 1e3, 'vz': v[:, 2] * 1e3,
                             'p': p},
            'solve_info': {'method': 'direct_saddle_point', 'converged': s['converged'], 'final_residual': resid},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Species transport (FASE 10.1 + 10.2) ─────────────────────────────────

    @staticmethod
    def _run_velocity(run_id: str, mesh: FEMMesh) -> tuple[np.ndarray, dict]:
        """Nodal velocity [m/s] of a finished fluid run on the same mesh (HDF5 fields x_vx/x_vy/x_vz, mm/s)."""
        import h5py
        from flask import current_app
        data_dir = str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver'))
        path = os.path.join(data_dir, f'{run_id}.h5')
        if not os.path.exists(path):
            raise ValueError(f'Transporte: el run de fluido {run_id} no tiene resultados guardados.')
        with h5py.File(path, 'r') as f:
            if 'fields/x_vx/step_0' not in f:
                raise ValueError(f'Transporte: el run {run_id} no es un run de fluido (sin campo de velocidad).')
            X = f['nodes'][:]
            v = np.column_stack([f[f'fields/x_{k}/step_0'][:] for k in ('vx', 'vy', 'vz')]) * 1e-3
        if X.shape != mesh.nodes.shape or not np.allclose(X, mesh.nodes, rtol=0, atol=1e-9 * max(1.0, np.abs(X).max())):
            raise ValueError('Transporte: la malla del run de fluido no coincide con la de este estudio (misma '
                             'geometría, tamaño y orden de malla).')
        return v, {'source': 'run', 'run_id': str(run_id), 'max_velocity_m_s': float(np.linalg.norm(v, axis=1).max())}

    def _solve_transport(self, mesh, mesh_meta, mat_spec, spec, all_bcs, all_loads, tier,
                         socketio, run_id, t_start) -> dict:
        from app.design.services.fem import transport as tr
        model = tr.TransportModel(mat_spec)
        bcs = [b for b in all_bcs if tr.is_transport_bc(b)]
        loads = [ld for ld in all_loads if tr.is_transport_load(ld)]
        other = len(all_bcs) - len(bcs) + len(all_loads) - len(loads)
        if other:
            raise ValueError('Transporte: solo admite concentración impuesta (BC) y flujo / intercambio / fuentes de '
                             f'especie (cargas); hay {other} condiciones mecánicas, térmicas u otras.')
        vel = mat_spec.get('velocity')
        v_field = None
        if isinstance(vel, dict) and vel.get('run_id'):
            v_field, vinfo = self._run_velocity(vel['run_id'], mesh)
        elif spec.get('velocity_field') is not None:                       # inline nodal field (tests / scripts)
            v_field = np.asarray(spec['velocity_field'], float)
            vinfo = {'source': 'field', 'max_velocity_m_s': float(np.linalg.norm(v_field, axis=1).max())}
        else:
            vinfo = {'source': 'uniform', 'velocity_m_s': (model.velocity if model.velocity is not None
                                                           else np.zeros(3)).tolist()}
        time_spec = spec.get('time') or None
        ns, n = model.n_species, mesh.n_nodes
        self._emit(socketio, run_id, 10, f'transporte: {ns} especie(s), {ns * n:,} incógnitas'
                   + (f", {int(time_spec['n_steps'])} pasos" if time_spec else ' (estacionario)'), t_start)

        def prog(k, total, t):
            self._emit(socketio, run_id, 10 + int(80 * k / total), f'transporte: paso {k}/{total} (t = {t:.4g} s)',
                       t_start)
        snaps, info = tr.solve(mesh, model, bcs, loads, velocity=v_field, time=time_spec,
                               initial=mat_spec.get('initial'), probes=spec.get('probes'), progress=prog)
        prob = info.pop('problem')
        t_final, x = snaps[-1]
        X_all = np.stack([s[1] for s in snaps])                             # (n_out, ns·N)
        xmax = X_all.max(0)
        species_out, extra, fields = [], {}, []
        for s, spc in enumerate(model.species):
            sl = slice(s * n, (s + 1) * n)
            c = x[sl]
            key = f'c{s}'
            d = {'name': spc['name'], 'unit': spc['unit'], 'mass_unit': tr.mass_unit(spc['unit']), 'D': spc['D'],
                 'decay': spc['decay'], 'max_c': float(c.max()), 'min_c': float(c.min()),
                 'max_c_any_time': float(xmax[sl].max()), 'min_c_any_time': float(X_all[:, sl].min())}
            if info['steady']:
                d['rates'] = {k: info['rates'][k][s] for k in info['rates']}
                d['mass'] = info['mass'][s]
            else:
                d['mass_initial'] = info['mass_initial'][s]
                d['mass_final'] = info['mass_final'][s]
                d['budget'] = {k: info['budget'][k][s] for k in info['budget']}
            if spc.get('threshold') not in (None, ''):
                thr = float(spc['threshold'])
                d['threshold'] = thr
                d['volume_above_m3'] = tr.volume_above(mesh, c, thr)
                if not info['steady']:
                    d['volume_above_max_m3'] = tr.volume_above(mesh, xmax[sl], thr)
            species_out.append(d)
            extra[key] = c
            fields.append({'key': key, 'label': spc['name'], 'unit': spc['unit'], 'series': not info['steady']})
            if not info['steady']:
                extra[f'cmax{s}'] = xmax[sl]
                fields.append({'key': f'cmax{s}', 'label': f'{spc["name"]} máx. en el tiempo', 'unit': spc['unit']})
        trans = {'steady': info['steady'], 'n_species': ns, 'species': species_out, 'velocity': vinfo,
                 'stabilization': model.stabilization, 'peclet_max': tr.peclet_max(prob),
                 'mass_balance_error': info['mass_balance_error'], 'solver': info['solver'],
                 'reaction_matrix': model.R.tolist()}
        warnings = []
        if not info['steady']:
            ts = info['time']
            trans['time'] = {k: ts[k] for k in ('t_end', 'n_steps', 'dt', 'scheme', 'theta', 'n_output')}
            trans['courant_max'] = tr.courant_max(prob, ts['dt'])
            trans['times'] = [float(t) for t, _ in snaps]
            trans['mass_history'] = info['mass_history'][::max(1, len(info['mass_history']) // 200)]
        if model.streeter_phelps:
            sp_ = model.streeter_phelps
            DO = sp_['do_sat'] - x[n:2 * n]
            i = int(np.argmin(DO))
            trans['streeter_phelps'] = {**sp_, 'min_DO': float(DO[i]), 'min_DO_point_m': mesh.nodes[i].tolist(),
                                        'max_deficit': float(x[n:2 * n].max())}
            extra['DO'] = DO
            fields.append({'key': 'DO', 'label': 'Oxígeno disuelto', 'unit': model.species[1]['unit']})
            if sp_['do_sat'] > 0 and DO[i] < 0:
                warnings.append('El oxígeno disuelto calculado es negativo (déficit > saturación): la carga de DBO '
                                'agota el oxígeno; el modelo lineal de Streeter–Phelps deja de ser válido (anoxia).')
        if info['curves']:
            locs = info['probe_locations']
            trans['probes'] = [{'label': p.get('label') or f'P{i + 1}', 'point': list(map(float, p['point'])),
                                'inside': lc['inside'], 'distance_m': lc['distance_m'],
                                'curve': [[row[0]] + row[1 + i] for row in info['curves']]}
                               for i, (p, lc) in enumerate(zip(spec.get('probes') or [], locs))]
            stride = max(1, len(info['curves']) // 500)                      # summary stays small (≤ ~500 rows)
            for p in trans['probes']:
                vals = np.array([r[1:] for r in p['curve']])
                p['max'] = vals.max(0).tolist()
                p['t_max'] = [float(p['curve'][int(j)][0]) for j in vals.argmax(0)]
                p['curve'] = p['curve'][::stride] + ([p['curve'][-1]] if (len(p['curve']) - 1) % stride else [])
        Pe = trans['peclet_max']
        if model.stabilization == 'none' and Pe > 1:
            warnings.append(f'Péclet de elemento máx. ≈ {Pe:.3g} (> 1) sin estabilización: la concentración puede '
                            'oscilar entre nodos; active SUPG o refine la malla.')
        cmax_all = max(float(np.abs(X_all).max()), 1e-300)
        cmin_all = float(X_all.min())
        if cmin_all < -0.01 * cmax_all:
            warnings.append(f'Concentración mínima {cmin_all:.3g} (< −1 % del máximo): sub-oscilación en un frente '
                            'abrupto; refine la malla en el frente o reduzca el paso de tiempo.')
        trans['undershoot'] = min(cmin_all, 0.0) / cmax_all
        resid = info['mass_balance_error']
        s = {
            'physics': ['transport'],
            'n_nodes': n, 'n_elements': mesh.n_elements, 'n_dof': ns * n, 'element_type': mesh.element_type,
            'tier': tier, 'converged': bool(resid < 1e-6), 'n_iterations': (info['time']['n_steps']
                                                                            if not info['steady'] else 1),
            'final_residual': resid, 'solver_method': info['solver'],
            'wall_time_s': round(time.perf_counter() - t_start, 3), 'loads': prob.info,
            'material_model': 'scalar_transport', 'transport': trans, 'extra_fields': fields,
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements), 'result_hash': array_hash(x),
        }
        if warnings:
            s['warnings'] = warnings
        if mesh_meta:
            s['mesh'] = {k: val for k, val in mesh_meta.items() if k not in ('attempts', 'bridge')}
        series = None
        if not info['steady']:
            series = {'times': trans['times'],
                      'fields': {f'c{s_}': X_all[:, s_ * n:(s_ + 1) * n] for s_ in range(ns)}}
            if model.streeter_phelps:
                series['fields']['DO'] = model.streeter_phelps['do_sat'] - X_all[:, n:2 * n]
        return {
            'concentration': x, 'extra_fields': extra, 'time_series': series,
            'solve_info': {'method': info['solver'], 'converged': s['converged'], 'final_residual': resid},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Linear magnetostatics (scalar potential, current-free) ───────────────

    def _solve_magnetic(self, mesh, mesh_meta, material, all_bcs, all_loads, tier,
                        socketio, run_id, t_start) -> dict:
        from app.design.services.fem import magnetic as mg
        mm = material.mm
        bcs = [b for b in all_bcs if mg.is_magnetic_bc(b)]
        loads = [ld for ld in all_loads if mg.is_magnetic_load(ld)]
        other = len(all_bcs) - len(bcs) + len(all_loads) - len(loads)
        if other:
            raise ValueError('Magnético: solo admite potencial magnético (BC) y flujo magnético impuesto (carga); '
                             f'hay {other} condiciones mecánicas/térmicas.')
        if not bcs and not loads and not np.any(mm.Br):
            raise ValueError('Magnético: sin imán (Br), potencial ni flujo impuesto el campo es nulo.')
        if mm.curve is not None or any(mg.is_coil(b) for b in bcs):
            return self._solve_magnetic_sweep(mesh, mesh_meta, mm, bcs, loads, tier, socketio, run_id, t_start)
        self._emit(socketio, run_id, 30, f'magnetostática: resolviendo ψ ({mesh.n_nodes:,} incógnitas)', t_start)
        disp = FEMSolverDispatcher()
        info_lin: dict = {}

        def lin(Kf, r):
            x, inf = disp.solve_linear(Kf, r, tier=tier, tol=1e-10)
            info_lin.update(inf)
            return x

        psi, info = mg.solve(mesh, mm, bcs, loads, linear_solve=lin)
        H, B = mg.fields(mesh, psi, mm)
        Bm, Hm = np.linalg.norm(B, axis=1), np.linalg.norm(H, axis=1)
        poles = [{'label': b.get('label'), 'potential_A': float(b['magnetic_potential']),
                  'face_set': b.get('face_set') if isinstance(b.get('face_set'), str)
                  else f"{len(b.get('face_set') or [])} caras",
                  'flux_in_Wb': f} for b, f in zip(bcs, info['flux_in_Wb'])]
        W = mg.energy(mesh, psi, mm)
        mag = {'mu_r': mm.mu_r, 'Br_T': mm.Br.tolist(), 'max_B_T': float(Bm.max()), 'max_H_A_m': float(Hm.max()),
               'min_potential_A': float(psi.min()), 'max_potential_A': float(psi.max()),
               'poles': poles, 'flux_loads': info['loads'], 'field_energy_J': W,
               'potential_pinned': info['pinned']}
        levels = sorted({p['potential_A'] for p in poles})
        if len(levels) == 2 and not loads and not np.any(mm.Br):
            mmf = levels[1] - levels[0]
            phi = sum(p['flux_in_Wb'] for p in poles if p['potential_A'] == levels[1])
            mag.update(mmf_A=mmf, flux_Wb=phi, permeance_H=phi / mmf if mmf else None,
                       reluctance_1_H=mmf / phi if phi else None)
        resid = info['residual']
        s = {
            'physics': ['magnetic'],
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_nodes,
            'element_type': mesh.element_type, 'tier': tier, 'converged': bool(resid < 1e-6), 'n_iterations': 1,
            'final_residual': resid, 'solver_method': info_lin.get('method', 'direct'),
            'wall_time_s': round(time.perf_counter() - t_start, 3), 'loads': info['loads'],
            'material_model': 'linear_magnetic', 'magnetic': mag,
            'extra_fields': [{'key': 'Bmag', 'label': '|B| densidad de flujo', 'unit': 'T'},
                             {'key': 'Bx', 'label': 'Bx', 'unit': 'T'}, {'key': 'By', 'label': 'By', 'unit': 'T'},
                             {'key': 'Bz', 'label': 'Bz', 'unit': 'T'},
                             {'key': 'Hmag', 'label': '|H| intensidad de campo', 'unit': 'kA/m'},
                             {'key': 'psi', 'label': 'Potencial magnético ψ', 'unit': 'A'}],
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(psi),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'magnetic_potential': psi,
            'extra_fields': {'Bmag': Bm, 'Bx': B[:, 0], 'By': B[:, 1], 'Bz': B[:, 2], 'Hmag': Hm / 1e3, 'psi': psi},
            'solve_info': {'method': s['solver_method'], 'converged': s['converged'], 'final_residual': resid},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    def _solve_magnetic_sweep(self, mesh, mesh_meta, mm, bcs, loads, tier, socketio, run_id, t_start) -> dict:
        """Coil excitation and / or saturation: the coil potentials (ψ = N·I on the coil's faces, relative to
        the other pole faces) are swept from I/steps to I; saturating materials are solved by Newton from the
        previous point. Reports the magnetisation curve λ(I) = N·Φ with secant and incremental inductance."""
        from app.design.services.fem import magnetic as mg
        coils = [i for i, b in enumerate(bcs) if mg.is_coil(b)]
        curve = mm.curve
        steps = max([int(bcs[i]['coil'].get('steps') or 0) for i in coils] + [0]) or (10 if curve and coils else 1)
        disp = FEMSolverDispatcher()
        info_lin: dict = {}

        def lin(Kf, r):
            x, inf = disp.solve_linear(Kf, r, tier=tier, tol=1e-12)
            info_lin.update(inf)
            return x

        rows, psi, info, newton_its = [], None, {}, 0
        for k in range(1, steps + 1):
            lam = k / steps
            bk = [({**b, 'magnetic_potential': lam * float(b['magnetic_potential'])} if i in coils else b)
                  for i, b in enumerate(bcs)]
            if curve is not None:
                psi, info = mg.solve_nonlinear(mesh, curve, bk, loads, psi0=psi, linear_solve=lin)
                newton_its += info['newton_iterations']
                H, B = mg.fields_nonlinear(mesh, psi, curve)
            else:
                psi, info = mg.solve(mesh, mm, bk, loads, linear_solve=lin)
                info['energy_J'] = mg.energy(mesh, psi, mm)
                info['coenergy_J'] = info['energy_J']
                H, B = mg.fields(mesh, psi, mm)
            row = {'factor': lam, 'max_B_T': float(np.linalg.norm(B, axis=1).max()),
                   'energy_J': info['energy_J'], 'coenergy_J': info['coenergy_J'], 'coils': []}
            for i in coils:
                c = bcs[i]['coil']
                N, I = float(c['turns']), lam * float(c['current'])
                phi = info['flux_in_Wb'][i]
                dP = mg.differential_permeance(mesh, psi, bk, i, curve=curve, mat=mm, linear_solve=lin)
                row['coils'].append({'current_A': I, 'mmf_A': N * I, 'flux_Wb': phi, 'flux_linkage_Wb': N * phi,
                                     'L_secant_H': N * phi / I if I else None, 'L_incremental_H': N * N * dP})
            rows.append(row)
            self._emit(socketio, run_id, 30 + int(60 * k / steps),
                       f'magnetostática: paso {k}/{steps}, |B| máx {row["max_B_T"]:.3g} T'
                       + (f', Newton {info["newton_iterations"]} it' if curve is not None else ''), t_start)
        Bm, Hm = np.linalg.norm(B, axis=1), np.linalg.norm(H, axis=1)
        last = rows[-1]
        poles = [{'label': b.get('label'), 'potential_A': float(b['magnetic_potential']),
                  'face_set': b.get('face_set') if isinstance(b.get('face_set'), str)
                  else f"{len(b.get('face_set') or [])} caras", 'flux_in_Wb': f,
                  **({'coil': True} if i in coils else {})} for i, (b, f) in enumerate(zip(bcs, info['flux_in_Wb']))]
        mag = {'mu_r': mm.mu_r if curve is None else curve.mu_r_initial, 'Br_T': mm.Br.tolist(),
               'max_B_T': float(Bm.max()), 'max_H_A_m': float(Hm.max()),
               'min_potential_A': float(psi.min()), 'max_potential_A': float(psi.max()), 'poles': poles,
               'flux_loads': info['loads'], 'field_energy_J': last['energy_J'], 'coenergy_J': last['coenergy_J'],
               'potential_pinned': info['pinned'], 'sweep_steps': steps,
               'coils': [{'label': bcs[i].get('label'), 'turns': float(bcs[i]['coil']['turns']),
                          **last['coils'][j]} for j, i in enumerate(coils)],
               'curve': [{'factor': r['factor'], 'max_B_T': r['max_B_T'], 'energy_J': r['energy_J'],
                          'coenergy_J': r['coenergy_J'], **(r['coils'][0] if r['coils'] else {})} for r in rows]}
        if curve is not None:
            mur = curve.ratio(Hm) / mg.MU0
            mag['saturation'] = {**curve.spec, 'mu_r_initial': curve.mu_r_initial, 'newton_iterations': newton_its,
                                 'min_mu_r': float(mur.min()), 'residuals': info['residuals']}
        resid = float(info['residual'])
        extra = [{'key': 'Bmag', 'label': '|B| densidad de flujo', 'unit': 'T'},
                 {'key': 'Bx', 'label': 'Bx', 'unit': 'T'}, {'key': 'By', 'label': 'By', 'unit': 'T'},
                 {'key': 'Bz', 'label': 'Bz', 'unit': 'T'},
                 {'key': 'Hmag', 'label': '|H| intensidad de campo', 'unit': 'kA/m'},
                 {'key': 'psi', 'label': 'Potencial magnético ψ', 'unit': 'A'}]
        fields = {'Bmag': Bm, 'Bx': B[:, 0], 'By': B[:, 1], 'Bz': B[:, 2], 'Hmag': Hm / 1e3, 'psi': psi}
        if curve is not None:
            extra.append({'key': 'mur', 'label': 'μr efectiva (B/μ₀H)', 'unit': ''})
            fields['mur'] = mur
        s = {
            'physics': ['magnetic'],
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_nodes,
            'element_type': mesh.element_type, 'tier': tier, 'converged': bool(resid < 1e-6),
            'n_iterations': newton_its or steps, 'final_residual': resid,
            'solver_method': info_lin.get('method', 'direct'),
            'wall_time_s': round(time.perf_counter() - t_start, 3), 'loads': info['loads'],
            'material_model': 'linear_magnetic' if curve is None else 'saturable_magnetic', 'magnetic': mag,
            'extra_fields': extra,
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(psi),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'magnetic_potential': psi, 'extra_fields': fields,
            'solve_info': {'method': s['solver_method'], 'converged': s['converged'], 'final_residual': resid},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Viscoelastic (generalized Maxwell, time stepping) ────────────────────

    VISCO_DIRECT_MAX_DOF = 60_000     # one sparse LU of K₀ reused by every time step; above: AMG-PCG per step

    def _solve_viscoelastic(self, mesh, mesh_meta, material, mat_spec, spec, all_bcs, all_loads,
                            tier, socketio, run_id, t_start) -> dict:
        from app.design.services.fem import viscoelastic as ve
        from app.design.services.fem import plasticity as pl
        prony = material.prony
        tm = spec.get('time') or {}
        t_end = float(tm.get('t_end') or 10 * float(prony.tau.max()))
        n_steps = int(tm.get('n_steps') or 40)
        history = tm.get('history') or [[0.0, 1.0], [t_end, 1.0]]
        rho = float(mat_spec.get('rho', 0.0) or 0.0)
        loads = [({**ld, 'density': ld.get('density', rho)} if 'gravity' in ld else ld) for ld in all_loads]
        load_info: list = []
        F = assemble_F(mesh, loads, load_info)
        dofs, vals = dirichlet(mesh, all_bcs)
        if not len(dofs):
            raise ValueError('Sin condiciones de frontera: el sistema es singular (movimiento de '
                             'cuerpo rígido). Agrega al menos un nodo BC.')
        D0 = material.get_D_matrix()
        K0 = assemble_K(mesh, D0)
        lin = None
        if len(mesh.nodes) * 3 - len(dofs) > self.VISCO_DIRECT_MAX_DOF:
            disp = FEMSolverDispatcher()
            B = rigid_body_modes(mesh.nodes)
            mask = np.ones(mesh.n_dof_structural, bool)
            mask[dofs] = False

            def lin(Kff, r):
                x, info = disp.solve_linear(Kff.tocsr(), r, tier=tier, tol=1e-10, near_nullspace=B[mask])
                return x

        def progress(n, total, t):
            self._emit(socketio, run_id, 30 + int(60 * (n + 1) / total), f'paso {n + 1}/{total} · t = {t:.4g} s',
                       t_start)

        self._emit(socketio, run_id, 30, f'viscoelástico: {n_steps} pasos hasta t = {t_end:.4g} s', t_start)
        r = ve.solve_viscoelastic(mesh, prony, D0, K0, F, dofs, vals, history, t_end, n_steps,
                                  linear_solver=lin, progress_cb=progress)
        u, lam, info, f_int = r['u'], r['load_factor'], r['info'], r['f_int']
        sig_gp = r['sigma_gp']
        Rf = f_int - lam * F
        reaction = [float(Rf[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)]
        applied = [float(lam * F[c::3].sum()) for c in range(3)]
        scale = max(1e-30, float(np.abs(applied).max()), float(np.abs(reaction).max()))
        equilibrium_error = float(np.abs(np.add(reaction, applied)).max() / scale)
        disp_ = u.reshape(-1, 3)
        dmag = np.linalg.norm(disp_, axis=1)
        el_sigma = sig_gp.mean(axis=1)
        el_vm = tb.von_mises_v(el_sigma)
        node_vm = tb.von_mises_v(pl.gp_to_nodal(mesh.n_nodes, mesh.elements, sig_gp))
        curve = r['curve']
        s = {
            'max_displacement_m': float(dmag.max()), 'max_displacement_mm': round(float(dmag.max()) * 1000, 6),
            'max_von_mises_pa': float(el_vm.max()), 'max_von_mises_mpa': round(float(el_vm.max()) / 1e6, 4),
            'max_von_mises_nodal_mpa': round(float(node_vm.max()) / 1e6, 4),
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_dof_structural,
            'element_type': mesh.element_type, 'tier': tier,
            'converged': info['converged'], 'n_iterations': info['n_iterations'],
            'final_residual': info['final_residual'], 'solver_method': info['method'],
            'wall_time_s': round(time.perf_counter() - t_start, 3),
            'applied_load_N': applied, 'reaction_N': reaction, 'equilibrium_error': equilibrium_error,
            'loads': load_info, 'n_constrained_dofs': int(len(dofs)),
            'material_model': 'viscoelastic_maxwell',
            'viscoelastic': {**prony.to_dict(), 't_end_s': t_end, 'n_time_steps': info['n_time_steps'],
                             'history': history, 'load_factor': lam,
                             'initial_max_displacement_m': curve[0]['max_displacement_m'] if curve else 0.0,
                             'creep_ratio': (curve[-1]['max_displacement_m'] / curve[0]['max_displacement_m']
                                             if curve and curve[0]['max_displacement_m'] > 0 else None),
                             'curve': curve},
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements),
            'result_hash': array_hash(u),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'displacement': disp_.tolist(), 'displacement_magnitude': dmag.tolist(),
            'von_mises_elemental': el_vm.tolist(), 'von_mises_nodal': node_vm.tolist(),
            'sigma_elemental': el_sigma.tolist(), 'solve_info': info,
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s, 'mesh': mesh,
        }

    # ── Thermal (FASE 2 multiphysics) ─────────────────────────────────────────

    def _solve_thermal(self, mesh: FEMMesh, mat_spec: dict, bcs: list, loads: list,
                       tier: int, tol: float) -> tuple[np.ndarray, dict]:
        """Steady conduction → nodal temperature + summary (heat balance, flux)."""
        k = conductivity(mat_spec)
        t0 = time.perf_counter()
        load_info: list = []
        K, F, conv = th.assemble_thermal(mesh, k, loads, load_info)
        dofs, vals = th.temperature_dirichlet(mesh, bcs)
        if not len(dofs) and not conv:
            raise ValueError('Problema térmico sin temperatura impuesta ni convección: la temperatura '
                             'queda indeterminada. Agrega un BC de temperatura o una carga de convección.')
        Kf, rhs, free = reduce_system(K, F, dofs, vals)
        Tf, info = FEMSolverDispatcher().solve_linear(Kf, rhs, tier=tier, tol=tol)
        T = np.zeros(mesh.n_nodes)
        T[free] = Tf
        T[dofs] = vals
        # heat balance [W]: sources + flux + heat entering at fixed-T faces = convective loss
        R = K @ T - F
        q_fixed = float(R[dofs].sum()) if len(dofs) else 0.0
        q_conv = th.convective_heat(mesh, T, conv)
        q_src = sum(m.get('heat_W', 0.0) for m in load_info if m.get('kind') == 'heat_source')
        q_flux = sum(m.get('heat_W', 0.0) for m in load_info if m.get('kind') == 'heat_flux')
        scale = max(1e-30, abs(q_src), abs(q_flux), abs(q_fixed), abs(q_conv))
        _, qn = th.heat_flux(mesh.nodes, mesh.elements, T, k)
        qmag = np.linalg.norm(qn, axis=1)
        return T, {
            'k': np.asarray(k).tolist(), 'n_dof': int(mesh.n_nodes), 'n_fixed_temperature_nodes': int(len(dofs)),
            'min_temperature': float(T.min()), 'max_temperature': float(T.max()),
            'max_heat_flux_w_m2': float(qmag.max()) if len(qmag) else 0.0,
            'heat_balance_W': {'source': q_src, 'flux_in': q_flux, 'fixed_T_in': q_fixed,
                               'convection_out': q_conv},
            'heat_balance_error': abs(q_src + q_flux + q_fixed - q_conv) / scale,
            'loads': load_info, 'solver_method': info.get('method'),
            'converged': info.get('converged', False), 'wall_time_s': round(time.perf_counter() - t0, 3),
            'heat_flux_nodal': qn.tolist(),
        }

    def _thermal_only_results(self, mesh, mesh_meta, T, thermal, tier, t_start) -> dict:
        qn = thermal.pop('heat_flux_nodal')
        s = {
            'physics': ['thermal'], 'thermal': thermal,
            'max_temperature': thermal['max_temperature'], 'min_temperature': thermal['min_temperature'],
            'max_heat_flux_w_m2': thermal['max_heat_flux_w_m2'],
            'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': mesh.n_nodes,
            'element_type': mesh.element_type, 'tier': tier,
            'converged': thermal['converged'], 'n_iterations': 1, 'final_residual': None,
            'solver_method': thermal['solver_method'],
            'wall_time_s': round(time.perf_counter() - t_start, 3),
            'mesh_hash': mesh_hash(mesh.nodes, mesh.elements), 'result_hash': array_hash(T),
        }
        if mesh_meta:
            s['mesh'] = {k: v for k, v in mesh_meta.items() if k not in ('attempts', 'bridge')}
        return {
            'temperature': T.tolist(), 'heat_flux_nodal': qn, 'mesh': mesh,
            'solve_info': {'method': thermal['solver_method'], 'converged': thermal['converged']},
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(), 'elements': mesh.elements.tolist(), 'summary': s,
        }

    # ── Mesh builder ──────────────────────────────────────────────────────────

    def _build_mesh(self, spec: dict, progress=None) -> tuple[FEMMesh, dict]:
        source = spec.get('mesh_source', 'inline')
        p = spec.get('mesh_params') or {}
        order = int(p.get('order', spec.get('element_order', 1)))

        if source == 'cantilever':
            return FEMMesh.generate_cantilever(
                length=float(p.get('length', 0.050)),
                width=float(p.get('width', 0.010)),
                height=float(p.get('height', 0.010)),
                n_along_length=int(p.get('n_along_length', 12)),
                order=order,
            ), {}

        if source == 'plate':
            kw = {k: float(p[k]) for k in ('length', 'height', 'thickness', 'mesh_size', 'support_width',
                                            'hole_radius') if p.get(k) is not None}
            return FEMMesh.generate_plate(**kw, order=order), {}

        if source == 'ring':
            kw = {k: float(p[k]) for k in ('inner_radius', 'outer_radius', 'thickness', 'mesh_size')
                  if p.get(k) is not None}
            return FEMMesh.generate_ring(**kw, order=int(p.get('order', 2))), {}

        if source == 'geometry':
            from app.design.services.fem.cad_mesh import mesh_geometry
            return mesh_geometry(spec['geometry_id'], mesh_size=p.get('mesh_size'),
                                 order=int(p.get('order', 2)), progress=progress)

        if source == 'cae_mesh':
            return FEMMesh.from_cae_mesh_id(spec['mesh_id']), {}

        if source == 'graph':
            return self._build_mesh_from_graph(spec['graph_id']), {}

        # 'inline'
        nodes = spec.get('nodes')
        elements = spec.get('elements')
        if nodes is None or elements is None:
            raise ValueError("Inline mesh requires 'nodes' and 'elements' in spec.")
        return FEMMesh.from_inline(nodes, elements, node_sets=spec.get('node_sets', {}),
                                   face_sets=spec.get('face_sets')), {}

    def _build_mesh_from_graph(self, graph_id: str) -> FEMMesh:
        """Extract mesh from the design graph's GEOMETRY node."""
        from app.design.models.graph import DesignNode

        geom_nodes = DesignNode.query.filter_by(
            graph_id=graph_id, node_type='GEOMETRY'
        ).all()

        if not geom_nodes:
            raise ValueError(f"No GEOMETRY node found in graph {graph_id}. "
                             "Add a geometry node first.")

        props = geom_nodes[0].properties or {}
        if 'mesh_id' in props:
            return FEMMesh.from_cae_mesh_id(props['mesh_id'])

        # Fall back to cantilever if no mesh attached (useful during dev)
        logger.warning("GEOMETRY node has no mesh_id. Generating default cantilever.")
        return FEMMesh.generate_cantilever()

    # ── Post-processing ───────────────────────────────────────────────────────

    def _postprocess(self, mesh: FEMMesh, D: np.ndarray,
                     u: np.ndarray, solve_info: dict, t_start: float, eps0=None) -> dict:
        """Displacement and stress fields (vectorised, T4 and T10); ``eps0`` = thermal strain."""
        disp = u.reshape(-1, 3)
        disp_mag = np.linalg.norm(disp, axis=1)
        max_disp = float(disp_mag.max()) if len(disp_mag) else 0.0

        el_sigma, nodal_sigma = tb.nodal_stress(mesh.nodes, mesh.elements, u, D, eps0=eps0)
        el_von_mises = tb.von_mises_v(el_sigma)
        node_vm = tb.von_mises_v(nodal_sigma)
        max_vm = float(el_von_mises.max()) if len(el_von_mises) else 0.0
        max_vm_nodal = float(node_vm.max()) if len(node_vm) else 0.0

        wall_total = time.perf_counter() - t_start

        return {
            'displacement': disp.tolist(),
            'displacement_magnitude': disp_mag.tolist(),
            'von_mises_elemental': el_von_mises.tolist(),
            'von_mises_nodal': node_vm.tolist(),
            'sigma_elemental': el_sigma.tolist(),
            'solve_info': solve_info,
            'surface_triangles': mesh.extract_surface_triangles(),
            'nodes': mesh.nodes.tolist(),
            'elements': mesh.elements.tolist(),
            'summary': {
                'max_displacement_m': max_disp,
                'max_displacement_mm': round(max_disp * 1000, 6),
                'max_von_mises_pa': max_vm,
                'max_von_mises_mpa': round(max_vm / 1e6, 4),
                'max_von_mises_nodal_mpa': round(max_vm_nodal / 1e6, 4),
                'n_nodes': mesh.n_nodes,
                'n_elements': mesh.n_elements,
                'n_dof': mesh.n_dof_structural,
                'tier': mesh.estimate_tier(),
                'converged': solve_info.get('converged', False),
                'n_iterations': solve_info.get('n_iterations', 0),
                'final_residual': solve_info.get('final_residual', None),
                'wall_time_s': round(wall_total, 3),
                'solver_method': solve_info.get('method', 'unknown'),
            },
        }

    # ── HDF5 result storage ───────────────────────────────────────────────────

    def _save_results(self, run_id: str, result: dict, app) -> str:
        """Save field results to HDF5 and update SimulationRun record."""
        try:
            import h5py
        except ImportError:
            logger.warning("h5py not installed; results not persisted to HDF5.")
            return ''

        data_dir = app.config.get('SOLVER_DATA_DIR', 'data/solver')
        os.makedirs(str(data_dir), exist_ok=True)
        path = os.path.join(str(data_dir), f"{run_id}.h5")

        with h5py.File(path, 'w') as f:
            f.create_dataset('nodes',    data=np.array(result['nodes']))
            f.create_dataset('elements', data=np.array(result['elements']))

            fields = f.create_group('fields')
            for name in ('displacement', 'displacement_magnitude', 'von_mises_nodal',
                         'von_mises_elemental', 'temperature', 'heat_flux_nodal',
                         'equivalent_plastic_strain', 'equivalent_plastic_strain_elemental'):
                if result.get(name) is not None:
                    fields.create_dataset(f'{name}/step_0', data=np.array(result[name]))

            series = result.get('time_series') or {}
            for key, data in (result.get('extra_fields') or {}).items():   # generic nodal fields (new physics)
                if key in (series.get('fields') or {}):
                    continue
                fields.create_dataset(f'x_{key}/step_0', data=np.asarray(data, dtype=np.float64))
            # transient results (FASE 10.2): fields/x_<key>/step_<n> in time order, attrs times + final_step
            for key, steps in (series.get('fields') or {}).items():
                g = fields.create_group(f'x_{key}')
                for i, arr in enumerate(steps):
                    g.create_dataset(f'step_{i}', data=np.asarray(arr, dtype=np.float64))
                g.attrs['times'] = np.asarray(series['times'], float)
                g.attrs['final_step'] = len(steps) - 1

            surf = result.get('surface_triangles', [])
            if surf:
                f.create_dataset('surface_triangles', data=np.array(surf))

            # Metadata
            for key in ('max_displacement_m', 'max_von_mises_pa', 'max_temperature', 'min_temperature'):
                if result['summary'].get(key) is not None:
                    f.attrs[key] = result['summary'][key]
            f.attrs['converged']           = int(result['summary']['converged'])
            f.attrs['element_type']        = result['summary'].get('element_type', 'T4')
            import json as _json
            f.attrs['summary_json'] = _json.dumps(
                {k: v for k, v in result['summary'].items()}, default=float)

        logger.info(f"Results saved to {path}")
        return path

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _update_run(self, run_id: str, status: str, result: dict = None,
                    error: str = None):
        if run_id is None:
            return
        try:
            from app.extensions import db
            from app.design.models.simulation import SimulationRun

            run = SimulationRun.query.filter_by(id=run_id).first()
            if not run:
                return
            run.status = status
            if error:
                run.mesh_stats = {**(run.mesh_stats or {}), 'error': str(error)[:2000]}

            if result:
                s = result.get('summary', {})
                si = result.get('solve_info', {})
                run.converged = s.get('converged')
                run.n_iterations = s.get('n_iterations')
                run.final_residual = s.get('final_residual')
                run.wall_time = s.get('wall_time_s')
                run.mesh_stats = {
                    'n_nodes': s.get('n_nodes'),
                    'n_elements': s.get('n_elements'),
                    'n_dof': s.get('n_dof'),
                    'element_type': s.get('element_type'),
                    'tier': s.get('tier'),
                    'equilibrium_error': s.get('equilibrium_error'),
                    'mesh': s.get('mesh'),
                }
                run.convergence_log = si.get('convergence_log', [])
                run.mesh_hash = s.get('mesh_hash')
                run.result_hash = s.get('result_hash')
                run.summary = _json_safe({k: v for k, v in s.items() if k != 'convergence_log'})
                if result.get('adaptive_log') is not None:
                    run.adaptive_log = _json_safe(result['adaptive_log'])

            db.session.commit()
        except Exception as e:
            logger.warning(f"Could not update SimulationRun {run_id}: {e}")

    def _record_fingerprint(self, run_id: str, solver_spec: dict):
        """Hash/environment as seen by the process that actually solves (the worker may run
        other library versions than the web process that enqueued the run)."""
        try:
            from app.extensions import db
            from app.design.models.simulation import SimulationRun
            from app.design.services.traceability.hasher import fingerprint, provenance
            run = db.session.get(SimulationRun, run_id)
            if run is None:
                return
            fp = fingerprint(solver_spec)
            if run.hash and run.hash != fp['hash']:
                logger.info('Run %s: worker hash %s differs from enqueue hash %s (environment)',
                            run_id, fp['hash'][:12], run.hash[:12])
            run.hash, run.inputs, run.environment = fp['hash'], fp['inputs'], fp['environment']
            run.provenance = provenance()
            db.session.commit()
        except Exception as e:
            logger.warning(f"Could not record fingerprint for run {run_id}: {e}")

    # ── Write-back results to RESULT nodes ───────────────────────────────────

    def _update_result_nodes(self, run_id: str, result: dict, solver_spec: dict):
        """Actualiza los nodos RESULT en el grafo con resultados de la simulación."""
        graph_id = solver_spec.get('graph_id')
        if not graph_id:
            return

        try:
            from app.extensions import db
            from app.design.models.graph import DesignGraph, DesignNode

            graph = DesignGraph.query.filter_by(id=graph_id).first()
            if not graph:
                return

            # Busca todos los nodos RESULT en el grafo
            result_nodes = DesignNode.query.filter_by(graph_id=graph_id, node_type='RESULT').all()
            if not result_nodes:
                return

            summary = result.get('summary', {})
            for node in result_nodes:
                node.properties = {
                    'run_id': str(run_id),
                    'max_von_mises_mpa': summary.get('max_von_mises_mpa'),
                    'max_displacement_mm': summary.get('max_displacement_mm'),
                    'safety_factor': 1.0,  # placeholder
                }

            db.session.commit()
            logger.info(f"Updated {len(result_nodes)} RESULT nodes for graph {graph_id}")
        except Exception as e:
            logger.warning(f"Could not update RESULT nodes for graph {graph_id}: {e}")

    # ── Analytical validation ─────────────────────────────────────────────────

    @staticmethod
    def cantilever_analytical(E: float, nu: float,
                              length: float, width: float, height: float,
                              tip_force: float) -> dict:
        """Euler-Bernoulli analytical solution for a cantilever beam.

        Force applied in Y direction at x=length.
        Moment of inertia about Z axis: I = width * height³ / 12.

        Returns:
            dict with tip_deflection_m, tip_deflection_mm, max_bending_stress_pa
        """
        I = width * height**3 / 12.0
        delta = tip_force * length**3 / (3.0 * E * I)
        sigma_max = tip_force * length * (height / 2.0) / I   # at x=0, top/bottom fiber
        return {
            'tip_deflection_m': delta,
            'tip_deflection_mm': round(delta * 1000, 6),
            'max_bending_stress_pa': sigma_max,
            'max_bending_stress_mpa': round(sigma_max / 1e6, 4),
            'I_m4': I,
        }


def _json_safe(x):
    """numpy scalars/arrays → plain JSON types (for JSONB columns)."""
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x
