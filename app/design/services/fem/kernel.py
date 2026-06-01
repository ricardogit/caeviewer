"""FEM Kernel — orchestrates the complete simulation pipeline.

FASE 2 full implementation:
  1. Build FEMMesh from spec (inline / cantilever / graph / cae mesh)
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

from app.design.services.fem.assembler import assemble_K, assemble_F, apply_bcs
from app.design.services.fem.constitutive import build_material
from app.design.services.fem.elements import t4_stress, von_mises
from app.design.services.fem.mesh import FEMMesh
from app.design.services.fem.solver import FEMSolverDispatcher, check_tier_limits, TierLimitExceeded
from app.design.services.fem.error_estimator import compute_error_indicators, mark_elements_for_refinement, compute_global_error
from app.design.services.fem.mesh_adaptivity import refine_marked_elements_bisection

logger = logging.getLogger(__name__)


class FEMKernel:
    """Orchestrates the full FEM pipeline from spec dict to results."""

    # ── Public async entry point ───────────────────────────────────────────────

    def solve_async(self, app, run_id: str, solver_spec: dict, socketio):
        """Called in a background thread by flask-socketio.start_background_task."""
        with app.app_context():
            self._update_run(run_id, 'running')
            socketio.emit('solver_progress',
                          {'run_id': run_id, 'iter': 0, 'status': 'starting',
                           'residual': None, 'wall_time': 0, 'percent': 0},
                          room=run_id)
            try:
                result = self._solve(run_id, solver_spec, socketio)
                self._save_results(run_id, result, app)
                self._update_run(run_id, 'done', result)
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

    # ── Synchronous solve (also used by the test endpoint) ────────────────────

    def solve_sync(self, solver_spec: dict) -> dict:
        """Run the solver synchronously and return the result dict."""
        return self._solve(run_id=None, solver_spec=solver_spec, socketio=None)

    # ── Adaptive refinement solve (FASE 3) ─────────────────────────────────────

    def solve_adaptive_sync(self, solver_spec: dict, max_cycles: int = 5,
                           target_error: float = 0.05, refinement_fraction: float = 0.2) -> dict:
        """Solve with adaptive h-refinement (longest-edge bisection).

        Args:
            solver_spec: as in solve_sync
            max_cycles: max refinement iterations
            target_error: stop if global error < target (0.05 = 5%)
            refinement_fraction: fraction of elements to refine per cycle
        """
        adaptive_log = []
        mesh_spec = solver_spec.copy()
        cycle = 0

        for cycle in range(max_cycles):
            # Solve with current mesh
            result = self._solve(run_id=None, solver_spec=mesh_spec, socketio=None)
            mesh = result['mesh']

            # Estimate error
            el_sigma = np.array(result['sigma_elemental'])
            E = float(solver_spec.get('material', {}).get('E', 210e9))
            nu = float(solver_spec.get('material', {}).get('nu', 0.3))

            error_indicators = compute_error_indicators(mesh.nodes, mesh.elements, el_sigma, E, nu)
            global_error = compute_global_error(error_indicators)

            log_entry = {
                'cycle': cycle,
                'n_nodes': mesh.n_nodes,
                'n_elements': mesh.n_elements,
                'global_error': float(global_error),
                'max_displacement_mm': result['summary']['max_displacement_mm'],
                'max_von_mises_mpa': result['summary']['max_von_mises_mpa'],
            }
            adaptive_log.append(log_entry)
            logger.info(f"Adaptive cycle {cycle}: {mesh.n_nodes} nodes, "
                       f"error={global_error:.4f}")

            # Check convergence
            if global_error < target_error or cycle == max_cycles - 1:
                result['adaptive_log'] = adaptive_log
                return result

            # Mark elements and refine
            mark_refine = mark_elements_for_refinement(
                error_indicators, strategy='fraction', target_fraction=refinement_fraction)
            n_marked = np.sum(mark_refine)
            logger.info(f"Refining {n_marked} elements ({100*n_marked/len(error_indicators):.1f}%)")

            nodes_new, elements_new = refine_marked_elements_bisection(
                mesh.nodes, mesh.elements, mark_refine)

            # Update spec for next cycle
            mesh_spec = solver_spec.copy()
            mesh_spec['mesh_source'] = 'inline'
            mesh_spec['nodes'] = nodes_new
            mesh_spec['elements'] = elements_new
            mesh_spec['element_type'] = 'T4'

        result['adaptive_log'] = adaptive_log
        return result

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def _solve(self, run_id, solver_spec: dict, socketio) -> dict:
        t_start = time.perf_counter()

        # 1. Build mesh
        mesh = self._build_mesh(solver_spec)

        # 2. Tier check
        tier = int(solver_spec.get('tier', mesh.estimate_tier()))
        check_tier_limits(mesh.n_nodes, mesh.n_elements, mesh.n_dof_structural, tier)

        # 3. Material / constitutive model
        mat_spec = solver_spec.get('material', {
            'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800.0
        })
        material = build_material(mat_spec)
        D = material.get_D_matrix()
        is_linear = material.is_linear()

        # Emit mesh info
        if socketio and run_id:
            socketio.emit('solver_progress', {
                'run_id': run_id, 'iter': 0, 'percent': 5,
                'status': f'mesh built: {mesh.n_nodes:,} nodes, {mesh.n_elements:,} elements',
                'wall_time': time.perf_counter() - t_start,
            }, room=run_id)

        # 4. Assemble K and F
        logger.info(f"Assembling K ({mesh.n_dof_structural:,} DOF)...")
        K = assemble_K(mesh, D)

        bcs = solver_spec.get('bcs', [])
        loads = solver_spec.get('loads', [])
        F = assemble_F(mesh, loads)

        if socketio and run_id:
            socketio.emit('solver_progress', {
                'run_id': run_id, 'iter': 0, 'percent': 30,
                'status': 'assembly complete, applying BCs',
                'wall_time': time.perf_counter() - t_start,
            }, room=run_id)

        # 5. Apply BCs
        K, F = apply_bcs(K, F, bcs, mesh)

        # 6. Solve
        solver = FEMSolverDispatcher()
        tol = float(solver_spec.get('tolerance', 1e-8))
        max_iter = int(solver_spec.get('max_iterations', 1000))

        def progress_cb(it, res):
            if socketio and run_id:
                pct = min(95, 35 + int(60 * it / max_iter))
                solver.stream_progress(socketio, run_id, it, res,
                                       time.perf_counter() - t_start, pct)

        u, solve_info = solver.solve(K, F, tier=tier, is_linear=is_linear,
                                     tol=tol, max_iter=max_iter,
                                     progress_cb=progress_cb)

        logger.info(f"Solve done: {solve_info['method']}, "
                    f"converged={solve_info['converged']}, "
                    f"wall={solve_info['wall_time']:.2f}s")

        # 7. Post-processing
        results = self._postprocess(mesh, D, u, solve_info, t_start)
        results['mesh'] = mesh
        return results

    # ── Mesh builder ──────────────────────────────────────────────────────────

    def _build_mesh(self, spec: dict) -> FEMMesh:
        source = spec.get('mesh_source', 'inline')

        if source == 'cantilever':
            p = spec.get('mesh_params', {})
            return FEMMesh.generate_cantilever(
                length=float(p.get('length', 0.050)),
                width=float(p.get('width', 0.010)),
                height=float(p.get('height', 0.010)),
                n_along_length=int(p.get('n_along_length', 12)),
            )

        elif source == 'cae_mesh':
            return FEMMesh.from_cae_mesh_id(spec['mesh_id'])

        elif source == 'graph':
            return self._build_mesh_from_graph(spec['graph_id'])

        else:  # 'inline'
            nodes = spec.get('nodes')
            elements = spec.get('elements')
            if nodes is None or elements is None:
                raise ValueError("Inline mesh requires 'nodes' and 'elements' in spec.")
            return FEMMesh.from_inline(
                nodes, elements,
                element_type=spec.get('element_type', 'T4'),
                node_sets=spec.get('node_sets', {}),
            )

    def _build_mesh_from_graph(self, graph_id: str) -> FEMMesh:
        """Extract mesh from the design graph's GEOMETRY node."""
        from app.design.models.graph import DesignNode

        geom_nodes = DesignNode.query.filter_by(
            graph_id=graph_id, node_type='GEOMETRY'
        ).all()

        if not geom_nodes:
            raise ValueError(f"No GEOMETRY node found in graph {graph_id}. "
                             "Add a geometry node first.")

        geom_node = geom_nodes[0]
        props = geom_node.properties or {}

        if 'mesh_id' in props:
            return FEMMesh.from_cae_mesh_id(props['mesh_id'])

        # Fall back to cantilever if no mesh attached (useful during dev)
        logger.warning(f"GEOMETRY node has no mesh_id. Generating default cantilever.")
        return FEMMesh.generate_cantilever()

    # ── Post-processing ───────────────────────────────────────────────────────

    def _postprocess(self, mesh: FEMMesh, D: np.ndarray,
                     u: np.ndarray, solve_info: dict, t_start: float) -> dict:
        """Compute displacement and stress fields from the solution vector."""

        # Displacement field: reshape (n_nodes, 3)
        disp = u.reshape(-1, 3)
        disp_mag = np.linalg.norm(disp, axis=1)
        max_disp = float(disp_mag.max())

        # Element stresses and Von Mises
        el_von_mises = np.zeros(mesh.n_elements, dtype=np.float64)
        el_sigma = np.zeros((mesh.n_elements, 6), dtype=np.float64)

        for i, el in enumerate(mesh.elements):
            u_e = u[np.array([3*n + d for n in el for d in range(3)])]
            coords = mesh.nodes[el]
            sigma = t4_stress(coords, D, u_e)
            el_sigma[i] = sigma
            el_von_mises[i] = von_mises(sigma)

        max_vm = float(el_von_mises.max())

        # Nodal Von Mises (average of adjacent elements)
        node_vm = np.zeros(mesh.n_nodes)
        node_count = np.zeros(mesh.n_nodes)
        for i, el in enumerate(mesh.elements):
            for n in el:
                node_vm[n] += el_von_mises[i]
                node_count[n] += 1
        with np.errstate(invalid='ignore'):
            node_vm = np.where(node_count > 0, node_vm / node_count, 0.0)

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
            fields.create_dataset('displacement/step_0',
                                  data=np.array(result['displacement']))
            fields.create_dataset('displacement_magnitude/step_0',
                                  data=np.array(result['displacement_magnitude']))
            fields.create_dataset('von_mises_nodal/step_0',
                                  data=np.array(result['von_mises_nodal']))
            fields.create_dataset('von_mises_elemental/step_0',
                                  data=np.array(result['von_mises_elemental']))

            surf = result.get('surface_triangles', [])
            if surf:
                f.create_dataset('surface_triangles', data=np.array(surf))

            # Metadata
            f.attrs['max_displacement_m'] = result['summary']['max_displacement_m']
            f.attrs['max_von_mises_pa']   = result['summary']['max_von_mises_pa']
            f.attrs['converged']           = int(result['summary']['converged'])

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
                    'tier': s.get('tier'),
                }
                run.convergence_log = si.get('convergence_log', [])

            db.session.commit()
        except Exception as e:
            logger.warning(f"Could not update SimulationRun {run_id}: {e}")

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
