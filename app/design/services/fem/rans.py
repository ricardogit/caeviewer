"""Reynolds-averaged turbulent flow (FASE 10.4): standard k-ε with wall functions on Taylor–Hood P2-P1 meshes.

    ρ(v·∇)v − ∇·[(μ + ρν_t)(∇v + ∇vᵀ)] + ∇p* = ρb,   ∇·v = 0,   ν_t = C_μ k²/ε,   p* = p + ⅔ρk
    v·∇k − ∇·[(ν + ν_t/σ_k)∇k] = P − ε,              P = ν_t · 2S:S
    v·∇ε − ∇·[(ν + ν_t/σ_ε)∇ε] = (C₁ P − C₂ ε) ε/k

Launder–Spalding constants C_μ 0.09, C₁ 1.44, C₂ 1.92, σ_k 1.0, σ_ε 1.3.

**Wall functions** (Mohammadi & Pironneau): the mesh boundary of a wall is the line at distance δ from the physical
wall (``wall_distance``); the layer 0 < y < δ is not meshed. On it v·n = 0 (exact DOF constraint on axis-aligned
faces, penalty otherwise) and the tangential traction is τ_w = ρu_τ² along −v_t, u_τ from |v_t| at δ through
Reichardt's profile, U = u_τ u⁺(δu_τ/ν) (viscous sublayer → log law: the laminar ρν|v|/δ when the flow is slow, nothing
divides by zero near reattachment; linearised with the exact tangent dτ/dU). Wall values k = u_τ²/√C_μ,
ε = u_τ³/(κ_ε δ), κ_ε = √((C₂ − C₁)σ_ε√C_μ) = 0.433 (the model's own log-layer constant). Wall nodes on the rim of an
inlet take the inlet values (no slip). Valid for 30 ≲ δ⁺ ≲ 300.

**Limiters**: ν_t = C_μ k T with Durbin's realizability bound T ≤ 0.6/(√6 C_μ |S|), production ≤ 10 ε (Menter) and
ε source C₁(ε/k)P; neither is active in an equilibrium log layer, both are needed at the corner of a backward step.

**Discretisation**: momentum as in ``stokes`` (P2 velocity, P1 pressure) with the symmetric viscous form and the
variable effective viscosity sampled at the degree-5 points; k and ε are P1 on the 8 sub-tetrahedra of every T10
(all T10 nodes are vertices: the same resolution as the velocity, positive lumped mass and positive interpolation of
ν_t), Galerkin + SUPG, destruction implicit and lumped, production explicit, values clipped at a small floor.
Segregated Picard: momentum (Oseen, lagged ν_t) → k → ε → ν_t (under-relaxed 0.3), until the steady
momentum residual and the k, ε updates are small. The k-ε equations use a pseudo-time step for robustness; the
converged state does not depend on it.
"""
from __future__ import annotations

import math

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

from app.design.services.fem import stokes as st
from app.design.services.fem import tet_batch as tb

CMU, C1, C2, SIG_K, SIG_E, KAPPA = 0.09, 1.44, 1.92, 1.0, 1.3, 0.41
CMU25, CMU75 = CMU ** 0.25, CMU ** 0.75
# κ of the model's own log layer (P = ε, k = u_τ²/√C_μ): κ² = (C₂ − C₁) σ_ε √C_μ → 0.4327. Used for the wall ε so
# the near-wall k is the equilibrium value (κ = 0.41 there gives k⁺ 3.09 instead of 3.33 and c_f −6 %).
KAPPA_EPS = math.sqrt((C2 - C1) * SIG_E * math.sqrt(CMU))
DURBIN_ALPHA = 0.6        # realizability time-scale bound
P_LIMIT = 10.0            # production limiter P_k ≤ 10 ε
MODELS = ('k_epsilon',)

# 8 sub-tetrahedra of a T10 (local node ids; mids 4:(0,1) 5:(1,2) 6:(0,2) 7:(0,3) 8:(1,3) 9:(2,3)): four corner
# tets + the inner octahedron split along the 4–9 diagonal.
SUB_TETS = np.array([(0, 4, 6, 7), (4, 1, 5, 8), (6, 5, 2, 9), (7, 8, 9, 3),
                     (4, 9, 5, 6), (4, 9, 6, 7), (4, 9, 7, 8), (4, 9, 8, 5)])


def reichardt(yp):
    """Reichardt's wall law u⁺(y⁺): u⁺ = y⁺ near the wall, (1/κ) ln y⁺ + 5.6 in the log layer."""
    yp = np.asarray(yp, float)
    return np.log1p(KAPPA * yp) / KAPPA + 7.8 * (1.0 - np.exp(-yp / 11.0) - yp / 11.0 * np.exp(-yp / 3.0))


def utau_from_velocity(U, y, nu, iters: int = 60):
    """Friction velocity u_τ with U = u_τ u⁺(y u_τ/ν) (Reichardt), vectorised Newton with a bisection safeguard.
    U ≥ 0 tangential speed at the distance y from the wall."""
    U = np.maximum(np.asarray(U, float), 0.0)
    lo = np.zeros_like(U)
    hi = np.sqrt(U * nu / y) + U + 1e-300                    # g(hi) > 0: u⁺ ≥ y⁺ would give u_τ ≤ √(Uν/y)
    ut = np.sqrt(U * nu / y)                                  # viscous-sublayer guess
    for _ in range(iters):
        yp = y * ut / nu
        up = reichardt(yp)
        g = ut * up - U
        dup = (KAPPA / (1 + KAPPA * yp) / KAPPA
               + 7.8 * (np.exp(-yp / 11) / 11 - np.exp(-yp / 3) / 11 + yp / 33 * np.exp(-yp / 3)))
        dg = up + ut * dup * y / nu
        lo = np.where(g < 0, ut, lo)
        hi = np.where(g > 0, ut, hi)
        nxt = ut - g / np.maximum(dg, 1e-300)
        bad = (nxt <= lo) | (nxt >= hi)
        ut = np.where(bad, 0.5 * (lo + hi), nxt)
    return np.where(U > 0, ut, 0.0)


