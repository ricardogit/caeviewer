"""3-D hydrostatic stratified flow in σ layers (FASE 10.4) on the 2-D water-domain mesh (FASE 10.5).

Multilayer Saint-Venant system with mass exchange (Audusse, Bristeau, Perthame & Sainte-Marie 2011; Audusse,
Bristeau, Pelanti & Sainte-Marie 2011): the water column of each triangle is split into L layers of fixed
fractions l_α of the depth H (σ layers, α = 0 at the bed). Unknowns per cell: H, h_α u_α, h_α v_α (h_α = l_α H)
and the layer contents h_α c_α of the tracers (temperature, salinity, passive species).

    ∂H/∂t + Σ_α ∇·(h_α u_α) = 0
    ∂h_α/∂t + ∇·(h_α u_α) = G_{α+½} − G_{α−½}                       (G = mass exchange through σ surfaces)
    ∂(h_α u_α)/∂t + ∇·(h_α u_α⊗u_α) + g h_α ∇η = −h_α (∇_σ P'_α + b_α ∇_σ z_α)  (baroclinic, σ-corrected)
        + u_{α+½}G_{α+½} − u_{α−½}G_{α−½} + vertical stresses (bed drag, wind) − f k×(h_α u_α)
    ∂(h_α c_α)/∂t + ∇·(h_α u_α c_α) = c_{α+½}G_{α+½} − c_{α−½}G_{α−½} + ∂_z(κ ∂_z c) + ∇·(h_α D ∇c_α)

Horizontal fluxes: the HLL solver of the 2-D model applied per layer with **common** wave speeds (total depth,
extreme layer velocities) and the same hydrostatic reconstruction / P1 bed → the layer fluxes sum exactly to the
2-D flux: a column moving as a block reproduces the 2-D model to round-off, the lake at rest is exact for any
number of layers, and a uniform tracer stays uniform. G follows from the layer mass divergences (upwind vertical
advection). Buoyancy b = g(ρ − ρ₀)/ρ₀ from ρ(T, S) (linear or UNESCO 1981 at p = 0); P'_α = ∫_{z_α}^η b dz.
Vertical processes are split after each SSP-RK2 step and solved implicitly per column (tridiagonal): viscosity /
diffusivity from a closure (``constant`` ν_v, κ_v or ``k_epsilon``: 1-D k-ε on the layer interfaces with buoyancy
production, c₃⁻ from the steady Richardson number, Galperin length limit, log-law Dirichlet values at the bed and
under the wind), quadratic bed drag on the bottom layer (log law from the roughness z₀, or Manning), wind stress
on the top layer. Coriolis = exact rotation per layer.
"""
from __future__ import annotations

import math
import time as _time

import numpy as np

from .shallow_water import G, RHO_AIR, BOUNDARY_KINDS, SWGrid, _sum3, wind_drag

KAPPA = 0.41
CLOSURES = ('constant', 'k_epsilon')
EOS = ('linear', 'unesco')


# ── Equation of state ────────────────────────────────────────────────────────

def density_unesco(T, S):
    """UNESCO 1981 (Millero & Poisson) density at atmospheric pressure [kg/m³], T [°C], S [psu]."""
    T, S = np.asarray(T, float), np.maximum(np.asarray(S, float), 0.0)
    rw = 999.842594 + T * (6.793952e-2 + T * (-9.095290e-3 + T * (1.001685e-4 + T * (-1.120083e-6 + T * 6.536332e-9))))
    a = 0.824493 + T * (-4.0899e-3 + T * (7.6438e-5 + T * (-8.2467e-7 + T * 5.3875e-9)))
    b = -5.72466e-3 + T * (1.0227e-4 - T * 1.6546e-6)
    return rw + a * S + b * S ** 1.5 + 4.8314e-4 * S * S


def make_eos(spec: dict | None, rho0: float):
    """(T, S) → ρ. ``{'model': 'linear', 'T_ref', 'S_ref', 'alpha', 'beta', 'rho_ref'}`` or ``{'model': 'unesco'}``."""
    spec = dict(spec or {})
    model = spec.get('model', 'linear')
    if model not in EOS:
        raise ValueError(f'Estratificado: ecuación de estado desconocida «{model}» ({" | ".join(EOS)}).')
    if model == 'unesco':
        return density_unesco
    rr = float(spec.get('rho_ref', rho0))
    T0, S0 = float(spec.get('T_ref', 10.0)), float(spec.get('S_ref', 35.0))
    al, be = float(spec.get('alpha', 2e-4)), float(spec.get('beta', 7.6e-4))
    return lambda T, S: rr * (1 - al * (np.asarray(T) - T0) + be * (np.asarray(S) - S0))


# ── Riemann solver per layer ─────────────────────────────────────────────────

def hll_layers(HL, unL, utL, HR, unR, utR, frac):
    """Layer fluxes (L, nf) through a face, wave speeds common to the column (total depth, extreme layer
    velocities). Mass: HLL of each layer state (dissipation acts on the depth only). Momentum: each layer's
    momentum upwinded by its own mass flux + the fraction of the **depth-averaged** HLL pressure / dissipation
    term (F1 − F0 ū_up of the 2-D flux of (H, ū)). The HLL momentum dissipation s_L s_R Δ(H u_α) would otherwise
    damp baroclinic velocity differences with the external wave speed (ν ~ √(gH) Δx/2: internal waves vanish).
    A column moving as a block gets exactly the fractions of the 2-D flux; the sum over layers of the mass flux is
    the 2-D mass flux of the depth-averaged state. Returns F0, F1, F2 (L, nf) and the max wave speed (nf)."""
    cL, cR = np.sqrt(G * HL), np.sqrt(G * HR)
    sL = np.minimum(unL.min(0) - cL, unR.min(0) - cR)
    sR = np.maximum(unL.max(0) + cL, unR.max(0) + cR)
    dryL, dryR = HL <= 0, HR <= 0
    sL = np.where(dryL, unR.min(0) - 2 * cR, sL)
    sR = np.where(dryR, unL.max(0) + 2 * cL, sR)
    fr = frac[:, None]
    den = sR - sL
    both = dryL & dryR
    den = np.where(both | (den == 0), 1.0, den)
    supL, supR = sL >= 0, sR <= 0

    def hll(FL, FR, UL, UR):
        F = (sR * FL - sL * FR + sL * sR * (UR - UL)) / den
        return np.where(both, 0.0, np.where(supL, FL, np.where(supR, FR, F)))
    F0 = hll(HL * unL, HR * unR, HL, HR) * fr                       # layer mass fluxes
    ubL, ubR = (fr * unL).sum(0), (fr * unR).sum(0)                  # depth-averaged normal velocity
    F0b = hll(HL * ubL, HR * ubR, HL, HR)
    F1b = hll(HL * ubL * ubL + 0.5 * G * HL * HL, HR * ubR * ubR + 0.5 * G * HR * HR, HL * ubL, HR * ubR)
    P = F1b - F0b * np.where(F0b >= 0, ubL, ubR)                     # pressure + barotropic dissipation
    up = F0 >= 0
    F1 = F0 * np.where(up, unL, unR) + fr * P
    F2 = F0 * np.where(up, utL, utR)
    smax = np.where(both, 0.0, np.maximum(np.abs(sL), np.abs(sR)))
    return F0, F1, F2, smax


