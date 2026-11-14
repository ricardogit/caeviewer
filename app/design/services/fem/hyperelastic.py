"""Compressible Neo-Hookean hyperelasticity, total Lagrangian (large displacements and strains).

    W = μ/2 (I₁ − 3) − μ ln J + λ/2 (ln J)²
    S = μ (I − C⁻¹) + λ ln J C⁻¹                                   (2nd Piola-Kirchhoff)
    ℂ = λ C⁻¹ ⊗ C⁻¹ + (μ − λ ln J)(C⁻¹ ⊙ C⁻¹ + C⁻¹ ⊡ C⁻¹)            (material tangent dS/dE)

μ, λ from the small-strain E and ν (the model reduces to linear elasticity for small strains).
Element residual f = ∫ B_NLᵀ S dV₀ with B_NL = sym(Fᵀ ∇₀N); tangent K = ∫ B_NLᵀ ℂ B_NL dV₀ + geometric
stiffness ∫ ∇₀N · S · ∇₀N dV₀ ⊗ I. T4 (1 Gauss point) and T10 (4 points), reference configuration.

Loads are **dead** (fixed direction and magnitude, assembled on the reference configuration: a pressure
keeps its reference normal and area); prescribed displacements are scaled with the load factor. Newton with
load steps, step growth and cut-backs (same driver logic as the J2 solver); a trial state with J ≤ 0 at any
Gauss point counts as a failed iteration (the step is cut back).
"""
from __future__ import annotations

import logging
import time

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.plasticity import _linear_solve, gauss_points

logger = logging.getLogger(__name__)

_VOIGT = ((0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2))
_I3 = np.eye(3)


class NeoHookean:
    def __init__(self, E: float, nu: float):
        if not E > 0 or not -1 < nu < 0.5:
            raise ValueError('Neo-Hookean: E > 0 y −1 < ν < 0.5')
        self.E, self.nu = float(E), float(nu)
        self.mu = self.E / (2 * (1 + self.nu))
        self.lam = self.E * self.nu / ((1 + self.nu) * (1 - 2 * self.nu))

    def to_dict(self) -> dict:
        return {'E': self.E, 'nu': self.nu, 'mu': self.mu, 'lambda': self.lam}

    def stress_tangent(self, F: np.ndarray, need_C: bool = True):
        """F (N,3,3) → S (N,3,3), ℂ in Voigt (N,6,6) and J (N,)."""
        J = np.linalg.det(F)
        C = np.einsum('nki,nkj->nij', F, F)
        Ci = np.linalg.inv(C)
        lnJ = np.log(np.where(J > 0, J, np.nan))
        S = self.mu * (_I3[None] - Ci) + (self.lam * lnJ)[:, None, None] * Ci
        if not need_C:
            return S, None, J
        mu_p = self.mu - self.lam * lnJ
        D = np.empty((len(F), 6, 6))
        for P, (i, j) in enumerate(_VOIGT):
            for Q, (k, l) in enumerate(_VOIGT):
                D[:, P, Q] = (self.lam * Ci[:, i, j] * Ci[:, k, l]
                              + mu_p * (Ci[:, i, k] * Ci[:, j, l] + Ci[:, i, l] * Ci[:, j, k]))
        return S, D, J


def cauchy(F: np.ndarray, S: np.ndarray) -> np.ndarray:
    """σ = J⁻¹ F S Fᵀ in Voigt (N,6) (xx yy zz xy yz xz)."""
    J = np.linalg.det(F)
    sig = np.einsum('nik,nkl,njl->nij', F, S, F) / J[:, None, None]
    return np.stack([sig[:, i, j] for i, j in _VOIGT], axis=1)


