"""FEM Solver dispatcher — selects strategy by tier, linearity, physics.

FASE 2: direct solver (spsolve), CG with ILU preconditioner, tier enforcement.
"""
from __future__ import annotations
import logging
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

logger = logging.getLogger(__name__)

# ── Tier limits ───────────────────────────────────────────────────────────────

TIER_LIMITS = {
    0: {'max_dof': 30_000,     'max_nodes': 5_000,      'max_elements': 20_000},
    1: {'max_dof': 600_000,    'max_nodes': 100_000,    'max_elements': 400_000},
    2: {'max_dof': 6_000_000,  'max_nodes': 1_000_000,  'max_elements': 4_000_000},
    3: {'max_dof': 60_000_000, 'max_nodes': 10_000_000, 'max_elements': 40_000_000},
}


class TierLimitExceeded(Exception):
    def __init__(self, violations: list, suggested_tier: int = None):
        self.violations = violations
        self.suggested_tier = suggested_tier
        super().__init__('; '.join(violations))

    def to_dict(self):
        return {'error': 'TierLimitExceeded', 'violations': self.violations,
                'suggested_tier': self.suggested_tier}


def check_tier_limits(n_nodes: int, n_elements: int, n_dof: int, tier: int):
    lim = TIER_LIMITS.get(tier, TIER_LIMITS[3])
    v = []
    if n_dof > lim['max_dof']:
        v.append(f"DOF {n_dof:,} > Tier {tier} limit {lim['max_dof']:,}")
    if n_nodes > lim['max_nodes']:
        v.append(f"Nodes {n_nodes:,} > Tier {tier} limit {lim['max_nodes']:,}")
    if n_elements > lim['max_elements']:
        v.append(f"Elements {n_elements:,} > Tier {tier} limit {lim['max_elements']:,}")
    if v:
        raise TierLimitExceeded(v, min(tier + 1, 3))


# ── Solver strategies ─────────────────────────────────────────────────────────

def solve_direct(K: sp.csr_matrix, F: np.ndarray) -> tuple[np.ndarray, dict]:
    """Direct sparse solve: scipy.sparse.linalg.spsolve."""
    t0 = time.perf_counter()
    u = spla.spsolve(K, F)
    wall = time.perf_counter() - t0
    return u, {'method': 'direct_spsolve', 'wall_time': wall,
                'converged': True, 'n_iterations': 1, 'final_residual': 0.0}


def solve_cg(K: sp.csr_matrix, F: np.ndarray, tol: float = 1e-8,
             max_iter: int = 5000) -> tuple[np.ndarray, dict]:
    """Conjugate Gradient with incomplete LU preconditioner (ILU0)."""
    t0 = time.perf_counter()

    try:
        ilu = spla.spilu(K.tocsc(), drop_tol=1e-4, fill_factor=10)
        M = spla.LinearOperator(K.shape, ilu.solve)
    except Exception as e:
        logger.warning(f"ILU preconditioner failed ({e}); using no preconditioning.")
        M = None

    residuals = []

    def callback(xk):
        r = np.linalg.norm(F - K @ xk) / (np.linalg.norm(F) + 1e-300)
        residuals.append(r)

    u, info = spla.cg(K, F, M=M, rtol=tol, maxiter=max_iter, callback=callback)
    wall = time.perf_counter() - t0
    final_res = float(residuals[-1]) if residuals else float('nan')
    return u, {'method': 'cg_ilu', 'wall_time': wall,
                'converged': info == 0, 'n_iterations': len(residuals),
                'final_residual': final_res}


# ── Dispatcher ────────────────────────────────────────────────────────────────

class FEMSolverDispatcher:
    """Routes a solve call to the appropriate strategy."""

    def solve_linear(self, K: sp.csr_matrix, F: np.ndarray,
                     tier: int, tol: float = 1e-8,
                     max_iter: int = 5000,
                     progress_cb=None) -> tuple[np.ndarray, dict]:
        """Solve K u = F for linear systems.

        Args:
            K, F:        assembled system.
            tier:        model tier (0-3) — selects solver.
            tol:         convergence tolerance (for iterative solvers).
            max_iter:    maximum iterations (for iterative solvers).
            progress_cb: optional callable(iter, residual) for streaming.

        Returns:
            (u, solve_info): displacement vector + solver metadata.
        """
        n_dof = K.shape[0]
        logger.info(f"Solving linear system: {n_dof:,} DOF, Tier {tier}")

        if tier <= 1:
            return solve_direct(K, F)
        else:
            return solve_cg(K, F, tol=tol, max_iter=max_iter)

    def solve(self, K: sp.csr_matrix, F: np.ndarray, tier: int,
              is_linear: bool = True, **kwargs) -> tuple[np.ndarray, dict]:
        if is_linear:
            return self.solve_linear(K, F, tier, **kwargs)
        else:
            from app.design.services.fem.nonlinear import NewtonRaphson
            logger.info("Dispatching to Newton-Raphson (non-linear)")
            nr = NewtonRaphson()
            return nr.solve_assembled(K, F, tier=tier, **kwargs)

    def stream_progress(self, socketio, room: str, iter_n: int,
                        residual: float, wall_time: float, percent: float = 0.0):
        socketio.emit('solver_progress', {
            'run_id': room,
            'iter': iter_n,
            'residual': residual,
            'wall_time': wall_time,
            'percent': percent,
        }, room=room)
