"""FEM Solver dispatcher — selects strategy by tier, linearity, physics.

FASE 2: direct solver (spsolve), CG with ILU preconditioner, tier enforcement.
"""
from __future__ import annotations
import inspect
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
#
# Measured on T10 cantilevers (FASE 2): SuperLU is fine up to a few thousand DOF
# but explodes in 3D (29K DOF: 67 s with RCM, 44 s with MMD) while Jacobi-PCG
# solves the same system in 5.5 s to 1e-12. ILU(drop 1e-5) did not converge.
# So: direct below DIRECT_MAX_DOF, PCG above; smoothed-aggregation AMG is used
# as preconditioner when the optional ``pyamg`` package is installed.

DIRECT_MAX_DOF = 6_000

_CG_TOL_KW = 'rtol' if 'rtol' in inspect.signature(spla.cg).parameters else 'tol'


def solve_direct(K: sp.csr_matrix, F: np.ndarray) -> tuple[np.ndarray, dict]:
    """Direct sparse solve: scipy.sparse.linalg.spsolve."""
    t0 = time.perf_counter()
    u = spla.spsolve(K.tocsc(), F)
    wall = time.perf_counter() - t0
    r = float(np.linalg.norm(K @ u - F) / (np.linalg.norm(F) or 1.0))
    return u, {'method': 'direct_spsolve', 'wall_time': wall,
               'converged': bool(np.isfinite(u).all()), 'n_iterations': 1, 'final_residual': r}


def rigid_body_modes(nodes_xyz: np.ndarray) -> np.ndarray:
    """(3n, 6) translations + rotations, the near-nullspace for elasticity AMG."""
    x, y, z = (nodes_xyz - nodes_xyz.mean(0)).T
    n = len(nodes_xyz)
    B = np.zeros((3 * n, 6))
    B[0::3, 0] = 1; B[1::3, 1] = 1; B[2::3, 2] = 1
    B[0::3, 3] = -y; B[1::3, 3] = x
    B[1::3, 4] = -z; B[2::3, 4] = y
    B[0::3, 5] = z; B[2::3, 5] = -x
    return B


def _amg_preconditioner(K, B=None):
    try:
        import pyamg
    except ImportError:
        return None, None
    # pyamg estimates spectral radii from a random start vector (legacy np.random): seed it so
    # the hierarchy, and therefore the solution, is bitwise reproducible (FASE 7).
    state = np.random.get_state()
    np.random.seed(0)
    try:
        ml = pyamg.smoothed_aggregation_solver(K, B=B if B is not None and B.shape[0] == K.shape[0] else None)
    finally:
        np.random.set_state(state)
    return ml.aspreconditioner(cycle='V'), 'cg_amg'


def solve_cg(K: sp.csr_matrix, F: np.ndarray, tol: float = 1e-10,
             max_iter: int = None, progress_cb=None, near_nullspace=None) -> tuple[np.ndarray, dict]:
    """Preconditioned CG (AMG if pyamg is available, else Jacobi)."""
    t0 = time.perf_counter()
    K = K.tocsr()
    n = K.shape[0]
    M, method = _amg_preconditioner(K, near_nullspace)
    if M is None:
        diag = K.diagonal()
        if np.any(diag <= 0):
            raise ValueError('Matriz de rigidez con diagonal no positiva: revisa restricciones y malla.')
        dinv = 1.0 / diag
        M, method = spla.LinearOperator(K.shape, matvec=lambda v: dinv * v), 'cg_jacobi'
    max_iter = max_iter or max(2000, 100 * int(np.sqrt(n)))
    fn = float(np.linalg.norm(F)) or 1.0
    log = []
    it = [0]

    def callback(xk):
        it[0] += 1
        if it[0] % 25 == 0:
            r = float(np.linalg.norm(F - K @ xk) / fn)
            log.append({'iter': it[0], 'residual': r, 'wall_time': time.perf_counter() - t0})
            if progress_cb:
                progress_cb(it[0], r)

    u, info = spla.cg(K, F, M=M, maxiter=max_iter, callback=callback, atol=0.0, **{_CG_TOL_KW: tol})
    final = float(np.linalg.norm(F - K @ u) / fn)
    log.append({'iter': it[0], 'residual': final, 'wall_time': time.perf_counter() - t0})
    return u, {'method': method, 'wall_time': time.perf_counter() - t0,
               'converged': info == 0, 'n_iterations': it[0],
               'final_residual': final, 'convergence_log': log}


# ── Dispatcher ────────────────────────────────────────────────────────────────

class FEMSolverDispatcher:
    """Routes a solve call to the appropriate strategy."""

    def solve_linear(self, K: sp.csr_matrix, F: np.ndarray,
                     tier: int, tol: float = 1e-10,
                     max_iter: int = None,
                     progress_cb=None, near_nullspace=None) -> tuple[np.ndarray, dict]:
        """Solve K u = F (K symmetric positive definite after BC elimination).

        Direct below DIRECT_MAX_DOF (any tier), preconditioned CG above.
        """
        n_dof = K.shape[0]
        logger.info(f"Solving linear system: {n_dof:,} DOF, Tier {tier}")
        if n_dof <= DIRECT_MAX_DOF:
            return solve_direct(K, F)
        return solve_cg(K, F, tol=min(tol, 1e-9), max_iter=max_iter,
                        progress_cb=progress_cb, near_nullspace=near_nullspace)

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