class TLOperator:
    """Reference geometry at the Gauss points and the total-Lagrangian element operators."""

    CHUNK = 10_000

    def __init__(self, nodes, elements):
        self.elements = elements
        self.et = tb.etype_of(elements)
        pts, w = gauss_points(self.et)
        X = nodes[elements]
        dets, dNs = [], []
        for p in pts:
            det, dN = tb._jac(X, tb.dshape(self.et, p))
            dets.append(det)
            dNs.append(dN)
        self.wdet = np.stack(dets, axis=1) * w[None, :]          # (m,g)
        self.dN = np.stack(dNs, axis=1)                           # (m,g,3,n)
        self.dofs = tb.element_dofs(elements)
        nd = self.dofs.shape[1]
        self.rows = np.repeat(self.dofs, nd, axis=1).ravel()
        self.cols = np.tile(self.dofs, (1, nd)).ravel()

    def deformation_gradient(self, u: np.ndarray) -> np.ndarray:
        """F = I + ∇₀u at every Gauss point, (m,g,3,3)."""
        ue = u[self.dofs].reshape(len(self.elements), -1, 3)      # (m,n,3)
        return _I3[None, None] + np.einsum('mnk,mgjn->mgkj', ue, self.dN)

    @staticmethod
    def _B(F: np.ndarray, dN: np.ndarray) -> np.ndarray:
        """B_NL (m,6,3n): δE (Voigt, engineering shear) = B δu. F (m,3,3), dN (m,3,n)."""
        m, _, n = dN.shape
        B = np.zeros((m, 6, n, 3))
        for P, (i, j) in enumerate(_VOIGT):
            t = np.einsum('mk,mn->mnk', F[:, :, i], dN[:, j])
            if i != j:
                t = t + np.einsum('mk,mn->mnk', F[:, :, j], dN[:, i])
            B[:, P] = t
        return B.reshape(m, 6, 3 * n)

    def assemble(self, mat: NeoHookean, u: np.ndarray, n_dof: int, need_K: bool = True):
        """Internal force, tangent, Gauss-point S (m,g,3,3), F and min J."""
        Fg = self.deformation_gradient(u)
        m, g = self.wdet.shape
        S, D, J = mat.stress_tangent(Fg.reshape(-1, 3, 3), need_C=need_K)
        S = S.reshape(m, g, 3, 3)
        if need_K:
            D = D.reshape(m, g, 6, 6)
        f = np.zeros(n_dof)
        nd = self.dofs.shape[1]

        data = np.zeros((m, nd, nd)) if need_K else None
        Sv = np.stack([S[..., i, j] for i, j in _VOIGT], axis=-1)   # (m,g,6)
        for a in range(0, m, self.CHUNK):
            s = slice(a, a + self.CHUNK)
            fe = np.zeros((len(self.elements[s]), nd))
            for k in range(g):
                w = self.wdet[s, k]
                dN = self.dN[s, k]
                B = self._B(Fg[s, k], dN)
                fe += w[:, None] * np.einsum('mai,ma->mi', B, Sv[s, k])
                if need_K:
                    Km = np.einsum('mai,mab,mbj->mij', B, D[s, k], B, optimize=True)
                    Gab = np.einsum('min,mij,mjp->mnp', dN, S[s, k], dN)               # (m,n,n)
                    Kg = np.einsum('mnp,kl->mnkpl', Gab, _I3).reshape(-1, nd, nd)
                    data[s] += w[:, None, None] * (Km + Kg)
            np.add.at(f, self.dofs[s], fe)
        K = (sp.coo_matrix((data.ravel(), (self.rows, self.cols)), shape=(n_dof, n_dof)).tocsr()
             if need_K else None)

        return f, K, S, Fg, float(np.nanmin(J)) if np.isfinite(J).any() else -1.0


