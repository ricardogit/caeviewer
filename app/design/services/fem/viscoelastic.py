"""Linear viscoelasticity: generalized Maxwell model (Prony series), small strains, quasi-static.

Relaxation modulus  E(t) = E₀ [g∞ + Σᵢ gᵢ exp(−t/τᵢ)],  g∞ = 1 − Σ gᵢ > 0,  ν constant, so the whole
D relaxes: D(t) = g(t) D₀ (D₀ = instantaneous isotropic elasticity). Stress = hereditary integral
σ(t) = ∫ g(t − s) D₀ ε̇(s) ds, written with one internal stress hᵢ per Prony term and Gauss point:

    hᵢⁿ⁺¹ = e^{−Δt/τᵢ} hᵢⁿ + gᵢ γᵢ D₀ Δε,   γᵢ = (1 − e^{−Δt/τᵢ}) / (Δt/τᵢ)     (exact for ε linear in the step)
    σⁿ⁺¹  = g∞ D₀ εⁿ⁺¹ + Σ hᵢⁿ⁺¹

so each time step is linear: (c K₀) Δu = λⁿ⁺¹F − f(σ*), c = g∞ + Σ gᵢγᵢ, σ* = g∞D₀εⁿ + Σ e^{−Δt/τᵢ}hᵢⁿ.
K₀ is factorised once (constant Δt or not: only the scalar c changes). A step at Δt = 0 (t = 0, or a jump in
the load history) is instantaneous: c = 1 (elastic with E₀).

Loads and prescribed displacements follow a piecewise-linear history λ(t). Time integration error is
O(Δt²) when the strain rate is smooth (creep); a step load held constant (relaxation) is exact.
"""
from __future__ import annotations

import logging
import time

import numpy as np

from app.design.services.fem.plasticity import _Operator

logger = logging.getLogger(__name__)


class PronySeries:
    def __init__(self, E0: float, nu: float, terms):
        self.E0, self.nu = float(E0), float(nu)
        self.g = np.array([float(t['g']) for t in terms or []], dtype=np.float64)
        self.tau = np.array([float(t['tau']) for t in terms or []], dtype=np.float64)
        if not self.E0 > 0 or not -1 < self.nu < 0.5:
            raise ValueError('Viscoelástico: E₀ > 0 y −1 < ν < 0.5')
        if not len(self.g):
            raise ValueError('Viscoelástico: indica al menos un término de Prony (g, τ).')
        if (self.g <= 0).any() or (self.tau <= 0).any():
            raise ValueError('Viscoelástico: cada término de Prony necesita g > 0 y τ > 0 [s].')
        self.g_inf = 1.0 - float(self.g.sum())
        if not self.g_inf > 0:
            raise ValueError('Viscoelástico: Σ gᵢ debe ser < 1 (el módulo a largo plazo E∞ = E₀(1 − Σgᵢ) > 0).')

    def to_dict(self) -> dict:
        return {'E0': self.E0, 'nu': self.nu, 'E_inf': self.E0 * self.g_inf, 'g_inf': self.g_inf,
                'prony': [{'g': float(g), 'tau': float(t)} for g, t in zip(self.g, self.tau)]}

    def relaxation(self, t):
        """g(t) = E(t)/E₀."""
        t = np.asarray(t, dtype=np.float64)
        return self.g_inf + np.sum(self.g[:, None] * np.exp(-np.atleast_1d(t)[None, :] / self.tau[:, None]),
                                   axis=0).reshape(t.shape)


def load_factor(history, t: float) -> float:
    """Piecewise-linear λ(t) from [[t, λ], ...] (sorted by t; constant beyond the ends). A repeated time
    is a jump: the later entry wins for t ≥ that time."""
    ts = np.array([float(p[0]) for p in history])
    ls = np.array([float(p[1]) for p in history])
    hits = np.flatnonzero(ts == t)
    if len(hits):
        return float(ls[hits[-1]])
    return float(np.interp(t, ts, ls))


def time_grid(history, t_end: float, n_steps: int) -> np.ndarray:
    """Uniform grid 0 … t_end plus every breakpoint of the history (a jump time appears twice: before and
    after the jump, the second one with Δt = 0)."""
    t = set(np.linspace(0.0, float(t_end), int(n_steps) + 1).tolist())
    t |= {float(p[0]) for p in history if 0.0 <= float(p[0]) <= t_end}
    grid = sorted(t)
    jumps = [float(history[i][0]) for i in range(1, len(history)) if float(history[i][0]) == float(history[i - 1][0])]
    out = []
    for x in grid:
        out.append(x)
        if x in jumps and x > 0:
            out.append(x)                   # instantaneous step at the jump
    return np.array(out)


