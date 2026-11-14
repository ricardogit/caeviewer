"""Linear magnetostatics with a magnetic scalar potential (current-free regions).

    H = −∇ψ,   B = μ₀ μr H + Br,   ∇·B = 0   in Ω (one material region, no coils / currents)

Weak form (reuses the conduction operators of ``thermal``, scaled by 1/μ₀ so the matrix is O(μr)):

    ∫ μr ∇w·∇ψ dV = ∫ ∇w·(Br/μ₀) dV + ∫ w (Bn_in/μ₀) dA

Boundary conditions:
    ψ = ψ̄ on a face set (BC ``magnetic_potential`` [A]): equipotential face, B normal to it — a pole face
          against ideal iron (μ → ∞). The difference of ψ between two faces is the magnetomotive force (A·turn).
    Bn imposed (load ``magnetic_flux`` [T], positive = flux entering the body).
    Natural (no condition): Bn = 0, flux runs parallel to the face (flux wall / symmetry plane).

Without any potential BC ψ is fixed only up to a constant: the first node is pinned to 0, which needs the
imposed fluxes to balance. ψ is in ampere(-turns); B in tesla, H in A/m, flux Φ in weber.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem import thermal as th
from app.design.services.fem.mesh import FEMMesh

MU0 = 4e-7 * np.pi
KEYS = ('mu_r',)


class MagneticMaterial:
    """mu_r (relative permeability, > 0) and remanent flux density Br [T] (permanent magnet, global frame)."""

    def __init__(self, spec: dict):
        mu_r = spec.get('mu_r')
        if mu_r is None or float(mu_r) <= 0:
            raise ValueError('Material magnético: la permeabilidad relativa μr debe ser > 0.')
        self.mu_r = float(mu_r)
        br = spec.get('Br') or [0.0, 0.0, 0.0]
        self.Br = np.asarray([float(b) for b in br], float)
        if self.Br.shape != (3,):
            raise ValueError('Material magnético: Br debe ser un vector [Bx, By, Bz] en T.')

    @property
    def mu(self) -> float:
        return MU0 * self.mu_r

    def to_dict(self) -> dict:
        return {'mu_r': self.mu_r, 'Br': self.Br.tolist()}


def is_magnetic_bc(bc: dict) -> bool:
    return 'magnetic_potential' in bc


def is_magnetic_load(ld: dict) -> bool:
    return 'magnetic_flux' in ld


def remanence_vector(nodes, elements, M: np.ndarray, n: int) -> np.ndarray:
    """∫ ∇N · M dV (uniform M)."""
    et = tb.etype_of(elements)
    X = nodes[elements]
    fe = np.zeros((len(elements), tb.N_NODES[et]))
    for p, wg in zip(*th._gauss(et)):
        det, dN = tb._jac(X, tb.dshape(et, p))               # dN (m,3,n)
        fe += (wg * det)[:, None] * np.einsum('man,a->mn', dN, M)
    F = np.zeros(n)
    np.add.at(F, elements, fe)
    return F


def assemble(mesh: FEMMesh, mat: MagneticMaterial, loads: list, info: list | None = None):
    """K (μr-scaled conduction matrix) and F (remanence + imposed normal flux, /μ₀)."""
    from app.design.services.fem.assembler import BoundaryConditionError, _face_tris
    n = mesh.n_nodes
    K = th.assemble_Kt(mesh, mat.mu_r)
    F = remanence_vector(mesh.nodes, mesh.elements, mat.Br / MU0, n) if np.any(mat.Br) else np.zeros(n)
    for i, ld in enumerate(loads):
        if 'face_set' not in ld:
            raise BoundaryConditionError(f'Carga magnética {i}: el flujo impuesto necesita caras (face_set).')
        tris = _face_tris(mesh, ld['face_set'])
        NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
        Fi = np.zeros(n)
        np.add.at(Fi, tris, NdA * float(ld['magnetic_flux']) / MU0)
        F += Fi
        if info is not None:
            fs = ld['face_set']
            info.append({'index': i, 'label': ld.get('label'), 'kind': 'magnetic_flux',
                         'face_set': fs if isinstance(fs, str) else f'{len(fs)} caras',
                         'Bn_T': float(ld['magnetic_flux']), 'area_m2': float(area.sum()),
                         'flux_Wb': float(ld['magnetic_flux'] * area.sum())})
    return K.tocsr(), F


def potential_dirichlet(mesh: FEMMesh, bcs: list):
    """Prescribed (nodes, ψ) and the node groups per BC entry (for the flux through each pole face)."""
    from app.design.services.fem.assembler import _face_tris, _node_set
    presc: dict[int, float] = {}
    groups = []
    for bc in bcs:
        nodes = np.unique(_face_tris(mesh, bc['face_set'])) if 'face_set' in bc \
            else _node_set(mesh, bc.get('node_set', ''))
        for nd in nodes:
            presc[int(nd)] = float(bc['magnetic_potential'])
        groups.append(nodes)
    dofs = np.array(sorted(presc), dtype=np.int64)
    return dofs, np.array([presc[d] for d in dofs], float), groups


def fields(mesh: FEMMesh, psi: np.ndarray, mat: MagneticMaterial):
    """Nodal H [A/m] and B [T] (T10: Gauss-point extrapolation like the heat flux)."""
    _, H = th.heat_flux(mesh.nodes, mesh.elements, psi, 1.0)        # −∇ψ
    return H, MU0 * mat.mu_r * H + mat.Br[None, :]


def energy(mesh: FEMMesh, psi: np.ndarray, mat: MagneticMaterial) -> float:
    """½ ∫ μ |H|² dV [J] (field energy; for a magnet it is the energy of H, not the co-energy)."""
    K = th.assemble_Kt(mesh, mat.mu_r)
    return float(0.5 * MU0 * psi @ (K @ psi))


def solve(mesh: FEMMesh, mat: MagneticMaterial, bcs: list, loads: list, linear_solve=None):
    """ψ (N,), info {pinned, residual, flux_in per BC group [Wb], load_info}."""
    from app.design.services.fem.assembler import reduce_system
    load_info: list = []
    K, F = assemble(mesh, mat, loads, load_info)
    dofs, vals, groups = potential_dirichlet(mesh, bcs)
    pinned = False
    if not len(dofs):
        net = sum(m['flux_Wb'] for m in load_info)
        scale = max([abs(m['flux_Wb']) for m in load_info] + [1e-300])
        if load_info and abs(net) > 1e-6 * scale:
            raise ValueError(f'Magnético: sin potencial impuesto el flujo que entra debe salir (balance '
                             f'{net:.3g} Wb ≠ 0). Agrega una cara con potencial magnético o equilibra los flujos.')
        dofs, vals, pinned = np.array([0], np.int64), np.array([0.0]), True
    Kf, rhs, free = reduce_system(K, F, dofs, vals)
    if linear_solve is None:
        import scipy.sparse.linalg as spla
        xf = spla.spsolve(sp.csc_matrix(Kf), rhs)
    else:
        xf = linear_solve(Kf, rhs)
    psi = np.zeros(mesh.n_nodes)
    psi[free] = xf
    psi[dofs] = vals
    R = K @ psi - F                                    # reaction = flux entering at the prescribed nodes (/μ₀)
    fr = R.copy()
    fr[dofs] = 0.0
    residual = float(np.linalg.norm(fr) / max(np.linalg.norm(F), np.linalg.norm(K @ psi), 1e-300))
    flux_in = [float(MU0 * R[g].sum()) for g in groups]
    return psi, {'pinned': pinned, 'residual': residual, 'flux_in_Wb': flux_in, 'loads': load_info}
