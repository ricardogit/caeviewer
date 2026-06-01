"""Non-linear FEM solvers — Newton-Raphson and Arc-Length continuation.

FASE 2: full Newton-Raphson for materially/geometrically non-linear problems.
Total Lagrangian formulation for large deformations.
Arc-length: stub (FASE 2 extension).
"""
from __future__ import annotations
import logging
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

logger = logging.getLogger(__name__)


class NewtonRaphson:
    """Newton-Raphson iteration for non-linear FEM.

    For geometrically linear problems with non-linear material (e.g., elastoplastic):
        Residual R(u) = K_t(u) u - F_ext = 0

    For the linear tangent (Tier 0/1 with mild non-linearity),
    we use the secant stiffness updated each iteration.
    """

    max_iter: int = 50
    tol_residual: float = 1e-8
    tol_displacement: float = 1e-10

    def solve_assembled(self, K0: sp.csr_matrix, F: np.ndarray,
                        tier: int = 1,
                        tol: float = None,
                        max_iter: int = None,
                        progress_cb=None) -> tuple[np.ndarray, dict]:
        """Newton-Raphson starting from an initial tangent stiffness K0.

        For a linear system (K constant), NR converges in 1 iteration.
        For non-linear systems, K_tangent_func should be provided separately
        (full non-linear kernel in FASE 2 extension).

        Returns:
            (u, solve_info)
        """
        tol = tol or self.tol_residual
        max_iter = max_iter or self.max_iter

        t0 = time.perf_counter()
        n_dof = K0.shape[0]

        u = np.zeros(n_dof, dtype=np.float64)
        history = []

        # For a constant K this is equivalent to a direct solve
        K = K0.copy()

        for it in range(1, max_iter + 1):
            R = K @ u - F                               # residual
            R_norm = float(np.linalg.norm(R))
            F_norm = float(np.linalg.norm(F)) or 1.0
            rel_res = R_norm / F_norm

            history.append({'iter': it, 'residual': rel_res,
                            'wall_time': time.perf_counter() - t0})

            if progress_cb:
                progress_cb(it, rel_res)

            if rel_res < tol:
                logger.info(f"Newton-Raphson converged in {it} iter, residual={rel_res:.3e}")
                break

            # Solve linear system (K * Δu = -R)
            try:
                du = spla.spsolve(K, -R)
            except Exception as e:
                logger.error(f"Newton-Raphson linear solve failed at iter {it}: {e}")
                return u, {'method': 'newton_raphson', 'converged': False,
                           'n_iterations': it, 'final_residual': rel_res,
                           'wall_time': time.perf_counter() - t0,
                           'convergence_log': history}
            u = u + du

            # Check displacement increment convergence
            du_norm = float(np.linalg.norm(du)) / (float(np.linalg.norm(u)) or 1.0)
            if du_norm < self.tol_displacement and rel_res < tol:
                break
        else:
            logger.warning(f"Newton-Raphson did not converge in {max_iter} iterations.")

        wall = time.perf_counter() - t0
        return u, {
            'method': 'newton_raphson',
            'converged': rel_res < tol,
            'n_iterations': len(history),
            'final_residual': history[-1]['residual'] if history else float('nan'),
            'wall_time': wall,
            'convergence_log': history,
        }


class ArcLengthContinuation:
    """Riks arc-length continuation.

    Full implementation: FASE 2 extension (complex geometry non-linearity).
    """

    def solve(self, system, u0, load_factor0: float, ds0: float):
        raise NotImplementedError("Arc-length implemented in FASE 2 extension")

    def _detect_limit_point(self, K_tangent) -> bool:
        raise NotImplementedError
