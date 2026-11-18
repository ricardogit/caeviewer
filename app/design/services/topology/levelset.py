"""Level-set topology optimization — FASE 4.2 (reaction-diffusion level set, Yamada et al. 2010).

The design is a nodal level-set function φ ∈ [−1, 1] on the (T4) design mesh:
    φ > 0  material,   φ < 0  void,   φ = 0  boundary.
Instead of transporting φ with the Hamilton-Jacobi equation and re-initialising it to a signed
distance (fragile on unstructured tetrahedra), φ evolves with the reaction-diffusion equation

    ∂φ/∂t = −(F' − λ) + τ L² ∇²φ                       (semi-implicit in time)

where F' ∝ −(strain-energy density) is the topological sensitivity of the compliance, λ the
volume multiplier (bisection each step so the material volume follows a ramp to the target) and τ
a dimensionless regularisation (perimeter-like: larger τ → simpler shapes); L = domain size.
With the lumped mass M and the Laplacian K_L (∫∇N·∇N):

    (M/Δt + τL² K_L) φⁿ⁺¹ = M (φⁿ/Δt + w),   w = normalised energy density at the nodes,

the system matrix is constant (factorised once) and φⁿ⁺¹(λ) = a − λ b with b fixed, so the volume
bisection costs no extra solves. The boundary stays sharp (0/1 elements except a one-element band)
and holes can nucleate anywhere (topology changes), unlike a pure shape-derivative level set.

Ersatz material: element density ρ_e = mean over its 4 nodes of the smoothed Heaviside H(φ), E(ρ) =
E₀ (ε + (1 − ε) ρ). Elements touching supports/loads are passive solid (φ = 1 at their nodes).
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from app.design.services.topology.simp import SIMPOptimizer, SIMPSettings, TopologyError

logger = logging.getLogger(__name__)


@dataclass
class LevelSetSettings:
    volume_fraction: float = 0.4
    tau: float = 2e-4                 # regularisation (dimensionless, × L²)
    dt: float = 0.1                   # pseudo time step (0.5 oscillates on the bridge hito)
    max_iter: int = 200
    ramp_iter: int = 40               # iterations to bring the volume from 1 to the target
    band: float = 0.1                 # half-width of the smoothed Heaviside (φ units)
    emin_ratio: float = 1e-3          # ersatz void stiffness
    tol_compliance: float = 1e-3      # relative compliance change over 5 iterations (after the ramp)
    keep_bc_load_solid: bool = True
    passive_solid_sets: list = field(default_factory=list)
    passive_void_sets: list = field(default_factory=list)
    snapshot_every: int = 5
    cg_tol: float = 1e-8

    @classmethod
    def from_dict(cls, d: dict | None) -> 'LevelSetSettings':
        d = dict(d or {})
        s = cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d and d[k] is not None})
        if not 0.02 <= s.volume_fraction <= 0.95:
            raise TopologyError('La fracción de volumen debe estar entre 0.02 y 0.95')
        if not 0 < s.tau <= 0.1:
            raise TopologyError('τ (regularización) debe estar entre 0 y 0.1')
        if not 0 < s.dt <= 10:
            raise TopologyError('Δt debe estar entre 0 y 10')
        s.max_iter = int(max(5, min(s.max_iter, 1000)))
        s.ramp_iter = int(max(1, min(s.ramp_iter, s.max_iter)))
        return s

    def to_dict(self) -> dict:
        return asdict(self)


class LevelSetOptimizer(SIMPOptimizer):
    """Reuses the SIMP machinery (T4 mesh, Ke⁰, reduced sparsity pattern, passive sets, solver)."""

    def __init__(self, mesh, D, loads, bcs, settings=None, progress=None, snapshot=None, check_cancel=None):
        self.ls = settings if isinstance(settings, LevelSetSettings) else LevelSetSettings.from_dict(settings)
        base = SIMPSettings(volume_fraction=self.ls.volume_fraction, p_penalization=1.0, projection=False,
                            emin_ratio=self.ls.emin_ratio, keep_bc_load_solid=self.ls.keep_bc_load_solid,
                            passive_solid_sets=self.ls.passive_solid_sets,
                            passive_void_sets=self.ls.passive_void_sets, cg_tol=self.ls.cg_tol)
        super().__init__(mesh, D, loads, bcs, base, progress=progress, snapshot=snapshot, check_cancel=check_cancel)
        self._setup_levelset()

    def _setup_levelset(self):
        from app.design.services.fem.thermal import assemble_Kt
        m = self.mesh
        el = m.elements
        nn = m.n_nodes
        self.node_vol = np.bincount(el.ravel(), weights=np.repeat(self.vol / 4.0, 4), minlength=nn)
        KL = assemble_Kt(m, 1.0)                                       # ∫∇N·∇N
        Lc = float(np.ptp(m.nodes, axis=0).max())
        A = sp.diags(self.node_vol / self.ls.dt) + (self.ls.tau * Lc * Lc) * KL
        self.fixed_solid = np.zeros(nn, bool)
        self.fixed_solid[np.unique(el[self.passive_solid])] = True
        self.fixed_void = np.zeros(nn, bool)
        self.fixed_void[np.unique(el[self.passive_void])] = True
        self.fixed_void &= ~self.fixed_solid
        self.free_nodes = np.flatnonzero(~(self.fixed_solid | self.fixed_void))
        fixed = np.flatnonzero(self.fixed_solid | self.fixed_void)
        A = A.tocsr()
        self.A_ff = A[self.free_nodes][:, self.free_nodes].tocsc()
        self.A_fc = A[self.free_nodes][:, fixed]
        self.fixed_idx = fixed
        self.lu = spla.splu(self.A_ff)
        self.b_vec = self.lu.solve(self.node_vol[self.free_nodes])     # response to a unit λ
        self.L_char = Lc

    # ── level set ↔ densities ────────────────────────────────────────────────

    def heaviside(self, phi):
        w = self.ls.band
        return np.clip(0.5 + 0.5 * phi / w, 0.0, 1.0)

    def densities(self, phi):
        rho = self.heaviside(phi)[self.mesh.elements].mean(axis=1)
        rho[self.passive_solid] = 1.0
        rho[self.passive_void] = 0.0
        return rho

    def black_white(self, phi) -> np.ndarray:
        """0/1 design at exactly the target volume: the design elements with the largest mean φ
        (the φ = c contour that matches the volume), passive elements as they are."""
        key = phi[self.mesh.elements].mean(axis=1)
        d = np.flatnonzero(self.design)
        order = d[np.argsort(-key[d], kind='stable')]
        n_in = int(np.searchsorted(np.cumsum(self.vol[order]), self.v_target, side='right'))
        bw = np.zeros(self.mesh.n_elements)
        bw[order[:n_in]] = 1.0
        bw[self.passive_solid] = 1.0
        return bw

    def _fixed_phi(self):
        return np.where(self.fixed_solid[self.fixed_idx], 1.0, -1.0)

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> dict:
        ls = self.ls
        el = self.mesh.elements
        nn = self.mesh.n_nodes
        phi = np.ones(nn)
        phi[self.fixed_void] = -1.0
        fixed_phi = self._fixed_phi()
        coupling = self.A_fc @ fixed_phi
        history, state = [], {}
        uf = None
        converged = False
        t0 = time.perf_counter()
        v_full = self.volume(self.densities(phi)) / self.v_design
        it = 0
        for it in range(1, ls.max_iter + 1):
            if self.check_cancel:
                self.check_cancel()
            rho = self.densities(phi)
            c, dc, u, uf, cg_it = self.compliance_and_sensitivity(rho, x0=uf, state=state)
            # topological sensitivity: element strain-energy density at full stiffness → nodes
            ue = u[self.edofs]
            # actual strain-energy density (ersatz stiffness): with the full-stiffness energy the huge
            # strains of the soft void make every void node look valuable and the design flip-flops
            energy = np.einsum('ei,eij,ej->e', ue, self.Ke0, ue) * (ls.emin_ratio + (1 - ls.emin_ratio) * rho)
            dens = energy / self.vol
            wn = np.bincount(el.ravel(), weights=np.repeat(dens * self.vol / 4.0, 4), minlength=nn) / self.node_vol
            ref = float(np.mean(wn[self.free_nodes][phi[self.free_nodes] > 0])) if np.any(phi[self.free_nodes] > 0) \
                else float(np.mean(wn))
            wn = wn / max(ref, 1e-300)
            rhs = self.node_vol[self.free_nodes] * (phi[self.free_nodes] / ls.dt + wn[self.free_nodes]) - coupling
            a_vec = self.lu.solve(rhs)
            target = max(ls.volume_fraction, v_full - (v_full - ls.volume_fraction) * it / ls.ramp_iter)

            def vol_of(lam):
                p = phi.copy()
                p[self.free_nodes] = np.clip(a_vec - lam * self.b_vec, -1.0, 1.0)
                return self.volume(self.densities(p)) / self.v_design, p

            lo, hi = -1e3, 1e3
            for _ in range(80):                   # volume decreases with λ
                mid = 0.5 * (lo + hi)
                if vol_of(mid)[0] > target:
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 1e-9:
                    break
            vf, phi_new = vol_of(hi)
            change = float(np.abs(phi_new - phi).max())
            phi = phi_new
            rb = self.densities(phi)
            history.append({'iter': it, 'compliance': c, 'volume_fraction': vf, 'change': change,
                            'beta': None, 'cg_iterations': cg_it, 'grayness': self.grayness(rb),
                            'lambda': 0.5 * (lo + hi), 'target_volume': target,
                            'wall_time': round(time.perf_counter() - t0, 3)})
            if self.progress:
                self.progress(history[-1])
            if self.snapshot and (it == 1 or it % max(1, ls.snapshot_every) == 0):
                self.snapshot(it, rb)
            if it > ls.ramp_iter + 5 and abs(vf - ls.volume_fraction) < 0.005:
                cs = [h['compliance'] for h in history[-6:]]
                if (max(cs) - min(cs)) / abs(cs[-1]) < ls.tol_compliance:
                    converged = True
                    break

        rb = self.densities(phi)
        c, _, u, uf, _ = self.compliance_and_sensitivity(rb, x0=uf, state=state)
        bw = self.black_white(phi)
        e_ersatz, self.s.emin_ratio = self.s.emin_ratio, 1e-6      # 0/1 check with the SIMP void stiffness
        try:
            c_bw, _, u_bw, _, _ = self.compliance_and_sensitivity(bw, x0=uf, state=state)
        finally:
            self.s.emin_ratio = e_ersatz
        if self.snapshot:
            self.snapshot(it, rb)
        return {
            'x': phi, 'phi': phi, 'rho_filtered': rb, 'densities': rb, 'u': u, 'u_bw': u_bw,
            'history': history, 'converged': converged, 'n_iterations': it,
            'compliance': c, 'compliance_initial': self._initial_compliance(),
            'compliance_bw': c_bw, 'volume_fraction': self.volume(rb) / self.v_design,
            'volume_fraction_bw': float(self.vol[self.design] @ bw[self.design]) / self.v_design,
            'grayness': self.grayness(rb), 'filter_radius': None,
            'n_passive_solid': int(self.passive_solid.sum()), 'n_passive_void': int(self.passive_void.sum()),
            'n_design': int(self.design.sum()), 'beta_final': None,
            'wall_time': round(time.perf_counter() - t0 + self.setup_s, 3),
        }

    def _initial_compliance(self) -> float:
        """Compliance of the uniform design at the target volume, with SIMP's default penalisation
        (p = 3, void 1e-6), comparable to SIMP's first iterate (which is also projected at β = 1, so
        ρ̄ ≈ 0.39 for V = 0.4); the level set itself runs p = 1."""
        rho = np.full(self.mesh.n_elements, self.ls.volume_fraction)
        rho[self.passive_solid] = 1.0
        rho[self.passive_void] = 0.0
        ref = SIMPSettings()
        p, e = self.s.p_penalization, self.s.emin_ratio
        self.s.p_penalization, self.s.emin_ratio = ref.p_penalization, ref.emin_ratio
        try:
            return self.compliance_and_sensitivity(rho)[0]
        finally:
            self.s.p_penalization, self.s.emin_ratio = p, e