class TurbulenceSettings:
    def __init__(self, spec: dict | None):
        spec = spec or {}
        self.model = spec.get('model') or 'k_epsilon'
        if self.model not in MODELS:
            raise ValueError(f'Turbulencia: modelo desconocido {self.model!r} (k_epsilon).')
        wd = spec.get('wall_distance')
        self.wall_distance = None if wd in (None, '') else float(wd)       # δ [m]; None → from the mesh
        if self.wall_distance is not None and not self.wall_distance > 0:
            raise ValueError('Turbulencia: la distancia de pared δ debe ser > 0.')
        self.intensity = float(spec.get('inlet_intensity') if spec.get('inlet_intensity') is not None else 0.05)
        ls = spec.get('inlet_length_scale')
        self.length_scale = None if ls in (None, '') else float(ls)         # ℓ [m]; None → 0.07 × size
        if not 0 < self.intensity < 1:
            raise ValueError('Turbulencia: la intensidad de entrada debe estar entre 0 y 1 (p. ej. 0.05 = 5 %).')
        self.max_iter = int(spec.get('max_iter') or 400)
        self.tol = float(spec.get('tol') or 1e-6)
        self.relax = float(spec.get('relax') or 0.3)      # ν_t under-relaxation (0.7 limit-cycles behind a step)
        self.cfl = float(spec.get('cfl') or 5.0)            # initial local pseudo-time CFL (grows by SER)
        self.cfl_max = float(spec.get('cfl_max') or 1e4)


# ── P1 on the sub-tetrahedra (turbulence variables) ─────────────────────────

class IsoP1:
    """P1 elements on the 8 sub-tets of every T10: matrices N×N on all T10 nodes."""

    def __init__(self, mesh):
        n = mesh.n_nodes
        sub = mesh.elements[:, SUB_TETS].reshape(-1, 4)
        X = mesh.nodes[sub]
        D = X[:, 1:] - X[:, :1]                                  # rows = edge vectors
        det = np.linalg.det(D)
        if np.any(np.abs(det) < 1e-300):
            raise ValueError('Turbulencia: sub-tetraedros degenerados en la malla.')
        Di = np.linalg.inv(D)
        g = np.empty((len(sub), 4, 3))
        g[:, 1:] = Di.transpose(0, 2, 1)                         # ∇L_i = column i−1 of D⁻¹
        g[:, 0] = -g[:, 1:].sum(axis=1)
        self.n, self.sub, self.g, self.V = n, sub, g, np.abs(det) / 6.0
        self.rows = np.repeat(sub, 4, axis=1).ravel()
        self.cols = np.tile(sub, (1, 4)).ravel()
        self.ml = np.bincount(sub.ravel(), np.repeat(self.V / 4.0, 4), minlength=n)
        self.Kloc = self.V[:, None, None] * np.einsum('sia,sja->sij', g, g)
        self.h = np.cbrt(6.0 * np.sqrt(2.0) * self.V)            # equal-volume regular-tet edge

    def mat(self, loc) -> sp.csr_matrix:
        return sp.csr_matrix((loc.ravel(), (self.rows, self.cols)), shape=(self.n, self.n))

    def mean(self, f):
        return f[self.sub].mean(axis=1)

    def grad_v(self, v):
        """∂v_c/∂x_d per sub-tet, (s,3,3)."""
        return np.einsum('sac,sad->scd', v[self.sub], self.g)

    def lump(self, q):
        """∫ q N_i dV with q constant per sub-tet → nodal vector."""
        return np.bincount(self.sub.ravel(), np.repeat(self.V * q / 4.0, 4), minlength=self.n)


def _iso_weights():
    """(n_q, 10): P1-on-sub-tets interpolation weights at the degree-5 points of ``stokes._geometry`` (≥ 0)."""
    pts, _ = st._rule5()
    ref = tb.NODE_NAT['T10']
    W = np.zeros((len(pts), 10))
    for q, p in enumerate(pts):
        best = None
        for s in SUB_TETS:
            Xs = ref[s]
            lam = np.linalg.solve((Xs[1:] - Xs[0]).T, np.asarray(p) - Xs[0])
            L = np.array([1 - lam.sum(), *lam])
            if best is None or L.min() > best[1].min():
                best = (s, L)
        s, L = best
        W[q, s] = np.clip(L, 0, None)
        W[q] /= W[q].sum()
    return W


_W_ISO = None


def iso_weights():
    global _W_ISO
    if _W_ISO is None:
        _W_ISO = _iso_weights()
    return _W_ISO


# ── Momentum operators ───────────────────────────────────────────────────────

def viscous(mesh, mu: float, rho: float, nut: np.ndarray) -> sp.csr_matrix:
    """∫ μ_eff (∇v + ∇vᵀ) : ∇w dV, μ_eff = μ + ρν_t (ν_t nodal, P1 on the sub-tets) — 3N×3N."""
    n = mesh.n_nodes
    Ns, geo = st._geometry(mesh)
    W = iso_weights()
    rows, cols, vals = [], [], []
    for a in range(0, mesh.n_elements, 4000):
        el = mesh.elements[a:a + 4000]
        m = len(el)
        nue = nut[el]                                            # (m,10)
        D = np.stack([dNall[a:a + 4000] for _, dNall in geo])               # (Q,m,3,10)
        w = np.stack([wdet[a:a + 4000] for wdet, _ in geo]) * (mu + rho * (W @ nue.T))   # (Q,m)
        # transpose part: test (n,c), trial (k,d): μ ∂_d N_n ∂_c N_k;  Laplacian part on the c = d blocks
        Ke = np.einsum('qm,qmdn,qmck->mnckd', w, D, D, optimize=True)
        lap = np.einsum('qm,qman,qmak->mnk', w, D, D, optimize=True)
        for c in range(3):
            Ke[:, :, c, :, c] += lap
        dofs = tb.element_dofs(el)
        rows.append(np.repeat(dofs, 30, axis=1).ravel())
        cols.append(np.tile(dofs, (1, 30)).ravel())
        vals.append(Ke.reshape(m, -1).ravel())
    return sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(3 * n, 3 * n))


