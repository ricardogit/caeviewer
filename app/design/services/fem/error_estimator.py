"""Zienkiewicz-Zhu a-posteriori error estimator (FASE 3), T4 and T10.

Recovery: the finite-element stress σh is discontinuous between elements; the recovered field σ* is a
continuous nodal field interpolated with the same shape functions as the displacement.
- T4 (σh constant per element): nodal average of the element stresses (classic ZZ).
- T10 (σh linear): superconvergent patch recovery (SPR, Zienkiewicz-Zhu 1992) — for every corner node a
  quadratic polynomial is least-squares fitted to the Gauss-point stresses of the elements around it;
  it gives the corner value and, averaged with the other end's patch, the mid-edge values. A linear
  recovery (nodal averaging) cannot represent the quadratic part: on the FASE 2 beam its effectivity
  (estimate / true error) was 0.42–0.55, SPR gives 0.72–0.80 on coarse meshes and → 1 when refining.
  The remaining underestimate comes from the clamp singularity on the boundary.

The element indicator is the energy norm of the difference

    ηₑ² = ∫ₑ (σ* − σh)ᵀ D⁻¹ (σ* − σh) dV

integrated with a 14-point degree-5 rule (exact: the integrand is degree 2 for T4, 4 for T10). The
global estimate is relative to the energy of the solution:

    η = √( Σηₑ² / (‖u_h‖²_E + Σηₑ²) ),   ‖u_h‖²_E = ∫ σhᵀ D⁻¹ σh dV

(≈ ‖u − u_h‖_E / ‖u‖_E, the quantity the plan's 5 % tolerance refers to). Linear elastic, structural,
no initial strain: the adaptive loop rejects thermal / elastoplastic studies.
"""
from __future__ import annotations

import numpy as np

from app.design.services.fem import tet_batch as tb


def _rule14():
    """14-point degree-5 rule on the reference tet (positive weights, Σw = 1/6)."""
    pts, w = [], []
    for a, wa in ((0.0927352503108912, 0.01224884051939366), (0.3108859192633006, 0.01878132095300264)):
        for k in range(4):
            L = [a] * 4
            L[k] = 1 - 3 * a
            pts.append(L[1:])
            w.append(wa)
    c = 0.4544962958743504
    for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
        L = [0.5 - c] * 4
        L[i] = L[j] = c
        pts.append(L[1:])
        w.append(0.007091003462846911)
    return np.array(pts), np.array(w)


QUAD_PTS, QUAD_W = _rule14()


def _basis(x: np.ndarray, quadratic: bool) -> np.ndarray:
    """Polynomial basis at local coordinates x (..., 3) → (..., 4 | 10)."""
    one = np.ones(x.shape[:-1] + (1,))
    if not quadratic:
        return np.concatenate([one, x], axis=-1)
    a, b, c = x[..., 0:1], x[..., 1:2], x[..., 2:3]
    return np.concatenate([one, x, a * a, b * b, c * c, a * b, b * c, c * a], axis=-1)


