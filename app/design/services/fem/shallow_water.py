"""2D depth-averaged shallow-water equations (FASE 10.3) on the triangle mesh of a water domain (FASE 10.5).

    ∂H/∂t + ∇·(H u) = 0
    ∂(Hu)/∂t + ∇·(H u⊗u + ½gH² I) = −gH∇z_b − g n² |u| u / H^{1/3} + τ_w/ρ − f k×(Hu) + ∇·(H ν_t ∇u)

Cell-centred finite volumes (one cell per triangle; bed z_b constant per cell = −mean node depth):
  * HLL flux with HLLC-style upwinding of the tangential momentum, rotated to the face normal;
  * **hydrostatic reconstruction** (Audusse et al. 2004): H* = max(0, η − max(z_L, z_R)) + interface pressure
    correction → exactly well balanced (lake at rest, with dry cells) and positive under the CFL condition;
  * second order: least-squares gradients of (η, u, v), Barth–Jespersen limiter, first order in cells next to
    dry ones (wet/dry fronts) — ``order: 1`` turns it off; SSP-RK2 (Heun) in time, Δt from CFL·A/Σλ L;
  * Manning friction semi-implicit (split, unconditionally stable), Coriolis as an exact rotation, wind stress
    (Wu 1982 drag) explicit, constant horizontal viscosity explicit (edge fluxes).
Boundaries by boundary id of the mesh: ``wall`` (coast, impermeable, slip), ``level`` / ``tide`` (imposed η(t):
ghost state from the outgoing Riemann invariant u_n + 2c), ``free`` (transmissive), ``river`` (imposed discharge
Q(t) distributed by conveyance H^{5/3}; the mass flux is imposed exactly). Mass budget integrated with the RK
weights (balance = round-off). Cells with H < h_dry have their momentum zeroed (mass untouched).
"""
from __future__ import annotations

import math
import time as _time

import numpy as np

G = 9.80665
OMEGA = 7.2921159e-5
RHO_AIR = 1.225
BOUNDARY_KINDS = ('wall', 'level', 'tide', 'free', 'river')


# ── Mesh topology ─────────────────────────────────────────────────────────────

