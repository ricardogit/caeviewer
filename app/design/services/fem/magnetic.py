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
        self.curve = BHCurve(spec['bh_curve']) if spec.get('bh_curve') else None
        mu_r = spec.get('mu_r')
        if mu_r in (None, '') and self.curve is not None:      # saturating: μr = initial slope of the curve
            mu_r = self.curve.mu_r_initial
        if mu_r is None or float(mu_r) <= 0:
            raise ValueError('Material magnético: la permeabilidad relativa μr debe ser > 0.')
        self.mu_r = float(mu_r)
        br = spec.get('Br') or [0.0, 0.0, 0.0]
        self.Br = np.asarray([float(b) for b in br], float)
        if self.Br.shape != (3,):
            raise ValueError('Material magnético: Br debe ser un vector [Bx, By, Bz] en T.')
        if self.curve is not None and np.any(self.Br):
            raise ValueError('Material magnético: saturación (curva B-H) e imán permanente (Br) a la vez no están '
                             'soportados.')

    @property
    def mu(self) -> float:
        return MU0 * self.mu_r

    def to_dict(self) -> dict:
        d = {'mu_r': self.mu_r, 'Br': self.Br.tolist()}
        if self.curve is not None:
            d['bh_curve'] = self.curve.spec
        return d


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


# ── Saturation (non-linear B-H curve) and coil excitation ────────────────────

class BHCurve:
    """Anhysteretic, isotropic B(H) with B ∥ H: b(h) for h = |H| ≥ 0 and its derivative.

    ``{'model': 'tanh', 'mu_r': μr_initial, 'Js': saturation polarisation [T]}``:
        b = μ₀h + Js·tanh(μ₀(μr − 1)h / Js)   (initial slope μ₀μr, tends to Js + μ₀h)
    ``{'model': 'table', 'points': [[H [A/m], B [T]], …]}``: monotone C¹ PCHIP through (0, 0) and the points,
        continued with slope μ₀ after the last point (fully saturated: only the vacuum part grows)."""

    def __init__(self, spec: dict):
        model = spec.get('model', 'tanh')
        if model == 'tanh':
            self.mu_r, self.Js = float(spec.get('mu_r') or 0), float(spec.get('Js') or 0)
            if self.mu_r <= 1 or self.Js <= 0:
                raise ValueError('Curva B-H: el modelo de saturación necesita μr inicial > 1 y polarización de '
                                 'saturación Js > 0 (T).')
            self.c = MU0 * (self.mu_r - 1) / self.Js
            self.model = 'tanh'
            self.spec = {'model': 'tanh', 'mu_r': self.mu_r, 'Js': self.Js}
        elif model == 'table':
            from scipy.interpolate import PchipInterpolator
            pts = sorted((float(h), float(b)) for h, b in (spec.get('points') or []) if float(h) > 0)
            if len(pts) < 2:
                raise ValueError('Curva B-H: la tabla necesita al menos 2 puntos (H > 0, B).')
            H = np.array([0.0] + [p[0] for p in pts])
            B = np.array([0.0] + [p[1] for p in pts])
            if np.any(np.diff(H) <= 0) or np.any(np.diff(B) <= 0):
                raise ValueError('Curva B-H: H y B deben crecer estrictamente (sin puntos repetidos).')
            if np.any(B[1:] / H[1:] < MU0 * (1 - 1e-9)):
                raise ValueError('Curva B-H: B/H < μ₀ en algún punto (permeabilidad relativa < 1).')
            self.H, self.B = H, B
            self.p = PchipInterpolator(H, B, extrapolate=False)
            self.dp = self.p.derivative()
            self.ip = self.p.antiderivative()
            self.model = 'table'
            self.spec = {'model': 'table', 'points': [[float(h), float(b)] for h, b in zip(H[1:], B[1:])]}
        else:
            raise ValueError(f'Curva B-H: modelo desconocido {model!r} (tanh | table).')

    def b(self, h):
        h = np.asarray(h, float)
        if self.model == 'tanh':
            return MU0 * h + self.Js * np.tanh(self.c * h)
        Hm = self.H[-1]
        return np.where(h <= Hm, self.p(np.minimum(h, Hm)), self.B[-1] + MU0 * (h - Hm))

    def db(self, h):
        h = np.asarray(h, float)
        if self.model == 'tanh':
            return MU0 + self.Js * self.c / np.cosh(np.minimum(self.c * h, 350.0)) ** 2
        Hm = self.H[-1]
        return np.where(h <= Hm, self.dp(np.minimum(h, Hm)), MU0)

    def coenergy_density(self, h):
        """∫₀ʰ b dh [J/m³]."""
        h = np.asarray(h, float)
        if self.model == 'tanh':
            x = np.abs(self.c * h)
            lncosh = x + np.log1p(np.exp(-2 * x)) - np.log(2.0)
            return 0.5 * MU0 * h ** 2 + self.Js / self.c * lncosh
        Hm = self.H[-1]
        tail = np.maximum(h - Hm, 0)
        return np.where(h <= Hm, self.ip(np.minimum(h, Hm)),
                        self.ip(Hm) + self.B[-1] * tail + 0.5 * MU0 * tail ** 2)

    @property
    def mu_r_initial(self) -> float:
        return float(self.db(0.0) / MU0)

    def ratio(self, h):
        """b(h)/h, = b'(0) at h = 0."""
        h = np.asarray(h, float)
        small = h < 1e-12
        hs = np.where(small, 1.0, h)
        return np.where(small, self.db(0.0), self.b(hs) / hs)