def spr_t10(nodes: np.ndarray, elements: np.ndarray, u: np.ndarray, D: np.ndarray) -> np.ndarray:
    """SPR nodal stress (N,6) of a T10 solution (see the module docstring)."""
    corners = elements[:, :4]
    gpx, gps = [], []
    for p in tb.GAUSS_TET4:
        gpx.append(np.einsum('n,mnk->mk', tb.shape('T10', p), nodes[elements]))
        gps.append(tb.strain_at(nodes, elements, u, p) @ D.T)
    gpx, gps = np.stack(gpx, 1), np.stack(gps, 1)                      # (m,4,3), (m,4,6)

    verts = np.unique(corners)
    vidx = -np.ones(len(nodes), dtype=np.int64)
    vidx[verts] = np.arange(len(verts))
    # patch size per vertex: max distance to the Gauss points of its elements (scales the basis)
    xv = nodes[corners]                                                  # (m,4,3)
    dist = np.linalg.norm(gpx[:, None, :, :] - xv[:, :, None, :], axis=3).max(axis=2)   # (m,4)
    h = np.zeros(len(verts))
    np.maximum.at(h, vidx[corners].ravel(), dist.ravel())
    hv = h[vidx[corners]]                                                # (m,4)
    loc = (gpx[:, None, :, :] - xv[:, :, None, :]) / hv[:, :, None, None]  # (m,4 corners,4 gp,3)

    def fit(quadratic):
        P = _basis(loc, quadratic)                                       # (m,4,4,k)
        k = P.shape[-1]
        A = np.zeros((len(verts), k, k))
        bb = np.zeros((len(verts), k, 6))
        np.add.at(A, vidx[corners].ravel(), np.einsum('mcgi,mcgj->mcij', P, P).reshape(-1, k, k))
        np.add.at(bb, vidx[corners].ravel(), np.einsum('mcgi,mgs->mcis', P, gps).reshape(-1, k, 6))
        return A, bb

    A2, b2 = fit(True)
    A1, b1 = fit(False)
    cnt = np.bincount(vidx[corners].ravel(), minlength=len(verts)) * 4      # sample points per patch
    # quadratic where the patch has enough, well-conditioned samples, else linear (thin boundary patches)
    with np.errstate(all='ignore'):
        cond = np.linalg.cond(A2)
    quad = (cnt >= 20) & np.isfinite(cond) & (cond < 1e10)
    coef2 = np.zeros_like(b2)
    coef2[quad] = np.linalg.solve(A2[quad], b2[quad])
    lin = ~quad
    c1 = np.zeros_like(b1)
    if lin.any():
        c1[lin] = np.linalg.solve(A1[lin] + 1e-12 * np.eye(4), b1[lin])

    def evaluate(v, x):
        """Patch polynomial of vertices v (q,) at points x (q,3)."""
        z = (x - nodes[verts[v]]) / h[v][:, None]
        out = np.einsum('qi,qis->qs', _basis(z, True), coef2[v])
        if lin.any():
            l = lin[v]
            out[l] = np.einsum('qi,qis->qs', _basis(z[l], False), c1[v[l]])
        return out

    sig = np.zeros((len(nodes), 6))
    sig[verts] = evaluate(np.arange(len(verts)), nodes[verts])
    # mid-edge nodes: mean of the two end patches evaluated at the mid node
    i, j = tb.T10_EDGES[:, 0], tb.T10_EDGES[:, 1]
    mid = elements[:, 4:].ravel()
    a, b = corners[:, i].ravel(), corners[:, j].ravel()
    val = 0.5 * (evaluate(vidx[a], nodes[mid]) + evaluate(vidx[b], nodes[mid]))
    acc = np.zeros((len(nodes), 6))
    n = np.zeros(len(nodes))
    np.add.at(acc, mid, val)
    np.add.at(n, mid, 1)
    has = n > 0
    sig[has] = acc[has] / n[has, None]
    return sig


def zz_estimate(nodes: np.ndarray, elements: np.ndarray, u: np.ndarray, D: np.ndarray) -> dict:
    """ZZ indicators of a linear elastic solution ``u`` (3 DOF/node).

    Returns {eta2 (m,) ηₑ², energy (m,) element energy norm² ∫σhD⁻¹σh, relative_error η,
    error_energy Σηₑ², solution_energy Σ energy}.
    """
    nodes = np.asarray(nodes, float)
    elements = np.asarray(elements, np.int64)
    et = tb.etype_of(elements)
    C = np.linalg.inv(D)
    sig_nodal = spr_t10(nodes, elements, u, D) if et == 'T10' else tb.nodal_stress(nodes, elements, u, D)[1]
    sig_el_nodes = sig_nodal[elements]                                  # (m,n,6)
    X = nodes[elements]
    ue = u[tb.element_dofs(elements)]
    eta2 = np.zeros(len(elements))
    energy = np.zeros(len(elements))
    for p, w in zip(QUAD_PTS, QUAD_W):
        det, dN = tb._jac(X, tb.dshape(et, p))
        sig_h = np.einsum('mij,mj->mi', tb._B(dN), ue) @ D.T            # (m,6)
        sig_s = np.einsum('n,mnk->mk', tb.shape(et, p), sig_el_nodes)   # (m,6)
        d = sig_s - sig_h
        eta2 += w * det * np.einsum('mi,ij,mj->m', d, C, d)
        energy += w * det * np.einsum('mi,ij,mj->m', sig_h, C, sig_h)
    err, sol = float(eta2.sum()), float(energy.sum())
    return {'eta2': eta2, 'energy': energy, 'error_energy': err, 'solution_energy': sol,
            'relative_error': float(np.sqrt(err / (sol + err))) if sol + err > 0 else 0.0}


def mark_dorfler(eta2: np.ndarray, theta: float = 0.5) -> np.ndarray:
    """Dörfler (bulk) marking: the fewest elements whose ηₑ² add up to ≥ θ·Σηₑ²."""
    eta2 = np.asarray(eta2, float)
    marked = np.zeros(len(eta2), dtype=bool)
    total = eta2.sum()
    if total <= 0:
        return marked
    order = np.argsort(-eta2, kind='stable')
    n = int(np.searchsorted(np.cumsum(eta2[order]), theta * total) + 1)
    marked[order[:min(n, len(eta2))]] = True
    return marked
