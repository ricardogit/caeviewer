"""J2 (von Mises) elastoplasticity with isotropic hardening — FASE 2.5 material non-linearity.

Small strains, associative flow, backward-Euler radial return with the consistent (algorithmic)
tangent, so the global Newton-Raphson converges quadratically. Voigt order
[xx, yy, zz, xy, yz, xz] with engineering shear strains (as ``tet_batch``).

Hardening σy(εp) (εp = accumulated equivalent plastic strain):
  * ``perfect``                      σy
  * ``linear``  {H}                  σy + H εp
  * ``voce``    {Q, b, H=0}          σy + Q (1 − e^(−b εp)) + H εp
  * ``table``   {ep: [...], sy: [...]}  piecewise linear (flat after the last point); e.g. the
    plastic branch of a FASE 6 tensile fit (``hardening_table_from_fit``).

``solve_plastic`` drives the load: ``load_path`` targets (default [1.0], [1, 0] = load and unload),
``n_load_steps`` per segment, Newton per step, automatic cut-backs; when a step cannot converge
with a tiny increment the analysis stops at the last converged load factor (limit load).
"""
from __future__ import annotations

import logging
import time

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb

logger = logging.getLogger(__name__)

M = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
IDEV = np.diag([1.0, 1.0, 1.0, 0.5, 0.5, 0.5]) - np.outer(M, M) / 3.0   # eng. strain → tensor deviator
SHEAR2 = np.array([1.0, 1.0, 1.0, 2.0, 2.0, 2.0])                       # tensor ↔ Voigt double products


class PlasticityError(ValueError):
    """Invalid plasticity input (user-facing, Spanish)."""


class J2Material:
    def __init__(self, E: float, nu: float, sigma_y: float, hardening: dict | None = None):
        if not sigma_y or sigma_y <= 0:
            raise PlasticityError('El modelo elastoplástico necesita el límite elástico σy > 0.')
        self.E, self.nu, self.sigma_y = float(E), float(nu), float(sigma_y)
        self.G = E / (2 * (1 + nu))
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        self.D = lam * np.outer(M, M) + self.G * np.diag([2.0, 2.0, 2.0, 1.0, 1.0, 1.0])
        h = dict(hardening or {'type': 'perfect'})
        self.kind = h.get('type', 'perfect')
        self.H = float(h.get('H', 0.0) or 0.0)
        self.Q, self.b = float(h.get('Q', 0.0) or 0.0), float(h.get('b', 0.0) or 0.0)
        if self.kind == 'table':
            ep = np.asarray(h.get('ep') or [], float)
            sy = np.asarray(h.get('sy') or [], float)
            if len(ep) < 2 or len(ep) != len(sy) or np.any(np.diff(ep) <= 0):
                raise PlasticityError('Tabla de endurecimiento inválida (εp creciente, mismo número de σy).')
            self.ep_tab, self.sy_tab = ep - ep[0], sy
            self.sigma_y = float(sy[0])
        elif self.kind not in ('perfect', 'linear', 'voce'):
            raise PlasticityError(f'Endurecimiento "{self.kind}" no soportado (perfect, linear, voce, table).')

    def to_dict(self) -> dict:
        d = {'E': self.E, 'nu': self.nu, 'sigma_y': self.sigma_y, 'hardening': self.kind}
        if self.kind == 'table':
            d['n_points'] = len(self.ep_tab)
        return d

    # hardening law
    def sy(self, ep):
        ep = np.asarray(ep, float)
        if self.kind == 'table':
            return np.interp(ep, self.ep_tab, self.sy_tab)
        out = self.sigma_y + self.H * ep
        if self.kind == 'voce':
            out = out + self.Q * (1 - np.exp(-self.b * ep))
        return out

    def dsy(self, ep):
        ep = np.asarray(ep, float)
        if self.kind == 'table':
            slopes = np.diff(self.sy_tab) / np.diff(self.ep_tab)
            i = np.clip(np.searchsorted(self.ep_tab, ep, side='right') - 1, 0, len(slopes) - 1)
            return np.where(ep >= self.ep_tab[-1], 0.0, slopes[i])
        out = np.full_like(ep, self.H)
        if self.kind == 'voce':
            out = out + self.Q * self.b * np.exp(-self.b * ep)
        return out

    def return_map(self, eps: np.ndarray, eps_p: np.ndarray, ep: np.ndarray):
        """Radial return at n points. eps, eps_p (n,6) Voigt engineering; ep (n,).
        Returns sigma (n,6), C (n,6,6) consistent tangent, eps_p_new, ep_new, plastic mask."""
        G = self.G
        sig_tr = (eps - eps_p) @ self.D.T
        p = sig_tr[:, :3].mean(axis=1)
        s_tr = sig_tr - p[:, None] * M
        norm_s = np.sqrt(np.einsum('ij,ij->i', s_tr * SHEAR2, s_tr))
        q_tr = np.sqrt(1.5) * norm_s
        f_tr = q_tr - self.sy(ep)
        plastic = f_tr > 1e-10 * self.sigma_y
        sigma = sig_tr.copy()
        C = np.broadcast_to(self.D, (len(eps), 6, 6)).copy()
        eps_p_new, ep_new = eps_p.copy(), ep.copy()
        if not plastic.any():
            return sigma, C, eps_p_new, ep_new, plastic
        q, en, s = q_tr[plastic], ep[plastic], s_tr[plastic]
        dg = f_tr[plastic] / (3 * G + np.maximum(self.dsy(en), 0.0))
        for _ in range(50):                       # local Newton on q − 3GΔγ − σy(εp + Δγ) = 0
            g = q - 3 * G * dg - self.sy(en + dg)
            dg = dg + g / (3 * G + self.dsy(en + dg))
            if np.all(np.abs(g) <= 1e-12 * self.sigma_y):
                break
        dg = np.maximum(dg, 0.0)
        Hn = self.dsy(en + dg)
        fac = 1 - 3 * G * dg / q
        sigma[plastic] = s * fac[:, None] + p[plastic, None] * M
        n_tensor = 1.5 * s / q[:, None]                       # ∂q/∂σ (tensor components)
        eps_p_new[plastic] = eps_p[plastic] + dg[:, None] * n_tensor * SHEAR2
        ep_new[plastic] = en + dg
        a = s / norm_s[plastic][:, None]                      # unit deviator
        C[plastic] = (self.D[None] - (6 * G * G * dg / q)[:, None, None] * IDEV[None]
                      + (6 * G * G * (dg / q - 1 / (3 * G + Hn)))[:, None, None] * np.einsum('ni,nj->nij', a, a))
        return sigma, C, eps_p_new, ep_new, plastic


