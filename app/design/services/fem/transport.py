"""Advection–diffusion–reaction transport of dissolved species (FASE 10.1 + 10.2, 3D).

For species s = 1..ns on T4/T10, with a given velocity field v (uniform, or the nodal field of a fluid run):

    ∂c_s/∂t + v·∇c_s − D_s Δc_s + Σ_r R_sr c_r = S_s          in Ω

R = linear reaction matrix: first-order decay λ_s on the diagonal plus conversions i → j (``reactions``) and the
Streeter–Phelps preset (BOD decays with kd into dissolved-oxygen deficit, which reaerates with ka).

Weak form (non-conservative advection: with ∇·v = 0 the net advective outflow is ∮ c v·n dA), with SUPG
(consistent streamline-upwind test function w + τ v·∇w applied to the whole residual: storage, advection,
−DΔc (straight T10, exact second derivatives), reaction and volumetric sources):

    τ_e = ((2|v|/h̃)² + (12 D/h̃²)² + λ²)^(-1/2),  h̃ = h (T4) or h/2 (T10),
    h = 2|v| / Σ_a |v·∇L_a| (streamline element length over the corner functions, Tezduyar's h_UGN)

τ has no 1/Δt term (it would make the stabilisation depend on the time step). SUPG is opt-out (``'none'``).

Conditions (same ``bcs``/``loads`` lists as the other physics, recognised by key; each may carry ``species``
(index or name, default 0) and ``history`` [[t, factor], …] (piecewise linear, constant outside)):
    BC   ``concentration`` c̄ on ``face_set``/``node_set`` (inlet / fixed concentration)
    load ``species_flux`` q [c·m/s] into the body on ``face_set``
         ``exchange`` {k [m/s], c_ext} on ``face_set``: flux k (c_ext − c) into the body (atmosphere / bed)
         ``species_source`` S [c/s] uniform in the volume
         ``point_source`` {point [m], rate [c·m³/s]} (discharge of mass per second; a Dirac at the point)
Free faces: zero diffusive flux (∂c/∂n = 0): an outlet where the flow leaves.

Time: ``time`` {t_end, n_steps, scheme 'bdf2' (default) | 'cn' | 'be' | 'theta' (+ theta), n_output}; without
``time`` the steady problem is solved. Fixed Δt; the matrix is factorised once.

Porous medium (FASE 10.6, material ``porous`` {porosity n_e, alpha_L, alpha_T} + per species ``retardation`` R ≥ 1;
v = pore velocity, e.g. of a Darcy run): n_e R ∂c/∂t + n_e v·∇c − ∇·(n_e 𝔻∇c) + n_e R λ c = S, with the
Bear–Scheidegger dispersion 𝔻 = (D_m + α_T|v|) I + (α_L − α_T) v vᵀ/|v| (D_m = species D, pore-water diffusion);
decay and conversions act on the dissolved + sorbed mass. SUPG: the same test function with τ from |v|, the
longitudinal 𝔻_L = D_m + α_L|v| and Rλ (= τ of the equation divided by n_e R, rescaled). Sources / fluxes are per
bulk volume / area; masses are total (dissolved + sorbed) m = ∫ n_e R c dV.

Mass balance: m = ∫c dV (consistent mass; the SUPG mass rows sum to zero). The budget terms (sources, mass entering
through the fixed-concentration nodes = their reactions, advective outflow, exchange, reaction) are integrated with
the same weights as the time scheme, so m(t_end) − m(0) − Σ terms is round-off: any visible error is a bug.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.mesh import FEMMesh

BC_KEYS = ('concentration',)
LOAD_KEYS = ('species_flux', 'exchange', 'species_source', 'point_source')
SCHEMES = ('bdf2', 'cn', 'be', 'theta')
DIRECT_MAX = 300_000              # unknowns (species × nodes) solved with a sparse LU, above: ILU-GMRES


def is_transport_bc(bc: dict) -> bool:
    return 'concentration' in bc


def is_transport_load(ld: dict) -> bool:
    return any(k in ld for k in LOAD_KEYS)


def mass_unit(unit: str) -> str:
    return {'mg/L': 'g', 'g/m³': 'g', 'g/m3': 'g', 'kg/m³': 'kg', 'kg/m3': 'kg', 'µg/L': 'mg', 'ug/L': 'mg'}.get(
        unit, f'{unit}·m³')


# ── Model ─────────────────────────────────────────────────────────────────────

class TransportModel:
    """Species, diffusivities, reaction matrix, stabilisation and (optionally uniform) velocity."""

    def __init__(self, spec: dict):
        sp_list = spec.get('species') or [{'name': 'c'}]
        self.species = []
        for i, s in enumerate(sp_list):
            D = float(s.get('D', 0.0) or 0.0)
            lam = float(s.get('decay', 0.0) or 0.0)
            if D < 0 or lam < 0:
                raise ValueError(f'Especie {s.get("name") or i}: la difusividad D y el decaimiento λ deben ser ≥ 0.')
            Rt = float(s.get('retardation', 1.0) or 1.0)
            if Rt < 1:
                raise ValueError(f'Especie {s.get("name") or i}: el factor de retardo R debe ser ≥ 1.')
            self.species.append({'name': str(s.get('name') or f'c{i + 1}'), 'D': D, 'decay': lam,
                                 'unit': s.get('unit') or 'mg/L', 'threshold': s.get('threshold'),
                                 'retardation': Rt})
        ns = len(self.species)
        R = np.diag([s['decay'] for s in self.species])
        for r in spec.get('reactions') or []:
            i, j = self.index(r['from']), self.index(r['to'])
            k = float(r['rate'])
            if k < 0 or i == j:
                raise ValueError('Reacción: tasa ≥ 0 entre dos especies distintas.')
            R[i, i] += k
            R[j, i] -= float(r.get('yield', 1.0)) * k
        self.streeter_phelps = None
        rx = spec.get('reaction')
        if rx:
            if rx.get('model') != 'streeter_phelps':
                raise ValueError(f'Reacción desconocida {rx.get("model")!r} (streeter_phelps).')
            if ns != 2:
                raise ValueError('Streeter–Phelps necesita exactamente dos especies: DBO y déficit de oxígeno.')
            kd, ka = float(rx['kd']), float(rx['ka'])
            if kd <= 0 or ka <= 0:
                raise ValueError('Streeter–Phelps: kd y ka deben ser > 0 (1/s).')
            R[0, 0] += kd
            R[1, 0] -= kd
            R[1, 1] += ka
            self.streeter_phelps = {'kd': kd, 'ka': ka, 'do_sat': float(rx.get('do_sat', 0.0) or 0.0)}
        self.R = R
        por = spec.get('porous')
        self.porous = None
        if por:
            ne = float(por.get('porosity', 0.0) or 0.0)
            aL, aT = float(por.get('alpha_L', 0.0) or 0.0), float(por.get('alpha_T', 0.0) or 0.0)
            if not 0 < ne <= 1 or aL < 0 or aT < 0:
                raise ValueError('Medio poroso: porosidad eficaz en (0, 1] y dispersividades α_L, α_T ≥ 0 (m).')
            self.porous = {'porosity': ne, 'alpha_L': aL, 'alpha_T': aT}
        elif any(sp_['retardation'] != 1.0 for sp_ in self.species):
            raise ValueError('El retardo por adsorción solo se aplica en un medio poroso (porous).')
        ne = self.porous['porosity'] if self.porous else 1.0
        self.phi = ne                                                  # advection / dispersion coefficient
        self.cap = np.array([ne * sp_['retardation'] for sp_ in self.species])   # storage coefficient n_e R
        stab = spec.get('stabilization', 'supg')
        if stab not in ('supg', 'none'):
            raise ValueError(f'Estabilización desconocida {stab!r} (supg | none).')
        self.stabilization = stab
        v = spec.get('velocity')
        self.velocity = np.asarray(v, float) if isinstance(v, (list, tuple, np.ndarray)) else None
        if self.velocity is not None and self.velocity.shape != (3,):
            raise ValueError('Velocidad uniforme: [vx, vy, vz] en m/s.')

    @property
    def n_species(self) -> int:
        return len(self.species)

    def index(self, key) -> int:
        if key is None:
            return 0
        if isinstance(key, (int, float)) and not isinstance(key, bool):
            i = int(key)
        else:
            names = [s['name'] for s in self.species]
            if key not in names:
                raise ValueError(f'Especie {key!r} desconocida ({", ".join(names)}).')
            i = names.index(key)
        if not 0 <= i < self.n_species:
            raise ValueError(f'Especie {key} fuera de rango (hay {self.n_species}).')
        return i


def nodal_velocity(mesh: FEMMesh, model: TransportModel, v=None) -> np.ndarray:
    if v is not None:
        v = np.asarray(v, float)
        if v.shape != (mesh.n_nodes, 3):
            raise ValueError(f'Campo de velocidad con forma {v.shape}; se esperaba ({mesh.n_nodes}, 3).')
        return v
    if model.velocity is None:
        return np.zeros((mesh.n_nodes, 3))
    return np.broadcast_to(model.velocity, (mesh.n_nodes, 3)).copy()


# ── Element operators ─────────────────────────────────────────────────────────

def _rule():
    from app.design.services.fem.error_estimator import QUAD_PTS, QUAD_W     # 14 points, degree 5
    return QUAD_PTS, QUAD_W


def _corner_geometry(nodes, el):
    Xc = nodes[el[:, :4]]
    _, gL = tb._jac(Xc, tb.dshape('T4', (0.25, 0.25, 0.25)))                # ∇L_a (m,3,4), constant
    return Xc, gL


def _laplacian(gL, et):
    """ΔN_j on straight elements (m,n): 0 for T4; T10 corners 4|∇L_i|², mids 8 ∇L_i·∇L_j."""
    m = gL.shape[0]
    if et == 'T4':
        return np.zeros((m, 4))
    lap = np.zeros((m, 10))
    for i in range(4):
        lap[:, i] = 4.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, i])
    for e_, (i, j) in enumerate(tb.T10_EDGES):
        lap[:, 4 + e_] = 8.0 * np.einsum('ma,ma->m', gL[:, :, i], gL[:, :, j])
    return lap


def dispersion_tensor(v: np.ndarray, aL: float, aT: float) -> np.ndarray:
    """Mechanical dispersion α_T|v| I + (α_L − α_T) v vᵀ/|v| for v (…,3) → (…,3,3) (molecular part excluded)."""
    vn = np.linalg.norm(v, axis=-1)
    with np.errstate(invalid='ignore', divide='ignore'):
        vv = np.where(vn[..., None, None] > 0, v[..., :, None] * v[..., None, :] / vn[..., None, None], 0.0)
    return aT * vn[..., None, None] * np.eye(3) + (aL - aT) * vv


def _hessian_contract(gL, et, Dt):
    """𝔻:∇∇N_j on straight elements (m,n) for element tensors Dt (m,3,3): T10 corners 4 ∇L_iᵀ𝔻∇L_i, mids
    8 ∇L_iᵀ𝔻∇L_j; 0 for T4."""
    m = gL.shape[0]
    if et == 'T4':
        return np.zeros((m, 4))
    out = np.zeros((m, 10))
    DgL = np.einsum('mab,mbk->mak', Dt, gL)
    for i in range(4):
        out[:, i] = 4.0 * np.einsum('ma,ma->m', gL[:, :, i], DgL[:, :, i])
    for e_, (i, j) in enumerate(tb.T10_EDGES):
        out[:, 4 + e_] = 8.0 * np.einsum('ma,ma->m', gL[:, :, i], DgL[:, :, j])
    return out


def element_size(nodes, el, v_c: np.ndarray, gL: np.ndarray) -> np.ndarray:
    """Streamline length h_UGN = 2|v| / Σ|v·∇L_a| (longest corner edge where v = 0)."""
    Xc = nodes[el[:, :4]]
    hmax = np.max([np.linalg.norm(Xc[:, i] - Xc[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)], axis=0)
    vn = np.linalg.norm(v_c, axis=1)
    s = np.abs(np.einsum('ma,mak->mk', v_c, gL)).sum(1)
    with np.errstate(divide='ignore', invalid='ignore'):
        h = np.where((vn > 0) & (s > 0), 2.0 * vn / s, hmax)
    return h


def tau_supg(vn, h_t, D, lam):
    """τ = ((2|v|/h̃)² + (12D/h̃²)² + λ²)^(-1/2); 0 where everything vanishes."""
    den = (2 * vn / h_t) ** 2 + (12.0 * D / h_t ** 2) ** 2 + lam ** 2
    with np.errstate(divide='ignore'):
        return np.where(den > 0, 1.0 / np.sqrt(den), 0.0)


def assemble_operators(mesh: FEMMesh, model: TransportModel, v: np.ndarray):
    """Global matrices: M (mass), A (advection), K (∫∇N·∇N), and per species the SUPG matrices
    P_s = ∫τ(v·∇N_i)N_j (mass/reaction/source perturbation), Q_s = ∫τ(v·∇N_i)(v·∇N_j − D_s ΔN_j).
    Porous: also Kd = ∫∇N_iᵀ 𝔻_mech ∇N_j (dispersion at the quadrature points) and Q_s gets −𝔻_e:∇∇N_j (element-
    centroid tensor, straight geometry); τ_s uses 𝔻_L = D_s + α_L|v| and R_s λ_s.
    Also element stats (h, |v|, Péclet, Courant ingredients)."""
    n = mesh.n_nodes
    et = mesh.element_type
    pts, wts = _rule()
    ns = model.n_species
    supg = model.stabilization == 'supg'
    rows_all, cols_all = [], []
    por = model.porous
    vals = {k: [] for k in (('M', 'A', 'K', 'Kd') if por else ('M', 'A', 'K'))}
    for s in range(ns):
        vals[f'P{s}'] = []
        vals[f'Q{s}'] = []
    h_all, vn_all = [], []
    for a in range(0, mesh.n_elements, 8000):
        el = mesh.elements[a:a + 8000]
        m, nd = el.shape
        X = mesh.nodes[el]
        ve = v[el]                                                              # (m,n,3)
        _, gL = _corner_geometry(mesh.nodes, el)
        v_c = ve[:, :4].mean(1) if et == 'T4' else np.einsum('n,mnc->mc', tb.shape(et, (0.25,) * 3), ve)
        h = element_size(mesh.nodes, el, v_c, gL)
        vn = np.linalg.norm(v_c, axis=1)
        h_all.append(h)
        vn_all.append(vn)
        h_t = h if et == 'T4' else 0.5 * h
        lap = _laplacian(gL, et)
        if por:
            Dc = dispersion_tensor(v_c, por['alpha_L'], por['alpha_T'])
            hes = _hessian_contract(gL, et, Dc)
            Kde = np.zeros((m, nd, nd))
            AHe = np.zeros((m, nd, nd))
        Me = np.zeros((m, nd, nd))
        Ae = np.zeros((m, nd, nd))
        Ke = np.zeros((m, nd, nd))
        Pe = np.zeros((m, nd, nd))
        AAe = np.zeros((m, nd, nd))
        ALe = np.zeros((m, nd, nd))
        for p, wg in zip(pts, wts):
            det, dN = tb._jac(X, tb.dshape(et, p))
            N = tb.shape(et, p)
            w = wg * det
            vq = np.einsum('n,mnc->mc', N, ve)
            adv = np.einsum('mc,mcj->mj', vq, dN)                               # v·∇N_j
            Me += w[:, None, None] * np.outer(N, N)[None]
            Ae += w[:, None, None] * N[None, :, None] * adv[:, None, :]
            Ke += w[:, None, None] * np.einsum('mci,mcj->mij', dN, dN)
            if por:
                Dq = dispersion_tensor(vq, por['alpha_L'], por['alpha_T'])
                Kde += w[:, None, None] * np.einsum('mci,mcj->mij', dN, np.einsum('mcd,mdj->mcj', Dq, dN))
                if supg:
                    AHe += w[:, None, None] * adv[:, :, None] * hes[:, None, :]
            if supg:
                Pe += w[:, None, None] * adv[:, :, None] * N[None, None, :]
                AAe += w[:, None, None] * adv[:, :, None] * adv[:, None, :]
                ALe += w[:, None, None] * adv[:, :, None] * lap[:, None, :]
        rows_all.append(np.repeat(el, nd, axis=1).ravel())
        cols_all.append(np.tile(el, (1, nd)).ravel())
        vals['M'].append(Me.ravel())
        vals['A'].append(Ae.ravel())
        vals['K'].append(Ke.ravel())
        if por:
            vals['Kd'].append(Kde.ravel())
        for s, spc in enumerate(model.species):
            if supg:
                tau = tau_supg(vn, h_t, species_DL(model, s, vn), spc['retardation'] * model.R[s, s])
                vals[f'P{s}'].append((tau[:, None, None] * Pe).ravel())
                Qe = AAe - spc['D'] * ALe - (AHe if por else 0.0)
                vals[f'Q{s}'].append((tau[:, None, None] * Qe).ravel())
            else:
                vals[f'P{s}'].append(np.zeros(Me.size))
                vals[f'Q{s}'].append(np.zeros(Me.size))
    rows = np.concatenate(rows_all)
    cols = np.concatenate(cols_all)
    ops = {k: sp.csr_matrix((np.concatenate(vs), (rows, cols)), shape=(n, n)) for k, vs in vals.items()}
    ops['h'] = np.concatenate(h_all)
    ops['vn'] = np.concatenate(vn_all)
    ops['h_tilde'] = ops['h'] if et == 'T4' else 0.5 * ops['h']
    # size of the equilateral tet with the same volume: robust to slivers (h_UGN of a sliver can be tiny), used
    # for the reported Péclet / Courant numbers (not for τ)
    ops['h_vol'] = np.cbrt(6.0 * np.sqrt(2.0) * tb.volumes(mesh.nodes, mesh.elements[:, :4]))
    return ops


def species_DL(model: TransportModel, s: int, vn):
    """Longitudinal diffusivity D_s + α_L|v| (just D_s without a porous medium)."""
    D = model.species[s]['D']
    return D + model.porous['alpha_L'] * vn if model.porous else D


def supg_source_vector(mesh: FEMMesh, v: np.ndarray, tau: np.ndarray) -> np.ndarray:
    """∫ τ (v·∇N_i) dV per node (SUPG part of a uniform unit volumetric source)."""
    et = mesh.element_type
    pts, wts = _rule()
    F = np.zeros(mesh.n_nodes)
    for a in range(0, mesh.n_elements, 8000):
        el = mesh.elements[a:a + 8000]
        X = mesh.nodes[el]
        ve = v[el]
        fe = np.zeros(el.shape)
        for p, wg in zip(pts, wts):
            det, dN = tb._jac(X, tb.dshape(et, p))
            vq = np.einsum('n,mnc->mc', tb.shape(et, p), ve)
            fe += (wg * det)[:, None] * np.einsum('mc,mcj->mj', vq, dN)
        np.add.at(F, el, tau[a:a + 8000, None] * fe)
    return F


def lumped_volume(mesh: FEMMesh) -> np.ndarray:
    """∫ N_i dV (consistent), used for the uniform source and volume above a threshold."""
    from app.design.services.fem.thermal import source_vector
    return source_vector(mesh.nodes, mesh.elements, 1.0, mesh.n_nodes)


# ── Point location (point sources, probes) ────────────────────────────────────

def locate(mesh: FEMMesh, points) -> list[dict]:
    """Containing element and natural coordinates (corner barycentrics; exact on straight elements).
    A point outside the mesh goes to the nearest element (``inside`` False, ``distance_m`` > 0)."""
    from scipy.spatial import cKDTree
    P = np.atleast_2d(np.asarray(points, float))
    Xc = mesh.nodes[mesh.elements[:, :4]]
    cent = Xc.mean(1)
    tree = cKDTree(cent)
    k = min(48, mesh.n_elements)
    out = []
    for p in P:
        _, cand = tree.query(p, k=k)
        cand = np.atleast_1d(cand)
        J = np.stack([Xc[cand, 1] - Xc[cand, 0], Xc[cand, 2] - Xc[cand, 0], Xc[cand, 3] - Xc[cand, 0]], axis=2)
        nat = np.linalg.solve(J, (p - Xc[cand, 0])[:, :, None])[:, :, 0]
        bary = np.column_stack([1 - nat.sum(1), nat])
        score = bary.min(1)
        b = int(np.argmax(score))
        inside = bool(score[b] >= -1e-9)
        nat_b = nat[b]
        if not inside:                                  # clamp into the element
            bc = np.clip(bary[b], 0, None)
            bc /= bc.sum()
            nat_b = bc[1:]
        e = int(cand[b])
        X_e = mesh.nodes[mesh.elements[e]]
        x = tb.shape(mesh.element_type, nat_b) @ X_e
        out.append({'element': e, 'nat': nat_b, 'inside': inside, 'distance_m': float(np.linalg.norm(x - p))})
    return out


def interpolate(mesh: FEMMesh, c: np.ndarray, loc: dict) -> float:
    el = mesh.elements[loc['element']]
    return float(tb.shape(mesh.element_type, loc['nat']) @ c[el])


# ── Histories ─────────────────────────────────────────────────────────────────

def history_factor(hist, t: float) -> float:
    if not hist:
        return 1.0
    h = np.asarray(hist, float)
    if h.ndim != 2 or h.shape[1] != 2 or np.any(np.diff(h[:, 0]) < 0):
        raise ValueError('Serie temporal: [[t, factor], …] con t creciente.')
    return float(np.interp(t, h[:, 0], h[:, 1]))


# ── Problem assembly ─────────────────────────────────────────────────────────

class _Problem:
    """Block operators of the full multi-species problem (unknown order: species-major, x[s·N + i])."""

    def __init__(self, mesh: FEMMesh, model: TransportModel, v: np.ndarray, bcs: list, loads: list):
        from app.design.services.fem.assembler import BoundaryConditionError, _face_tris, _node_set
        from app.design.services.fem.thermal import convection_batch
        self.mesh, self.model, self.v = mesh, model, v
        n, ns = mesh.n_nodes, model.n_species
        self.n, self.ns = n, ns
        ops = assemble_operators(mesh, model, v)
        self.ops = ops
        M, A, K = ops['M'], ops['A'], ops['K']
        Wb = [M + ops[f'P{s}'] for s in range(ns)]                   # storage / reaction test operator
        C = [A + model.species[s]['D'] * K + ops[f'Q{s}'] for s in range(ns)]
        if model.porous:                                             # n_e (advection + dispersion), n_e R storage
            C = [model.phi * (C[s] + ops['Kd']) for s in range(ns)]
            W = [model.cap[s] * Wb[s] for s in range(ns)]
        else:
            W = Wb
        self.Kex = [sp.csr_matrix((n, n)) for _ in range(ns)]
        # loads: (species, vector, history, kind, meta)
        self.load_terms = []
        self.info = []
        vol = None
        for i, ld in enumerate(loads):
            s = model.index(ld.get('species'))
            meta = {'index': i, 'label': ld.get('label'), 'species': model.species[s]['name']}
            Fi = np.zeros(n)
            if 'species_source' in ld:
                S = float(ld['species_source'])
                if vol is None:
                    vol = lumped_volume(mesh)
                Fi = S * vol
                if model.stabilization == 'supg':
                    tau = tau_supg(ops['vn'], ops['h_tilde'], species_DL(model, s, ops['vn']),
                                   model.species[s]['retardation'] * model.R[s, s])
                    Fi = Fi + S * supg_source_vector(mesh, v, tau)
                meta.update(kind='species_source', rate=S)
            elif 'point_source' in ld:
                ps = ld['point_source']
                loc = locate(mesh, [ps['point']])[0]
                if not loc['inside']:
                    raise BoundaryConditionError(f'Fuente puntual {i}: el punto {ps["point"]} está fuera de la malla.')
                e = loc['element']
                el = mesh.elements[e]
                wtest = tb.shape(mesh.element_type, loc['nat'])
                if model.stabilization == 'supg':      # consistent: the residual contains −Q δ(x − x_s) too
                    _, dN = tb._jac(mesh.nodes[el][None], tb.dshape(mesh.element_type, loc['nat']))
                    vq = wtest @ v[el]
                    tau = tau_supg(ops['vn'][e:e + 1], ops['h_tilde'][e:e + 1],
                                   species_DL(model, s, ops['vn'][e:e + 1]),
                                   model.species[s]['retardation'] * model.R[s, s])[0]
                    wtest = wtest + tau * (vq @ dN[0])
                np.add.at(Fi, el, float(ps['rate']) * wtest)
                meta.update(kind='point_source', rate=float(ps['rate']), point=list(map(float, ps['point'])))
            elif 'face_set' in ld:
                tris = _face_tris(mesh, ld['face_set'])
                if 'species_flux' in ld:
                    NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
                    np.add.at(Fi, tris, NdA * float(ld['species_flux']))
                    meta.update(kind='species_flux', flux=float(ld['species_flux']), area_m2=float(area.sum()))
                elif 'exchange' in ld:
                    ex = ld['exchange']
                    k, cext = float(ex.get('k', 0.0)), float(ex.get('c_ext', 0.0))
                    if k < 0:
                        raise BoundaryConditionError(f'Intercambio {i}: k ≥ 0 (m/s).')
                    Me, NdA = convection_batch(mesh.nodes, tris, k)
                    nd = tris.shape[1]
                    self.Kex[s] = self.Kex[s] + sp.csr_matrix(
                        (Me.ravel(), (np.repeat(tris, nd, axis=1).ravel(), np.tile(tris, (1, nd)).ravel())),
                        shape=(n, n))
                    np.add.at(Fi, tris, NdA * k * cext)
                    meta.update(kind='exchange', k=k, c_ext=cext, area_m2=float(NdA.sum()))
                else:
                    raise BoundaryConditionError(f'Carga de transporte {i} sin tipo.')
            else:
                raise BoundaryConditionError(f'Carga de transporte {i}: flujo / intercambio necesitan caras.')
            self.load_terms.append((s, Fi, ld.get('history')))
            self.info.append(meta)
        R = model.R
        blocks_S = [[None] * ns for _ in range(ns)]
        blocks_W = [[None] * ns for _ in range(ns)]
        for s in range(ns):
            for r in range(ns):
                Bs = (C[s] + self.Kex[s]) if s == r else None
                if R[s, r] != 0:                       # reaction of species r's total mass, tested like s
                    Rw = R[s, r] * model.cap[r] * Wb[s] if model.porous else R[s, r] * W[s]
                    Bs = Rw if Bs is None else Bs + Rw
                blocks_S[s][r] = Bs
            blocks_W[s][s] = W[s]
        self.S = sp.bmat(blocks_S, format='csr', dtype=float) if ns > 1 else blocks_S[0][0].tocsr()
        self.W = sp.block_diag(W, format='csr') if ns > 1 else W[0].tocsr()
        self.M, self.A = M, A
        # Dirichlet: node (global unknown) → (value, history) of the last entry
        presc: dict[int, tuple] = {}
        for bc in bcs:
            s = model.index(bc.get('species'))
            nodes = np.unique(_face_tris(mesh, bc['face_set'])) if 'face_set' in bc \
                else _node_set(mesh, bc.get('node_set', ''))
            for nd in nodes:
                presc[s * n + int(nd)] = (float(bc['concentration']), bc.get('history'))
        self.dofs = np.array(sorted(presc), dtype=np.int64)
        self._dvals = np.array([presc[d][0] for d in self.dofs])
        self._dhist = [presc[d][1] for d in self.dofs]
        mask = np.ones(n * ns, bool)
        mask[self.dofs] = False
        self.free = np.flatnonzero(mask)

    def F(self, t: float) -> np.ndarray:
        F = np.zeros(self.n * self.ns)
        for s, Fi, hist in self.load_terms:
            F[s * self.n:(s + 1) * self.n] += history_factor(hist, t) * Fi
        return F

    def dirichlet_values(self, t: float) -> np.ndarray:
        if not any(self._dhist):
            return self._dvals
        return np.array([v * history_factor(h, t) for v, h in zip(self._dvals, self._dhist)])

    def rates(self, x: np.ndarray, F: np.ndarray) -> dict:
        """Budget rates per species [c·m³/s]: source in, advective out, exchange out, reaction out."""
        n, ns = self.n, self.ns
        one = np.ones(n)
        MT = self.M.T @ one                       # 1ᵀM
        AT = self.A.T @ one
        out = {'source': np.zeros(ns), 'advection_out': np.zeros(ns), 'exchange_out': np.zeros(ns),
               'reaction_out': np.zeros(ns)}
        cs = [x[s * n:(s + 1) * n] for s in range(ns)]
        mass = np.array([MT @ c for c in cs])
        if self.model.porous:
            mass = self.model.cap * mass                              # dissolved + sorbed
        for s in range(ns):
            out['source'][s] = F[s * n:(s + 1) * n].sum()
            out['advection_out'][s] = self.model.phi * (AT @ cs[s])
            out['exchange_out'][s] = one @ (self.Kex[s] @ cs[s])
            out['reaction_out'][s] = self.model.R[s] @ mass
        return out, mass


class _Solver:
    """Factorised reduced system A_ff x_f = b_f − A_fd x_d."""

    def __init__(self, A: sp.csr_matrix, free, dofs):
        self.A = A.tocsr()
        self.free, self.dofs = free, dofs
        Aff = self.A[free][:, free].tocsc()
        self.Afd = self.A[free][:, dofs].tocsr()
        self.method = 'splu' if len(free) <= DIRECT_MAX else 'ilu_gmres'
        if self.method == 'splu':
            self.lu = spla.splu(Aff, permc_spec='COLAMD')
        else:
            self.Aff = Aff
            ilu = spla.spilu(Aff, drop_tol=1e-5, fill_factor=10)
            self.Mp = spla.LinearOperator(Aff.shape, ilu.solve)

    def solve(self, b: np.ndarray, xd: np.ndarray, x0=None) -> np.ndarray:
        x = np.zeros(self.A.shape[0])
        x[self.dofs] = xd
        rhs = b[self.free] - (self.Afd @ xd if len(self.dofs) else 0.0)
        if self.method == 'splu':
            x[self.free] = self.lu.solve(rhs)
        else:
            xf, info = spla.gmres(self.Aff, rhs, M=self.Mp, rtol=1e-10, atol=0.0, restart=60, maxiter=400,
                                  x0=None if x0 is None else x0[self.free])
            if info != 0:
                raise ValueError(f'Transporte: GMRES no convergió (info {info}).')
            x[self.free] = xf
        return x

    def reaction(self, x: np.ndarray, b: np.ndarray) -> np.ndarray:
        r = np.zeros(self.A.shape[0])
        if len(self.dofs):
            r[self.dofs] = self.A[self.dofs] @ x - b[self.dofs]
        return r


def initial_field(mesh: FEMMesh, model: TransportModel, initial) -> np.ndarray:
    """Initial concentrations x (species-major). ``initial``: list per species of {value} | {gaussian: {center,
    sigma, peak | mass}} | nodal array, or None (zero)."""
    n = mesh.n_nodes
    x = np.zeros(n * model.n_species)
    if initial is None:
        return x
    if isinstance(initial, dict):
        initial = [initial]
    for s, ic in enumerate(initial[:model.n_species]):
        if ic is None:
            continue
        sl = slice(s * n, (s + 1) * n)
        if isinstance(ic, (list, np.ndarray)):
            a = np.asarray(ic, float)
            if a.shape != (n,):
                raise ValueError(f'Condición inicial de la especie {s}: {a.shape} valores, se esperaban {n}.')
            x[sl] = a
        elif 'gaussian' in ic:
            g = ic['gaussian']
            x0 = np.asarray(g['center'], float)
            sig = float(g['sigma'])
            if sig <= 0:
                raise ValueError('Pulso gaussiano: σ > 0.')
            prof = np.exp(-np.sum((mesh.nodes - x0) ** 2, axis=1) / (2 * sig ** 2))
            if g.get('mass') is not None:
                x[sl] = float(g['mass']) * prof / (2 * np.pi * sig ** 2) ** 1.5
            else:
                x[sl] = float(g.get('peak', 1.0)) * prof
        else:
            x[sl] = float(ic.get('value', 0.0) or 0.0)
    return x


def time_settings(time: dict) -> dict:
    t_end = float(time.get('t_end', 0.0))
    n_steps = int(time.get('n_steps', 0))
    if not (t_end > 0 and n_steps >= 1):
        raise ValueError('Transitorio: t_end > 0 y n_steps ≥ 1.')
    scheme = time.get('scheme', 'bdf2')
    if scheme not in SCHEMES:
        raise ValueError(f'Esquema temporal desconocido {scheme!r} ({", ".join(SCHEMES)}).')
    theta = {'be': 1.0, 'cn': 0.5}.get(scheme, float(time.get('theta', 1.0)))
    if scheme == 'theta' and not 0.5 <= theta <= 1.0:
        raise ValueError('θ debe estar en [0.5, 1] (estable).')
    n_out = max(1, min(int(time.get('n_output', min(n_steps, 50))), n_steps))
    return {'t_end': t_end, 'n_steps': n_steps, 'dt': t_end / n_steps, 'scheme': scheme, 'theta': theta,
            'n_output': n_out}


def solve(mesh: FEMMesh, model: TransportModel, bcs: list, loads: list, *, velocity=None, time: dict | None = None,
          initial=None, probes: list | None = None, progress=None) -> tuple[list, dict]:
    """Returns (snapshots [(t, x (ns·N,))], info). Steady without ``time`` (one snapshot)."""
    v = nodal_velocity(mesh, model, velocity)
    prob = _Problem(mesh, model, v, bcs, loads)
    n, ns = prob.n, prob.ns
    locs = locate(mesh, [p['point'] for p in probes]) if probes else []
    budget = {k: np.zeros(ns) for k in ('source', 'boundary_in', 'advection_out', 'exchange_out', 'reaction_out')}
    curves = []

    def sample(t, x):
        if locs:
            curves.append([t] + [[interpolate(mesh, x[s * n:(s + 1) * n], lc) for s in range(ns)] for lc in locs])

    if time is None:
        sol = _Solver(prob.S, prob.free, prob.dofs)
        F = prob.F(0.0)
        x = sol.solve(F, prob.dirichlet_values(0.0))
        rt, mass = prob.rates(x, F)
        r = sol.reaction(x, F)
        bin_ = np.array([r[s * n:(s + 1) * n].sum() for s in range(ns)])
        rates = {**{k: rt[k] for k in rt}, 'boundary_in': bin_}
        net = rates['source'] + bin_ - rates['advection_out'] - rates['exchange_out'] - rates['reaction_out']
        scale = np.maximum.reduce([np.abs(rates[k]) for k in rates]) + 1e-300
        sample(0.0, x)
        info = {'steady': True, 'rates': {k: v_.tolist() for k, v_ in rates.items()}, 'mass': mass.tolist(),
                'mass_balance_error': float(np.max(np.abs(net) / scale)), 'solver': sol.method, 'problem': prob,
                'curves': curves, 'probe_locations': locs}
        return [(0.0, x)], info

    ts = time_settings(time)
    dt, th_, scheme = ts['dt'], ts['theta'], ts['scheme']
    # The initial field is kept at the fixed-concentration nodes too: the boundary value switches on at t = 0⁺.
    # Overwriting them at t = 0 adds the mass of the boundary-layer interpolant (O(h), and with T10 of either
    # sign), which shifts a front by that mass / section: 1 % on the Ogata–Banks hito, independent of Δt.
    x = initial_field(mesh, model, initial)
    F_old = prob.F(0.0)
    rt_old, m0 = prob.rates(x, F_old)
    mass_hist = [m0]
    out_every = ts['n_steps'] / ts['n_output']
    snaps = [(0.0, x.copy())]
    sample(0.0, x)
    W, S = prob.W, prob.S
    if scheme == 'bdf2':
        sol_first = _Solver(W / dt + S, prob.free, prob.dofs)                # BE start
        sol = _Solver(1.5 * W / dt + S, prob.free, prob.dofs)
    else:
        sol_first = sol = _Solver(W / dt + th_ * S, prob.free, prob.dofs)
    x_prev = None
    d_prev = {k: np.zeros(ns) for k in budget}                              # BDF2 per-term mass increments
    next_out = out_every
    for k in range(1, ts['n_steps'] + 1):
        t = k * dt
        Fn = prob.F(t)
        xd = prob.dirichlet_values(t)
        if scheme == 'bdf2' and k >= 2:
            b = W @ (2.0 * x - 0.5 * x_prev) / dt + Fn
            xn = sol.solve(b, xd, x)
            r = sol.reaction(xn, b)
            rt, mn = prob.rates(xn, Fn)
            q = {kk: rt[kk] for kk in rt}
            q['boundary_in'] = np.array([r[s * n:(s + 1) * n].sum() for s in range(ns)])
            # 3δ_{n+1} − δ_n = 2Δt q_{n+1} for each term (linear) → term increments
            d = {kk: (2 * dt * q[kk] + d_prev[kk]) / 3.0 for kk in budget}
        else:
            th_k = 1.0 if scheme == 'bdf2' else th_
            solver = sol_first if scheme == 'bdf2' else sol
            b = W @ x / dt - (1 - th_k) * (S @ x - F_old) + th_k * Fn
            xn = solver.solve(b, xd, x)
            r = solver.reaction(xn, b)
            rt, mn = prob.rates(xn, Fn)
            d = {kk: dt * (th_k * rt[kk] + (1 - th_k) * rt_old[kk]) for kk in rt}
            d['boundary_in'] = dt * np.array([r[s * n:(s + 1) * n].sum() for s in range(ns)])
        for kk in budget:
            budget[kk] += d[kk]
        d_prev = d
        x_prev, x = x, xn
        F_old, rt_old = Fn, rt
        mass_hist.append(mn)
        sample(t, x)
        if k >= next_out - 1e-9 or k == ts['n_steps']:
            snaps.append((t, x.copy()))
            next_out += out_every
        if progress and (k % max(1, ts['n_steps'] // 20) == 0):
            progress(k, ts['n_steps'], t)
    m_end = mass_hist[-1]
    net = budget['source'] + budget['boundary_in'] - budget['advection_out'] - budget['exchange_out'] \
        - budget['reaction_out']
    scale = np.maximum.reduce([np.abs(budget[k]) for k in budget] + [np.abs(m0), np.abs(m_end)]) + 1e-300
    err = np.abs(m_end - m0 - net) / scale
    info = {'steady': False, 'time': ts, 'mass_initial': m0.tolist(), 'mass_final': m_end.tolist(),
            'mass_history': np.asarray(mass_hist).tolist(), 'budget': {k: v_.tolist() for k, v_ in budget.items()},
            'mass_balance_error': float(err.max()), 'solver': sol.method, 'problem': prob, 'curves': curves,
            'probe_locations': locs}
    return snaps, info


# ── Post-processing helpers ──────────────────────────────────────────────────

def peclet_max(prob: _Problem) -> float:
    """Max element Péclet |v| h / (2 D), h = edge of the equal-volume regular tet (T10 nodes are h/2 apart),
    over the species with D > 0 (inf with pure advection and flow)."""
    vals = []
    vn = prob.ops['vn']
    for i, s in enumerate(prob.model.species):
        DL = species_DL(prob.model, i, vn)
        if np.all(np.asarray(DL) > 0) and (s['D'] > 0 or prob.model.porous):
            vals.append(float(np.max(vn * prob.ops['h_vol'] / (2 * DL))))
        elif np.any(vn > 0):
            vals.append(float('inf'))
    return max(vals) if vals else 0.0


def courant_max(prob: _Problem, dt: float) -> float:
    """Max |v| Δt / h (h = equal-volume regular tet edge; T10 node spacing is h/2)."""
    return float(np.max(prob.ops['vn'] * dt / prob.ops['h_vol']))


def volume_above(mesh: FEMMesh, c: np.ndarray, threshold: float) -> float:
    """Volume where c > threshold: corner-linear interpolation per element, fraction of its 4 corners above
    (first order; T10 ∫N dV corner weights are negative, so nodal weights cannot be used)."""
    vol = tb.volumes(mesh.nodes, mesh.elements)
    frac = (c[mesh.elements[:, :4]] > threshold).mean(1)
    return float(vol @ frac)
