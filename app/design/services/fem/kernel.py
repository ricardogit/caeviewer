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
                                                  ViscoelasticMaxwell)
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

        # 3b. Thermal field (FASE 2 multiphysics): steady conduction, then one-way coupling
        T = thermal = None
        if 'thermal' in physics:
            T, thermal = self._solve_thermal(mesh, mat_spec, [b for b in all_bcs if th.is_thermal_bc(b)],
                                             [ld for ld in all_loads if th.is_thermal_load(ld)], tier,
                                             float(solver_spec.get('tolerance', 1e-8)))
            self._emit(socketio, run_id, 20 if 'structural' in physics else 90,
                       f"thermal solved: T {thermal['min_temperature']:.4g} .. "
                       f"{thermal['max_temperature']:.4g}", t_start)
            if 'structural' not in physics:
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