class SWGrid:
    """Finite-volume topology of a triangle mesh: cells, interior faces (L → R, normal out of L), boundary
    faces (normal outward) with their boundary id."""

    def __init__(self, nodes, tris, bed_nodes, boundary: dict):
        nodes = np.asarray(nodes, float)[:, :2]
        tris = np.asarray(tris, np.int64)
        P = nodes[tris]
        area = 0.5 * ((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1])
                      - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
        neg = area < 0
        if neg.any():                                   # CCW cells
            tris = tris.copy()
            tris[neg] = tris[neg][:, [0, 2, 1]]
            P = nodes[tris]
            area = np.abs(area)
        if np.any(area <= 0):
            raise ValueError('Aguas someras: hay triángulos degenerados (área nula).')
        self.nodes, self.tris, self.area = nodes, tris, area
        self.nc = len(tris)
        self.cen = P.mean(1)
        zn = -np.asarray(bed_nodes, float) if bed_nodes is not None else np.zeros(len(nodes))
        self.zb = zn[tris].mean(1)
        # P1 bed at the midpoint of each cell edge (slot k = edge tris[k] → tris[k+1]) and outward n·L per slot
        self.zf = np.stack([0.5 * (zn[tris[:, k]] + zn[tris[:, (k + 1) % 3]]) for k in range(3)], 1)
        d = np.stack([P[:, (k + 1) % 3] - P[:, k] for k in range(3)], 1)
        self.nLx, self.nLy = d[..., 1], -d[..., 0]
        n = len(nodes)
        a = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
        b = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
        cell = np.tile(np.arange(self.nc), 3)
        key = np.minimum(a, b) * n + np.maximum(a, b)
        order = np.argsort(key, kind='stable')
        ks = key[order]
        start = np.r_[0, np.flatnonzero(np.diff(ks)) + 1]
        count = np.diff(np.r_[start, len(ks)])
        if np.any(count > 2):
            raise ValueError('Aguas someras: malla no conforme (arista con más de dos triángulos).')
        first = order[start]
        inter = count == 2
        fi, se = first[inter], order[start[inter] + 1]
        bi = first[~inter]

        def geom(idx):
            pa, pb = nodes[a[idx]], nodes[b[idx]]
            d = pb - pa
            L = np.hypot(d[:, 0], d[:, 1])
            return np.column_stack([d[:, 1], -d[:, 0]]) / L[:, None], L, 0.5 * (pa + pb)
        self.L, self.R = cell[fi], cell[se]
        self.sL, self.sR, self.sB = fi // self.nc, se // self.nc, bi // self.nc
        # cell → neighbour across each of its 3 edges (itself on the boundary)
        self.nb = np.tile(np.arange(self.nc)[:, None], (1, 3))
        self.nb[self.L, self.sL] = self.R
        self.nb[self.R, self.sR] = self.L
        self.n, self.len, self.mid = geom(fi)                  # CCW edge a→b of L: outward normal (dy, −dx)
        self.bc_cell = cell[bi]
        self.bn, self.blen, self.bmid = geom(bi)
        bkey = key[bi]
        self.bid = np.full(len(bi), 'wall', dtype=object)
        self.bid_names = []
        for name, pairs in (boundary or {}).items():
            pairs = np.asarray(pairs, np.int64).reshape(-1, 2)
            if not len(pairs):
                continue
            k = np.minimum(pairs[:, 0], pairs[:, 1]) * n + np.maximum(pairs[:, 0], pairs[:, 1])
            hit = np.isin(bkey, k)
            self.bid[hit] = name
            self.bid_names.append(name)
        # least-squares gradient operator (boundary faces as mirrored ghosts → full rank)
        self._lsq_setup()

    def _lsq_setup(self):
        nc = self.nc
        P = self.nodes[self.tris]
        self.cf = np.stack([0.5 * (P[:, k] + P[:, (k + 1) % 3]) for k in range(3)], 1) - self.cen[:, None, :]
        dc = self.cen[self.nb] - self.cen[:, None, :]                    # zero across boundary edges
        isb = self.nb == np.arange(nc)[:, None]
        # mirrored ghost centroid on the boundary, weight 1e-3: it only regularises cells with one neighbour
        # (two interior neighbours make the gradient exact for linear fields)
        ghost = np.where(isb[:, :, None], 2 * self.cf, dc)
        wg = np.where(isb, 1e-3, 1.0)[:, :, None, None]
        self.Minv = np.linalg.inv(np.sum(wg * ghost[:, :, :, None] * ghost[:, :, None, :], axis=1))
        self.isb = isb
        self.dc = dc
        self.perim = np.zeros(nc)
        self.dist = np.linalg.norm(self.cen[self.R] - self.cen[self.L], axis=1)
        self.tvec = (self.cen[self.R] - self.cen[self.L]) / self.dist[:, None]

    def acc(self, idx, w):
        return np.bincount(idx, weights=w, minlength=self.nc)

    def gradient(self, w):
        """LSQ cell gradients of cell fields (k, nc) → (gx, gy), each (k, nc); boundary ghosts carry the cell value."""
        dw = w[:, self.nb] - w[:, :, None]
        dx, dy = self.dc[None, :, :, 0], self.dc[None, :, :, 1]
        rx = _sum3(dw * dx)
        ry = _sum3(dw * dy)
        M = self.Minv
        return M[:, 0, 0] * rx + M[:, 0, 1] * ry, M[:, 1, 0] * rx + M[:, 1, 1] * ry

    def increments(self, gx, gy):
        """Unlimited increments to the 3 edge midpoints: (k, nc, 3)."""
        return gx[:, :, None] * self.cf[None, :, :, 0] + gy[:, :, None] * self.cf[None, :, :, 1]

    def limit(self, w, d):
        """Barth–Jespersen limiter φ ∈ [0, 1] per (field, cell) for the midpoint increments ``d``."""
        wn = w[:, self.nb]
        up = np.maximum(np.maximum(w, wn[..., 0]), np.maximum(wn[..., 1], wn[..., 2]))[:, :, None] - w[:, :, None]
        lo = np.minimum(np.minimum(w, wn[..., 0]), np.minimum(wn[..., 1], wn[..., 2]))[:, :, None] - w[:, :, None]
        with np.errstate(divide='ignore', invalid='ignore'):
            ph = np.where(d > 1e-14, np.minimum(1, up / d), np.where(d < -1e-14, np.minimum(1, lo / d), 1.0))
        return np.clip(np.minimum(np.minimum(ph[..., 0], ph[..., 1]), ph[..., 2]), 0, 1)

    def locate(self, pts) -> np.ndarray:
        """Cell index containing each point (nearest centroid when outside)."""
        from scipy.spatial import cKDTree
        pts = np.asarray(pts, float).reshape(-1, 2)
        tree = cKDTree(self.cen)
        _, cand = tree.query(pts, k=min(12, self.nc))
        cand = np.atleast_2d(cand)
        out = cand[:, 0].copy()
        P = self.nodes[self.tris]
        for i, p in enumerate(pts):
            for c in cand[i]:
                a, b, cc = P[c]
                T = np.array([b - a, cc - a]).T
                lam = np.linalg.solve(T, p - a)
                if lam.min() >= -1e-9 and lam.sum() <= 1 + 1e-9:
                    out[i] = c
                    break
        return out

    def node_average(self, v, weight=None):
        """Area-weighted average of a cell field onto the nodes (``weight`` masks cells, e.g. wet ones)."""
        w = self.area if weight is None else self.area * weight
        num = np.zeros(len(self.nodes))
        den = np.zeros(len(self.nodes))
        for k in range(3):
            np.add.at(num, self.tris[:, k], w * v)
            np.add.at(den, self.tris[:, k], w)
        with np.errstate(invalid='ignore', divide='ignore'):
            return num / den, den


