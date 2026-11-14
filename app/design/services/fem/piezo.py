"""Linear piezoelectricity (static), stress-charge form, poling along material axis 3.

    σ = Cᴱ ε − eᵀ E,      D = e ε + κˢ E,      E = −∇φ,      ∇·σ = 0,  ∇·D = 0 (no free volume charge)

Unknowns u (3/node) and φ (1/node), same T4/T10 shape functions. Weak form (symmetric, indefinite):

    [ K_uu    K_uφ ] [u]   [ F ]        K_uu = ∫Bᵀ C B,  K_uφ = ∫Bᵀ eᵀ ∇N,  K_φφ = ∫∇Nᵀ κ ∇N
    [ K_uφᵀ  −K_φφ ] [φ] = [ −Q ]       Q = ∮ N ρ_s dA (free surface charge density on a face)

Voigt order of the kernel (xx yy zz xy yz xz, engineering shear). Material constants are given in the
material axes (IEEE: c11 c12 c13 c33 c44 c66, e31 e33 e15, ε11ˢ ε33ˢ relative to ε0) and rotated with
``axis_1``/``axis_2`` (poling = axis 3 = 1 × 2). Electrodes are prescribed potentials (``voltage`` on a
face/node set); a face with no electric condition has D·n = 0 (a floating electrode is not modelled as an
equipotential). The charge on each electrode is the reaction of its potential equations.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.constitutive import material_axes, rotate_D, strain_rotation
from app.design.services.fem.plasticity import gauss_points, gp_to_nodal

EPS0 = 8.8541878128e-12

# PZT-5H (stress-charge form; values as tabulated by common FE material libraries)
PZT5H = {'c11': 127.205e9, 'c12': 80.212e9, 'c13': 84.670e9, 'c33': 117.436e9, 'c44': 22.988e9,
         'c66': 23.474e9, 'e31': -6.623, 'e33': 23.240, 'e15': 17.034, 'eps11': 1704.4, 'eps33': 1433.6,
         'rho': 7500.0}
KEYS = ('c11', 'c12', 'c13', 'c33', 'c44', 'c66', 'e31', 'e33', 'e15', 'eps11', 'eps33')


class PiezoMaterial:
    """Transversely isotropic (6mm) piezoelectric in the material axes, rotated to the global frame."""

    def __init__(self, spec: dict):
        missing = [k for k in KEYS if spec.get(k) in (None, '')]
        if missing:
            raise ValueError(f"Material piezoeléctrico: faltan {', '.join(missing)}")
        p = {k: float(spec[k]) for k in KEYS}
        self.params = p
        Cm = np.zeros((6, 6))
        Cm[0, 0] = Cm[1, 1] = p['c11']
        Cm[2, 2] = p['c33']
        Cm[0, 1] = Cm[1, 0] = p['c12']
        Cm[0, 2] = Cm[2, 0] = Cm[1, 2] = Cm[2, 1] = p['c13']
        Cm[3, 3] = p['c66']                     # xy
        Cm[4, 4] = Cm[5, 5] = p['c44']          # yz, xz
        if np.linalg.eigvalsh(Cm).min() <= 0:
            raise ValueError('Constantes elásticas cᴱ no admisibles (no definida positiva).')
        em = np.zeros((3, 6))
        em[2, 0] = em[2, 1] = p['e31']
        em[2, 2] = p['e33']
        em[0, 5] = p['e15']                     # E1 ↔ γxz
        em[1, 4] = p['e15']                     # E2 ↔ γyz
        km = np.diag([p['eps11'], p['eps11'], p['eps33']]) * EPS0
        if min(p['eps11'], p['eps33']) <= 0:
            raise ValueError('Permitividades relativas ε11ˢ, ε33ˢ deben ser positivas.')
        R = material_axes(spec)
        T = strain_rotation(R)
        self.R = R
        self.C = rotate_D(Cm, R)
        self.e = R.T @ em @ T                    # D_g = Rᵀ D_m, ε_m = T ε_g
        self.kappa = R.T @ km @ R
        self.C_m, self.e_m, self.kappa_m = Cm, em, km

    def d_matrix(self) -> np.ndarray:
        """Strain-charge coefficients d = e Sᴱ (3×6, global), [m/V] = [C/N]."""
        return self.e @ np.linalg.inv(self.C)

    def free_permittivity(self) -> np.ndarray:
        """κᵀ = κˢ + e Sᴱ eᵀ (stress-free), global 3×3."""
        return self.kappa + self.e @ np.linalg.inv(self.C) @ self.e.T


def assemble(mesh, mat: PiezoMaterial):
    """Global coupled matrix (3N + N) as CSR: u DOFs first (node-major), then φ (one per node)."""
    from app.design.services.fem.assembler import assemble_K
    n = mesh.n_nodes
    Kuu = assemble_K(mesh, mat.C)
    rows_c, cols_c, vals_c, rows_p, cols_p, vals_p = [], [], [], [], [], []
    et = mesh.element_type
    pts, w = gauss_points(et)
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        X = mesh.nodes[el]
        ne = el.shape[1]
        Kc = np.zeros((len(el), 3 * ne, ne))
        Kp = np.zeros((len(el), ne, ne))
        for p, wg in zip(pts, w):
            det, dN = tb._jac(X, tb.dshape(et, p))                  # dN (m,3,n)
            B = tb._B(dN)                                            # (m,6,3n)
            Kc += (wg * det)[:, None, None] * np.einsum('mai,ja,mjn->min', B, mat.e, dN, optimize=True)
            Kp += (wg * det)[:, None, None] * np.einsum('man,ab,mbk->mnk', dN, mat.kappa, dN, optimize=True)
        dofs = tb.element_dofs(el)
        rows_c.append(np.repeat(dofs, ne, axis=1).ravel())
        cols_c.append(np.tile(el, (1, 3 * ne)).ravel())
        vals_c.append(Kc.reshape(len(el), -1).ravel())
        rows_p.append(np.repeat(el, ne, axis=1).ravel())
        cols_p.append(np.tile(el, (1, ne)).ravel())
        vals_p.append(Kp.reshape(len(el), -1).ravel())
    Kuf = sp.csr_matrix((np.concatenate(vals_c), (np.concatenate(rows_c), np.concatenate(cols_c))),
                        shape=(3 * n, n))
    Kff = sp.csr_matrix((np.concatenate(vals_p), (np.concatenate(rows_p), np.concatenate(cols_p))), shape=(n, n))
    return sp.bmat([[Kuu, Kuf], [Kuf.T, -Kff]], format='csr'), Kuu, Kuf, Kff


def charge_vector(mesh, loads: list, info: list | None = None) -> np.ndarray:
    """Q = ∮ N ρ_s dA for ``surface_charge`` loads [C/m²] on face sets."""
    from app.design.services.fem.assembler import BoundaryConditionError, _face_tris
    Q = np.zeros(mesh.n_nodes)
    for i, ld in enumerate(loads):
        if 'surface_charge' not in ld:
            continue
        if 'face_set' not in ld:
            raise BoundaryConditionError(f'Carga de carga eléctrica {i} sin face_set.')
        tris = _face_tris(mesh, ld['face_set'])
        NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
        q = np.zeros(mesh.n_nodes)
        np.add.at(q, tris, NdA * float(ld['surface_charge']))
        Q += q
        if info is not None:
            info.append({'index': i, 'label': ld.get('label'), 'kind': 'surface_charge',
                         'charge_C': float(q.sum()), 'area_m2': float(area.sum())})
    return Q


def voltage_dirichlet(mesh, bcs: list):
    """Electrodes: (nodes, V) and the node groups of each voltage entry (for the electrode charges)."""
    from app.design.services.fem.assembler import _face_tris, _node_set
    presc, groups = {}, []
    for bc in bcs:
        if 'voltage' not in bc:
            continue
        nodes = np.unique(_face_tris(mesh, bc['face_set'])) if 'face_set' in bc \
            else _node_set(mesh, bc.get('node_set', ''))
        for nd in nodes:
            presc[int(nd)] = float(bc['voltage'])
        groups.append((bc, nodes))
    dofs = np.array(sorted(presc), dtype=np.int64)
    return dofs, np.array([presc[d] for d in dofs], float), groups


def postprocess(mesh, mat: PiezoMaterial, u: np.ndarray, phi: np.ndarray):
    """Gauss-point stress σ = Cε + eᵀ∇φ, field E = −∇φ and D = eε − κ∇φ → nodal (Gauss extrapolation)."""
    et = mesh.element_type
    pts, _ = gauss_points(et)
    X = mesh.nodes[mesh.elements]
    ue = u[tb.element_dofs(mesh.elements)]
    pe = phi[mesh.elements]
    sig, Ef, Df = [], [], []
    for p in pts:
        _, dN = tb._jac(X, tb.dshape(et, p))
        eps = np.einsum('mij,mj->mi', tb._B(dN), ue)
        grad = np.einsum('man,mn->ma', dN, pe)
        sig.append(eps @ mat.C.T + grad @ mat.e)               # eᵀ∇φ (Voigt 6)
        Ef.append(-grad)
        Df.append(eps @ mat.e.T - grad @ mat.kappa.T)
    sig, Ef, Df = (np.stack(a, axis=1) for a in (sig, Ef, Df))   # (m,g,·)
    n = mesh.n_nodes
    return {'sigma_gp': sig, 'E_gp': Ef, 'D_gp': Df,
            'sigma_nodal': gp_to_nodal(n, mesh.elements, sig), 'E_nodal': gp_to_nodal(n, mesh.elements, Ef),
            'D_nodal': gp_to_nodal(n, mesh.elements, Df)}
