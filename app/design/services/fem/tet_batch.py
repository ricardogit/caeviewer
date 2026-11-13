"""Vectorised tetrahedral elements (T4, T10) and consistent loads.

Everything here works on *batches* of elements so the kernel never loops over
elements in Python (FASE 2: T10 for ±1 % bending accuracy without locking).

Node ordering (internal, = VTK quadratic tetra)::

    corners 0..3, then mid-edge nodes
    4:(0,1)  5:(1,2)  6:(0,2)  7:(0,3)  8:(1,3)  9:(2,3)

Gmsh writes 8/9 on the other two edges and Abaqus C3D10 uses yet another order,
so ``canonicalize`` re-orders mid-edge nodes geometrically (nearest edge
midpoint) and fixes inverted elements; never rely on a file's convention.

Natural coordinates: L1 = 1-ξ-η-ζ, L2 = ξ, L3 = η, L4 = ζ.
Voigt order everywhere: [εxx, εyy, εzz, γxy, γyz, γxz].
"""
from __future__ import annotations

import numpy as np

T10_EDGES = np.array([(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)])

# Boundary face → local node indices (corners a,b,c then mids ab, bc, ca), T6 order.
TET_FACES_T4 = np.array([(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])
TET_FACES_T10 = np.array([(0, 2, 1, 6, 5, 4), (0, 1, 3, 4, 8, 7),
                          (0, 3, 2, 7, 9, 6), (1, 2, 3, 5, 9, 8)])

N_NODES = {'T4': 4, 'T10': 10}

# 4-point Gauss rule on the reference tet (degree 2, exact for T10 stiffness).
_A, _B = 0.5854101966249685, 0.1381966011250105
GAUSS_TET4 = np.array([[_B, _B, _B], [_A, _B, _B], [_B, _A, _B], [_B, _B, _A]])  # (ξ, η, ζ)
W_TET4 = np.full(4, 1.0 / 24.0)

# 3-point rule on the reference triangle (degree 2).
GAUSS_TRI3 = np.array([[1 / 6, 1 / 6], [2 / 3, 1 / 6], [1 / 6, 2 / 3]])
W_TRI3 = np.full(3, 1.0 / 6.0)

# Natural coordinates of the element nodes (for nodal stress evaluation).
NODE_NAT = {
    'T4': np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float),
}
_c = NODE_NAT['T4']
NODE_NAT['T10'] = np.vstack([_c, (_c[T10_EDGES[:, 0]] + _c[T10_EDGES[:, 1]]) / 2])


# ── Shape functions ──────────────────────────────────────────────────────────

_DL = np.array([[-1, -1, -1], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)   # dLi/d(ξ,η,ζ), (4,3)


def _L(p):
    x, y, z = p
    return np.array([1 - x - y - z, x, y, z])


def shape(etype: str, p) -> np.ndarray:
    """N at natural point p, shape (n,)."""
    L = _L(p)
    if etype == 'T4':
        return L
    corners = L * (2 * L - 1)
    mids = 4 * L[T10_EDGES[:, 0]] * L[T10_EDGES[:, 1]]
    return np.concatenate([corners, mids])


def dshape(etype: str, p) -> np.ndarray:
    """dN/d(ξ,η,ζ) at natural point p, shape (3, n)."""
    if etype == 'T4':
        return _DL.T.copy()
    L = _L(p)
    d = np.empty((10, 3))
    d[:4] = (4 * L - 1)[:, None] * _DL
    i, j = T10_EDGES[:, 0], T10_EDGES[:, 1]
    d[4:] = 4 * (L[i][:, None] * _DL[j] + L[j][:, None] * _DL[i])
    return d.T


def shape_tri(order: int, r: float, s: float) -> np.ndarray:
    L = np.array([1 - r - s, r, s])
    if order == 1:
        return L
    return np.concatenate([L * (2 * L - 1), [4 * L[0] * L[1], 4 * L[1] * L[2], 4 * L[2] * L[0]]])


def dshape_tri(order: int, r: float, s: float) -> np.ndarray:
    """dN/d(r,s), shape (2, n)."""
    dL = np.array([[-1, -1], [1, 0], [0, 1]], float)
    if order == 1:
        return dL.T.copy()
    L = np.array([1 - r - s, r, s])
    d = np.empty((6, 2))
    d[:3] = (4 * L - 1)[:, None] * dL
    for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0))):
        d[3 + k] = 4 * (L[a] * dL[b] + L[b] * dL[a])
    return d.T