def _sum3(a):
    return a[..., 0] + a[..., 1] + a[..., 2]


# ── Riemann solver ───────────────────────────────────────────────────────────

def hll_flux(HL, unL, utL, HR, unR, utR):
    """HLL flux in the face frame (mass, normal momentum, tangential momentum), with the tangential momentum
    upwinded by the mass flux (HLLC contact); dry states use the dry-front speeds u ∓ 2c. Also returns the max
    wave speed per face."""
    cL, cR = np.sqrt(G * HL), np.sqrt(G * HR)
    sL = np.minimum(unL - cL, unR - cR)
    sR = np.maximum(unL + cL, unR + cR)
    dryL, dryR = HL <= 0, HR <= 0
    sL = np.where(dryL, unR - 2 * cR, sL)
    sR = np.where(dryR, unL + 2 * cL, sR)
    FL0, FR0 = HL * unL, HR * unR
    FL1, FR1 = HL * unL * unL + 0.5 * G * HL * HL, HR * unR * unR + 0.5 * G * HR * HR
    den = sR - sL
    both = dryL & dryR
    den = np.where(both | (den == 0), 1.0, den)
    F0 = (sR * FL0 - sL * FR0 + sL * sR * (HR - HL)) / den
    F1 = (sR * FL1 - sL * FR1 + sL * sR * (HR * unR - HL * unL)) / den
    F0 = np.where(sL >= 0, FL0, np.where(sR <= 0, FR0, F0))
    F1 = np.where(sL >= 0, FL1, np.where(sR <= 0, FR1, F1))
    F0 = np.where(both, 0.0, F0)
    F1 = np.where(both, 0.0, F1)
    F2 = F0 * np.where(F0 >= 0, utL, utR)
    smax = np.where(both, 0.0, np.maximum(np.abs(sL), np.abs(sR)))
    return F0, F1, F2, smax


# ── Forcings ─────────────────────────────────────────────────────────────────

def make_signal(spec, default=0.0):
    """Time function from {'value': c} | {'constituents': [...], 'z0'} | {'series': {'t': [...], 'v': [...]}}
    (+ optional 'ramp' seconds: smooth 0 → 1 start of the oscillating part)."""
    from app.geodata.forcing import tide
    if spec is None:
        return lambda t: default
    if isinstance(spec, (int, float)):
        return lambda t: float(spec)
    ramp = float(spec.get('ramp') or 0)

    def r(t):
        return 1.0 if ramp <= 0 or t >= ramp else 0.5 * (1 - math.cos(math.pi * t / ramp))
    if 'constituents' in spec:
        cons, z0 = spec['constituents'], float(spec.get('z0') or 0)
        return lambda t: z0 + r(t) * float(tide([t], cons, 0.0)[0])
    if 'series' in spec:
        ts = np.asarray(spec['series']['t'], float)
        vs = np.asarray(spec['series']['v'], float)
        v0 = float(vs[0])
        return lambda t: v0 + r(t) * (float(np.interp(t, ts, vs)) - v0)
    v = float(spec.get('value', default))
    return lambda t: v


def wind_vector(spec):
    """(t) → (Wx, Wy) [m/s] from {'speed', 'direction'} (meteorological: direction the wind comes from, degrees
    clockwise from north) or {'series': {'t', 'u', 'v'}}."""
    if spec is None:
        return lambda t: (0.0, 0.0)
    if 'series' in spec:
        s = spec['series']
        ts, us, vs = (np.asarray(s[k], float) for k in ('t', 'u', 'v'))
        return lambda t: (float(np.interp(t, ts, us)), float(np.interp(t, ts, vs)))
    sp, th = float(spec.get('speed', 0)), math.radians(float(spec.get('direction', 0)))
    w = (-sp * math.sin(th), -sp * math.cos(th))
    return lambda t: w


def wind_drag(W):
    """Wu (1982): C_d = (0.8 + 0.065 |W|)·1e-3."""
    return (0.8 + 0.065 * W) * 1e-3


# ── Solver ───────────────────────────────────────────────────────────────────