def is_coil(bc: dict) -> bool:
    return isinstance(bc.get('coil'), dict)


def nonlinear_system(mesh: FEMMesh, curve: BHCurve, psi: np.ndarray, tangent: bool = True):
    """Internal flux vector Fint = ∫ ∇Nᵀ(−B)/μ₀ dV (B = b(|H|)Ĥ, H = −∇ψ), tangent K_t = ∂Fint/∂ψ (CSR or
    None), field energy W = ∫(hb − ∫b dh) dV and co-energy W' = ∫∫b dh dV [J]."""
    n = mesh.n_nodes
    et = tb.etype_of(mesh.elements)
    pts, wts = th._gauss(et)
    Fint = np.zeros(n)
    rows, cols, vals = [], [], []
    W = Wc = 0.0
    eye = np.eye(3)
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        X = mesh.nodes[el]
        pe = psi[el]
        nd = el.shape[1]
        fe = np.zeros((len(el), nd))
        Ke = np.zeros((len(el), nd, nd)) if tangent else None
        for p, wg in zip(pts, wts):
            det, dN = tb._jac(X, tb.dshape(et, p))                    # dN (m,3,n)
            w = wg * det
            Hv = -np.einsum('man,mn->ma', dN, pe)
            h = np.linalg.norm(Hv, axis=1)
            r = curve.ratio(h)
            fe -= (w * r / MU0)[:, None] * np.einsum('man,ma->mn', dN, Hv)     # ∫∇N·(−B)/μ₀
            wc = curve.coenergy_density(h)
            Wc += float((w * wc).sum())
            W += float((w * (h * curve.b(h) - wc)).sum())
            if tangent:
                hat = Hv / np.maximum(h, 1e-300)[:, None]
                T = (r[:, None, None] * eye[None] + (curve.db(h) - r)[:, None, None]
                     * np.einsum('ma,mb->mab', hat, hat)) / MU0
                Ke += w[:, None, None] * np.einsum('mai,mab,mbj->mij', dN, T, dN)
        np.add.at(Fint, el, fe)
        if tangent:
            rows.append(np.repeat(el, nd, axis=1).ravel())
            cols.append(np.tile(el, (1, nd)).ravel())
            vals.append(Ke.ravel())
    Kt = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)) \
        if tangent else None
    return Fint, Kt, W, Wc