# ── Geometry helpers ─────────────────────────────────────────────────────────

def etype_of(elements: np.ndarray) -> str:
    n = elements.shape[1]
    if n == 4:
        return 'T4'
    if n == 10:
        return 'T10'
    raise ValueError(f'Unsupported tetra with {n} nodes')


GMSH_TET10_TO_INTERNAL = np.array([0, 1, 2, 3, 4, 5, 6, 7, 9, 8])   # Gmsh puts (2,3) at 8, (1,3) at 9


def canonicalize(nodes: np.ndarray, elements: np.ndarray, reorder_mids: bool = True) -> np.ndarray:
    """Return elements with positive orientation and internal mid-node order.

    ``reorder_mids=False`` when the mid-node order is already internal (e.g. Gmsh
    output after GMSH_TET10_TO_INTERNAL): the geometric nearest-edge test is
    unreliable for strongly curved, flat T10 elements.
    """
    el = np.array(elements, dtype=np.int64, copy=True)
    if el.shape[1] == 10 and reorder_mids:
        X = nodes[el]                                             # (m,10,3)
        mids = X[:, 4:]                                           # (m,6,3)
        emid = (X[:, T10_EDGES[:, 0]] + X[:, T10_EDGES[:, 1]]) / 2  # (m,6,3)
        d = np.linalg.norm(mids[:, :, None, :] - emid[:, None, :, :], axis=3)  # node k vs edge e
        edge_of_node = d.argmin(axis=2)                           # (m,6)
        ok = np.sort(edge_of_node, axis=1) == np.arange(6)
        if not ok.all():
            bad = int((~ok.all(axis=1)).sum())
            raise ValueError(f'{bad} T10 elements have mid-edge nodes that do not map 1:1 to edges')
        perm = np.argsort(edge_of_node, axis=1)                   # edge e -> which mid node
        el[:, 4:] = np.take_along_axis(el[:, 4:], perm, axis=1)
    X = nodes[el[:, :4]]
    vol6 = np.einsum('ij,ij->i', np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0]), X[:, 3] - X[:, 0])
    if np.any(np.abs(vol6) < 1e-300):
        raise ValueError(f'{int((np.abs(vol6) < 1e-300).sum())} degenerate (zero-volume) tetrahedra')
    neg = vol6 < 0
    if neg.any():
        # swap corners 1<->2: edges (0,1)<->(0,2) and (1,3)<->(2,3)
        el[neg, 1], el[neg, 2] = el[neg, 2].copy(), el[neg, 1].copy()
        if el.shape[1] == 10:
            el[neg, 4], el[neg, 6] = el[neg, 6].copy(), el[neg, 4].copy()
            el[neg, 8], el[neg, 9] = el[neg, 9].copy(), el[neg, 8].copy()
    return el


def _jac(X: np.ndarray, dN_nat: np.ndarray):
    """X (m,n,3), dN_nat (3,n) → detJ (m,), dN global (m,3,n)."""
    J = np.einsum('kn,mnj->mkj', dN_nat, X)          # (m,3,3): J[k,j] = Σ dN_k/dnat * x_j
    det = np.linalg.det(J)
    if np.any(det <= 0):
        raise ValueError(f'{int((det <= 0).sum())} elements with non-positive Jacobian '
                         '(inverted or badly curved). Check mesh quality.')
    dN = np.linalg.solve(J, np.broadcast_to(dN_nat, (len(X),) + dN_nat.shape))
    return det, dN


def _B(dN: np.ndarray) -> np.ndarray:
    """dN (m,3,n) → B (m,6,3n)."""
    m, _, n = dN.shape
    B = np.zeros((m, 6, 3 * n))
    dx, dy, dz = dN[:, 0], dN[:, 1], dN[:, 2]
    B[:, 0, 0::3] = dx
    B[:, 1, 1::3] = dy
    B[:, 2, 2::3] = dz
    B[:, 3, 0::3] = dy
    B[:, 3, 1::3] = dx
    B[:, 4, 1::3] = dz
    B[:, 4, 2::3] = dy
    B[:, 5, 0::3] = dz
    B[:, 5, 2::3] = dx
    return B


def element_dofs(elements: np.ndarray) -> np.ndarray:
    """(m,n) → (m,3n) global DOF indices (node-major: 3*node + comp)."""
    return (3 * elements[:, :, None] + np.arange(3)).reshape(len(elements), -1)