class ShallowWater:
    """``grid`` SWGrid; ``params`` {manning (scalar or per cell), coriolis_f (scalar / per cell), nu_t, h_dry,
    order (1|2), cfl}; ``boundaries`` {id: {'kind', 'signal' (level / discharge function), 'label'}}."""

    def __init__(self, grid: SWGrid, params: dict, boundaries: dict, wind=None):
        self.g = grid
        self.p = params
        self.h_dry = float(params.get('h_dry', 1e-3))
        self.order = int(params.get('order', 2))
        self.cfl = float(params.get('cfl', 0.45 if self.order == 2 else 0.9))
        n = params.get('manning', 0.0)
        self.n2 = (np.broadcast_to(np.asarray(n, float), (grid.nc,)) ** 2).copy()
        f = params.get('coriolis_f', 0.0)
        self.f = np.broadcast_to(np.asarray(f, float), (grid.nc,)).copy()
        self.nu = float(params.get('nu_t', 0.0))
        self.wind = wind
        self.bnd = boundaries
        kinds = np.array([boundaries.get(b, {}).get('kind', 'wall') if b != 'wall' else 'wall'
                          for b in grid.bid], dtype=object)
        bad = set(kinds) - set(BOUNDARY_KINDS)
        if bad:
            raise ValueError(f'Aguas someras: tipo de contorno desconocido {bad}.')
        self.bkind = kinds
        self.groups = {}
        for name in sorted(set(grid.bid)):
            idx = np.flatnonzero(grid.bid == name)
            self.groups[name] = idx
        self.river = [(name, idx, boundaries[name]['signal']) for name, idx in self.groups.items()
                      if boundaries.get(name, {}).get('kind') == 'river']
        self.level = [(name, idx, boundaries[name]['signal']) for name, idx in self.groups.items()
                      if boundaries.get(name, {}).get('kind') in ('level', 'tide')]
        self.free_idx = np.flatnonzero(kinds == 'free')
        self.wall_idx = np.flatnonzero(kinds == 'wall')
        # depth-averaged tracers (FASE 10.4): unknowns H·c after (H, Hu, Hv); D [m²/s], first-order decay λ [1/s]
        tr = params.get('tracers') or []
        self.ns = len(tr)
        self.D = np.array([float(s.get('D') or 0.0) for s in tr])
        self.lam = np.array([float(s.get('decay') or 0.0) for s in tr])
        nbf = len(grid.bid)
        self.c_ext = np.zeros((self.ns, nbf))               # inflow concentration per boundary face
        self.c_interior = np.zeros(nbf, bool)               # free sides without a value: zero gradient
        for name, idx in self.groups.items():
            b = boundaries.get(name, {})
            ci = b.get('c_in')
            if ci is None:
                self.c_interior[idx] = b.get('kind') == 'free'
            elif self.ns:
                self.c_ext[:, idx] = np.asarray(ci, float).reshape(self.ns, 1)
        self.sources = []
        for s in params.get('sources') or []:
            cell = int(s['cell']) if 'cell' in s else int(grid.locate([s['xy']])[0])
            mass = np.zeros(self.ns) if s.get('mass') is None else np.asarray(s['mass'], float).reshape(self.ns)
            self.sources.append({'cell': cell, 'Q': float(s.get('Q') or 0.0), 'mass': mass,
                                 'factor': s.get('factor') or (lambda t: 1.0), 'label': s.get('label')})
        self._tb = np.zeros((self.ns, len(self.groups)))

    # primitive variables
    def velocity(self, U):
        H = U[0]
        wet = H > self.h_dry
        u = np.where(wet, U[1] / np.where(wet, H, 1), 0.0)
        v = np.where(wet, U[2] / np.where(wet, H, 1), 0.0)
        return u, v, wet

    def _faces(self, U):
        """Face states (left/right for interior faces, interior side for boundary faces)."""
        g = self.g
        H = U[0]
        u, v, wet = self.velocity(U)
        eta = H + g.zb
        w = np.stack([eta, u, v])
        if self.ns:
            with np.errstate(divide='ignore', invalid='ignore'):
                c = np.where(H > 1e-12, U[3:] / np.where(H > 1e-12, H, 1.0), 0.0)
            w = np.vstack([w, c])
        if self.order == 2:
            d = g.increments(*g.gradient(w))
            phi = g.limit(w, d)
            # first order where the cell or a neighbour is (nearly) dry
            near = H < 10 * self.h_dry
            nn = near[g.nb]
            phi[:, near | nn[:, 0] | nn[:, 1] | nn[:, 2]] = 0.0
            Wc = w[:, :, None] + phi[:, :, None] * d
            dry_side = (Wc[0] - g.zf) <= 0                          # partly dry with the reconstruction → order 1
            rows = dry_side[:, 0] | dry_side[:, 1] | dry_side[:, 2]
            if rows.any():
                Wc[:, rows, :] = w[:, rows, None]
        else:
            Wc = np.repeat(w[:, :, None], 3, axis=2)
        # bed seen by each side: the continuous P1 bed at the edge midpoint where the cell is wet on all its edges
        # (consistent on slopes, centred source below), the cell-constant bed (Audusse step) where partly dry
        wet3 = (Wc[0] - g.zf) > 0
        full = wet3[:, 0] & wet3[:, 1] & wet3[:, 2]
        zside = np.where(full[:, None], g.zf, g.zb[:, None])
        self._zside, self._full = zside, full
        wL, wR, wB = Wc[:, g.L, g.sL], Wc[:, g.R, g.sR], Wc[:, g.bc_cell, g.sB]
        return wL, wR, wB, zside[g.L, g.sL], zside[g.R, g.sR], zside[g.bc_cell, g.sB], Wc

    def rhs(self, U, t):
        """dU/dt (3, nc), boundary mass fluxes per group (outward, m³/s) and the max wave speed per cell term."""
        g = self.g
        wL, wR, wB, zL, zR, zB, Wc = self._faces(U)
        HL = np.maximum(wL[0] - zL, 0)
        HR = np.maximum(wR[0] - zR, 0)
        zs = np.maximum(zL, zR)
        HLs = np.maximum(wL[0] - zs, 0)
        HRs = np.maximum(wR[0] - zs, 0)
        nx, ny = g.n[:, 0], g.n[:, 1]
        unL, utL = wL[1] * nx + wL[2] * ny, -wL[1] * ny + wL[2] * nx
        unR, utR = wR[1] * nx + wR[2] * ny, -wR[1] * ny + wR[2] * nx
        F0, F1, F2, smax = hll_flux(HLs, unL, utL, HRs, unR, utR)
        # Audusse correction (pressure of the dropped depth)
        cL = 0.5 * G * (HL * HL - HLs * HLs)
        cR = 0.5 * G * (HR * HR - HRs * HRs)
        Fx, Fy = F1 * nx - F2 * ny, F1 * ny + F2 * nx
        Ln = g.len
        A = g.acc
        dU = np.zeros((3 + self.ns, g.nc))
        dU[0] = A(g.R, F0 * Ln) - A(g.L, F0 * Ln)
        dU[1] = A(g.R, (Fx + cR * nx) * Ln) - A(g.L, (Fx + cL * nx) * Ln)
        dU[2] = A(g.R, (Fy + cR * ny) * Ln) - A(g.L, (Fy + cL * ny) * Ln)
        for k in range(self.ns):
            ft = F0 * np.where(F0 > 0, wL[3 + k], wR[3 + k]) * Ln
            dU[3 + k] = A(g.R, ft) - A(g.L, ft)
        lam = A(g.L, smax * Ln) + A(g.R, smax * Ln)
        # centred bed-slope source of the sloped cells: −g Σ nL (H_side + H)/2 (z_side − z)  (lake at rest exact)
        full = self._full
        if full.any():
            Hs = np.maximum(Wc[0] - self._zside, 0)
            wgt = np.where(full[:, None], -G * 0.5 * (Hs + U[0][:, None]) * (self._zside - g.zb[:, None]), 0.0)
            dU[1] += _sum3(wgt * g.nLx)
            dU[2] += _sum3(wgt * g.nLy)

        # boundary faces
        c = g.bc_cell
        HB = np.maximum(wB[0] - zB, 0)
        bx, by = g.bn[:, 0], g.bn[:, 1]
        unB, utB = wB[1] * bx + wB[2] * by, -wB[1] * by + wB[2] * bx
        Hg, ung, utg = HB.copy(), -unB, utB.copy()            # wall by default
        fi = self.free_idx
        # transmissive: depth mirrored about the cell value (same face jump as the interior faces of a sloping,
        # first-order cell: no spurious control at the outlet; = H_B when the reconstruction is linear and exact)
        Hg[fi], ung[fi] = np.maximum(2 * U[0][c[fi]] - HB[fi], 0), unB[fi]
        for _, idx, sig in self.level:
            eta_ext = sig(t)
            Hg[idx] = np.maximum(eta_ext - zB[idx], 0)
            cin, cg = np.sqrt(G * HB[idx]), np.sqrt(G * Hg[idx])
            ung[idx] = np.where(Hg[idx] > 0, unB[idx] + 2 * (cin - cg), 0.0)
            utg[idx] = utB[idx]
        B0, B1, B2, bs = hll_flux(HB, unB, utB, Hg, ung, utg)
        for _, idx, sig in self.river:                        # imposed discharge: exact mass flux
            Q = float(sig(t))
            Hc = np.maximum(HB[idx], self.h_dry)
            conv = Hc ** (5 / 3) * g.blen[idx]
            qn = -Q * Hc ** (5 / 3) / conv.sum()              # per unit width, inward
            Href = np.maximum(HB[idx], (qn * qn / G) ** (1 / 3))
            B0[idx] = qn
            B1[idx] = qn * qn / Href + 0.5 * G * Href * Href
            B2[idx] = 0.0
            bs[idx] = np.abs(qn) / Href + np.sqrt(G * Href)
        Bx, By = B1 * bx - B2 * by, B1 * by + B2 * bx
        Lb = g.blen
        dU[0] -= A(c, B0 * Lb)
        dU[1] -= A(c, Bx * Lb)
        dU[2] -= A(c, By * Lb)
        lam += A(c, bs * Lb)
        bflux = {name: float(np.sum(B0[idx] * Lb[idx])) for name, idx in self.groups.items()}
        if self.ns:
            cin = np.where(self.c_interior[None], wB[3:], self.c_ext)
            ftb = B0 * np.where(B0 > 0, wB[3:], cin) * Lb
            for k in range(self.ns):
                dU[3 + k] -= A(c, ftb[k])
            self._tb = np.stack([ftb[:, idx].sum(1) for idx in self.groups.values()], 1)
            # horizontal diffusion ∇·(H D ∇c) between wet cells. Face gradient = mean of the LSQ cell gradients
            # corrected along the centroid line: ∇c_f = ḡ + ((c_R − c_L)/d − ḡ·t) t → exact for linear c on any
            # triangulation (the plain two-point flux is inconsistent where t ∦ n). Two-point where a cell is
            # next to a dry one (its gradient would see the dry zeros).
            kd = np.flatnonzero(self.D > 0)
            if len(kd):
                Hc_ = U[0]
                wet_ = Hc_ > self.h_dry
                He = 0.5 * (Hc_[g.L] + Hc_[g.R]) * (wet_[g.L] & wet_[g.R])
                ck = np.where(wet_, U[3 + kd] / np.where(wet_, Hc_, 1.0), 0.0)
                gx, gy = g.gradient(ck)
                near = ~wet_ | ~wet_[g.nb].all(1)
                ok = ~(near[g.L] | near[g.R])
                tx, ty = g.tvec[:, 0], g.tvec[:, 1]
                tn = tx * g.n[:, 0] + ty * g.n[:, 1]
                mx, my = 0.5 * (gx[:, g.L] + gx[:, g.R]), 0.5 * (gy[:, g.L] + gy[:, g.R])
                dct = (ck[:, g.R] - ck[:, g.L]) / g.dist
                gn = np.where(ok, mx * g.n[:, 0] + my * g.n[:, 1] + (dct - mx * tx - my * ty) * tn, dct)
                for j, k in enumerate(kd):
                    fl = self.D[k] * He * gn[j] * Ln
                    dU[3 + k] += A(g.L, fl) - A(g.R, fl)
        # point sources (outfalls): water Q [m³/s] and tracer mass [c·m³/s] into their cell
        self._src = np.zeros(1 + self.ns)
        for s in self.sources:
            fct = float(s['factor'](t))
            dU[0][s['cell']] += s['Q'] * fct
            self._src[0] += s['Q'] * fct
            if self.ns:
                dU[3:, s['cell']] += s['mass'] * fct
                self._src[1:] += s['mass'] * fct

        dU /= g.area
        # wind (explicit)
        if self.wind is not None:
            Wx, Wy = self.wind(t)
            W = math.hypot(Wx, Wy)
            if W > 0:
                k = RHO_AIR / self.p.get('rho', 1025.0) * wind_drag(W) * W
                wet = U[0] > self.h_dry
                dU[1] += np.where(wet, k * Wx, 0.0)
                dU[2] += np.where(wet, k * Wy, 0.0)
        # horizontal viscosity ∇·(H ν ∇u) (explicit, two-point flux)
        if self.nu > 0:
            u, v, wet = self.velocity(U)
            He = 0.5 * (U[0][g.L] + U[0][g.R]) * (wet[g.L] & wet[g.R])
            for comp, q in ((1, u), (2, v)):
                fl = self.nu * He * (q[g.R] - q[g.L]) / g.dist * g.len
                dU[comp] += (A(g.L, fl) - A(g.R, fl)) / g.area
        return dU, bflux, lam / g.area

    def _sources_split(self, U, dt):
        """Manning (semi-implicit) and Coriolis (exact rotation) after the RK step; dry cells lose momentum."""
        H = U[0]
        wet = H > self.h_dry
        if np.any(self.n2 > 0):
            u, v, _ = self.velocity(U)
            sp = np.hypot(u, v)
            with np.errstate(divide='ignore', invalid='ignore'):
                k = np.where(wet, dt * G * self.n2 * sp / np.where(wet, H, 1) ** (4 / 3), 0.0)
            U[1] /= 1 + k
            U[2] /= 1 + k
        if np.any(self.f != 0):
            th = self.f * dt
            c, s = np.cos(th), np.sin(th)
            hu, hv = U[1].copy(), U[2].copy()
            U[1] = c * hu + s * hv
            U[2] = -s * hu + c * hv
        U[1][~wet] = 0.0
        U[2][~wet] = 0.0
        self._decayed = np.zeros(self.ns)
        for k in range(self.ns):
            if self.lam[k] > 0:
                before = U[3 + k].copy()
                U[3 + k] *= math.exp(-self.lam[k] * dt)
                self._decayed[k] = float(np.sum(self.g.area * (before - U[3 + k])))
        return U

    def dt_from(self, lam, U):
        dt = self.cfl / max(float(lam.max()), 1e-300)
        nu = max(self.nu, float(self.D.max()) if self.ns else 0.0)
        if nu > 0:
            dt = min(dt, 0.25 * float(np.min(self.g.dist)) ** 2 / nu)
        return dt

    def step(self, U, t, dt_max):
        """One SSP-RK2 step; returns (U, dt, boundary volumes over the step {id: m³ outward}, clipped mass)."""
        k1, b1, lam = self.rhs(U, t)
        t1, s1 = self._tb.copy(), self._src.copy()
        self.dt_cfl = self.dt_from(lam, U)
        dt = min(self.dt_cfl, dt_max)
        U1 = U + dt * k1
        clip1 = self._clip(U1)
        k2, b2, _ = self.rhs(U1, t + dt)
        Un = 0.5 * (U + U1 + dt * k2)
        clip2 = self._clip(Un)
        clip = 0.5 * clip1 + clip2                  # stage-1 clipping enters the average with weight ½
        Un = self._sources_split(Un, dt)
        vol = {k: 0.5 * dt * (b1[k] + b2[k]) for k in b1}
        self.last = {'tracer_out': 0.5 * dt * (t1 + self._tb), 'source': 0.5 * dt * (s1 + self._src),
                     'decayed': self._decayed, 'clipped': clip}
        return Un, dt, vol, float(clip[0])

    def _clip(self, U):
        """Negative depths → 0 (with their tracer); negative tracer mass → 0. Removed volume / mass per row."""
        A = self.g.area
        out = np.zeros(1 + self.ns)
        neg = U[0] < 0
        if neg.any():
            out[0] = -float(np.sum(A[neg] * U[0][neg]))
            U[0][neg] = 0.0
            if self.ns:
                out[1:] -= np.sum(A[neg] * U[3:, neg], axis=1)       # mass removed with the dried cell
                U[3:, neg] = 0.0
        if self.ns:
            m = U[3:] < 0
            if m.any():
                out[1:] -= np.sum(np.where(m, A * U[3:], 0.0), axis=1)
                U[3:][m] = 0.0
        return out


