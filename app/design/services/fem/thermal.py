"""Steady-state heat conduction and thermal-strain loads (FASE 2 multiphysics).

Vectorised T4/T10, one DOF (temperature) per node, SI units (W, m, K; temperatures in °C
are fine since only differences enter the structural coupling).

    −∇·(k ∇T) = Q   in Ω
    T = T̄                         on Γ_T   (BC entry with ``temperature``)
    −k ∂T/∂n = −q                 on Γ_q   (``heat_flux`` q W/m², positive = into the body)
    −k ∂T/∂n = h (T − T∞)         on Γ_h   (``convection`` {h W/m²K, T_inf})
    Q W/m³                         (``heat_source``, whole body or ``face_set`` ignored)

Thermo-mechanical coupling is one-way: the solved T gives the thermal strain
ε_th = α (T − T_ref) [1,1,1,0,0,0]; its consistent load F = ∫ Bᵀ D ε_th dV is added to the
structural right-hand side and the stress is σ = D (ε − ε_th).
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.mesh import FEMMesh

THERMAL_LOAD_KEYS = ('heat_flux', 'convection', 'heat_source')
VOIGT_M = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])

# Dunavant degree-4 rule on the reference triangle (weights sum to 1/2 like GAUSS_TRI3):
# exact for N_i N_j of quadratic (T6) triangles, needed by the convection matrix.
_A1, _B1, _W1 = 0.445948490915965, 0.108103018168070, 0.223381589678011
_A2, _B2, _W2 = 0.091576213509771, 0.816847572980459, 0.109951743655322
TRI_D4 = np.array([[_A1, _A1], [_B1, _A1], [_A1, _B1], [_A2, _A2], [_B2, _A2], [_A2, _B2]])
W_TRI_D4 = 0.5 * np.array([_W1] * 3 + [_W2] * 3)


def is_thermal_bc(bc: dict) -> bool:
    return 'temperature' in bc


def is_thermal_load(load: dict) -> bool:
    return any(k in load for k in THERMAL_LOAD_KEYS)


def _gauss(et: str):
    if et == 'T4':
        return np.array([[0.25, 0.25, 0.25]]), np.array([1.0 / 6.0])
    return tb.GAUSS_TET4, tb.W_TET4


# ── Element operators ────────────────────────────────────────────────────────

def conductivity_batch(nodes: np.ndarray, elements: np.ndarray, k: float) -> np.ndarray:
    """Ke = ∫ k ∇Nᵀ ∇N dV for every element, (m, n, n)."""
    et = tb.etype_of(elements)
    X = nodes[elements]
    n = tb.N_NODES[et]
    Ke = np.zeros((len(elements), n, n))
    for p, wg in zip(*_gauss(et)):
        det, dN = tb._jac(X, tb.dshape(et, p))                 # dN (m,3,n)
        Ke += (wg * det * k)[:, None, None] * np.einsum('man,mak->mnk', dN, dN)
    return Ke


def assemble_Kt(mesh: FEMMesh, k: float) -> sp.csr_matrix:
    n = mesh.n_nodes
    K = sp.csr_matrix((n, n))
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        Ke = conductivity_batch(mesh.nodes, el, k)
        nd = el.shape[1]
        rows = np.repeat(el, nd, axis=1).ravel()
        cols = np.tile(el, (1, nd)).ravel()
        K = K + sp.csr_matrix((Ke.ravel(), (rows, cols)), shape=(n, n))
    return K


def source_vector(nodes, elements, Q: float, n: int) -> np.ndarray:
    """∫ Q N dV (uniform volumetric source, W/m³)."""
    et = tb.etype_of(elements)
    X = nodes[elements]
    nw = np.zeros((len(elements), tb.N_NODES[et]))
    for p, wg in zip(tb.GAUSS_TET4, tb.W_TET4):
        det, _ = tb._jac(X, tb.dshape(et, p))
        nw += (wg * det)[:, None] * tb.shape(et, p)[None, :]
    F = np.zeros(n)
    np.add.at(F, elements, nw * Q)
    return F


def convection_batch(nodes: np.ndarray, tris: np.ndarray, h: float):
    """Surface matrix ∫ h N Nᵀ dA (k,n,n) and ∫ N dA (k,n) with a degree-4 rule."""
    order = 1 if tris.shape[1] == 3 else 2
    X = nodes[tris]
    k, n = tris.shape
    M = np.zeros((k, n, n))
    NdA = np.zeros((k, n))
    for (r, s), wg in zip(TRI_D4, W_TRI_D4):
        t = np.einsum('an,knj->kaj', tb.dshape_tri(order, r, s), X)
        jac = np.linalg.norm(np.cross(t[:, 0], t[:, 1]), axis=1)
        N = tb.shape_tri(order, r, s)
        M += (wg * jac * h)[:, None, None] * np.outer(N, N)[None]
        NdA += (wg * jac)[:, None] * N[None]
    return M, NdA


# ── Global thermal problem ───────────────────────────────────────────────────

def assemble_thermal(mesh: FEMMesh, k: float, loads: list, info: list | None = None):
    """Global conductivity (+ convection) matrix and heat-load vector.

    Returns (K, F, conv) where ``conv`` lists (tris, h, T_inf) for the heat balance."""
    from app.design.services.fem.assembler import BoundaryConditionError, _face_tris
    if not k or k <= 0:
        raise ValueError('Conductividad térmica k no definida o no positiva (MATERIAL.k, W/m·K).')
    n = mesh.n_nodes
    K = assemble_Kt(mesh, k)
    F = np.zeros(n)
    conv = []
    for i, ld in enumerate(loads):
        meta = {'index': i, 'label': ld.get('label')}
        if 'heat_source' in ld:
            Fi = source_vector(mesh.nodes, mesh.elements, float(ld['heat_source']), n)
            meta['kind'] = 'heat_source'
            meta['heat_W'] = float(Fi.sum())
            F += Fi
        elif 'face_set' in ld:
            tris = _face_tris(mesh, ld['face_set'])
            if 'heat_flux' in ld:
                NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
                Fi = np.zeros(n)
                np.add.at(Fi, tris, NdA * float(ld['heat_flux']))
                meta.update(kind='heat_flux', area_m2=float(area.sum()), heat_W=float(Fi.sum()))
                F += Fi
            elif 'convection' in ld:
                c = ld['convection']
                h, Tinf = float(c.get('h', 0.0)), float(c.get('T_inf', 0.0))
                Me, NdA = convection_batch(mesh.nodes, tris, h)
                nd = tris.shape[1]
                K = K + sp.csr_matrix((Me.ravel(), (np.repeat(tris, nd, axis=1).ravel(),
                                                    np.tile(tris, (1, nd)).ravel())), shape=(n, n))
                np.add.at(F, tris, NdA * h * Tinf)
                conv.append((tris, h, Tinf))
                meta.update(kind='convection', area_m2=float(NdA.sum()), h=h, T_inf=Tinf)
            else:
                raise BoundaryConditionError(f'Carga térmica {i} sin tipo (heat_flux o convection).')
        else:
            raise BoundaryConditionError(f'Carga térmica {i}: heat_flux/convection necesitan face_set.')
        if info is not None:
            info.append(meta)
    return K.tocsr(), F, conv


def temperature_dirichlet(mesh: FEMMesh, bcs: list) -> tuple[np.ndarray, np.ndarray]:
    """Prescribed (nodes, T) from BC entries with ``temperature``; later entries win."""
    from app.design.services.fem.assembler import _face_tris, _node_set
    presc: dict[int, float] = {}
    for bc in bcs:
        nodes = np.unique(_face_tris(mesh, bc['face_set'])) if 'face_set' in bc \
            else _node_set(mesh, bc.get('node_set', ''))
        for nd in nodes:
            presc[int(nd)] = float(bc['temperature'])
    dofs = np.array(sorted(presc), dtype=np.int64)
    return dofs, np.array([presc[d] for d in dofs], float)


def convective_heat(mesh: FEMMesh, T: np.ndarray, conv: list) -> float:
    """Heat leaving through convective faces, ∫ h (T − T∞) dA [W]."""
    out = 0.0
    for tris, h, Tinf in conv:
        _, NdA = convection_batch(mesh.nodes, tris, h)
        out += float(h * np.sum(NdA * (T[tris] - Tinf)))
    return out


def heat_flux(nodes, elements, T: np.ndarray, k: float) -> tuple[np.ndarray, np.ndarray]:
    """q = −k ∇T: element mean (m,3) and nodal average (N,3) (T10 via Gauss points like stress)."""
    et = tb.etype_of(elements)
    X = nodes[elements]
    Te = T[elements]
    if et == 'T4':
        _, dN = tb._jac(X, tb.dshape('T4', (0.25,) * 3))
        elem = -k * np.einsum('man,mn->ma', dN, Te)
        per_node = np.repeat(elem[:, None], 4, axis=1)
    else:
        gp = np.stack([-k * np.einsum('man,mn->ma', tb._jac(X, tb.dshape(et, p))[1], Te)
                       for p in tb.GAUSS_TET4], axis=1)                      # (m,4,3)
        elem = gp.mean(axis=1)
        corners = np.einsum('cg,mgk->mck', tb._GP_TO_CORNER, gp)
        mids = (corners[:, tb.T10_EDGES[:, 0]] + corners[:, tb.T10_EDGES[:, 1]]) / 2
        per_node = np.concatenate([corners, mids], axis=1)
    acc = np.zeros((len(nodes), 3))
    cnt = np.zeros(len(nodes))
    for j in range(elements.shape[1]):
        np.add.at(acc, elements[:, j], per_node[:, j])
        np.add.at(cnt, elements[:, j], 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        nodal = np.where(cnt[:, None] > 0, acc / cnt[:, None], 0.0)
    return elem, nodal


# ── Thermo-mechanical coupling ───────────────────────────────────────────────

def thermal_strain_at(elements, T: np.ndarray, alpha: float, T_ref: float, p) -> np.ndarray:
    """ε_th (m,6) at natural point p."""
    et = tb.etype_of(elements)
    Tp = T[elements] @ tb.shape(et, p)
    return (alpha * (Tp - T_ref))[:, None] * VOIGT_M[None, :]


def thermal_load(mesh: FEMMesh, D: np.ndarray, T: np.ndarray, alpha: float, T_ref: float) -> np.ndarray:
    """Consistent structural load F = ∫ Bᵀ D ε_th dV (self-equilibrated)."""
    n_dof = mesh.n_dof_structural
    F = np.zeros(n_dof)
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        et = tb.etype_of(el)
        X = mesh.nodes[el]
        Fe = np.zeros((len(el), 3 * tb.N_NODES[et]))
        for p, wg in zip(*_gauss(et)):
            det, dN = tb._jac(X, tb.dshape(et, p))
            sig0 = thermal_strain_at(el, T, alpha, T_ref, p) @ D.T          # (m,6)
            Fe += (wg * det)[:, None] * np.einsum('mai,ma->mi', tb._B(dN), sig0)
        np.add.at(F, tb.element_dofs(el), Fe)
    return F
