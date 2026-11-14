"""Steady incompressible Stokes flow (creeping flow, Re ≪ 1) of a Newtonian fluid.

    −μ∇²v + ∇p = ρb,   ∇·v = 0

Taylor–Hood P2–P1 on T10 meshes (inf-sup stable): velocity at every node (3 DOF), pressure at the corner
nodes only (linear). Laplacian form μ∫∇w:∇v dV, so the natural condition on a face without velocity BCs is
the pseudo-traction μ ∂v/∂n − p n = −p_face n ("do nothing": an outlet at p = 0, or a ``pressure`` load).

Spec entries reuse the structural ones: ``dofs``/``values`` BCs prescribe velocities [m/s] (no-slip wall =
all three = 0, slip wall = normal component = 0, inlet = velocity profile value), ``pressure`` loads [Pa] are
the face pressure (positive pushes into the fluid), ``gravity`` uses ρ. The system
[[A, Bᵀ], [B, 0]] is solved directly; when every boundary node has its normal velocity prescribed
(enclosed flow) the pressure is only defined up to a constant and one corner pressure is pinned to 0.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb

KEYS = ('mu',)


class FluidMaterial:
    def __init__(self, spec: dict):
        mu = spec.get('mu')
        if mu in (None, ''):
            raise ValueError('Fluido newtoniano: falta la viscosidad dinámica μ [Pa·s].')
        self.mu = float(mu)
        self.rho = float(spec.get('rho') or 0.0)
        if not self.mu > 0:
            raise ValueError('Fluido newtoniano: la viscosidad μ debe ser > 0.')
        if self.rho < 0:
            raise ValueError('Fluido newtoniano: la densidad no puede ser negativa.')


def pressure_index(mesh):
    """Corner nodes carry pressure: (corner node ids, map node → pressure index or −1)."""
    corners = np.unique(mesh.elements[:, :4])
    pidx = np.full(mesh.n_nodes, -1, np.int64)
    pidx[corners] = np.arange(len(corners))
    return corners, pidx


def assemble(mesh, mu: float = 1.0):
    """A (3N×3N, Laplacian form ×μ) and B (Np×3N, −∫q ∇·v dV) as CSR."""
    if mesh.element_type != 'T10':
        raise ValueError('Stokes necesita elementos cuadráticos T10 (Taylor-Hood P2-P1); T4 no es estable.')
    n = mesh.n_nodes
    corners, pidx = pressure_index(mesh)
    rows_a, cols_a, vals_a, rows_b, cols_b, vals_b = [], [], [], [], [], []
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        X = mesh.nodes[el]
        m = len(el)
        Kl = np.zeros((m, 10, 10))
        Be = np.zeros((m, 4, 30))
        for p, wg in zip(tb.GAUSS_TET4, tb.W_TET4):     # degree 2: exact for straight T10
            det, dN = tb._jac(X, tb.dshape('T10', p))  # (m,3,10)
            w = (wg * det)[:, None, None]
            Kl += w * np.einsum('man,mak->mnk', dN, dN, optimize=True)
            L = tb._L(p)                                # linear pressure shape functions (corners)
            div = dN.transpose(0, 2, 1).reshape(m, 30)  # ∂N_j/∂x_c at column 3j + c
            Be -= w * L[None, :, None] * div[:, None, :]
        rows_a.append(np.repeat(el, 10, axis=1).ravel())
        cols_a.append(np.tile(el, (1, 10)).ravel())
        vals_a.append(Kl.reshape(m, -1).ravel())
        pr = pidx[el[:, :4]]
        rows_b.append(np.repeat(pr, 30, axis=1).ravel())
        cols_b.append(np.tile(tb.element_dofs(el), (1, 4)).ravel())
        vals_b.append(Be.reshape(m, -1).ravel())
    Kl = sp.csr_matrix((np.concatenate(vals_a), (np.concatenate(rows_a), np.concatenate(cols_a))), shape=(n, n))
    A = (mu * sp.kron(Kl, sp.identity(3), format='csr')).tocsr()
    B = sp.csr_matrix((np.concatenate(vals_b), (np.concatenate(rows_b), np.concatenate(cols_b))),
                      shape=(len(corners), 3 * n))
    return A, B, corners, pidx


def is_enclosed(mesh, dofs: np.ndarray) -> bool:
    """True when no boundary face lets fluid in/out freely: the normal-direction velocity DOF (dominant axis
    of the face normal) is prescribed at every node of every boundary face → pressure level undetermined."""
    presc = np.zeros(3 * mesh.n_nodes, bool)
    presc[dofs] = True
    tris = tb.boundary_faces(mesh.elements)
    X = mesh.nodes[tris[:, :3]]
    nrm = np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    ax = np.argmax(np.abs(nrm), axis=1)
    return bool(presc[3 * tris + ax[:, None]].all())


def solve(mesh, mat: FluidMaterial, F: np.ndarray, dofs: np.ndarray, vals: np.ndarray):
    """Velocity (N,3) [m/s], nodal pressure (N,) [Pa] (mid nodes = mean of the edge ends), info."""
    from scipy.sparse.linalg import spsolve
    A, B, corners, pidx = assemble(mesh, 1.0)           # μ-normalised: unknowns v and p/μ
    n3, n_p = 3 * mesh.n_nodes, len(corners)
    K = sp.bmat([[A, B.T], [B, None]], format='csr')
    rhs = np.concatenate([F / mat.mu, np.zeros(n_p)])
    pin = is_enclosed(mesh, dofs)
    cdofs = np.concatenate([dofs, [n3]]) if pin else dofs      # pin the first corner pressure
    cvals = np.concatenate([vals, [0.0]]) if pin else vals
    x = np.zeros(n3 + n_p)
    x[cdofs] = cvals
    mask = np.ones(len(x), bool)
    mask[cdofs] = False
    free = np.flatnonzero(mask)
    Kf = K[free][:, free].tocsc()
    x[free] = spsolve(Kf, rhs[free] - K[free][:, cdofs] @ cvals)
    resid = float(np.linalg.norm(K[free] @ x - rhs[free]) / max(np.linalg.norm(rhs[free]),
                                                                 np.linalg.norm(K[free][:, cdofs] @ cvals), 1e-30))
    v = x[:n3].reshape(-1, 3)
    pc = x[n3:] * mat.mu
    p = np.zeros(mesh.n_nodes)
    p[corners] = pc
    el = mesh.elements
    for k, (i, j) in enumerate(tb.T10_EDGES):
        p[el[:, 4 + k]] = 0.5 * (pc[pidx[el[:, i]]] + pc[pidx[el[:, j]]])
    # reaction of the prescribed velocities = force of the fluid on walls/inlets (sign: on the fluid)
    R = (K[:n3] @ x - rhs[:n3]) * mat.mu
    return v, p, {'n_dof': int(len(x)), 'n_pressure': int(n_p), 'pressure_pinned': pin, 'residual': resid,
                  'reaction': R}


def flow_rate(mesh, v: np.ndarray, face_set) -> tuple[float, float]:
    """Outward volume flow ∫v·n dA [m³/s] and area [m²] of a face set (or of whole boundary for '@all')."""
    from app.design.services.fem.assembler import _face_tris
    tris = tb.boundary_faces(mesh.elements) if face_set == '@all' else _face_tris(mesh, face_set)
    _, NndA, area = tb.surface_integrals(mesh.nodes, tris)
    sgn = tb.outward_sign(mesh.nodes, mesh.elements, tris)
    q = np.einsum('k,knj,knj->', sgn, NndA, v[tris])
    return float(q), float(area.sum())


def velocity_gradient_max(mesh, v: np.ndarray) -> float:
    """Max |∇v| (Frobenius) at the Gauss points [1/s] — for the wall shear-rate estimate."""
    X = mesh.nodes[mesh.elements]
    ve = v[mesh.elements]                               # (m,10,3)
    g = 0.0
    for p in tb.GAUSS_TET4:
        _, dN = tb._jac(X, tb.dshape('T10', p))
        G = np.einsum('man,mnc->mca', dN, ve)
        g = max(g, float(np.sqrt((G ** 2).sum(axis=(1, 2))).max()))
    return g