def history_at(history, grid: np.ndarray) -> np.ndarray:
    """λ at each grid time; at a duplicated (jump) time the first occurrence takes the value before the jump."""
    lam = []
    seen = {}
    for x in grid:
        k = seen.get(x, 0)
        seen[x] = k + 1
        pts = [i for i, p in enumerate(history) if float(p[0]) == x]
        if len(pts) >= 2 and k == 0:
            lam.append(float(history[pts[0]][1]))
        elif len(pts) >= 2:
            lam.append(float(history[pts[-1]][1]))
        else:
            lam.append(load_factor(history, x))
    return np.array(lam)


def solve_viscoelastic(mesh, prony: PronySeries, D0: np.ndarray, K0, F_ext: np.ndarray, dofs: np.ndarray,
                       vals: np.ndarray, history, t_end: float, n_steps: int, *, linear_solver=None,
                       progress_cb=None) -> dict:
    """Time stepping. ``K0`` = elastic stiffness with D₀ (global CSR); ``F_ext``/``vals`` at λ = 1.
    ``linear_solver(K_ff, rhs)`` → x (defaults to a sparse LU of K₀_ff, factorised once)."""
    t_start = time.perf_counter()
    op = _Operator(mesh.nodes, mesh.elements)
    n_dof = mesh.n_dof_structural
    m, g = op.wdet.shape
    mask = np.ones(n_dof, bool)
    mask[dofs] = False
    free = np.flatnonzero(mask)
    Kff = K0[free][:, free].tocsc()
    Kfc = K0[free][:, dofs].tocsr()
    if linear_solver is None:
        from scipy.sparse.linalg import splu
        lu = splu(Kff)
        solve = lu.solve
    else:
        solve = lambda r: linear_solver(Kff, r)   # noqa: E731

    grid = time_grid(history, t_end, n_steps)
    lam_t = history_at(history, grid)
    u = np.zeros(n_dof)
    eps = np.zeros((m, g, 6))
    h = np.zeros((len(prony.g), m, g, 6))
    sigma = np.zeros((m, g, 6))
    curve = []
    t_prev = None
    for n, (t, lam) in enumerate(zip(grid, lam_t)):
        dt = 0.0 if t_prev is None else float(t - t_prev)
        if dt > 0:
            x = dt / prony.tau
            e = np.exp(-x)
            gam = -np.expm1(-x) / x
        else:
            e = np.ones_like(prony.tau)
            gam = np.ones_like(prony.tau)
        c = prony.g_inf + float(np.sum(prony.g * gam))
        sig_star = prony.g_inf * (eps @ D0.T) + np.tensordot(e, h, axes=(0, 0))
        f_star, _ = op.internal_force_and_tangent(sig_star, None, n_dof, need_K=False)
        du_c = lam * vals - u[dofs]
        rhs = (lam * F_ext - f_star)[free] - c * (Kfc @ du_c if len(dofs) else 0.0)
        du = np.zeros(n_dof)
        du[free] = solve(rhs) / c
        du[dofs] = du_c
        u = u + du
        eps_new = op.strains(u).reshape(m, g, 6)
        d_sig = (eps_new - eps) @ D0.T
        h = e[:, None, None, None] * h + (prony.g * gam)[:, None, None, None] * d_sig[None]
        sigma = prony.g_inf * (eps_new @ D0.T) + h.sum(axis=0)
        eps = eps_new
        f_int, _ = op.internal_force_and_tangent(sigma, None, n_dof, need_K=False)
        R = f_int - lam * F_ext
        curve.append({'time_s': float(t), 'load_factor': float(lam),
                      'max_displacement_m': float(np.linalg.norm(u.reshape(-1, 3), axis=1).max()),
                      'reaction_N': [float(R[c_::3][dofs[dofs % 3 == c_] // 3].sum()) for c_ in range(3)]})
        if progress_cb:
            progress_cb(n, len(grid), float(t))
        t_prev = t
    resid = float(np.linalg.norm(R[free]) / max(np.linalg.norm(lam_t[-1] * F_ext), np.linalg.norm(f_int[dofs]), 1e-30))
    return {'u': u, 'sigma_gp': sigma, 'eps_gp': eps, 'operator': op, 'f_int': f_int, 'curve': curve,
            'load_factor': float(lam_t[-1]), 'times': grid.tolist(),
            'info': {'method': 'viscoelastic_prony_time_stepping', 'converged': bool(resid < 1e-6),
                     'n_time_steps': int(len(grid)), 'final_residual': resid, 'n_iterations': int(len(grid)),
                     'wall_time': time.perf_counter() - t_start}}