def solve_hyperelastic(mesh, mat: NeoHookean, F_ext: np.ndarray, dofs: np.ndarray, vals: np.ndarray, *,
                       n_steps: int = 10, tol: float = 1e-8, max_iter: int = 30, tier: int = 1,
                       near_nullspace=None, progress_cb=None, max_cutbacks: int = 8) -> dict:
    """Newton-Raphson with load steps to λ = 1 (dead loads ``F_ext`` and Dirichlet ``vals`` scaled by λ)."""
    t0 = time.perf_counter()
    op = TLOperator(mesh.nodes, mesh.elements)
    n_dof = mesh.n_dof_structural
    mask = np.ones(n_dof, bool)
    mask[dofs] = False
    free = np.flatnonzero(mask)
    B_free = near_nullspace[free] if near_nullspace is not None else None

    u = np.zeros(n_dof)
    lam = 0.0
    d_lam = nominal = 1.0 / max(1, int(n_steps))
    log, curve = [], [{'load_factor': 0.0, 'max_displacement_m': 0.0, 'reaction_N': [0.0, 0.0, 0.0],
                       'min_J': 1.0}]
    total_it, cutbacks, stopped, failed_msg, step_no = 0, 0, False, None, 0
    peak_F = float(np.linalg.norm(F_ext))
    react_scale = 0.0
    while 1.0 - lam > 1e-12 and not stopped:
        nxt = min(1.0, lam + d_lam)
        if 1.0 - nxt < 1e-9:
            nxt = 1.0
        step_no += 1
        # tangent predictor from the last converged state: K_ff Δu_f = R_f − K_fc Δu_c
        u_try = u.copy()
        try:
            f0, K0, *_ = op.assemble(mat, u, n_dof)
            du_c = nxt * vals - u[dofs]
            rhs = (nxt * F_ext - f0)[free] - (K0[free][:, dofs] @ du_c if len(dofs) else 0.0)
            duf, ok_lin = _linear_solve(None, K0[free][:, free].tocsr(), rhs, tier, B_free)
            if ok_lin and np.all(np.isfinite(duf)):
                u_try[free] += duf
        except Exception as e:                         # singular tangent: plain Newton from u
            logger.debug('Neo-Hookean predictor failed: %s', e)
        u_try[dofs] = nxt * vals
        converged, best = False, np.inf
        for it in range(1, max_iter + 1):
            f_int, K, S, Fg, minJ = op.assemble(mat, u_try, n_dof)
            if not minJ > 0:
                break
            R = nxt * F_ext - f_int
            react = float(np.linalg.norm(f_int[dofs])) if len(dofs) else 0.0
            ref = max(peak_F, react, react_scale, 1e-30)
            rel = float(np.linalg.norm(R[free])) / ref
            total_it += 1
            log.append({'step': step_no, 'load_factor': nxt, 'iter': it, 'residual': rel})
            if progress_cb:
                progress_cb(total_it, rel, nxt)
            if rel < tol:
                converged = True
                break
            if not np.isfinite(rel) or it == max_iter or (it >= 10 and rel > best):
                break
            best = min(best, rel)
            try:
                duf, ok_lin = _linear_solve(None, K[free][:, free].tocsr(), R[free], tier, B_free)
            except Exception as e:                     # singular tangent (instability)
                failed_msg = str(e)
                break
            if not ok_lin or not np.all(np.isfinite(duf)):
                break
            u_try[free] += duf
        if converged:
            u, lam = u_try, nxt
            react_scale = max(react_scale, react)
            curve.append({'load_factor': lam,
                          'max_displacement_m': float(np.linalg.norm(u.reshape(-1, 3), axis=1).max()),
                          'reaction_N': [float(-R[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)],
                          'min_J': minJ, 'iterations': it})
            if it <= 5 and d_lam < nominal:
                d_lam = min(nominal, 1.5 * d_lam)
        else:
            cutbacks += 1
            d_lam /= 2
            if d_lam < nominal / 2 ** max_cutbacks:
                stopped = True
                logger.info('Neo-Hookean: no convergence beyond load factor %.4f', lam)

    f_int, _, S, Fg, minJ = op.assemble(mat, u, n_dof, need_K=False)
    return {
        'u': u, 'load_factor': lam, 'curve': curve, 'operator': op, 'f_int': f_int, 'S_gp': S, 'F_gp': Fg,
        'min_J': minJ,
        'info': {'method': 'newton_raphson_total_lagrangian', 'converged': bool(not stopped and lam == 1.0),
                 'n_iterations': total_it, 'final_residual': log[-1]['residual'] if log else None,
                 'n_steps': step_no, 'cutbacks': cutbacks, 'stopped_early': bool(stopped), 'load_factor': lam,
                 'wall_time': time.perf_counter() - t0, 'convergence_log': log,
                 **({'linear_solver_error': failed_msg} if failed_msg else {})},
    }