# ── Batched element operators ────────────────────────────────────────────────

def stiffness_batch(nodes: np.ndarray, elements: np.ndarray, D: np.ndarray) -> np.ndarray:
    """Ke for every element, shape (m, 3n, 3n)."""
    et = etype_of(elements)
    X = nodes[elements]
    nd = 3 * N_NODES[et]
    Ke = np.zeros((len(elements), nd, nd))
    pts, w = (GAUSS_TET4[:1] * 0 + 0.25, [1 / 6]) if et == 'T4' else (GAUSS_TET4, W_TET4)
    for p, wg in zip(pts, w):
        det, dN = _jac(X, dshape(et, p))
        B = _B(dN)
        Ke += (wg * det)[:, None, None] * np.einsum('mai,ab,mbj->mij', B, D, B, optimize=True)
    return Ke


def volumes(nodes: np.ndarray, elements: np.ndarray) -> np.ndarray:
    et = etype_of(elements)
    X = nodes[elements]
    if et == 'T4':
        return _jac(X, dshape('T4', (0.25,) * 3))[0] / 6.0
    return sum(wg * _jac(X, dshape(et, p))[0] for p, wg in zip(GAUSS_TET4, W_TET4))


def strain_at(nodes, elements, u, p) -> np.ndarray:
    """Strain (m,6) at natural point p of every element."""
    et = etype_of(elements)
    _, dN = _jac(nodes[elements], dshape(et, p))
    ue = u[element_dofs(elements)]                  # (m,3n)
    return np.einsum('mij,mj->mi', _B(dN), ue)


# Barycentric coordinates (L1..L4) of the 4 Gauss points; a linear field sampled at
# the Gauss points is extrapolated to the corners with the inverse of this matrix.
_GP_BARY = np.array([[1 - p.sum(), *p] for p in GAUSS_TET4])
_GP_TO_CORNER = np.linalg.inv(_GP_BARY)


def nodal_stress(nodes, elements, u, D) -> tuple[np.ndarray, np.ndarray]:
    """Element stress (m,6) and nodal-averaged stress (N,6).

    T4: constant stress per element. T10: stress at the 4 Gauss points (where the
    Jacobian is guaranteed positive, unlike the vertices of curved elements),
    linearly extrapolated to the corners; mid-edge nodes take the mean of their
    edge's corners. Element value = mean of the Gauss-point stresses.
    """
    et = etype_of(elements)
    if et == 'T4':
        elem = strain_at(nodes, elements, u, (0.25, 0.25, 0.25)) @ D.T
        per_node = np.repeat(elem[:, None, :], 4, axis=1)                       # (m,4,6)
    else:
        gp = np.stack([strain_at(nodes, elements, u, p) @ D.T for p in GAUSS_TET4], axis=1)  # (m,4,6)
        elem = gp.mean(axis=1)
        corners = np.einsum('cg,mgk->mck', _GP_TO_CORNER, gp)                   # (m,4,6)
        mids = (corners[:, T10_EDGES[:, 0]] + corners[:, T10_EDGES[:, 1]]) / 2  # (m,6,6)
        per_node = np.concatenate([corners, mids], axis=1)                      # (m,10,6)
    centroid = elem
    acc = np.zeros((len(nodes), 6))
    cnt = np.zeros(len(nodes))
    for k in range(elements.shape[1]):
        np.add.at(acc, elements[:, k], per_node[:, k])
        np.add.at(cnt, elements[:, k], 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        nodal = np.where(cnt[:, None] > 0, acc / cnt[:, None], 0.0)
    return centroid, nodal


def von_mises_v(s: np.ndarray) -> np.ndarray:
    sxx, syy, szz, sxy, syz, sxz = s.T
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2
                          + 6.0 * (sxy ** 2 + syz ** 2 + sxz ** 2)))


# ── Consistent loads ─────────────────────────────────────────────────────────

def body_load(nodes, elements, b: np.ndarray, n_dof: int) -> np.ndarray:
    """Consistent nodal forces of a uniform body force density b [N/m³]."""
    et = etype_of(elements)
    X = nodes[elements]
    F = np.zeros(n_dof)
    nw = np.zeros((len(elements), N_NODES[et]))
    for p, wg in zip(GAUSS_TET4, W_TET4):
        det, _ = _jac(X, dshape(et, p))
        nw += (wg * det)[:, None] * shape(et, p)[None, :]
    for c in range(3):
        np.add.at(F, 3 * elements + c, nw * b[c])
    return F