def solve_nonlinear(mesh: FEMMesh, curve: BHCurve, bcs: list, loads: list, psi0=None, linear_solve=None,
                    tol: float = 1e-10, max_iter: int = 40):
    """Saturating magnetostatics: Newton with backtracking on Fint(ψ) = F, Dirichlet ψ from ``bcs``. If the
    full step fails, the excitation (prescribed ψ and imposed flux) is ramped in 2, 4, 8, 16 sub-steps.
    ``psi0`` (e.g. the previous point of a current sweep) is the starting guess.
    Returns ψ, info {residual, newton_iterations, residuals, substeps, flux_in_Wb, loads, energy_J, coenergy_J}."""
    import scipy.sparse.linalg as spla
    from app.design.services.fem.assembler import BoundaryConditionError
    n = mesh.n_nodes
    load_info: list = []
    lin_mat = MagneticMaterial({'mu_r': curve.mu_r_initial})
    K0, F = assemble(mesh, lin_mat, loads, load_info)
    dofs, vals, groups = potential_dirichlet(mesh, bcs)
    if not len(dofs):
        raise BoundaryConditionError('Magnético con saturación: hace falta al menos una cara con potencial '
                                     'magnético (referencia).')
    free = np.setdiff1d(np.arange(n), dofs)

    def lsolve(K, r):
        Kf = K[free][:, free]
        return linear_solve(Kf, r) if linear_solve is not None else spla.spsolve(sp.csc_matrix(Kf), r)

    def newton(psi, lam):
        psi = psi.copy()
        psi[dofs] = lam * vals
        hist = []
        Fl = lam * F
        for _ in range(max_iter):
            Fint, Kt, _, _ = nonlinear_system(mesh, curve, psi)
            R = Fint - Fl
            scale = max(np.linalg.norm(Fl), np.linalg.norm(Fint[dofs]), 1e-300)
            rn = float(np.linalg.norm(R[free]) / scale)
            hist.append(rn)
            if rn < tol:
                return psi, hist, True
            d = np.zeros(n)
            d[free] = lsolve(Kt, -R[free])
            alpha, r0 = 1.0, float(np.linalg.norm(R[free]))
            for _ in range(8):
                trial = psi + alpha * d
                Rt = nonlinear_system(mesh, curve, trial, tangent=False)[0] - Fl
                if float(np.linalg.norm(Rt[free])) < (1 - 1e-4 * alpha) * r0:
                    break
                alpha *= 0.5
            psi = trial
        return psi, hist, False

    if psi0 is None:                                     # linear start at the initial permeability
        start = np.zeros(n)
        start[dofs] = vals
        start[free] = lsolve(K0, (F - K0 @ start)[free])
    else:                                                # tangent predictor from the previous state (sweep)
        start = np.asarray(psi0, float).copy()
        Kt = nonlinear_system(mesh, curve, start)[1]
        delta = np.zeros(n)
        delta[dofs] = vals - start[dofs]
        start[dofs] = vals
        start[free] += lsolve(Kt, -(Kt @ delta)[free])
    history, ok, steps = [], False, 1
    for steps in (1, 2, 4, 8, 16):
        psi = start.copy()
        for k in range(1, steps + 1):
            psi, hist, ok = newton(psi, k / steps)
            history += hist
            if not ok:
                break
        if ok:
            break
    if not ok:
        raise ValueError('Magnético con saturación: Newton no converge ni con 16 subpasos de excitación. '
                         'Revise la curva B-H (monótona, sin saltos) y la excitación.')
    Fint, _, W, Wc = nonlinear_system(mesh, curve, psi, tangent=False)
    R = Fint - F
    flux_in = [float(MU0 * R[g].sum()) for g in groups]
    return psi, {'pinned': False, 'residual': history[-1], 'newton_iterations': len(history),
                 'residuals': history, 'substeps': steps, 'flux_in_Wb': flux_in, 'loads': load_info,
                 'energy_J': W, 'coenergy_J': Wc}


def fields_nonlinear(mesh: FEMMesh, psi: np.ndarray, curve: BHCurve):
    """Nodal H [A/m] and B = b(|H|)Ĥ [T]."""
    _, H = th.heat_flux(mesh.nodes, mesh.elements, psi, 1.0)
    return H, curve.ratio(np.linalg.norm(H, axis=1))[:, None] * H


def differential_permeance(mesh: FEMMesh, psi: np.ndarray, bcs: list, index: int, curve: BHCurve | None = None,
                           mat: MagneticMaterial | None = None, linear_solve=None) -> float:
    """dΦ/dMMF [H] of pole ``index`` at the state ψ: the tangent problem with δψ = 1 on that pole's faces and 0
    on the other prescribed faces. Incremental inductance of a coil = N² · this (secant = N²Φ/(NI))."""
    import scipy.sparse.linalg as spla
    if curve is not None:
        Kt = nonlinear_system(mesh, curve, psi)[1]
    else:
        Kt = assemble(mesh, mat, [])[0]
    dofs, _, groups = potential_dirichlet(mesh, bcs)
    n = mesh.n_nodes
    d = np.zeros(n)
    d[groups[index]] = 1.0
    free = np.setdiff1d(np.arange(n), dofs)
    Kf = Kt[free][:, free]
    r = -(Kt @ d)[free]
    d[free] = linear_solve(Kf, r) if linear_solve is not None else spla.spsolve(sp.csc_matrix(Kf), r)
    return float(MU0 * (Kt @ d)[groups[index]].sum())