def von_mises(sig: np.ndarray) -> np.ndarray:
    return tb.von_mises_v(sig.reshape(-1, 6)).reshape(sig.shape[:-1])


# ── Gauss-point bookkeeping ──────────────────────────────────────────────────

def gauss_points(etype: str):
    if etype == 'T4':
        return np.array([[0.25, 0.25, 0.25]]), np.array([1.0 / 6.0])
    return tb.GAUSS_TET4, tb.W_TET4


def gp_to_nodal(n_nodes: int, elements: np.ndarray, gp: np.ndarray) -> np.ndarray:
    """Gauss-point values (m,g,k) → nodal average (N,k): T4 constant, T10 linear extrapolation
    of the 4 Gauss points to the corners, mid-edge nodes = mean of their corners."""
    if gp.shape[1] == 1:
        per_node = np.repeat(gp, elements.shape[1], axis=1)
    else:
        corners = np.einsum('cg,mgk->mck', tb._GP_TO_CORNER, gp)
        mids = (corners[:, tb.T10_EDGES[:, 0]] + corners[:, tb.T10_EDGES[:, 1]]) / 2
        per_node = np.concatenate([corners, mids], axis=1)
    acc = np.zeros((n_nodes, gp.shape[2]))
    cnt = np.zeros(n_nodes)
    for j in range(elements.shape[1]):
        np.add.at(acc, elements[:, j], per_node[:, j])
        np.add.at(cnt, elements[:, j], 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(cnt[:, None] > 0, acc / cnt[:, None], 0.0)


class _Operator:
    """Element geometry at the Gauss points, kept for the whole analysis."""

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
        self.dofs = tb.element_dofs(elements)                     # (m,nd)
        nd = self.dofs.shape[1]
        self.rows = np.repeat(self.dofs, nd, axis=1).ravel()
        self.cols = np.tile(self.dofs, (1, nd)).ravel()
        self.n_gp = len(w)

    def strains(self, u):
        m, g = self.wdet.shape
        out = np.empty((m, g, 6))
        ue = u[self.dofs]
        for a in range(0, m, self.CHUNK):
            s = slice(a, a + self.CHUNK)
            for k in range(g):
                out[s, k] = np.einsum('mij,mj->mi', tb._B(self.dN[s, k]), ue[s])
        return out

    def internal_force_and_tangent(self, sigma, C, n_dof, need_K=True):
        m, g = self.wdet.shape
        f = np.zeros(n_dof)
        data = np.empty((m, self.dofs.shape[1], self.dofs.shape[1])) if need_K else None
        for a in range(0, m, self.CHUNK):
            s = slice(a, a + self.CHUNK)
            fe = np.zeros((len(self.elements[s]), self.dofs.shape[1]))
            if need_K:
                data[s] = 0.0
            for k in range(g):
                B = tb._B(self.dN[s, k])
                w = self.wdet[s, k]
                fe += w[:, None] * np.einsum('mai,ma->mi', B, sigma[s, k])
                if need_K:
                    data[s] += w[:, None, None] * np.einsum('mai,mab,mbj->mij', B, C[s, k], B, optimize=True)
            np.add.at(f, self.dofs[s], fe)
        K = sp.coo_matrix((data.ravel(), (self.rows, self.cols)), shape=(n_dof, n_dof)).tocsr() if need_K else None
        return f, K


# ── Incremental-iterative solver ─────────────────────────────────────────────

def solve_plastic(mesh, mat: J2Material, F_ext: np.ndarray, dofs: np.ndarray, vals: np.ndarray, *,
                  load_path=(1.0,), n_steps: int = 10, tol: float = 1e-8, max_iter: int = 25,
                  eps0_gp: np.ndarray | None = None, tier: int = 1, near_nullspace=None,
                  progress_cb=None, max_cutbacks: int = 8) -> dict:
    """Newton-Raphson with load stepping. ``F_ext`` and Dirichlet ``vals`` are the loads at λ = 1
    (both scaled by λ); ``eps0_gp`` (m,g,6) an initial strain at λ = 1 (thermal), also scaled."""
    t0 = time.perf_counter()
    op = _Operator(mesh.nodes, mesh.elements)
    n_dof = mesh.n_dof_structural
    m, g = op.wdet.shape
    mask = np.ones(n_dof, bool)
    mask[dofs] = False
    free = np.flatnonzero(mask)
    B_free = near_nullspace[free] if near_nullspace is not None else None
    solver = None

    u = np.zeros(n_dof)
    eps_p = np.zeros((m * g, 6))
    ep = np.zeros(m * g)
    sigma = np.zeros((m * g, 6))
    lam = 0.0
    log, curve = [], [{'load_factor': 0.0, 'max_displacement_m': 0.0, 'reaction_N': [0.0, 0.0, 0.0],
                       'plastic_fraction': 0.0}]
    total_it, cutbacks, limit_reached, failed_msg = 0, 0, False, None
    peak_F = float(np.linalg.norm(F_ext)) * max(abs(float(x)) for x in load_path)
    peak_react = 0.0
    step_no = 0

    def evaluate(u_try, lam_t, need_K=True):
        eps = op.strains(u_try).reshape(-1, 6)
        if eps0_gp is not None:
            eps = eps - lam_t * eps0_gp.reshape(-1, 6)
        sig, C, epn, epq, pl = mat.return_map(eps, eps_p, ep)
        f_int, K = op.internal_force_and_tangent(sig.reshape(m, g, 6), C.reshape(m, g, 6, 6), n_dof, need_K)
        return f_int, K, sig, epn, epq, pl

    for target_end in load_path:
        seg_start = lam
        span = float(target_end) - seg_start
        if abs(span) < 1e-15:
            continue
        d_lam = span / max(1, int(n_steps))
        nominal = abs(d_lam)
        while abs(target_end - lam) > 1e-12 and not limit_reached:
            nxt = lam + d_lam
            if (nxt - target_end) * np.sign(span) > -1e-9 * abs(span):
                nxt = float(target_end)
            u_try = u.copy()
            u_try[dofs] = nxt * vals
            converged, rel, best = False, np.inf, np.inf
            step_no += 1
            for it in range(1, max_iter + 1):
                f_int, K, sig, epn, epq, pl = evaluate(u_try, nxt)
                R = nxt * F_ext - f_int
                react = float(np.linalg.norm(f_int[dofs])) if len(dofs) else 0.0
                # absolute force tolerance on the peak load scale (unloading to λ = 0 has no load)
                ref = max(peak_F, react, peak_react, 1e-30)
                rel = float(np.linalg.norm(R[free])) / ref
                total_it += 1
                log.append({'step': step_no, 'load_factor': nxt, 'iter': it, 'residual': rel})
                if progress_cb:
                    progress_cb(total_it, rel, nxt)
                if rel < tol:
                    converged = True
                    break
                stagnating = it >= 8 and rel > best
                best = min(best, rel)
                if not np.isfinite(rel) or it == max_iter or stagnating:
                    break                              # diverging / stagnating → cut the step back
                Kf = K[free][:, free].tocsr()
                try:
                    duf, ok_lin = _linear_solve(solver, Kf, R[free], tier, B_free)
                except Exception as e:                 # singular tangent (collapse mechanism)
                    failed_msg = str(e)
                    break
                if not ok_lin or not np.all(np.isfinite(duf)):
                    break
                u_try[free] += duf
            if converged:
                u, sigma, eps_p, ep, lam = u_try, sig, epn, epq, nxt
                peak_react = max(peak_react, react)
                umag = np.linalg.norm(u.reshape(-1, 3), axis=1)
                curve.append({'load_factor': lam, 'max_displacement_m': float(umag.max()),
                              'reaction_N': [float(-R[c::3][dofs[dofs % 3 == c] // 3].sum()) for c in range(3)],
                              'plastic_fraction': float((ep > 0).mean()), 'iterations': it})
                if it <= 4 and abs(d_lam) < nominal:
                    d_lam = np.sign(span) * min(nominal, 1.5 * abs(d_lam))
            else:
                cutbacks += 1
                d_lam /= 2
                if abs(d_lam) < nominal / 2 ** max_cutbacks:
                    limit_reached = True
                    logger.info('Plasticity: no convergence beyond load factor %.4f (limit load)', lam)
        if limit_reached:
            break

    reached = (not limit_reached) and abs(lam - float(load_path[-1])) < 1e-12
    return {
        'u': u, 'sigma_gp': sigma.reshape(m, g, 6), 'ep_gp': ep.reshape(m, g), 'eps_p_gp': eps_p.reshape(m, g, 6),
        'load_factor': lam, 'curve': curve, 'operator': op,
        'info': {'method': 'newton_raphson_j2', 'converged': bool(reached), 'n_iterations': total_it,
                 'final_residual': log[-1]['residual'] if log else None, 'n_steps': step_no,
                 'cutbacks': cutbacks, 'limit_load_reached': bool(limit_reached), 'load_factor': lam,
                 'wall_time': time.perf_counter() - t0, 'convergence_log': log,
                 **({'linear_solver_error': failed_msg} if failed_msg else {})},
    }


NEWTON_DIRECT_MAX_DOF = 20_000     # Newton systems near a limit load are badly conditioned for PCG


def _linear_solve(solver, K, r, tier, B):
    """Direct below NEWTON_DIRECT_MAX_DOF, else AMG-PCG with an iteration cap; a PCG that does
    not converge counts as a failed Newton iteration (the step is cut back)."""
    from app.design.services.fem.solver import solve_direct, solve_cg
    if K.shape[0] <= NEWTON_DIRECT_MAX_DOF:
        x, _ = solve_direct(K, r)
        return x, True
    x, info = solve_cg(K, r, tol=1e-10, max_iter=1500, near_nullspace=B)
    return x, bool(info.get('converged'))


def hardening_table_from_fit(model, p, E_mpa: float, eps_max: float, n: int = 40) -> dict | None:
    """Plastic branch of a fitted uniaxial curve σ(ε) (FASE 6, MPa) as a hardening table in Pa:
    εp = ε − σ/E, σy(εp) = σ, sampled densely near yield (geometric spacing in εp)."""
    if not getattr(model, 'elastoplastic', False):
        return None
    e = np.linspace(0, max(eps_max, 0.01), 4000)
    s = model.predict(e, p)
    epl = e - s / E_mpa
    ok = epl > 1e-6
    if ok.sum() < 3:
        return None
    epl, s = epl[ok], s[ok]
    targets = np.geomspace(max(epl[0], 1e-5), epl[-1], n)
    sy = np.interp(targets, epl, s)
    keep = np.concatenate([[True], np.diff(targets) > 0])
    targets, sy = targets[keep], np.maximum.accumulate(sy[keep])
    return {'type': 'table', 'ep': (targets - targets[0]).tolist(), 'sy': (sy * 1e6).tolist()}