def surface_integrals(nodes: np.ndarray, tris: np.ndarray):
    """For triangles (k,3|6): per-node ∫N dA (k,n) and ∫N n dA (k,n,3), plus area (k,).

    ``n`` is the (unnormalised direction of the) triangle normal following the
    node winding; callers orient it outward with ``outward_sign``.
    """
    order = 1 if tris.shape[1] == 3 else 2
    X = nodes[tris]                                       # (k,n,3)
    k, n = tris.shape
    NdA = np.zeros((k, n))
    NndA = np.zeros((k, n, 3))
    area = np.zeros(k)
    for (r, s), wg in zip(GAUSS_TRI3, W_TRI3):
        dN = dshape_tri(order, r, s)                      # (2,n)
        t = np.einsum('an,knj->kaj', dN, X)               # (k,2,3) tangents
        nvec = np.cross(t[:, 0], t[:, 1])                 # (k,3), |nvec| = dA/(dr ds)
        jac = np.linalg.norm(nvec, axis=1)
        N = shape_tri(order, r, s)
        NdA += wg * jac[:, None] * N[None, :]
        NndA += wg * N[None, :, None] * nvec[:, None, :]
        area += wg * jac
    return NdA, NndA, area


def boundary_faces(elements: np.ndarray) -> np.ndarray:
    """Faces used by exactly one element, outward-oriented, (k,3|6)."""
    faces_local = TET_FACES_T4 if elements.shape[1] == 4 else TET_FACES_T10
    allf = elements[:, faces_local].reshape(-1, faces_local.shape[1])
    key = np.sort(allf[:, :3], axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return allf[cnt[inv.ravel()] == 1]


def outward_sign(nodes: np.ndarray, elements: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """+1/-1 per triangle so that the winding normal points out of its owner tet."""
    keys_t = np.sort(tris[:, :3], axis=1)
    faces_local = TET_FACES_T4[:, :3]
    allf = np.sort(elements[:, faces_local].reshape(-1, 3), axis=1)
    owner = np.repeat(np.arange(len(elements)), 4)
    # lexicographic search of each triangle key among all tet faces
    order = np.lexsort(allf.T[::-1])
    sorted_f = allf[order]
    view = lambda a: np.ascontiguousarray(a).view([('', a.dtype)] * 3).ravel()  # noqa: E731
    sf, kt = view(sorted_f.astype(np.int64)), view(keys_t.astype(np.int64))
    pos = np.searchsorted(sf, kt)
    pos = np.clip(pos, 0, len(sf) - 1)
    found = sf[pos] == kt
    if not found.all():
        raise ValueError(f'{int((~found).sum())} surface triangles are not faces of the volume mesh')
    el = owner[order[pos]]
    c_tet = nodes[elements[el, :4]].mean(axis=1)
    X = nodes[tris[:, :3]]
    nrm = np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    return np.where(np.einsum('ij,ij->i', nrm, X.mean(axis=1) - c_tet) >= 0, 1.0, -1.0)


def surface_load(nodes, elements, tris, n_dof, *, total_force=None, pressure=None) -> tuple[np.ndarray, float]:
    """Consistent nodal forces on a set of boundary triangles.

    total_force: [Fx,Fy,Fz] in N, applied as a uniform traction F/A.
    pressure:    p in Pa, positive = pushes into the body (t = -p n_out).
    Returns (F, area).
    """
    NdA, NndA, area = surface_integrals(nodes, tris)
    A = float(area.sum())
    F = np.zeros(n_dof)
    if A <= 0:
        return F, A
    if total_force is not None:
        t = np.asarray(total_force, float) / A
        for c in range(3):
            np.add.at(F, 3 * tris + c, NdA * t[c])
    if pressure is not None:
        sgn = outward_sign(nodes, elements, tris)
        contrib = -float(pressure) * sgn[:, None, None] * NndA
        for c in range(3):
            np.add.at(F, 3 * tris + c, contrib[:, :, c])
    return F, A


def split_t6(tris: np.ndarray) -> np.ndarray:
    """T6 → 4 linear triangles for display; T3 passes through."""
    if tris.shape[1] == 3:
        return tris
    a, b, c, ab, bc, ca = tris.T
    return np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1),
                           np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