def thomas(a, b, c, d):
    """Tridiagonal solve along axis 0 for many columns: a sub (a[0] unused), b diag, c super (c[-1] unused)."""
    n = len(b)
    cp = np.empty_like(b)
    dp = np.empty_like(d)
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.empty_like(d)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def profile_values(spec, depth_below_surface):
    """Initial / boundary value: scalar, callable(d) or [[depth_m, value], ...] (depth below the surface)."""
    if spec is None:
        return None
    if callable(spec):
        return np.asarray(spec(depth_below_surface), float)
    if isinstance(spec, (int, float)):
        return np.full(np.shape(depth_below_surface), float(spec))
    pts = np.asarray(spec, float).reshape(-1, 2)
    o = np.argsort(pts[:, 0])
    return np.interp(depth_below_surface, pts[o, 0], pts[o, 1])


def roughness_from_manning(n):
    """Strickler: n = k_s^{1/6}/21.1 → z₀ = k_s/30."""
    return (21.1 * n) ** 6 / 30.0


# ── Solver ───────────────────────────────────────────────────────────────────

class Stratified3D:
    """``params``: layers (int) or layer_fractions (bottom → top), rho (ρ₀), eos {...}, temperature / salinity
    (bool, or initial value / profile), tracers [{name, D, decay}] (passive), closure constant|k_epsilon,
    nu_v, kappa_v (background / constant), bottom_roughness z₀ [m] | manning, coriolis_f, nu_t (horizontal), D_h
    (horizontal diffusivity of T, S), h_dry, order, cfl, keps {...}."""

    def __init__(self, grid: SWGrid, params: dict, boundaries: dict, wind=None):
        self.g = grid
        self.p = params
        fr = params.get('layer_fractions')
        if fr is None:
            nl = int(params.get('layers', 10))
            if nl < 1:
                raise ValueError('Estratificado: el número de capas debe ser ≥ 1.')
            fr = np.full(nl, 1.0 / nl)
        fr = np.asarray(fr, float)
        if np.any(fr <= 0):
            raise ValueError('Estratificado: fracciones de capa no positivas.')
        self.frac = fr / fr.sum()
        self.nl = L = len(self.frac)
        self.s = np.r_[0.0, np.cumsum(self.frac)]               # σ of the interfaces (0 bed … 1 surface)
        self.s[-1] = 1.0
        self.sc = 0.5 * (self.s[:-1] + self.s[1:])           # σ of the layer centres
        self.rho0 = float(params.get('rho', 1025.0))
        self.h_dry = float(params.get('h_dry', 1e-3))
        self.order = int(params.get('order', 2))
        self.cfl = float(params.get('cfl', 0.45 if self.order == 2 else 0.9))
        f = params.get('coriolis_f', 0.0)
        self.f = np.broadcast_to(np.asarray(f, float), (grid.nc,)).copy()
        self.nu_h = float(params.get('nu_t', 0.0))
        self.wind = wind
        self.bnd = boundaries
        # bed drag
        # bed roughness z₀ per cell [m]: given, or from Manning n (Strickler k_s, z₀ = k_s/30); log-law drag on the
        # bottom layer
        n = params.get('manning')
        z0 = params.get('bottom_roughness')
        if z0 is None:
            z0 = roughness_from_manning(np.asarray(n, float)) if n is not None and np.any(np.asarray(n) > 0) else 1e-3
        self.z0b = np.maximum(np.broadcast_to(np.asarray(z0, float), (grid.nc,)).copy(), 1e-6)
        self.cd_min = float(params.get('cd_min', 0.0))
        # tracers: T, S (active), then passive species
        self.names, self.D, self.lam = [], [], []
        self.iT = self.iS = None
        self.c_init = []
        if params.get('temperature') is not None and params.get('temperature') is not False:
            self.iT = len(self.names)
            self.names.append('T')
            self.D.append(float(params.get('D_h', 0.0)))
            self.lam.append(0.0)
            self.c_init.append(params.get('temperature') if params.get('temperature') is not True else 10.0)
        if params.get('salinity') is not None and params.get('salinity') is not False:
            self.iS = len(self.names)
            self.names.append('S')
            self.D.append(float(params.get('D_h', 0.0)))
            self.lam.append(0.0)
            self.c_init.append(params.get('salinity') if params.get('salinity') is not True else 35.0)
        self.passive = params.get('tracers') or []
        self.c_threshold = [None] * len(self.names)
        for s in self.passive:
            self.c_threshold.append(s.get('threshold'))
            self.names.append(s.get('name', f'c{len(self.names)}'))
            self.D.append(float(s.get('D') or 0.0))
            self.lam.append(float(s.get('decay') or 0.0))
            self.c_init.append(s.get('c0', 0.0))
        self.nt = len(self.names)
        self.D, self.lam = np.asarray(self.D, float), np.asarray(self.lam, float)
        self.active = self.iT is not None or self.iS is not None
        self.eos = make_eos(params.get('eos'), self.rho0)
        self.T_const = float(params.get('T_const', 10.0))
        self.S_const = float(params.get('S_const', 0.0 if self.iS is None else 35.0))
        # closure
        self.closure = params.get('closure', 'constant')
        if self.closure not in CLOSURES:
            raise ValueError(f'Estratificado: cierre vertical desconocido «{self.closure}» ({" | ".join(CLOSURES)}).')
        self.nu_b = float(params.get('nu_v', 1e-6 if self.closure == 'k_epsilon' else 1e-3))
        self.ka_b = float(params.get('kappa_v', 1e-7 if self.closure == 'k_epsilon' else self.nu_b))
        ke = dict(params.get('keps') or {})
        self.cmu = ke.get('c_mu', 0.09)
        self.c1, self.c2 = ke.get('c1', 1.44), ke.get('c2', 1.92)
        self.sk, self.se = ke.get('sigma_k', 1.0), ke.get('sigma_eps', 1.3)
        self.prt = ke.get('prandtl', 1.0)
        ri = ke.get('ri_st', 0.25)
        self.c3m = self.c2 - (self.c2 - self.c1) * self.prt / ri       # stable stratification (B < 0)
        self.c3p = ke.get('c3_plus', 1.0)
        self.k_min, self.eps_min = ke.get('k_min', 1e-9), ke.get('eps_min', 1e-12)
        self.galperin = ke.get('galperin', 0.53)
        self.z0s = ke.get('z0_surface', 0.02)
        nc = grid.nc
        self.k = np.full((L + 1, nc), self.k_min)
        self.eps = np.full((L + 1, nc), self.eps_min)
        self.nut = np.zeros((L + 1, nc))
        self.kat = np.zeros((L + 1, nc))
        # boundaries
        kinds = np.array([boundaries.get(b, {}).get('kind', 'wall') if b != 'wall' else 'wall'
                          for b in grid.bid], dtype=object)
        bad = set(kinds) - set(BOUNDARY_KINDS)
        if bad:
            raise ValueError(f'Estratificado: tipo de contorno desconocido {bad}.')
        self.groups = {name: np.flatnonzero(grid.bid == name) for name in sorted(set(grid.bid))}
        self.river = [(nm, idx, boundaries[nm]['signal']) for nm, idx in self.groups.items()
                      if boundaries.get(nm, {}).get('kind') == 'river']
        self.level = [(nm, idx, boundaries[nm]['signal']) for nm, idx in self.groups.items()
                      if boundaries.get(nm, {}).get('kind') in ('level', 'tide')]
        self.free_idx = np.flatnonzero(kinds == 'free')
        nbf = len(grid.bid)
        self.c_ext = np.zeros((self.nt, L, nbf))
        self.c_interior = np.zeros((self.nt, nbf), bool)
        for nm, idx in self.groups.items():
            b = boundaries.get(nm, {})
            ci = b.get('c_in')
            if ci is None:
                self.c_interior[:, idx] = b.get('kind') == 'free'
                if b.get('kind') in ('level', 'tide', 'river'):
                    # no inflow value given: a scalar initial value enters, a profile → zero gradient
                    for k in range(self.nt):
                        v0 = self.c_init[k]
                        if isinstance(v0, (int, float)):
                            self.c_ext[k][:, idx] = float(v0)
                        else:
                            self.c_interior[k, idx] = True
            elif self.nt:
                ci = list(ci) if isinstance(ci, (list, tuple, np.ndarray)) else [ci]
                for k in range(self.nt):
                    v = ci[k] if k < len(ci) else 0.0
                    if v is None:                                   # this tracer: zero gradient (interior value)
                        self.c_interior[k, idx] = True
                    elif isinstance(v, (list, tuple, np.ndarray)) and len(np.atleast_1d(v)) == L:
                        self.c_ext[k][:, idx] = np.asarray(v, float)[:, None]      # per-layer profile (bed → top)
                    else:
                        self.c_ext[k][:, idx] = float(v)
        self.sources = []
        for s in params.get('sources') or []:
            cell = int(s['cell']) if 'cell' in s else int(grid.locate([s['xy']])[0])
            mass = np.zeros(self.nt) if s.get('mass') is None else np.asarray(s['mass'], float).reshape(self.nt)
            sg = s.get('sigma')
            if sg is None:
                wq = self.frac.copy()
            else:
                wq = np.zeros(L)
                wq[min(int(np.searchsorted(self.s, float(sg), side='right')) - 1, L - 1)] = 1.0
            self.sources.append({'cell': cell, 'Q': float(s.get('Q') or 0.0), 'mass': mass, 'w': wq,
                                 'factor': s.get('factor') or (lambda t: 1.0), 'label': s.get('label')})
        self._tb = np.zeros((self.nt, len(self.groups)))
        self.nrow = 1 + 2 * L + self.nt * L
        self._lamv = np.zeros(nc)

    # layout helpers
    def split(self, U):
        L, nc = self.nl, self.g.nc
        return U[0], U[1:1 + L], U[1 + L:1 + 2 * L], U[1 + 2 * L:].reshape(self.nt, L, nc)

    def primitive(self, U):
        H, hu, hv, hc = self.split(U)
        wet = H > self.h_dry
        h = self.frac[:, None] * np.where(wet, H, 1.0)
        u = np.where(wet, hu / h, 0.0)
        v = np.where(wet, hv / h, 0.0)
        with np.errstate(divide='ignore', invalid='ignore'):
            hh = self.frac[:, None] * H
            c = np.where(hh > 1e-12, hc / np.where(hh > 1e-12, hh, 1.0), 0.0)
        return u, v, c, wet

    def initial_state(self, eta0=0.0):
        g = self.g
        U = np.zeros((self.nrow, g.nc))
        eta = np.broadcast_to(np.asarray(eta0, float), (g.nc,))
        H = np.maximum(eta - g.zb, 0)
        U[0] = H
        _, _, _, hc = self.split(U)
        d = (1 - self.sc[:, None]) * H[None]                 # depth of the layer centres below the surface
        for k in range(self.nt):
            v = profile_values(self.c_init[k], d)
            hc[k] = self.frac[:, None] * H * (0.0 if v is None else v)
        return U

    def density(self, c):
        """ρ per layer (L, nc) from the tracer values."""
        T = c[self.iT] if self.iT is not None else self.T_const
        S = c[self.iS] if self.iS is not None else self.S_const
        return np.broadcast_to(self.eos(T, S), c.shape[1:]) if self.nt else None

    def _acc(self, idx, W):
        k = W.shape[0]
        nc = self.g.nc
        off = (np.arange(k) * nc)[:, None] + idx[None]
        return np.bincount(off.ravel(), weights=W.ravel(), minlength=k * nc).reshape(k, nc)

    # ── horizontal step (RK right-hand side) ────────────────────────────────
    def rhs(self, U, t):
        g, L, nt, fr = self.g, self.nl, self.nt, self.frac
        if self.p.get('horizontal') is False:                 # 1-D water columns (tests): vertical physics only
            self._tb = np.zeros((nt, len(self.groups)))
            self._src = np.zeros(1 + nt)
            self._lamv = np.zeros(g.nc)
            return np.zeros_like(U), {k: 0.0 for k in self.groups}, np.full(g.nc, 1.0 / float(self.p['dt']))
        H = U[0]
        u, v, c, wet = self.primitive(U)
        eta = H + g.zb
        w = np.vstack([eta[None], u, v, c.reshape(nt * L, g.nc)])
        if self.order == 2:
            d = g.increments(*g.gradient(w))
            phi = g.limit(w, d)
            near = H < 10 * self.h_dry
            nn = near[g.nb]
            phi[:, near | nn[:, 0] | nn[:, 1] | nn[:, 2]] = 0.0
            Wc = w[:, :, None] + phi[:, :, None] * d
            dry_side = (Wc[0] - g.zf) <= 0
            rows = dry_side[:, 0] | dry_side[:, 1] | dry_side[:, 2]
            if rows.any():
                Wc[:, rows, :] = w[:, rows, None]
        else:
            Wc = np.repeat(w[:, :, None], 3, axis=2)
        wet3 = (Wc[0] - g.zf) > 0
        full = wet3[:, 0] & wet3[:, 1] & wet3[:, 2]
        zside = np.where(full[:, None], g.zf, g.zb[:, None])
        wL, wR, wB = Wc[:, g.L, g.sL], Wc[:, g.R, g.sR], Wc[:, g.bc_cell, g.sB]
        zL, zR, zB = zside[g.L, g.sL], zside[g.R, g.sR], zside[g.bc_cell, g.sB]
        iu, iv = slice(1, 1 + L), slice(1 + L, 1 + 2 * L)
        ic = slice(1 + 2 * L, None)
        HL = np.maximum(wL[0] - zL, 0)
        HR = np.maximum(wR[0] - zR, 0)
        zs = np.maximum(zL, zR)
        HLs = np.maximum(wL[0] - zs, 0)
        HRs = np.maximum(wR[0] - zs, 0)
        nx, ny = g.n[:, 0], g.n[:, 1]
        unL, utL = wL[iu] * nx + wL[iv] * ny, -wL[iu] * ny + wL[iv] * nx
        unR, utR = wR[iu] * nx + wR[iv] * ny, -wR[iu] * ny + wR[iv] * nx
        F0, F1, F2, smax = hll_layers(HLs, unL, utL, HRs, unR, utR, fr)
        cL = 0.5 * G * (HL * HL - HLs * HLs) * fr[:, None]
        cR = 0.5 * G * (HR * HR - HRs * HRs) * fr[:, None]
        Fx, Fy = F1 * nx - F2 * ny, F1 * ny + F2 * nx
        Ln = g.len
        A = self._acc
        Dm = A(g.R, F0 * Ln) - A(g.L, F0 * Ln)
        Dx = A(g.R, (Fx + cR * nx) * Ln) - A(g.L, (Fx + cL * nx) * Ln)
        Dy = A(g.R, (Fy + cR * ny) * Ln) - A(g.L, (Fy + cL * ny) * Ln)
        Dc = np.zeros((nt, L, g.nc))
        if nt:
            cLf, cRf = wL[ic].reshape(nt, L, -1), wR[ic].reshape(nt, L, -1)
            ft = (F0 * Ln)[None] * np.where(F0[None] > 0, cLf, cRf)
            Dc = (A(g.R, ft.reshape(nt * L, -1)) - A(g.L, ft.reshape(nt * L, -1))).reshape(nt, L, g.nc)
        lam = g.acc(g.L, smax * Ln) + g.acc(g.R, smax * Ln)
        if full.any():
            Hs = np.maximum(Wc[0] - zside, 0)
            wgt = np.where(full[:, None], -G * 0.5 * (Hs + H[:, None]) * (zside - g.zb[:, None]), 0.0)
            Dx += fr[:, None] * _sum3(wgt * g.nLx)[None]
            Dy += fr[:, None] * _sum3(wgt * g.nLy)[None]

        # boundary faces
        cb = g.bc_cell
        HB = np.maximum(wB[0] - zB, 0)
        bx, by = g.bn[:, 0], g.bn[:, 1]
        unB, utB = wB[iu] * bx + wB[iv] * by, -wB[iu] * by + wB[iv] * bx
        Hg, ung, utg = HB.copy(), -unB, utB.copy()
        fi = self.free_idx
        Hg[fi] = np.maximum(2 * H[cb[fi]] - HB[fi], 0)
        ung[:, fi] = unB[:, fi]
        for _, idx, sig in self.level:
            eta_ext = sig(t)
            Hg[idx] = np.maximum(eta_ext - zB[idx], 0)
            cin, cg = np.sqrt(G * HB[idx]), np.sqrt(G * Hg[idx])
            ung[:, idx] = np.where(Hg[idx] > 0, unB[:, idx] + 2 * (cin - cg), 0.0)
        B0, B1, B2, bs = hll_layers(HB, unB, utB, Hg, ung, utg, fr)
        for _, idx, sig in self.river:
            Q = float(sig(t))
            Hc = np.maximum(HB[idx], self.h_dry)
            conv = Hc ** (5 / 3) * g.blen[idx]
            qn = -Q * Hc ** (5 / 3) / conv.sum()
            Href = np.maximum(HB[idx], (qn * qn / G) ** (1 / 3))
            B0[:, idx] = fr[:, None] * qn
            B1[:, idx] = fr[:, None] * (qn * qn / Href + 0.5 * G * Href * Href)
            B2[:, idx] = 0.0
            bs[idx] = np.abs(qn) / Href + np.sqrt(G * Href)
        Bx, By = B1 * bx - B2 * by, B1 * by + B2 * bx
        Lb = g.blen
        Dm -= A(cb, B0 * Lb)
        Dx -= A(cb, Bx * Lb)
        Dy -= A(cb, By * Lb)
        lam += g.acc(cb, bs * Lb)
        B0s = B0.sum(0)
        bflux = {nm: float(np.sum(B0s[idx] * Lb[idx])) for nm, idx in self.groups.items()}
        if nt:
            cBf = wB[ic].reshape(nt, L, -1)
            cin = np.where(self.c_interior[:, None], cBf, self.c_ext)
            ftb = (B0 * Lb)[None] * np.where(B0[None] > 0, cBf, cin)
            Dc -= A(cb, ftb.reshape(nt * L, -1)).reshape(nt, L, g.nc)
            self._tb = np.stack([ftb[:, :, idx].sum((1, 2)) for idx in self.groups.values()], 1)
            kd = np.flatnonzero(self.D > 0)
            if len(kd):
                Dc[kd] += self._hdiff(H, wet, c[kd], self.D[kd])
        self._src = np.zeros(1 + nt)
        for s in self.sources:
            fct = float(s['factor'](t))
            Dm[:, s['cell']] += s['w'] * s['Q'] * fct
            self._src[0] += s['Q'] * fct
            if nt:
                Dc[:, :, s['cell']] += s['mass'][:, None] * s['w'][None] * fct
                self._src[1:] += s['mass'] * fct
        a = g.area
        Dm /= a
        Dx /= a
        Dy /= a
        Dc /= a
        dH = Dm.sum(0)
        # mass exchange through the σ surfaces: G_{α+½} = Σ_{β≤α} (D_β − l_β ∂H/∂t)  (positive upwards)
        Gi = np.zeros((L + 1, g.nc))
        Gi[1:] = np.cumsum(Dm - fr[:, None] * dH[None], axis=0)
        Gi[L] = 0.0
        self._lamv = np.max((np.abs(Gi[:-1]) + np.abs(Gi[1:])) / (fr[:, None] * np.maximum(H, self.h_dry)), axis=0)
        self._lamv = np.where(wet, self._lamv, 0.0)
        if L > 1:
            Gm = Gi[1:L]
            up = Gm > 0

            def vadv(q):                                   # q (..., L, nc) → net vertical advective gain
                fl = Gm * np.where(up, q[..., :-1, :], q[..., 1:, :])
                out = np.zeros_like(q)
                out[..., :-1, :] -= fl
                out[..., 1:, :] += fl
                return out
            Dx += vadv(u)
            Dy += vadv(v)
            if nt:
                Dc += vadv(c)
        # baroclinic pressure gradient
        if self.active:
            Dx_b, Dy_b = self._baroclinic(H, c, wet)
            Dx += Dx_b
            Dy += Dy_b
        # horizontal viscosity (two-point, per layer)
        if self.nu_h > 0:
            He = 0.5 * (H[g.L] + H[g.R]) * (wet[g.L] & wet[g.R])
            for D_, q in ((Dx, u), (Dy, v)):
                fl = self.nu_h * fr[:, None] * He * (q[:, g.R] - q[:, g.L]) / g.dist * g.len
                D_ += (A(g.L, fl) - A(g.R, fl)) / a
        dU = np.empty_like(U)
        dU[0] = dH
        dU[iu] = Dx
        dU[iv] = Dy
        dU[ic] = Dc.reshape(nt * L, g.nc)
        return dU, bflux, lam / a

    def _hdiff(self, H, wet, ck, Dk):
        """∇·(h_α D ∇c) per layer with the corrected face gradient (as the 2-D model)."""
        g, fr = self.g, self.frac
        ns_, L = ck.shape[:2]
        He = 0.5 * (H[g.L] + H[g.R]) * (wet[g.L] & wet[g.R])
        cf = ck.reshape(ns_ * L, -1)
        cf = np.where(wet, cf, 0.0)
        gx, gy = g.gradient(cf)
        near = ~wet | ~wet[g.nb].all(1)
        ok = ~(near[g.L] | near[g.R])
        tx, ty = g.tvec[:, 0], g.tvec[:, 1]
        tn = tx * g.n[:, 0] + ty * g.n[:, 1]
        mx, my = 0.5 * (gx[:, g.L] + gx[:, g.R]), 0.5 * (gy[:, g.L] + gy[:, g.R])
        dct = (cf[:, g.R] - cf[:, g.L]) / g.dist
        gn = np.where(ok, mx * g.n[:, 0] + my * g.n[:, 1] + (dct - mx * tx - my * ty) * tn, dct)
        fl = (np.repeat(Dk, L)[:, None] * np.tile(fr, ns_)[:, None]) * He * gn * g.len
        return (self._acc(g.L, fl) - self._acc(g.R, fl)).reshape(ns_, L, -1)

    def set_reference(self, U):
        """Reference density profile ρ_ref(z) = horizontal mean of the (initial) state on fine z bins. Its pressure
        gradient on z levels is exactly zero, so only b − b_ref goes through the σ-coordinate gradient (removes most
        of the pressure-gradient error over sloping beds); the surface term −h b_ref(η) ∇η is added explicitly."""
        self.zref = None
        if not self.active:
            return
        u, v, c, wet = self.primitive(U)
        if not wet.any():
            return
        H = U[0]
        z = (self.g.zb[None] + self.sc[:, None] * H[None])[:, wet].ravel()
        r = self.density(c)[:, wet].ravel()
        zt = (self.g.zb + H)[wet]
        lo, hi = float(min(z.min(), self.g.zb[wet].min())), float(max(z.max(), zt.max()))
        if hi - lo < 1e-9:
            return
        edges = np.linspace(lo, hi, 801)
        k = np.clip(np.searchsorted(edges, z, side='right') - 1, 0, 799)
        cnt = np.bincount(k, minlength=800)
        mean = np.bincount(k, weights=r, minlength=800) / np.maximum(cnt, 1)
        zc = np.bincount(k, weights=z, minlength=800) / np.maximum(cnt, 1)
        keep = cnt > 0
        self.zref, self.rref = zc[keep], mean[keep]

    def _rho_ref(self, z):
        return np.interp(z, self.zref, self.rref)

    def _baroclinic(self, H, c, wet):
        """−h_α (∇_σ P'_α + b'_α ∇_σ z_α) − h_α b_ref(η) ∇η, b' = g(ρ − ρ_ref(z))/ρ₀, P'_α = ∫_{z_α}^η b' dz
        (layer midpoint); without a reference profile b' = g(ρ − ρ₀)/ρ₀."""
        g, fr = self.g, self.frac
        rho = self.density(c)
        z = g.zb[None] + self.sc[:, None] * H[None]
        ref = getattr(self, 'zref', None) is not None
        b = G * (rho - (self._rho_ref(z) if ref else self.rho0)) / self.rho0      # (L, nc)
        h = fr[:, None] * H[None]
        above = np.cumsum((b * h)[::-1], axis=0)[::-1] - b * h     # Σ_{β>α} b_β h_β
        P = above + 0.5 * b * h
        gPx, gPy = g.gradient(P)
        gzx, gzy = g.gradient(z)
        ok = wet & wet[g.nb].all(1) & (H > 10 * self.h_dry)
        fx = -h * (gPx + b * gzx)
        fy = -h * (gPy + b * gzy)
        if ref:
            eta = g.zb + H
            bs = G * (self._rho_ref(eta) - self.rho0) / self.rho0
            ex, ey = g.gradient(eta[None])
            fx -= h * bs * ex[0]
            fy -= h * bs * ey[0]
        return np.where(ok, fx, 0.0), np.where(ok, fy, 0.0)

    # ── vertical step (implicit, per column) ────────────────────────────────
    def _drag(self, H, ub):
        if self.p.get('bottom_drag') is False:
            return np.zeros_like(H)
        zc = 0.5 * self.frac[0] * np.maximum(H, self.h_dry)
        cd = (KAPPA / np.log((zc + self.z0b) / self.z0b)) ** 2
        return np.maximum(cd, self.cd_min)

    def _turbulence(self, H, u, v, rho, dt, ustar_b2, ustar_s2, wet):
        """1-D k-ε on the interfaces (log-layer flux conditions at the bed / surface); updates ν_t, κ_t."""
        L, fr = self.nl, self.frac
        if L < 2:
            self.nut[:] = 0.0
            self.kat[:] = 0.0
            return
        Hs = np.maximum(H, self.h_dry)
        h = fr[:, None] * Hs[None]
        dz = 0.5 * (h[:-1] + h[1:])                                 # interior interfaces 1..L−1
        M2 = ((u[1:] - u[:-1]) ** 2 + (v[1:] - v[:-1]) ** 2) / dz ** 2
        N2 = -G / self.rho0 * (rho[1:] - rho[:-1]) / dz if rho is not None else np.zeros_like(dz)
        k, e = self.k, self.eps
        cmu = self.cmu
        nut_i, kat_i = self.nut[1:L], self.kat[1:L]
        P = nut_i * M2
        B = -kat_i * N2
        # boundaries: zero flux of k (log layer); ε flux of the log layer at the middle of the boundary layer,
        # −ν_t/σ_ε ∂ε/∂z = c_μ k²/(σ_ε z_m), z_m = h/2 + z₀, with the adjacent k (= u_*⁴/(σ_ε z_m) in equilibrium;
        # a Dirichlet ε at z₀ is not resolved by the layers, and a u_*-based flux kills the spin-up from rest)
        z0b = self.z0b
        Fb = cmu * k[1] ** 2 / (self.se * (0.5 * h[0] + z0b))
        Fs = np.where(ustar_s2 > 0, cmu * k[L - 1] ** 2 / (self.se * (0.5 * h[-1] + self.z0s)), 0.0)
        nu_c = 0.5 * (self.nut[:-1] + self.nut[1:]) + self.nu_b        # at the layer centres (L)

        def solve(phi, sig, src, sink, fb, fs):
            # dz_i (φ_i' − φ_i)/dt = ν_α/σ (φ_{i+1}' − φ_i')/h_α − ν_{α−1}/σ (φ_i' − φ_{i−1}')/h_{α−1}
            #                        + src − sink φ_i'   (boundary layers: imposed fluxes fb, fs instead)
            du = dt * nu_c[1:] / sig / h[1:]            # coupling i ↔ i+1 through layer α = i
            dl = dt * nu_c[:-1] / sig / h[:-1]          # coupling i ↔ i−1 through layer α = i−1
            du[-1] = 0.0
            dl[0] = 0.0
            a = -dl
            c_ = -du
            bdiag = dz + du + dl + dt * dz * sink
            d = dz * phi[1:L] + dt * dz * src
            d[0] += dt * fb
            d[-1] += dt * fs
            return thomas(a, bdiag, c_, d)
        Pp = P + np.maximum(B, 0.0)
        ki = k[1:L]
        ei = e[1:L]
        ksink = (ei + np.maximum(-B, 0.0)) / ki
        knew = np.maximum(solve(k, self.sk, Pp, ksink, 0.0, 0.0), self.k_min)
        c3 = np.where(B > 0, self.c3p, self.c3m)
        esrc = ei / ki * (self.c1 * P + np.maximum(c3 * B, 0.0))
        esink = ei / ki * (self.c2 + np.maximum(-c3 * B, 0.0) / np.maximum(ei, 1e-300))
        enew = np.maximum(solve(e, self.se, esrc, esink, Fb, Fs), self.eps_min)
        # Galperin length-scale limit in stable stratification
        Np = np.sqrt(np.maximum(N2, 0.0))
        elim = cmu ** 0.75 * knew ** 1.5 * Np / (self.galperin * np.sqrt(2 * knew))
        enew = np.maximum(enew, elim)
        k[1:L], e[1:L] = knew, enew
        k[0], k[L] = knew[0], knew[-1]
        e[0] = np.maximum(math.sqrt(self.cmu) * k[0] ** 1.5 / (KAPPA * z0b) * self.cmu ** 0.25, self.eps_min)
        e[L] = np.maximum(math.sqrt(self.cmu) * k[L] ** 1.5 / (KAPPA * self.z0s) * self.cmu ** 0.25, self.eps_min)
        dry = ~wet
        k[:, dry], e[:, dry] = self.k_min, self.eps_min
        nut = cmu * k * k / e
        self.nut[:] = np.where(wet, nut, 0.0)
        self.kat[:] = self.nut / self.prt

    def vertical(self, U, dt, t):
        """Vertical mixing, bed drag, wind and Coriolis (implicit per column); decay of passive tracers."""
        g, L, fr, nt = self.g, self.nl, self.frac, self.nt
        H, hu, hv, hc = self.split(U)
        u, v, c, wet = self.primitive(U)
        Hs = np.maximum(H, self.h_dry)
        h = fr[:, None] * Hs[None]
        rho = self.density(c) if self.active else None
        # stresses
        ub = np.hypot(u[0], v[0])
        cd = self._drag(H, ub)
        ustar_b2 = cd * ub * ub
        tx = ty = 0.0
        if self.p.get('surface_stress') is not None:          # imposed τ [N/m²] (tests)
            tx, ty = (float(x) / self.rho0 for x in self.p['surface_stress'])
        if self.wind is not None:
            Wx, Wy = self.wind(t)
            W = math.hypot(Wx, Wy)
            if W > 0:
                kw = RHO_AIR / self.rho0 * wind_drag(W) * W
                tx, ty = kw * Wx, kw * Wy
        ustar_s2 = np.full(g.nc, math.hypot(tx, ty))
        if self.closure == 'k_epsilon':
            self._turbulence(H, u, v, rho, dt, ustar_b2, ustar_s2, wet)
            nu_i = self.nut[1:L] + self.nu_b
            ka_i = self.kat[1:L] + self.ka_b
        else:
            nu_i = np.full((L - 1, g.nc), self.nu_b)
            ka_i = np.full((L - 1, g.nc), self.ka_b)
        dz = 0.5 * (h[:-1] + h[1:])
        if L > 1:
            cn = dt * nu_i / dz
            ck = dt * ka_i / dz
        else:
            cn = ck = np.zeros((0, g.nc))

        def tri(coef, extra_bottom=None):
            a = np.zeros((L, g.nc))
            c_ = np.zeros((L, g.nc))
            b = h.copy()
            if L > 1:
                a[1:] = -coef
                c_[:-1] = -coef
                b[1:] += coef
                b[:-1] += coef
            if extra_bottom is not None:
                b[0] += extra_bottom
            return a, b, c_
        a, b, c_ = tri(cn, dt * cd * ub)
        ru = h * u
        rv = h * v
        ru[-1] += dt * tx
        rv[-1] += dt * ty
        if self.p.get('body_force') is not None:               # uniform acceleration [m/s²] (tests: g·slope)
            fx, fy = (float(x) for x in self.p['body_force'])
            ru += dt * h * fx
            rv += dt * h * fy
        un = thomas(a, b, c_, ru)
        vn = thomas(a, b, c_, rv)
        un[:, ~wet] = 0.0
        vn[:, ~wet] = 0.0
        # Coriolis: exact rotation
        if np.any(self.f != 0):
            th = self.f * dt
            co, si = np.cos(th), np.sin(th)
            un, vn = co * un + si * vn, -si * un + co * vn
        hu[:] = fr[:, None] * H * un
        hv[:] = fr[:, None] * H * vn
        self._decayed = np.zeros(nt)
        if nt:
            a, b, c_ = tri(ck)
            for k in range(nt):
                cn_ = thomas(a, b, c_, h * c[k])
                cn_ = np.where(wet, cn_, c[k])
                hc[k] = fr[:, None] * H * cn_
                if self.lam[k] > 0:
                    before = hc[k].copy()
                    hc[k] *= math.exp(-self.lam[k] * dt)
                    self._decayed[k] = float(np.sum(g.area * (before - hc[k])))
        return U

    def dt_from(self, lam, U):
        dt = self.cfl / max(float(lam.max()), 1e-300) if self.p.get('horizontal') is not False else 1 / lam.max()
        lv = float(self._lamv.max())
        if lv > 0:
            dt = min(dt, self.cfl / lv)
        nu = max(self.nu_h, float(self.D.max()) if self.nt else 0.0)
        if nu > 0:
            dt = min(dt, 0.25 * float(np.min(self.g.dist)) ** 2 / nu)
        return dt

    def step(self, U, t, dt_max):
        k1, b1, lam = self.rhs(U, t)
        t1, s1 = self._tb.copy(), self._src.copy()
        self.dt_cfl = self.dt_from(lam, U)
        dt = min(self.dt_cfl, dt_max)
        U1 = U + dt * k1
        clip1 = self._clip(U1)
        k2, b2, _ = self.rhs(U1, t + dt)
        Un = 0.5 * (U + U1 + dt * k2)
        clip2 = self._clip(Un)
        clip = 0.5 * clip1 + clip2
        Un = self.vertical(Un, dt, t + dt)
        vol = {k: 0.5 * dt * (b1[k] + b2[k]) for k in b1}
        self.last = {'tracer_out': 0.5 * dt * (t1 + self._tb), 'source': 0.5 * dt * (s1 + self._src),
                     'decayed': self._decayed, 'clipped': clip}
        return Un, dt, vol, float(clip[0])

    def _clip(self, U):
        A = self.g.area
        out = np.zeros(1 + self.nt)
        H, hu, hv, hc = self.split(U)
        neg = H < 0
        if neg.any():
            out[0] = -float(np.sum(A[neg] * H[neg]))
            H[neg] = 0.0
            if self.nt:
                out[1:] -= np.sum(A[neg] * hc[:, :, neg].sum(1), axis=1)
                hc[:, :, neg] = 0.0
        if self.nt:
            m = hc < 0
            if m.any():
                out[1:] -= np.sum(np.where(m, A * hc, 0.0), axis=(1, 2))
                hc[m] = 0.0
        return out

    # diagnostics
    def depth_mean(self, U):
        u, v, c, wet = self.primitive(U)
        return (self.frac[:, None] * u).sum(0), (self.frac[:, None] * v).sum(0), wet