def solve(grid: SWGrid, params: dict, boundaries: dict, *, t_end: float, eta0=0.0, U0=None, wind=None,
          n_output: int = 24, probes=None, progress=None, max_steps: int = 2_000_000, c0=None) -> dict:
    """Run to ``t_end`` [s]. Returns snapshots [(t, U)], budget, probes and statistics. With ``params['tracers']``
    the rows 3.. of U are H·c per species; ``c0`` (ns, nc) or per-species scalars = initial concentration."""
    sw = ShallowWater(grid, params, boundaries, wind=wind)
    ns = sw.ns
    if U0 is None:
        eta = np.broadcast_to(np.asarray(eta0, float), (grid.nc,))
        U = np.zeros((3 + ns, grid.nc))
        U[0] = np.maximum(eta - grid.zb, 0)
        if ns and c0 is not None:
            U[3:] = U[0] * np.broadcast_to(np.asarray(c0, float).reshape(ns, -1), (ns, grid.nc))
    else:
        U = np.array(U0, float)
        if len(U) != 3 + ns:
            raise ValueError(f'U0 must have {3 + ns} rows.')
    mass0 = float(np.sum(grid.area * U[0]))
    tmass0 = np.sum(grid.area * U[3:], axis=1) if ns else np.zeros(0)
    t_out = np.zeros((ns, len(sw.groups)))
    t_in = np.zeros((ns, len(sw.groups)))
    t_src, t_dec, t_clip = np.zeros(ns), np.zeros(ns), np.zeros(ns)
    w_src = 0.0
    thr = np.array([s.get('threshold') if s.get('threshold') is not None else np.inf
                    for s in params.get('tracers') or []], float)
    cmax = np.zeros((ns, grid.nc))
    t_above = np.zeros((ns, grid.nc))
    out_t = np.linspace(0, t_end, n_output + 1)[1:]
    snaps = [(0.0, U.copy())]
    vol = {k: 0.0 for k in sw.groups}
    vol_in = {k: 0.0 for k in sw.groups}
    clipped = 0.0
    t, k_out, n_steps = 0.0, 0, 0
    pcells = grid.locate([p['xy'] for p in probes]) if probes else None
    prows = []
    smax = np.zeros(grid.nc)
    wet_ever = U[0] > sw.h_dry
    hmax = np.where(wet_ever, U[0] + grid.zb, -np.inf)          # highest water level reached (wet cells)
    wet0 = wet_ever.copy()
    dts = []
    t0 = _time.perf_counter()
    while t < t_end - 1e-9 * t_end:
        target = out_t[k_out]
        U, dt, v, cl = sw.step(U, t, target - t)
        if not np.all(np.isfinite(U)):
            raise ValueError(f'Aguas someras: la solución diverge en t = {t:.4g} s (reduzca el CFL o revise los '
                             f'contornos).')
        t += dt
        n_steps += 1
        dts.append(sw.dt_cfl)                       # stability step (the last one before an output is shortened)
        clipped += cl
        last = sw.last
        w_src += float(last['source'][0])
        if ns:
            t_out += last['tracer_out']
            t_in += -np.minimum(last['tracer_out'], 0.0)
            t_src += last['source'][1:]
            t_dec += last['decayed']
            t_clip += last['clipped'][1:]
            H_ = U[0]
            cc = np.where(H_ > sw.h_dry, U[3:] / np.where(H_ > sw.h_dry, H_, 1.0), 0.0)
            np.maximum(cmax, cc, out=cmax)
            t_above += dt * (cc > thr[:, None])
        for k_, val in v.items():
            vol[k_] += val
            vol_in[k_] += -min(val, 0.0)
        u, vv, wet = sw.velocity(U)
        sp = np.hypot(u, vv)
        np.maximum(smax, sp, out=smax)
        np.maximum(hmax, U[0] + grid.zb, out=hmax, where=wet)
        wet_ever |= wet
        if pcells is not None:
            row = [t] + [x for c in pcells for x in (U[0][c] + grid.zb[c], u[c], vv[c], U[0][c])]
            if ns:
                row += [float(cc[k, c]) for c in pcells for k in range(ns)]
            prows.append(row)
        if t >= target - 1e-9 * max(t_end, 1):
            snaps.append((t, U.copy()))
            k_out += 1
            if progress:
                progress(k_out, n_output, t)
            if k_out >= len(out_t):
                break
        if n_steps >= max_steps:
            raise ValueError(f'Aguas someras: más de {max_steps:,} pasos de tiempo (Δt {dt:.3g} s); reduzca t_end o '
                             f'engrose la malla.')
    mass1 = float(np.sum(grid.area * U[0]))
    net_out = sum(vol.values())
    scale = max(mass0, abs(sum(vol_in.values())), w_src, 1e-30)
    balance = (mass1 - mass0 + net_out - clipped - w_src) / scale
    tracers = []
    names = list(sw.groups)
    for k in range(ns):
        m1 = float(np.sum(grid.area * U[3 + k]))
        sc = max(tmass0[k], float(t_in[k].sum()), t_src[k], 1e-300)
        tracers.append({'mass0': float(tmass0[k]), 'mass1': m1, 'source': float(t_src[k]), 'decayed': float(t_dec[k]),
                        'clipped': float(t_clip[k]),
                        'boundary_out': {n_: float(t_out[k, j]) for j, n_ in enumerate(names)},
                        'boundary_in': {n_: float(t_in[k, j]) for j, n_ in enumerate(names)},
                        'balance_error': abs(m1 - tmass0[k] + float(t_out[k].sum()) - t_src[k] + t_dec[k]
                                             - t_clip[k]) / sc})
    u, vv, wet = sw.velocity(U)
    fr = np.where(wet, np.hypot(u, vv) / np.sqrt(G * np.maximum(U[0], 1e-12)), 0.0)
    return {'snaps': snaps, 'n_steps': n_steps, 'dt_min': float(min(dts)) if dts else 0.0,
            'dt_max': float(max(dts)) if dts else 0.0, 'mass0': mass0, 'mass1': mass1,
            'boundary_volume_out': vol, 'boundary_volume_in': vol_in, 'clipped_mass': clipped,
            'balance_error': float(abs(balance)), 'max_speed': smax, 'max_eta': hmax, 'wet_ever': wet_ever,
            'wet0': wet0, 'froude_max': float(fr.max()) if fr.size else 0.0, 'probe_cells': pcells,
            'probe_rows': prows, 'wall_time_s': _time.perf_counter() - t0, 'solver': sw, 'source_volume': w_src,
            'tracers': tracers, 'cmax': cmax, 't_above': t_above}