def supg_picard(mesh, a: np.ndarray, mu: float, rho: float, nut: np.ndarray, body=None):
    """Residual-based SUPG of the momentum equation, Oseen-linearised (advecting velocity a and τ frozen):

        Σ_e ∫ τ (a·∇w) · [ρ(a·∇)v + ∇p − μ_eff Δv − (∇v + ∇vᵀ)∇μ_eff − f] dV,
        τ = ((2|a|/h̃)² + (12 ν_eff/h̃²)²)^(-½) / ρ

    (h̃ = h/2 for P2; Δv from the straight corner geometry; ∇μ_eff from the P2 interpolation of the nodal ν_t —
    without that term the residual of a fully developed turbulent channel is not zero and SUPG drives a spurious
    secondary flow, −2 % wall shear). Returns
    (Jvv 3N×3N, Jvp 3N×Np, rhs 3N) to add to the momentum rows: Jvv v + Jvp p = rhs."""
    n = mesh.n_nodes
    corners, pidx = st.pressure_index(mesh)
    Ns, geo = st._geometry(mesh)
    W = iso_weights()
    f = np.zeros(3) if body is None else np.asarray(body, float)
    rhs = np.zeros(3 * n)
    rv, cv, vv, rp, cp, vp = [], [], [], [], [], []
    eye = np.eye(3)
    for a0 in range(0, mesh.n_elements, 4000):
        el = mesh.elements[a0:a0 + 4000]
        m = len(el)
        Xc = mesh.nodes[el[:, :4]]
        _, gL = tb._jac(Xc, tb.dshape('T4', (0.25, 0.25, 0.25)))
        lap = np.zeros((m, 10))
        for i in range(4):
            lap[:, i] = 4.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, i])
        for e_, (i, j) in enumerate(tb.T10_EDGES):
            lap[:, 4 + e_] = 8.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, j])
        h = np.max([np.linalg.norm(Xc[:, i] - Xc[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)], axis=0)
        ht = 0.5 * h
        ae = a[el]
        nue = nut[el]
        Jv = np.zeros((m, 10, 3, 10, 3))
        Jp = np.zeros((m, 10, 3, 4))
        Fe = np.zeros((m, 10, 3))
        for q, (N, (wdet, dNall)) in enumerate(zip(Ns, geo)):
            w, dN = wdet[a0:a0 + 4000], dNall[a0:a0 + 4000]
            aq = np.einsum('n,mnc->mc', N, ae)
            adv = np.einsum('md,mdj->mj', aq, dN)                               # a·∇N_j
            mu_q = mu + rho * (nue @ W[q])
            tau = 1.0 / (rho * np.sqrt((2 * np.linalg.norm(aq, axis=1) / ht) ** 2
                                       + (12.0 * mu_q / (rho * ht ** 2)) ** 2))
            wt = w * tau
            gnu = rho * np.einsum('mdn,mn->md', dN, nue)                       # ∇μ_t at the point
            base = rho * adv - mu_q[:, None] * lap - np.einsum('mdj,md->mj', dN, gnu)
            Jv += ((wt[:, None, None] * adv[:, :, None] * base[:, None, :])[:, :, None, :, None]
                   * eye[None, None, :, None, :])
            Jv -= (wt[:, None, None, None, None] * adv[:, :, None, None, None]
                   * np.einsum('mcj,md->mcjd', dN, gnu)[:, None, :, :, :])
            Jp += wt[:, None, None, None] * adv[:, :, None, None] * gL[:, None, :, :]
            Fe += wt[:, None, None] * adv[:, :, None] * f[None, None, :]
        dofs = tb.element_dofs(el)
        np.add.at(rhs, dofs, Fe.reshape(m, 30))
        Jb = Jv.reshape(m, 30, 30)
        rv.append(np.repeat(dofs, 30, axis=1).ravel())
        cv.append(np.tile(dofs, (1, 30)).ravel())
        vv.append(Jb.ravel())
        pc = pidx[el[:, :4]]
        rp.append(np.repeat(dofs, 4, axis=1).ravel())
        cp.append(np.tile(pc, (1, 30)).ravel())
        vp.append(Jp.reshape(m, 30, 4).ravel())
    Jvv = sp.csr_matrix((np.concatenate(vv), (np.concatenate(rv), np.concatenate(cv))), shape=(3 * n, 3 * n))
    Jvp = sp.csr_matrix((np.concatenate(vp), (np.concatenate(rp), np.concatenate(cp))), shape=(3 * n, len(corners)))
    return Jvv, Jvp, rhs


def mass(mesh) -> sp.csr_matrix:
    """Consistent P2 mass ∫ w·v dV, 3N×3N."""
    n = mesh.n_nodes
    Ns, geo = st._geometry(mesh)
    rows, cols, vals = [], [], []
    for a in range(0, mesh.n_elements, 20000):
        el = mesh.elements[a:a + 20000]
        Me = np.zeros((len(el), 10, 10))
        for N, (wdet, _) in zip(Ns, geo):
            Me += wdet[a:a + 20000, None, None] * np.outer(N, N)[None]
        rows.append(np.repeat(el, 10, axis=1).ravel())
        cols.append(np.tile(el, (1, 10)).ravel())
        vals.append(Me.ravel())
    M = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    return sp.kron(M, sp.identity(3), format='csr')


def face_mass(nodes, tris, coef) -> sp.csr_matrix:
    """∫ c N_a N_b dA on P2 triangles (c constant per face), N×N."""
    from app.design.services.fem.thermal import TRI_D4, W_TRI_D4
    n = len(nodes)
    X = nodes[tris]
    Me = np.zeros((len(tris), 6, 6))
    for (r, s), wg in zip(TRI_D4, W_TRI_D4):
        N = tb.shape_tri(2, r, s)
        t = np.einsum('an,knj->kaj', tb.dshape_tri(2, r, s), X)
        jac = np.linalg.norm(np.cross(t[:, 0], t[:, 1]), axis=1)
        Me += (wg * jac * coef)[:, None, None] * np.outer(N, N)[None]
    return sp.csr_matrix((Me.ravel(), (np.repeat(tris, 6, axis=1).ravel(), np.tile(tris, (1, 6)).ravel())),
                         shape=(n, n))


# ── Boundary bookkeeping ─────────────────────────────────────────────────────

def _entry_tris(mesh, bc) -> np.ndarray:
    from app.design.services.fem.assembler import _face_tris
    if 'face_set' in bc:
        return _face_tris(mesh, bc['face_set'])
    name = bc.get('node_set', '')
    if isinstance(name, str) and name in mesh.face_sets and len(mesh.face_sets[name]):
        return np.asarray(mesh.face_sets[name])
    from app.design.services.fem.assembler import _node_set
    nodes = np.zeros(mesh.n_nodes, bool)
    nodes[_node_set(mesh, name)] = True
    bf = tb.boundary_faces(mesh.elements)
    return bf[nodes[bf[:, :3]].all(axis=1)]


def _entry_nodes(mesh, bc) -> np.ndarray:
    from app.design.services.fem.assembler import _face_tris, _node_set
    if 'face_set' in bc:
        return np.unique(_face_tris(mesh, bc['face_set']))
    return _node_set(mesh, bc.get('node_set', ''))


def is_wall(bc: dict) -> bool:
    """A no-slip BC (all three velocity components = 0) is a wall-function wall in a turbulent study."""
    d = [int(x) for x in bc.get('dofs', [0, 1, 2])]
    vals = list(bc.get('values', [0.0] * len(d)))
    return sorted(set(d)) == [0, 1, 2] and not any(float(x) for x in vals[:len(d)])


def split_bcs(mesh, bcs: list):
    """(wall triangles (k,6), the other BC entries)."""
    walls, other = [], []
    for bc in bcs:
        if is_wall(bc):
            walls.append(_entry_tris(mesh, bc))
        else:
            other.append(bc)
    if not walls:
        raise ValueError('Turbulencia: no hay paredes (BC sin deslizamiento): las funciones de pared las necesitan.')
    tris = np.unique(np.concatenate(walls), axis=0)
    return tris, other


def wall_normals(mesh, tris):
    """Outward unit normal per wall node (area-weighted over its wall faces): (nodes, normals)."""
    X = mesh.nodes[tris[:, :3]]
    nrm = 0.5 * np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    nrm *= tb.outward_sign(mesh.nodes, mesh.elements, tris)[:, None]
    acc = np.zeros((mesh.n_nodes, 3))
    for j in range(tris.shape[1]):
        np.add.at(acc, tris[:, j], nrm)
    nodes = np.unique(tris)
    nn = acc[nodes]
    nn /= np.linalg.norm(nn, axis=1, keepdims=True)
    return nodes, nn


def wall_projectors(mesh, tris, nodes):
    """Per wall node, the projector onto the constrained (no-penetration) directions: the span of the unit normals of
    its wall faces (eigenvalues of the area-weighted Σ n nᵀ above 0.1, i.e. faces meeting at more than ~37°). A flat
    node gets n nᵀ; a node on an edge or corner gets every face's normal — imposing only the averaged normal there
    would let the flow slide along the bisector (a spurious jet down the face of a backward step)."""
    X = mesh.nodes[tris[:, :3]]
    nrm = 0.5 * np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    area = np.linalg.norm(nrm, axis=1)
    un = nrm / area[:, None]
    M = np.zeros((mesh.n_nodes, 3, 3))
    wsum = np.zeros(mesh.n_nodes)
    nn = area[:, None, None] * np.einsum('ka,kb->kab', un, un)
    for j in range(tris.shape[1]):
        np.add.at(M, tris[:, j], nn)
        np.add.at(wsum, tris[:, j], area)
    M = M[nodes] / wsum[nodes][:, None, None]
    lam, E = np.linalg.eigh(M)
    on = (lam > 0.1).astype(float)
    P = np.einsum('kai,ki,kbi->kab', E, on, E)
    P[np.abs(P) < 1e-12] = 0.0
    # convex edges (the wall turns away from the fluid: a face's centroid lies on the solid side of another face's
    # plane, e.g. the lip of a backward step): any velocity leaving the wall is admissible, the neighbouring nodes of
    # each face keep v·n = 0 → no constraint there (pinning the lip to v = 0 makes a stagnation point at the separation
    # line and a limit cycle in the shear layer)
    edge = np.flatnonzero(on.sum(axis=1) > 1)
    if len(edge):
        pos = {int(nd): i for i, nd in enumerate(nodes)}
        cen = X.mean(axis=1)
        faces_of = {int(nodes[i]): [] for i in edge}
        for f, tri in enumerate(tris):
            for nd in tri:
                lst = faces_of.get(int(nd))
                if lst is not None:
                    lst.append(f)
        for nd, fl in faces_of.items():
            fl = np.asarray(fl)
            d = cen[fl][None, :, :] - cen[fl][:, None, :]                   # c_j − c_i
            side = np.einsum('ija,ia->ij', d, un[fl])                      # (c_j − c_i)·n_i
            size = np.sqrt(area[fl]).max()
            if (side > 0.05 * size).any():
                P[pos[nd]] = 0.0
    return P


def default_wall_distance(mesh, tris) -> float:
    """½ × mean height of the elements on the wall faces (the wall-adjacent layer)."""
    X = mesh.nodes[tris[:, :3]]
    area = 0.5 * np.linalg.norm(np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0]), axis=1)
    key = {tuple(sorted(t)): i for i, t in enumerate(tris[:, :3].tolist())}
    Xe = mesh.nodes[mesh.elements[:, :4]]
    vol = np.abs(np.einsum('ij,ij->i', Xe[:, 1] - Xe[:, 0], np.cross(Xe[:, 2] - Xe[:, 0], Xe[:, 3] - Xe[:, 0]))) / 6
    hs = []
    for e, el in enumerate(mesh.elements[:, :4].tolist()):
        for f in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
            i = key.get(tuple(sorted(el[j] for j in f)))
            if i is not None:
                hs.append(3 * vol[e] / area[i])
    return 0.5 * float(np.mean(hs))