def solve(grid: SWGrid, params: dict, boundaries: dict, *, t_end: float, eta0=0.0, U0=None, wind=None,
          n_output: int = 24, probes=None, progress=None, max_steps: int = 2_000_000, state=None) -> dict:
    """Run to ``t_end`` [s]. Snapshots [(t, U)] (U rows: H, h_α u_α, h_α v_α, h_α c_α), budgets, probe series
    (surface / bottom values every step) and probe profiles at the outputs."""
    sw = Stratified3D(grid, params, boundaries, wind=wind)
    nt = sw.nt
    U = sw.initial_state(eta0) if U0 is None else np.array(U0, float)
    if U.shape[0] != sw.nrow:
        raise ValueError(f'U0 must have {sw.nrow} rows.')
    if state is not None:
        sw.k[:], sw.eps[:], sw.nut[:], sw.kat[:] = state
    sw.set_reference(U)
    A = grid.area
    mass0 = float(np.sum(A * U[0]))
    tmass0 = np.sum(A * sw.split(U)[3].sum(1), axis=1) if nt else np.zeros(0)
    t_out = np.zeros((nt, len(sw.groups)))
    t_in = np.zeros((nt, len(sw.groups)))
    t_src, t_dec, t_clip = np.zeros(nt), np.zeros(nt), np.zeros(nt)
    w_src = 0.0
    out_t = np.linspace(0, t_end, n_output + 1)[1:]
    snaps = [(0.0, U.copy())]
    vol = {k: 0.0 for k in sw.groups}
    vol_in = {k: 0.0 for k in sw.groups}
    clipped = 0.0
    t, k_out, n_steps = 0.0, 0, 0
    pcells = grid.locate([p['xy'] for p in probes]) if probes else None
    prows, profiles = [], []

    def profile_rows(Uc, tt):
        u, v, c, _ = sw.primitive(Uc)
        rho = sw.density(c) if sw.active else None
        H = Uc[0]
        out = []
        for cc in pcells:
            z = grid.zb[cc] + sw.sc * H[cc]
            nu_c = 0.5 * (sw.nut[:-1, cc] + sw.nut[1:, cc])
            d = {'t': tt, 'z': z.tolist(), 'u': u[:, cc].tolist(), 'v': v[:, cc].tolist(), 'nu_t': nu_c.tolist()}
            for k, nm in enumerate(sw.names):
                d[nm] = c[k, :, cc].tolist()
            if rho is not None:
                d['rho'] = rho[:, cc].tolist()
            out.append(d)
        return out
    if pcells is not None:
        profiles.append(profile_rows(U, 0.0))
    thr = np.array([np.inf if sw.c_threshold[k] is None else sw.c_threshold[k] for k in range(nt)], float)
    cmax = np.zeros((nt, grid.nc))
    t_above = np.zeros((nt, grid.nc))
    smax = np.zeros(grid.nc)
    smax_s = np.zeros(grid.nc)
    smax_b = np.zeros(grid.nc)
    wet_ever = U[0] > sw.h_dry
    hmax = np.where(wet_ever, U[0] + grid.zb, -np.inf)
    wet0 = wet_ever.copy()
    dts = []
    t0 = _time.perf_counter()
    while t < t_end - 1e-9 * t_end:
        target = out_t[k_out]
        U, dt, vv_, cl = sw.step(U, t, target - t)
        if not np.all(np.isfinite(U)):
            raise ValueError(f'Estratificado 3D: la solución diverge en t = {t:.4g} s (reduzca el CFL o revise los '
                             f'contornos).')
        t += dt
        n_steps += 1
        dts.append(sw.dt_cfl)
        clipped += cl
        last = sw.last
        w_src += float(last['source'][0])
        if nt:
            t_out += last['tracer_out']
            t_in += -np.minimum(last['tracer_out'], 0.0)
            t_src += last['source'][1:]
            t_dec += last['decayed']
            t_clip += last['clipped'][1:]
        for k_, val in vv_.items():
            vol[k_] += val
            vol_in[k_] += -min(val, 0.0)
        u, v, c, wet = sw.primitive(U)
        um, vm = (sw.frac[:, None] * u).sum(0), (sw.frac[:, None] * v).sum(0)
        if nt:
            cm = c.max(1)
            np.maximum(cmax, cm, out=cmax)
            t_above += dt * (cm > thr[:, None])
        np.maximum(smax, np.hypot(um, vm), out=smax)
        np.maximum(smax_s, np.hypot(u[-1], v[-1]), out=smax_s)
        np.maximum(smax_b, np.hypot(u[0], v[0]), out=smax_b)
        np.maximum(hmax, U[0] + grid.zb, out=hmax, where=wet)
        wet_ever |= wet
        if pcells is not None:
            row = [t]
            for cc in pcells:
                row += [U[0][cc] + grid.zb[cc], um[cc], vm[cc], U[0][cc], u[-1, cc], v[-1, cc], u[0, cc], v[0, cc]]
                row += [x for k in range(nt) for x in (c[k, -1, cc], c[k, 0, cc])]
            prows.append(row)
        if t >= target - 1e-9 * max(t_end, 1):
            snaps.append((t, U.copy()))
            if pcells is not None:
                profiles.append(profile_rows(U, t))
            k_out += 1
            if progress:
                progress(k_out, n_output, t)
            if k_out >= len(out_t):
                break
        if n_steps >= max_steps:
            raise ValueError(f'Estratificado 3D: más de {max_steps:,} pasos de tiempo (Δt {dt:.3g} s).')
    mass1 = float(np.sum(A * U[0]))
    net_out = sum(vol.values())
    scale = max(mass0, abs(sum(vol_in.values())), w_src, 1e-30)
    balance = (mass1 - mass0 + net_out - clipped - w_src) / scale
    tracers = []
    names = list(sw.groups)
    hc1 = sw.split(U)[3]
    for k in range(nt):
        m1 = float(np.sum(A * hc1[k].sum(0)))
        sc = max(abs(tmass0[k]), float(t_in[k].sum()), abs(t_src[k]), 1e-300)
        tracers.append({'name': sw.names[k], 'mass0': float(tmass0[k]), 'mass1': m1, 'source': float(t_src[k]),
                        'decayed': float(t_dec[k]), 'clipped': float(t_clip[k]),
                        'boundary_out': {n_: float(t_out[k, j]) for j, n_ in enumerate(names)},
                        'boundary_in': {n_: float(t_in[k, j]) for j, n_ in enumerate(names)},
                        'balance_error': abs(m1 - tmass0[k] + float(t_out[k].sum()) - t_src[k] + t_dec[k]
                                             - t_clip[k]) / sc})
    return {'snaps': snaps, 'n_steps': n_steps, 'dt_min': float(min(dts)) if dts else 0.0,
            'dt_max': float(max(dts)) if dts else 0.0, 'mass0': mass0, 'mass1': mass1,
            'boundary_volume_out': vol, 'boundary_volume_in': vol_in, 'clipped_mass': clipped,
            'balance_error': float(abs(balance)), 'max_speed': smax, 'max_speed_surface': smax_s,
            'max_speed_bottom': smax_b, 'max_eta': hmax, 'wet_ever': wet_ever, 'wet0': wet0,
            'probe_cells': pcells, 'probe_rows': prows, 'profiles': profiles, 'cmax': cmax, 't_above': t_above,
            'wall_time_s': _time.perf_counter() - t0, 'solver': sw, 'source_volume': w_src, 'tracers': tracers,
            'turbulence_state': (sw.k.copy(), sw.eps.copy(), sw.nut.copy(), sw.kat.copy())}