# ── Test meshes ──────────────────────────────────────────────────────────────

def rect_grid(xs, ys, bed=None, crisscross: bool = True):
    """Rectangle [xs] × [ys] split into triangles (alternating diagonals), boundaries x0 x1 y0 y1.
    ``bed(x, y)`` = depth [m, positive down] at the nodes."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    nx, ny = len(xs), len(ys)
    X, Y = np.meshgrid(xs, ys)
    nodes = np.column_stack([X.ravel(), Y.ravel()])
    idx = np.arange(nx * ny).reshape(ny, nx)
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = idx[j, i], idx[j, i + 1], idx[j + 1, i + 1], idx[j + 1, i]
            if not crisscross or (i + j) % 2 == 0:
                tris += [[a, b, c], [a, c, d]]
            else:
                tris += [[a, b, d], [b, c, d]]
    bnd = {'x0': np.column_stack([idx[:-1, 0], idx[1:, 0]]), 'x1': np.column_stack([idx[:-1, -1], idx[1:, -1]]),
           'y0': np.column_stack([idx[0, :-1], idx[0, 1:]]), 'y1': np.column_stack([idx[-1, :-1], idx[-1, 1:]])}
    depth = bed(nodes[:, 0], nodes[:, 1]) if bed is not None else np.zeros(len(nodes))
    return nodes, np.asarray(tris), depth, bnd