# ── Solver ───────────────────────────────────────────────────────────────────

def solve_rans(mesh, mat, F: np.ndarray, bcs: list, turb: TurbulenceSettings, *, body=None, progress=None):
    """Steady RANS k-ε. ``mat`` = stokes.FluidMaterial (μ, ρ). Returns (v, p*, info) with info['turbulence']
    {k, eps, nut (nodal), wall (per wall node), history, ...}."""
    from app.design.services.fem.assembler import dirichlet
    if mesh.element_type != 'T10':
        raise ValueError('Turbulencia: hace falta malla cuadrática T10 (Taylor-Hood P2-P1).')
    rho, mu = mat.rho, mat.mu
    if not rho > 0:
        raise ValueError('Turbulencia: hace falta la densidad ρ > 0.')
    nu = mu / rho
    n = mesh.n_nodes
    n3 = 3 * n
    iso = IsoP1(mesh)
    wtris, other = split_bcs(mesh, bcs)
    delta = turb.wall_distance or default_wall_distance(mesh, wtris)
    wnodes, wnorm = wall_normals(mesh, wtris)
    wproj = wall_projectors(mesh, wtris, wnodes)

    # velocity constraints: the other BCs win; no penetration (P v = 0) exact on axis-aligned nodes, else penalty
    dofs, vals = dirichlet(mesh, other) if other else (np.zeros(0, np.int64), np.zeros(0))
    presc = np.zeros(n3, bool)
    presc[dofs] = True
    pdg = np.einsum('kaa->ka', wproj)
    aligned = ((np.abs(wproj - np.einsum('ka,ab->kab', pdg, np.eye(3))).max(axis=(1, 2)) < 1e-9)
               & np.all((pdg < 1e-9) | (pdg > 1 - 1e-9), axis=1))
    wd = (3 * wnodes[:, None] + np.arange(3)[None])[aligned][pdg[aligned] > 0.5]
    wd = wd[~presc[wd]]
    dofs = np.concatenate([dofs, wd])
    vals = np.concatenate([vals, np.zeros(len(wd))])
    order = np.argsort(dofs)
    dofs, vals = dofs[order], vals[order]
    presc[dofs] = True
    pen_nodes, pen_P = wnodes[~aligned], wproj[~aligned]
    full_presc = presc.reshape(-1, 3).all(axis=1)
    keep = ~full_presc[pen_nodes]
    pen_nodes, pen_P = pen_nodes[keep], pen_P[keep]

    # scales and inlet turbulence
    ext = mesh.nodes.max(0) - mesh.nodes.min(0)
    L = float(ext[ext > 0].min())
    inlet_nodes, inlet_k, inlet_e = [], [], []
    speeds = []
    for bc in other:
        d = [int(x) for x in bc.get('dofs', [0, 1, 2])]
        vv = np.asarray(list(bc.get('values', [0.0] * len(d))) + [0.0] * 3, float)[:3]
        if sorted(set(d)) != [0, 1, 2] or not np.linalg.norm(vv) > 0:
            continue
        U = float(np.linalg.norm(vv))
        speeds.append(U)
        t = bc.get('turbulence') or {}
        inten = float(t.get('intensity', turb.intensity))
        ell = float(t.get('length_scale') or turb.length_scale or 0.07 * L)
        kin = 1.5 * (inten * U) ** 2
        nodes = _entry_nodes(mesh, bc)
        inlet_nodes.append(nodes)
        inlet_k.append(np.full(len(nodes), kin))
        inlet_e.append(np.full(len(nodes), CMU75 * kin ** 1.5 / ell))
    bvec = np.zeros(3) if body is None else np.asarray(body, float)
    if speeds:
        U_ref = max(speeds)
    elif np.linalg.norm(bvec) > 0:                       # body-force driven: u_τ ~ √(|b| L/ρ), U ~ 20 u_τ
        U_ref = 20.0 * math.sqrt(np.linalg.norm(bvec) * L / rho)
    else:
        raise ValueError('Turbulencia: sin velocidad de entrada ni fuerza de volumen no hay escala de velocidad.')
    ell0 = turb.length_scale or 0.07 * L
    k0 = 1.5 * (turb.intensity * U_ref) ** 2
    e0 = CMU75 * k0 ** 1.5 / ell0
    k_floor, e_floor = 1e-10 * U_ref ** 2, 1e-10 * CMU75 * U_ref ** 3 / L
    if inlet_nodes:
        in_n = np.concatenate(inlet_nodes)
        in_k, in_e = np.concatenate(inlet_k), np.concatenate(inlet_e)
        in_n, first = np.unique(in_n, return_index=True)
        in_k, in_e = in_k[first], in_e[first]
    else:
        in_n, in_k, in_e = np.zeros(0, np.int64), np.zeros(0), np.zeros(0)
    if len(in_n):
        # wall nodes on the rim of an inlet (sharing a boundary face with inlet nodes, without a velocity BC of their
        # own): no-slip + the neighbouring inlet k, ε. Left free, the wall law lets them slide against the imposed
        # inlet profile (a spurious jet at the corner).
        is_in = np.zeros(n, bool)
        is_in[in_n] = True
        is_w = np.zeros(n, bool)
        is_w[wnodes] = True
        bf = tb.boundary_faces(mesh.elements)
        wkeys = {tuple(t) for t in np.sort(wtris[:, :3], axis=1).tolist()}
        bf = bf[[tuple(t) not in wkeys for t in np.sort(bf[:, :3], axis=1).tolist()]]   # inlet faces, not walls
        f = bf[is_in[bf].any(axis=1)]
        rim = np.unique(f[is_w[f] & ~is_in[f]])
        rim = rim[~full_presc[rim]]
        if len(rim):
            rd = (3 * rim[:, None] + np.arange(3)[None]).ravel()
            keep_d = ~np.isin(dofs, rd)
            dofs = np.concatenate([dofs[keep_d], rd])
            vals = np.concatenate([vals[keep_d], np.zeros(len(rd))])
            order = np.argsort(dofs)
            dofs, vals = dofs[order], vals[order]
            presc[rd] = True
            keep = ~np.isin(pen_nodes, rim)
            pen_nodes, pen_P = pen_nodes[keep], pen_P[keep]
            near = np.argmin(np.linalg.norm(mesh.nodes[rim][:, None] - mesh.nodes[in_n][None], axis=2), axis=1)
            in_n = np.concatenate([in_n, rim])
            in_k = np.concatenate([in_k, in_k[near]])
            in_e = np.concatenate([in_e, in_e[near]])
            order = np.argsort(in_n)
            in_n, in_k, in_e = in_n[order], in_k[order], in_e[order]
    # wall values of k, ε on plane-wall nodes only: on an edge or corner (two or more constrained directions) the wall
    # law sees no tangential velocity across the edge (u_τ → 0, k → floor: a ν_t sink under the corner of a step);
    # there k and ε have zero flux and take their values from the flow
    edge = np.einsum('kaa->k', wproj) > 1.5
    wall_only = np.setdiff1d(wnodes[~edge], in_n)
    wall_idx = np.searchsorted(wnodes, wall_only)

    k = np.full(n, k0)
    eps = np.full(n, e0)
    k[in_n], eps[in_n] = in_k, in_e
    nut = CMU * k ** 2 / eps

    # constant operators
    _, B, corners, pidx = st.assemble(mesh, 1.0)
    n_p = len(corners)
    nx = n3 + n_p
    bf = tb.boundary_faces(mesh.elements)
    wkeys = {tuple(sorted(t)) for t in wtris[:, :3].tolist()}
    open_face = False
    for t in bf.tolist():
        if tuple(sorted(t[:3])) in wkeys:
            continue
        X = mesh.nodes[t[:3]]
        a = int(np.argmax(np.abs(np.cross(X[1] - X[0], X[2] - X[0]))))
        if not presc[[3 * i + a for i in t]].all():
            open_face = True
            break
    pin = not open_face
    cdofs = np.concatenate([dofs, [n3]]) if pin else dofs
    cvals = np.concatenate([vals, [0.0]]) if pin else vals
    mask = np.ones(nx, bool)
    mask[cdofs] = False
    free = np.flatnonzero(mask)
    zero_p = sp.csr_matrix((n_p, n_p))

    def wall_state(v, kk):
        """Per wall node (order of ``wnodes``): friction coefficient β (traction = −β v_t), u_τ, u*, |v_t|.
        u_τ from the tangential velocity at δ through Reichardt (U_p = u_τ u⁺(δu_τ/ν)), so the wall law holds for
        any δ⁺; before the first velocity (v None) u_τ ≈ u* = C_μ^¼ √k."""
        us = CMU25 * np.sqrt(np.maximum(kk[wnodes], 0.0))
        if v is None:
            ut = us
            vt = np.zeros(len(wnodes))
        else:
            vw = v[wnodes]
            vt = np.linalg.norm(vw - np.einsum('kab,kb->ka', wproj, vw), axis=1)
            ut = utau_from_velocity(vt, delta, nu)
        yp = ut * delta / nu
        up = reichardt(yp)
        small = yp <= 1e-8
        beta = np.where(small, mu / delta, rho * ut / np.maximum(up, 1e-300))
        # tangent dτ/dU = 2ρu_τ/(u⁺ + y⁺ du⁺/dy⁺) (U = u_τ u⁺(δu_τ/ν)); = β in the sublayer, ≈ 1.7β in the log layer
        dup = (1.0 / (1 + KAPPA * yp) + 7.8 * (np.exp(-yp / 11) / 11 - np.exp(-yp / 3) / 11
                                               + yp / 33 * np.exp(-yp / 3)))
        beta_t = np.where(small, mu / delta, 2 * rho * ut / np.maximum(up + yp * dup, 1e-300))
        return beta, ut, us, vt, beta_t

    def friction(v, kk, beta=None):
        """Wall friction ∫ β w·v dA (3N×3N), β = τ_w/|v_t| per wall node (from ``wall_state`` unless given)."""
        if beta is None:
            beta = wall_state(v, kk)[0]
        bn = np.zeros(n)
        bn[wnodes] = beta
        Mf = face_mass(mesh.nodes, wtris, bn[wtris].mean(axis=1))
        return sp.kron(Mf, sp.identity(3), format='csr')

    def penalty(A):
        if not len(pen_nodes):
            return sp.csr_matrix((n3, n3))
        dg = A.diagonal().reshape(-1, 3).max(axis=1)
        gam = 1e8 * dg[pen_nodes]
        rr = np.repeat(3 * pen_nodes[:, None] + np.arange(3)[None], 3, axis=1).ravel()
        cc = np.tile(3 * pen_nodes[:, None] + np.arange(3)[None], (1, 3)).ravel()
        vv = (gam[:, None, None] * pen_P).ravel()
        return sp.csr_matrix((vv, (rr, cc)), shape=(n3, n3))

    def momentum_operator(v, nut_, kk):
        """(Kv, P, g): momentum rows Kv v + (Bᵀ + P) p = F + g, linearised at v (SUPG when v is given)."""
        if v is None:
            A = viscous(mesh, mu, rho, nut_) + friction(v, kk)
            return A + penalty(A), sp.csr_matrix((n3, n_p)), np.zeros(n3)
        # Newton on the wall friction: τ ≈ τ(v_n) + β_t (v − v_n) → (β_t − β) v_n on the rhs. With the lagged secant
        # β = τ/U the log layer (τ ∝ U²) is a neutral 2-cycle: the channel at δ⁺ 200 never converges
        beta, _, _, _, beta_t = wall_state(v, kk)
        Ft, Fs = friction(v, kk, beta_t), friction(v, kk, beta)
        A = viscous(mesh, mu, rho, nut_) + Ft
        A = A + penalty(A)
        C, _ = st.convection(mesh, v, newton=False)                 # Picard (Newton on C diverges far from the
        Jvv, Jvp, g = supg_picard(mesh, v, mu, rho, nut_, bvec)     # solution, behind a step)
        return A + rho * C + Jvv, Jvp, g + (Ft - Fs) @ v.ravel()

    def solve_momentum(op, nut_, v_old=None, dt3=None):
        """Saddle solve with the momentum operator; with v_old/dt3 the local pseudo-time term ρ M_d/Δτ is added."""
        Kv, P, g = op
        f_v = F + g
        if dt3 is not None:
            m_t = rho * md3 / dt3
            Kv = Kv + sp.diags(m_t)
            f_v = f_v + m_t * v_old.ravel()
        mu_r = mu + rho * float(np.mean(nut_))
        S = sp.bmat([[Kv / mu_r, B.T + P], [B, zero_p]], format='csr')
        f = np.concatenate([f_v / mu_r, np.zeros(n_p)])
        x = np.zeros(nx)
        x[cdofs] = cvals
        x[free] = splu(S[free][:, free].tocsc()).solve((f - S @ x)[free])
        return x[:n3].reshape(-1, 3), x[n3:] * mu_r

    def momentum_residual(op, v, ph):
        """Relative steady momentum residual at the free velocity DOFs."""
        Kv, P, g = op
        Kvv = Kv @ v.ravel()
        r = Kvv + (B.T + P) @ ph - F - g
        fr = ~presc
        ref = max(float(np.linalg.norm(F[fr])), float(np.linalg.norm(Kvv[fr])), float(np.linalg.norm((B.T @ ph)[fr])),
                  1e-300)
        return float(np.linalg.norm(r[fr])) / ref

    # positive diagonal mass for the pseudo-time terms (diagonal of the consistent P2 mass, rescaled to the volume)
    Md = mass(mesh).diagonal()
    md3 = Md * (3 * iso.V.sum() / Md.sum())
    h_node = np.full(n, np.inf)
    np.minimum.at(h_node, iso.sub.ravel(), np.repeat(iso.h, 4))

    def local_dt(v, nut_, cfl):
        """Δτ_i = CFL h_i / (|v_i| + (ν + ν_t)/h_i) per node."""
        return cfl * h_node / (np.linalg.norm(v, axis=1) + (nu + nut_) / h_node)

    # ── turbulence step ──
    def scalar_solve(phi_old, conv_loc, diff_e, gamma, src, dtau, dir_idx, dir_val, tau_vg):
        """(ml/dτ + C + K_D + SUPG + diag(ml γ)) φ = ml φ_old/dτ + src, Dirichlet by elimination."""
        Kloc = conv_loc + diff_e[:, None, None] * iso.Kloc + tau_vg
        Kmat = iso.mat(Kloc) + sp.diags(iso.ml * (1.0 / dtau + gamma))       # dtau: per node
        rhs = iso.ml * phi_old / dtau + src
        phi = phi_old.copy()
        phi[dir_idx] = dir_val
        mk = np.ones(n, bool)
        mk[dir_idx] = False
        fr = np.flatnonzero(mk)
        Kc = Kmat.tocsr()
        phi[fr] = splu(Kc[fr][:, fr].tocsc()).solve(rhs[fr] - Kc[fr][:, dir_idx] @ phi[dir_idx])
        return phi

    def eddy_viscosity(v, k, eps):
        """ν_t = C_μ k T, T = min(k/ε, α/(√6 C_μ |S|)) (Durbin's realizability bound, α = 0.6, |S|² = S:S
        averaged to the nodes): keeps ν_t bounded where the strain is large (step corners, stagnation). Inactive in
        an equilibrium log layer (bound 3.85 κy/u_τ > k/ε = 3.33 κy/u_τ)."""
        G = iso.grad_v(v)
        S = 0.5 * (G + G.transpose(0, 2, 1))
        G2n = iso.lump(np.einsum('scd,scd->s', S, S)) / iso.ml
        T = np.minimum(k / eps, DURBIN_ALPHA / (math.sqrt(6.0) * CMU * np.sqrt(np.maximum(G2n, 1e-300))))
        return CMU * k * T

    def turbulence(v, k, eps, nut, dtau):
        ve = v[iso.sub]                                          # (s,4,3)
        vbar = ve.mean(axis=1)
        G = iso.grad_v(v)
        S = 0.5 * (G + G.transpose(0, 2, 1))
        G2 = 2.0 * np.einsum('scd,scd->s', S, S)
        nut_e = iso.mean(nut)
        Pk = iso.lump(nut_e * G2)
        Pk = np.minimum(Pk, P_LIMIT * iso.ml * eps)                      # production limiter P ≤ 10 ε
        Pe = C1 * (eps / k) * Pk                                         # C₁ (ε/k) P
        _, utw, _, _, _ = wall_state(v, k)
        utw = utw[wall_idx]
        # Mohammadi–Pironneau wall values: k = u_τ²/√C_μ, ε = u_τ³/(κ_ε δ) (ν_t = κ_ε u_τ δ → 0 smoothly at separation
        # and reattachment). A zero-flux k with wall-law production was tried first: k⁺ 3.16 instead of 3.33 in the
        # channel and no convergence behind a step.
        k_dir = np.concatenate([in_n, wall_only])
        k_val = np.concatenate([in_k, np.maximum(utw ** 2 / math.sqrt(CMU), k_floor)])
        e_wall = np.maximum(np.maximum(utw, 0.0) ** 3 / (KAPPA_EPS * delta), e_floor)
        conv = (iso.V / 20.0)[:, None, None] * np.einsum('sia,sja->sij', ve.sum(axis=1)[:, None, :] + ve, iso.g)
        vg = np.einsum('sa,sia->si', vbar, iso.g)                # v̄·∇N_i
        vm = np.linalg.norm(vbar, axis=1)
        h = np.where(np.abs(vg).sum(axis=1) > 0, 2.0 * vm / np.maximum(np.abs(vg).sum(axis=1), 1e-300), iso.h)
        out = []
        for phi, sig, gam, src, dir_idx, dir_val in (
                (k, SIG_K, eps / k, Pk, k_dir, k_val),
                (eps, SIG_E, C2 * eps / k, Pe, None, None)):
            D = nu + nut_e / sig
            g_e = iso.mean(gam)
            tau = 1.0 / np.sqrt((2 * vm / h) ** 2 + 9 * (4 * D / h ** 2) ** 2 + g_e ** 2 + iso.mean(1.0 / dtau) ** 2)
            tvg = (tau * iso.V)[:, None, None] * vg[:, :, None] * vg[:, None, :]
            if dir_idx is None:                                  # ε: inlet + wall values
                dir_idx = np.concatenate([in_n, wall_only])
                dir_val = np.concatenate([in_e, e_wall])
            res = scalar_solve(phi, conv, D, gam, src, dtau, dir_idx, dir_val, tvg)
            out.append(np.maximum(res, k_floor if sig == SIG_K else e_floor))
        return out[0], out[1]

    history = []
    v, ph = solve_momentum(momentum_operator(None, nut, k), nut)          # Stokes start with the initial ν_t
    Kv = momentum_operator(v, nut, k)
    rel_prev = momentum_residual(Kv, v, ph)
    cfl0, cfl = turb.cfl, turb.cfl
    converged = False
    it = 0
    for it in range(1, turb.max_iter + 1):
        dt = local_dt(v, nut, cfl)
        v_old = v
        v, ph = solve_momentum(Kv, nut, v_old, np.repeat(dt, 3))
        k_new, e_new = turbulence(v, k, eps, nut, dt)
        dk_node = int(np.argmax(np.abs(k_new - k)))
        dk = float(np.abs(k_new - k).max() / max(k_new.max(), 1e-300))
        de = float(np.abs(e_new - eps).max() / max(e_new.max(), 1e-300))
        k, eps = k_new, e_new
        nut_calc = eddy_viscosity(v, k, eps)
        nut = turb.relax * nut_calc + (1 - turb.relax) * nut
        Kv = momentum_operator(v, nut, k)
        rel = momentum_residual(Kv, v, ph)
        dv = float(np.abs(v - v_old).max() / max(np.abs(v).max(), 1e-300))
        dv_node = int(np.argmax(np.abs(v - v_old).max(axis=1)))
        history.append({'it': it, 'residual': rel, 'dv': dv, 'dk': dk, 'deps': de, 'cfl': cfl, 'dk_node': dk_node,
                        'dv_node': dv_node, 'k_at': float(k[dk_node]), 'eps_at': float(eps[dk_node]),
                        'v_at': v[dv_node].tolist()})
        if progress:
            progress(it, f'RANS k-ε it {it}: residuo {rel:.2e}, Δk {dk:.1e}, CFL {cfl:.3g}')
        if not np.isfinite(rel):
            raise ValueError('RANS k-ε diverge (residuo no finito). Revise las condiciones de contorno y la malla.')
        if rel < turb.tol and max(dk, de, dv) < 10 * turb.tol:
            converged = True
            break
        # the pseudo-time step grows geometrically (plain Picard in the limit) and is halved when the residual jumps
        cfl = cfl * 0.5 if rel > 2.0 * rel_prev else cfl * 1.3
        cfl = float(np.clip(cfl, cfl0, turb.cfl_max))
        rel_prev = rel

    nut = eddy_viscosity(v, k, eps)
    beta, ut, us, _, _ = wall_state(v, k)
    vw = v[wnodes]
    vt = vw - np.einsum('kab,kb->ka', wproj, vw)
    tau_w = beta[:, None] * vt                                   # wall shear stress vector on the wall [Pa]
    p_nodal = np.zeros(n)
    p_nodal[corners] = ph[:]
    for e_, (i, j) in enumerate(tb.T10_EDGES):
        p_nodal[mesh.elements[:, 4 + e_]] = 0.5 * (ph[pidx[mesh.elements[:, i]]] + ph[pidx[mesh.elements[:, j]]])
    R = np.zeros(n3)                                              # reactions at prescribed DOFs (on the fluid)
    Kv, P, g = momentum_operator(v, nut, k)
    full = Kv @ v.ravel() + (B.T + P) @ ph - F - g
    R[presc] = full[presc]
    # force of the fluid on the walls: friction (+ normal penalty) inside the operator, minus the reactions of the
    # wall normal constraints (R = force of the constraints on the fluid)
    A_w = viscous(mesh, mu, rho, nut) + friction(v, k)
    wall_part = (friction(v, k) + penalty(A_w)) @ v.ravel()
    wmask = np.zeros(n3, bool)
    wmask[(3 * wnodes[:, None] + np.arange(3)[None]).ravel()] = True
    wmask[(3 * in_n[:, None] + np.arange(3)[None]).ravel()] = False
    fw = np.where(wmask, wall_part - R, 0.0).reshape(-1, 3).sum(axis=0)
    return v, p_nodal, {
        'n_dof': int(nx + 2 * n), 'n_pressure': int(n_p), 'pressure_pinned': pin,
        'residual': history[-1]['residual'] if history else 0.0, 'reaction': R,
        'turbulence': {
            'model': turb.model, 'converged': converged, 'iterations': it, 'history': history,
            'k': k, 'eps': eps, 'nut': nut, 'wall_distance': delta,
            'wall': {'nodes': wnodes, 'normals': wnorm, 'u_tau': ut, 'u_star': us, 'y_plus': ut * delta / nu,
                     'tau_w': tau_w},
            'wall_tris': wtris, 'inlet': {'k': float(in_k.max()) if len(in_k) else None,
                                          'eps': float(in_e.max()) if len(in_e) else None},
            'U_ref': U_ref, 'wall_force': fw,
        }}
