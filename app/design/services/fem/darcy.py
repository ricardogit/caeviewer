"""Groundwater flow in a confined porous medium, Darcy's law (FASE 10.6).

    S_s ∂h/∂t = ∇·(K ∇h) + Q          in Ω,   q = −K ∇h (Darcy flux),  v = q / n_e (pore velocity → transport)

h = hydraulic head [m]; K = hydraulic conductivity [m/s]: scalar, principal values [K1, K2, K3] along the material
axes (``axis_1`` / ``axis_2``, like the orthotropic conductivity), and per-element zones ``K_zones`` [{box: [[x0, y0,
z0], [x1, y1, z1]] (m), K}] (heterogeneous aquifer: an element whose centroid is in a box takes that K; later zones
win); S_s = specific storage [1/m]; n_e = effective porosity (only for the pore velocity).

Conditions (same ``bcs`` / ``loads`` lists as the other physics, recognised by key; ``history`` [[t, factor]…]):
    BC   ``hydraulic_head`` h̄ [m] on ``face_set`` / ``node_set`` (lake, sea, river in contact, far field)
    load ``recharge`` R [m/s] into the body on ``face_set`` (infiltration; negative = evaporation)
         ``well`` {rate [m³/s], positive = extraction, injection < 0} on ``face_set`` (the well screen: the rate is
               spread by area) or at a ``point`` [m] (point sink)
         ``leakage`` {conductance [1/s], head [m]} on ``face_set``: flux C (h_ext − h) into the body (river bed,
               leaky aquitard: C = K' / b')
Free faces: no flow (∂h/∂n = 0, impermeable).

Time: ``time`` {t_end, n_steps, scheme 'bdf2' (default, variable-step, BE start) | 'cn' | 'be', dt_growth (geometric
step ratio, default 1: pumping tests want growing steps), n_output}; without ``time`` the steady problem. The
initial head is ``initial_head`` (material, default 0); drawdown s = h(0) − h is reported in transient runs.

Water budget [m³/s] integrated with the scheme's own weights: storage change = recharge − wells + head-boundary
inflow (reactions) + leakage → the balance error is round-off.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.mesh import FEMMesh
from app.design.services.fem.transport import history_factor, locate

BC_KEYS = ('hydraulic_head',)
LOAD_KEYS = ('recharge', 'well', 'leakage')
SCHEMES = ('bdf2', 'cn', 'be')
DIRECT_MAX = 400_000
DAY = 86_400.0


def is_darcy_bc(bc: dict) -> bool:
    return 'hydraulic_head' in bc


def is_darcy_load(ld: dict) -> bool:
    return any(k in ld for k in LOAD_KEYS)


def _gauss(et):
    if et == 'T4':
        return np.array([[0.25, 0.25, 0.25]]), np.array([1.0 / 6.0])
    return tb.GAUSS_TET4, tb.W_TET4


class PorousMedium:
    """Hydraulic properties of the ``porous_medium`` material spec."""

    def __init__(self, mat: dict):
        from app.design.services.fem.constitutive import conductivity
        K = mat.get('K')
        if K is None:
            raise ValueError('Medio poroso: falta la conductividad hidráulica K (m/s).')
        if isinstance(K, (list, tuple)):
            if len(K) != 3 or min(map(float, K)) <= 0:
                raise ValueError('Medio poroso: K = [K1, K2, K3] > 0 a lo largo de los ejes del material.')
            self.K = np.asarray(conductivity({'k': [float(k) for k in K], 'axis_1': mat.get('axis_1'),
                                              'axis_2': mat.get('axis_2')}), float)
        else:
            if not float(K) > 0:
                raise ValueError('Medio poroso: K > 0 (m/s).')
            self.K = float(K) * np.eye(3)
        self.zones = []
        for i, z in enumerate(mat.get('K_zones') or []):
            box = np.asarray(z.get('box'), float)
            Kz = z.get('K')
            if box.shape != (2, 3) or np.any(box[1] < box[0]):
                raise ValueError(f'Zona {i + 1} de K: box = [[xmin, ymin, zmin], [xmax, ymax, zmax]] (m).')
            Kt = PorousMedium({'K': Kz, 'axis_1': mat.get('axis_1'), 'axis_2': mat.get('axis_2')}).K
            self.zones.append((box, Kt, z.get('label') or f'zona {i + 1}'))
        self.Ss = float(mat.get('Ss', 0.0) or 0.0)
        self.porosity = float(mat.get('porosity', 0.3) or 0.3)
        if self.Ss < 0 or not 0 < self.porosity <= 1:
            raise ValueError('Medio poroso: almacenamiento específico S_s ≥ 0 y porosidad eficaz en (0, 1].')
        self.initial_head = mat.get('initial_head', 0.0)

    def element_K(self, mesh: FEMMesh) -> tuple[np.ndarray, np.ndarray]:
        """K tensor per element (m,3,3) and zone index per element (-1 = base material)."""
        m = mesh.n_elements
        Ke = np.broadcast_to(self.K, (m, 3, 3)).copy()
        zone = np.full(m, -1)
        if self.zones:
            cent = mesh.nodes[mesh.elements[:, :4]].mean(1)
            for i, (box, Kt, _) in enumerate(self.zones):
                tol = 1e-9 * max(1.0, float(np.abs(box).max()))
                inside = np.all((cent >= box[0] - tol) & (cent <= box[1] + tol), axis=1)
                Ke[inside] = Kt
                zone[inside] = i
        return Ke, zone


def assemble(mesh: FEMMesh, Ke: np.ndarray, Ss: float):
    """Stiffness ∫∇Nᵀ K_e ∇N and storage ∫S_s N Nᵀ (consistent)."""
    n = mesh.n_nodes
    et = mesh.element_type
    pts, wts = _gauss(et)
    from app.design.services.fem.transport import _rule
    mp, mw = _rule()
    rows, cols, kv, mv = [], [], [], []
    for a in range(0, mesh.n_elements, 20_000):
        el = mesh.elements[a:a + 20_000]
        X = mesh.nodes[el]
        K_ = Ke[a:a + 20_000]
        nd = el.shape[1]
        Kl = np.zeros((len(el), nd, nd))
        for p, wg in zip(pts, wts):
            det, dN = tb._jac(X, tb.dshape(et, p))
            Kl += (wg * det)[:, None, None] * np.einsum('man,mab,mbk->mnk', dN, K_, dN)
        Ml = np.zeros_like(Kl)
        if Ss > 0:
            for p, wg in zip(mp, mw):
                det, _ = tb._jac(X, tb.dshape(et, p))
                N = tb.shape(et, p)
                Ml += (wg * det)[:, None, None] * np.outer(N, N)[None]
        rows.append(np.repeat(el, nd, axis=1).ravel())
        cols.append(np.tile(el, (1, nd)).ravel())
        kv.append(Kl.ravel())
        mv.append((Ss * Ml).ravel())
    r, c = np.concatenate(rows), np.concatenate(cols)
    K = sp.csr_matrix((np.concatenate(kv), (r, c)), shape=(n, n))
    M = sp.csr_matrix((np.concatenate(mv), (r, c)), shape=(n, n))
    return K, M


class _Problem:
    def __init__(self, mesh: FEMMesh, med: PorousMedium, bcs: list, loads: list):
        from app.design.services.fem.assembler import BoundaryConditionError, _face_tris, _node_set
        from app.design.services.fem.thermal import convection_batch
        self.mesh, self.med = mesh, med
        n = mesh.n_nodes
        self.n = n
        self.Ke, self.zone = med.element_K(mesh)
        self.K, self.M = assemble(mesh, self.Ke, med.Ss)
        self.L = sp.csr_matrix((n, n))
        self.terms = []                     # (kind, vector, history)
        self.info = []
        for i, ld in enumerate(loads):
            meta = {'index': i, 'label': ld.get('label')}
            Fi = np.zeros(n)
            if 'well' in ld:
                w = ld['well']
                rate = float(w.get('rate', 0.0))
                if w.get('point') is not None:
                    loc = locate(mesh, [w['point']])[0]
                    if not loc['inside']:
                        raise BoundaryConditionError(f'Pozo {i}: el punto {w["point"]} está fuera de la malla.')
                    np.add.at(Fi, mesh.elements[loc['element']], -rate * tb.shape(mesh.element_type, loc['nat']))
                    meta['point'] = list(map(float, w['point']))
                elif 'face_set' in ld:
                    tris = _face_tris(mesh, ld['face_set'])
                    NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
                    np.add.at(Fi, tris, NdA * (-rate / area.sum()))
                    meta['screen_area_m2'] = float(area.sum())
                else:
                    raise BoundaryConditionError(f'Pozo {i}: indique las caras del filtro (face_set) o un punto.')
                meta.update(kind='well', rate_m3_s=rate)
                self.terms.append(('well', Fi, ld.get('history')))
            elif 'face_set' in ld:
                tris = _face_tris(mesh, ld['face_set'])
                if 'recharge' in ld:
                    NdA, _, area = tb.surface_integrals(mesh.nodes, tris)
                    np.add.at(Fi, tris, NdA * float(ld['recharge']))
                    meta.update(kind='recharge', rate_m_s=float(ld['recharge']), area_m2=float(area.sum()))
                    self.terms.append(('recharge', Fi, ld.get('history')))
                elif 'leakage' in ld:
                    lk = ld['leakage']
                    C, he = float(lk.get('conductance', 0.0)), float(lk.get('head', 0.0))
                    if C < 0:
                        raise BoundaryConditionError(f'Goteo {i}: conductancia ≥ 0 (1/s).')
                    Me, NdA = convection_batch(mesh.nodes, tris, C)
                    nd = tris.shape[1]
                    self.L = self.L + sp.csr_matrix(
                        (Me.ravel(), (np.repeat(tris, nd, axis=1).ravel(), np.tile(tris, (1, nd)).ravel())),
                        shape=(n, n))
                    np.add.at(Fi, tris, NdA * C * he)
                    meta.update(kind='leakage', conductance=C, head=he, area_m2=float(NdA.sum()))
                    self.terms.append(('leakage', Fi, ld.get('history')))
                else:
                    raise BoundaryConditionError(f'Carga de flujo subterráneo {i} sin tipo.')
            else:
                raise BoundaryConditionError(f'Carga de flujo subterráneo {i}: recarga / goteo necesitan caras.')
            self.info.append(meta)
        presc: dict[int, tuple] = {}
        for bc in bcs:
            nodes = np.unique(_face_tris(mesh, bc['face_set'])) if 'face_set' in bc \
                else _node_set(mesh, bc.get('node_set', ''))
            for nd in nodes:
                presc[int(nd)] = (float(bc['hydraulic_head']), bc.get('history'))
        self.dofs = np.array(sorted(presc), dtype=np.int64)
        self._dv = np.array([presc[d][0] for d in self.dofs])
        self._dh = [presc[d][1] for d in self.dofs]
        mask = np.ones(n, bool)
        mask[self.dofs] = False
        self.free = np.flatnonzero(mask)
        self.S = (self.K + self.L).tocsr()

    def F(self, t):
        F = np.zeros(self.n)
        parts = {'recharge': 0.0, 'well': 0.0, 'leakage': 0.0}
        for kind, Fi, hist in self.terms:
            f = history_factor(hist, t)
            F += f * Fi
            parts[kind] += f * Fi.sum()
        return F, parts

    def head_values(self, t):
        if not any(self._dh):
            return self._dv
        return np.array([v * history_factor(h, t) for v, h in zip(self._dv, self._dh)])

    def rates(self, h, parts, r):
        """Budget rates [m³/s]: recharge in, wells out, leakage in, head boundaries in."""
        return {'recharge': parts['recharge'], 'well_out': -parts['well'],
                'leakage_in': parts['leakage'] - float(np.sum(self.L @ h)),
                'boundary_in': float(r[self.dofs].sum()) if len(self.dofs) else 0.0,
                'boundary_in_gross': float(np.clip(r[self.dofs], 0, None).sum()) if len(self.dofs) else 0.0}


class _Solver:
    def __init__(self, A, free, dofs):
        self.A = A.tocsr()
        self.free, self.dofs = free, dofs
        Aff = self.A[free][:, free].tocsc()
        self.Afd = self.A[free][:, dofs].tocsr()
        self.method = 'splu' if len(free) <= DIRECT_MAX else 'amg_pcg'
        if self.method == 'splu':
            self.lu = spla.splu(Aff, permc_spec='COLAMD')
        else:
            import pyamg
            self.Aff = Aff.tocsr()
            self.ml = pyamg.smoothed_aggregation_solver(self.Aff)

    def solve(self, b, hd, x0=None):
        x = np.zeros(self.A.shape[0])
        x[self.dofs] = hd
        rhs = b[self.free] - (self.Afd @ hd if len(self.dofs) else 0.0)
        if self.method == 'splu':
            x[self.free] = self.lu.solve(rhs)
        else:
            x[self.free] = self.ml.solve(rhs, x0=None if x0 is None else x0[self.free], tol=1e-12, accel='cg',
                                         maxiter=500)
        r = np.zeros_like(x)
        if len(self.dofs):
            r[self.dofs] = self.A[self.dofs] @ x - b[self.dofs]
        return x, r


def time_settings(time: dict) -> dict:
    t_end = float(time.get('t_end', 0.0))
    n = int(time.get('n_steps', 0))
    if not (t_end > 0 and n >= 1):
        raise ValueError('Transitorio: t_end > 0 y n_steps ≥ 1.')
    scheme = time.get('scheme', 'bdf2')
    if scheme not in SCHEMES:
        raise ValueError(f'Esquema temporal desconocido {scheme!r} ({", ".join(SCHEMES)}).')
    g = float(time.get('dt_growth', 1.0) or 1.0)
    if not 1.0 <= g <= 2.0:
        raise ValueError('dt_growth (razón geométrica de pasos) debe estar en [1, 2].')
    if g == 1.0:
        dts = np.full(n, t_end / n)
    else:
        dts = t_end * (g - 1) / (g ** n - 1) * g ** np.arange(n)
    n_out = max(1, min(int(time.get('n_output', min(n, 50))), n))
    return {'t_end': t_end, 'n_steps': n, 'scheme': scheme, 'dt_growth': g, 'dt_first': float(dts[0]),
            'dt_last': float(dts[-1]), 'n_output': n_out, 'dts': dts}


def _initial(mesh, med, initial):
    h0 = med.initial_head if initial is None else initial
    if isinstance(h0, (list, np.ndarray)):
        a = np.asarray(h0, float)
        if a.shape != (mesh.n_nodes,):
            raise ValueError(f'Carga inicial: {a.shape} valores, se esperaban {mesh.n_nodes}.')
        return a.copy()
    return np.full(mesh.n_nodes, float(h0 or 0.0))


def solve(mesh: FEMMesh, med: PorousMedium, bcs: list, loads: list, *, time: dict | None = None, initial=None,
          probes: list | None = None, progress=None) -> tuple[list, dict]:
    """Returns (snapshots [(t, h)], info)."""
    prob = _Problem(mesh, med, bcs, loads)
    n = prob.n
    locs = locate(mesh, [p['point'] for p in probes]) if probes else []
    curves = []

    def sample(t, h):
        if locs:
            curves.append([t] + [float(tb.shape(mesh.element_type, lc['nat']) @ h[mesh.elements[lc['element']]])
                                 for lc in locs])

    if time is None:
        if not len(prob.dofs) and prob.L.nnz == 0:
            raise ValueError('Flujo subterráneo estacionario sin carga hidráulica impuesta ni goteo: la carga no '
                             'está determinada (añada un contorno de carga fija, p. ej. el límite lejano o un río).')
        sol = _Solver(prob.S, prob.free, prob.dofs)
        F, parts = prob.F(0.0)
        h, r = sol.solve(F, prob.head_values(0.0))
        rt = prob.rates(h, parts, r)
        net = rt['recharge'] - rt['well_out'] + rt['leakage_in'] + rt['boundary_in']
        # gross inflow at fixed heads as scale: between two head boundaries the net terms are all ≈ 0
        scale = max(abs(v) for v in rt.values()) + 1e-300
        sample(0.0, h)
        return [(0.0, h)], {'steady': True, 'rates': rt, 'balance_error': abs(net) / scale, 'solver': sol.method,
                            'problem': prob, 'curves': curves, 'probe_locations': locs}

    if med.Ss <= 0:
        raise ValueError('Flujo subterráneo transitorio: el almacenamiento específico S_s debe ser > 0 (1/m).')
    ts = time_settings(time)
    dts = ts.pop('dts')
    M, S = prob.M, prob.S
    h = _initial(mesh, med, initial)
    h0 = h.copy()
    one = np.ones(n)
    MT = M.T @ one
    vol0 = float(MT @ h)
    F_old, parts_old = prob.F(0.0)
    # rates at t = 0 (CN uses the explicit half of recharge / wells / leakage; head-boundary inflow comes from the
    # reaction of each step's own equation)
    rt_old = {'recharge': parts_old['recharge'], 'well_out': -parts_old['well'],
              'leakage_in': parts_old['leakage'] - float(np.sum(prob.L @ h)), 'boundary_in': 0.0,
              'boundary_in_gross': 0.0}
    budget = {k: 0.0 for k in ('recharge', 'well_out', 'leakage_in', 'boundary_in', 'boundary_in_gross')}
    snaps = [(0.0, h.copy())]
    sample(0.0, h)
    cache = {}

    def solver_for(coef):
        key = round(coef, 12)
        if key not in cache:
            if len(cache) > 3:
                cache.clear()
            cache[key] = _Solver(coef * M + (S if ts['scheme'] != 'cn' else 0.5 * S), prob.free, prob.dofs)
        return cache[key]

    t = 0.0
    h_prev = None
    d_prev = {k: 0.0 for k in budget}
    out_idx = set(np.unique(np.round(np.linspace(0, ts['n_steps'], ts['n_output'] + 1)[1:]).astype(int)))
    times = [0.0]
    head_hist = [vol0]
    for k in range(1, ts['n_steps'] + 1):
        dt = float(dts[k - 1])
        t += dt
        Fn, parts = prob.F(t)
        hd = prob.head_values(t)
        if ts['scheme'] == 'bdf2' and k >= 2:
            w = dt / float(dts[k - 2])
            a, bb, c = (1 + 2 * w) / (1 + w), 1 + w, w * w / (1 + w)
            sol = solver_for(a / dt)
            rhs = M @ (bb * h - c * h_prev) / dt + Fn
            hn, r = sol.solve(rhs, hd, h)
            rt = prob.rates(hn, parts, r)
            # a δ_{n+1} − c δ_n = Δt q_{n+1} per term (a − b + c = 0)
            d = {kk: (dt * rt[kk] + c * d_prev[kk]) / a for kk in budget}
        elif ts['scheme'] == 'cn':
            sol = solver_for(1.0 / dt)
            rhs = M @ h / dt - 0.5 * (S @ h - F_old) + 0.5 * Fn
            hn, r = sol.solve(rhs, hd, h)
            rt = prob.rates(hn, parts, r)
            # the reaction of the CN equation is already the step-average inflow at the fixed-head nodes
            d = {kk: dt * 0.5 * (rt[kk] + rt_old[kk]) for kk in budget if kk != 'boundary_in'}
            d['boundary_in'] = dt * rt['boundary_in']
            d['boundary_in_gross'] = dt * rt['boundary_in_gross']
        else:
            sol = solver_for(1.0 / dt)
            rhs = M @ h / dt + Fn
            hn, r = sol.solve(rhs, hd, h)
            rt = prob.rates(hn, parts, r)
            d = {kk: dt * rt[kk] for kk in budget}
        for kk in budget:
            budget[kk] += d[kk]
        d_prev = d
        h_prev, h = h, hn
        F_old, rt_old = Fn, rt
        head_hist.append(float(MT @ h))
        times.append(t)
        sample(t, h)
        if k in out_idx:
            snaps.append((t, h.copy()))
        if progress and k % max(1, ts['n_steps'] // 20) == 0:
            progress(k, ts['n_steps'], t)
    storage = head_hist[-1] - vol0
    net = budget['recharge'] - budget['well_out'] + budget['leakage_in'] + budget['boundary_in']
    scale = max([abs(v) for v in budget.values()] + [abs(storage)]) + 1e-300
    info = {'steady': False, 'time': ts, 'budget': {**budget, 'storage_change': storage},
            'balance_error': abs(storage - net) / scale, 'solver': next(iter(cache.values())).method,
            'problem': prob, 'curves': curves, 'probe_locations': locs, 'initial': h0,
            'storage_history': [[ti, hv - vol0] for ti, hv in zip(times, head_hist)][::max(1, len(times) // 200)]}
    return snaps, info


def darcy_flux(mesh: FEMMesh, Ke: np.ndarray, h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """q = −K∇h: element mean (m,3) and nodal average (N,3) (T10 via Gauss-point extrapolation)."""
    et = mesh.element_type
    el = mesh.elements
    X = mesh.nodes[el]
    he = h[el]
    if et == 'T4':
        _, dN = tb._jac(X, tb.dshape('T4', (0.25,) * 3))
        g = -np.einsum('man,mn->ma', dN, he)
        elem = np.einsum('mab,mb->ma', Ke, g)
        per_node = np.repeat(elem[:, None], 4, axis=1)
    else:
        gp = np.stack([-np.einsum('man,mn->ma', tb._jac(X, tb.dshape(et, p))[1], he) for p in tb.GAUSS_TET4], 1)
        gp = np.einsum('mab,mgb->mga', Ke, gp)
        elem = gp.mean(1)
        corners = np.einsum('cg,mgk->mck', tb._GP_TO_CORNER, gp)
        mids = (corners[:, tb.T10_EDGES[:, 0]] + corners[:, tb.T10_EDGES[:, 1]]) / 2
        per_node = np.concatenate([corners, mids], axis=1)
    acc = np.zeros((mesh.n_nodes, 3))
    cnt = np.zeros(mesh.n_nodes)
    for j in range(el.shape[1]):
        np.add.at(acc, el[:, j], per_node[:, j])
        np.add.at(cnt, el[:, j], 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        nodal = np.where(cnt[:, None] > 0, acc / cnt[:, None], 0.0)
    return elem, nodal


def face_flow(mesh: FEMMesh, Ke: np.ndarray, h: np.ndarray, face_set) -> float:
    """Outward flow through a face set ∫ q·n dA [m³/s] from the element gradients (post-processing only: the
    budget uses reactions, which are exact)."""
    from app.design.services.fem.assembler import _face_tris
    tris = _face_tris(mesh, face_set)
    elem, nodal = darcy_flux(mesh, Ke, h)
    _, NndA, _ = tb.surface_integrals(mesh.nodes, tris)                      # ∫ N n dA (k,n,3)
    sign = tb.outward_sign(mesh.nodes, mesh.elements, tris)
    return float(np.einsum('knc,knc,k->', NndA, nodal[tris], sign))
