"""SIMP topology optimization — Solid Isotropic Material with Penalization (FASE 4).

    E(ρ̄) = E₀ (ε + ρ̄^p (1 − ε))          modified SIMP, ε = emin_ratio
    min  C = Fᵀu     s.t.  K(ρ̄) u = F,   Σ_design v ρ̄ ≤ V_f Σ_design v,   0 ≤ x ≤ 1
    ρ̃ = filter(x),  ρ̄ = Heaviside_β(ρ̃)   (β continuation 1 → beta_max)

Update: Optimality Criteria with bisection on the Lagrange multiplier, evaluated through
filter + projection so the volume constraint holds for the *physical* densities ρ̄.

Elements: linear tets (T4). The element stiffness of every element is computed once (Ke⁰,
unit density); each iteration only rescales and re-sums it into the fixed sparse pattern of
the reduced (free-DOF) matrix, so assembly is a single ``bincount``. Elements touching loaded
or constrained faces are kept solid (passive), as is standard practice.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.assembler import assemble_F, dirichlet
from app.design.services.fem.mesh import FEMMesh
from app.design.services.topology.filter import DensityFilter, HeavisideProjection

logger = logging.getLogger(__name__)

MAX_ELEMENTS = 150_000        # Ke⁰ storage + pattern: ~1.2 kB/element
DIRECT_MAX_DOF = 3000
DIRECT_FALLBACK_DOF = 100_000      # direct solve when PCG fails (memory bound)


class TopologyError(ValueError):
    """User-facing problem with the optimization setup."""


@dataclass
class SIMPSettings:
    volume_fraction: float = 0.4
    p_penalization: float = 3.0
    filter_radius: float | None = None      # None → 2 × mean element edge
    filter_factor: float = 2.0
    max_iter: int = 150
    tol: float = 0.01                       # max |Δx| between iterations
    tol_compliance: float = 1e-3            # or: relative compliance change over 5 its (at β_max)
    move: float = 0.2                       # OC move limit
    emin_ratio: float = 1e-6                # void stiffness / solid stiffness
    projection: bool = True                 # Heaviside with β continuation
    beta_max: float = 16.0
    beta_every: int = 25                    # double β at least every N iterations
    eta: float = 0.5
    keep_bc_load_solid: bool = True         # elements touching BC/load sets are passive solid
    passive_solid_sets: list = field(default_factory=list)
    passive_void_sets: list = field(default_factory=list)
    snapshot_every: int = 5
    cg_tol: float = 1e-8
    # FASE 4.3: additive-manufacturing overhang filter (Langelaar, unstructured)
    am_constraint: bool = False
    build_direction: list = field(default_factory=lambda: [0.0, 0.0, 1.0])
    max_overhang_angle: float = 45.0

    @classmethod
    def from_dict(cls, d: dict | None) -> 'SIMPSettings':
        d = dict(d or {})
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and d[k] is not None}
        s = cls(**known)
        if not 0.02 <= s.volume_fraction <= 0.95:
            raise TopologyError('La fracción de volumen debe estar entre 0.02 y 0.95')
        if not 1.0 <= s.p_penalization <= 6.0:
            raise TopologyError('La penalización p debe estar entre 1 y 6')
        s.max_iter = int(max(1, min(s.max_iter, 1000)))
        if s.am_constraint:
            b = np.asarray(s.build_direction, float)
            if b.shape != (3,) or np.linalg.norm(b) < 1e-12:
                raise TopologyError('La dirección de impresión debe ser un vector [x, y, z] no nulo')
            if not 10.0 <= float(s.max_overhang_angle) <= 80.0:
                raise TopologyError('El ángulo máximo de voladizo debe estar entre 10° y 80°')
            s.build_direction = (b / np.linalg.norm(b)).tolist()
        return s

    def to_dict(self) -> dict:
        d = asdict(self)
        if not self.am_constraint:            # keep the hash of runs without AM unchanged (FASE 7)
            for k in ('am_constraint', 'build_direction', 'max_overhang_angle'):
                d.pop(k)
        return d


def to_t4(mesh: FEMMesh) -> FEMMesh:
    """Corner-node T4 mesh of a T10 mesh (topology optimization runs on linear tets)."""
    if mesh.element_type == 'T4':
        return mesh
    el = mesh.elements[:, :4]
    used = np.unique(el)
    remap = -np.ones(mesh.n_nodes, np.int64)
    remap[used] = np.arange(len(used))
    faces = {k: remap[v[:, :3]] for k, v in (mesh.face_sets or {}).items()}
    nsets = {k: remap[np.asarray(v)][remap[np.asarray(v)] >= 0] for k, v in (mesh.node_sets or {}).items()
             if k not in faces}
    return FEMMesh(mesh.nodes[used], remap[el], node_sets=nsets, face_sets=faces, canonical=True)


class SIMPOptimizer:
    """SIMP with density filter, Heaviside projection and OC update."""

    def __init__(self, mesh: FEMMesh, D: np.ndarray, loads: list, bcs: list,
                 settings: SIMPSettings | dict | None = None,
                 progress=None, snapshot=None, check_cancel=None):
        self.s = settings if isinstance(settings, SIMPSettings) else SIMPSettings.from_dict(settings)
        self.mesh = to_t4(mesh)
        if self.mesh.n_elements > MAX_ELEMENTS:
            raise TopologyError(f'{self.mesh.n_elements:,} elementos: la optimización topológica admite '
                                f'hasta {MAX_ELEMENTS:,}. Usa un tamaño de elemento mayor.')
        if any('gravity' in ld or 'body_force' in ld for ld in loads):
            raise TopologyError('Cargas de volumen (gravedad) dependen de la densidad: no están '
                                'soportadas todavía en optimización topológica.')
        self.D = D
        self.loads, self.bcs = loads, bcs
        self.progress, self.snapshot, self.check_cancel = progress, snapshot, check_cancel
        self._setup()

    # ── setup ─────────────────────────────────────────────────────────────────

    def _setup(self):
        m, s = self.mesh, self.s
        t0 = time.perf_counter()
        nodes, el = m.nodes, m.elements
        ne, ndof = len(el), m.n_dof_structural
        self.Ke0 = tb.stiffness_batch(nodes, el, self.D)                 # (ne, 12, 12)
        self.vol = tb.volumes(nodes, el)
        self.centroids = nodes[el].mean(axis=1)
        self.edofs = tb.element_dofs(el)

        F = assemble_F(m, self.loads)
        if not np.any(F):
            raise TopologyError('Sin cargas: la optimización necesita al menos una fuerza o presión.')
        dofs, vals = dirichlet(m, self.bcs)
        if not len(dofs):
            raise TopologyError('Sin condiciones de frontera.')
        if np.any(vals != 0):
            raise TopologyError('Desplazamientos prescritos distintos de cero no están soportados en '
                                'optimización topológica (minimiza la flexibilidad bajo fuerzas).')
        self.F = F
        free = np.ones(ndof, bool)
        free[dofs] = False
        self.free = np.flatnonzero(free)
        nf = len(self.free)
        red = -np.ones(ndof, np.int64)
        red[self.free] = np.arange(nf)

        # fixed sparsity pattern of the reduced matrix; entry → (element, local ij)
        r = red[self.edofs][:, :, None]
        c = red[self.edofs][:, None, :]
        r, c = np.broadcast_arrays(r, c)
        keep = (r >= 0) & (c >= 0)
        keys = r[keep] * nf + c[keep]
        uniq, self.inv = np.unique(keys, return_inverse=True)
        self.inv = self.inv.ravel()
        self.entry_el = np.broadcast_to(np.arange(ne)[:, None, None], keep.shape)[keep].astype(np.int64)
        self.entry_k = self.Ke0[keep]
        rows = uniq // nf
        self.indices = (uniq % nf).astype(np.int32)
        self.indptr = np.concatenate([[0], np.cumsum(np.bincount(rows, minlength=nf))]).astype(np.int32)
        self.nnz = len(uniq)
        self.rhs = F[self.free]
        from app.design.services.fem.solver import rigid_body_modes
        self.B = rigid_body_modes(nodes)[self.free]

        # passive elements
        def set_nodes(names):
            out = []
            for n in names if isinstance(names, (list, tuple)) else [names]:
                if n in (m.node_sets or {}):
                    out.append(np.asarray(m.node_sets[n], np.int64))
                elif n in (m.face_sets or {}):
                    out.append(np.unique(m.face_sets[n]))
                else:
                    raise TopologyError(f"Conjunto '{n}' no existe en la malla")
            return np.unique(np.concatenate(out)) if out else np.zeros(0, np.int64)

        def touching(names):
            mask = np.zeros(m.n_nodes, bool)
            mask[set_nodes(names)] = True
            return mask[el].any(axis=1)

        self.passive_solid = np.zeros(ne, bool)
        self.passive_void = np.zeros(ne, bool)
        if s.keep_bc_load_solid:
            for e in list(self.bcs) + list(self.loads):
                if e.get('keep_solid') is False or e.get('symmetry'):
                    continue                    # symmetry / plane constraints are not supports
                for key in ('face_set', 'node_set'):
                    if e.get(key):
                        self.passive_solid |= touching(e[key])
        for names in s.passive_solid_sets or []:
            self.passive_solid |= touching(names)
        for names in s.passive_void_sets or []:
            self.passive_void |= touching(names) & ~self.passive_solid
        self.design = ~(self.passive_solid | self.passive_void)
        if self.design.sum() < 10:
            raise TopologyError('Casi todos los elementos son pasivos: no queda dominio de diseño.')

        # filter
        edges = nodes[el[:, [1, 2, 3, 2, 3, 3]]] - nodes[el[:, [0, 0, 0, 1, 1, 2]]]
        self.h_mean = float(np.linalg.norm(edges, axis=2).mean())
        if s.filter_radius is None:
            s.filter_radius = s.filter_factor * self.h_mean
        self.filter = DensityFilter(s.filter_radius).build_weight_matrix(self.centroids, self.vol)
        self.proj = HeavisideProjection(beta=1.0, eta=s.eta)
        self.am = None
        if s.am_constraint:
            from app.design.services.topology.am_constraints import AMConstraints
            self.am = AMConstraints(self.centroids, self.vol, self.h_mean, s.build_direction,
                                    s.max_overhang_angle)
        self.v_design = float(self.vol[self.design].sum())
        self.v_target = s.volume_fraction * self.v_design
        self.setup_s = time.perf_counter() - t0
        logger.info('SIMP setup: %d elements (%d design), %d free DOF, nnz %d, filter r=%.4g, %.2fs',
                    ne, int(self.design.sum()), nf, self.nnz, s.filter_radius, self.setup_s)

    # ── pieces ────────────────────────────────────────────────────────────────

    def physical(self, x: np.ndarray, keep: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """x → (ρ̃ filtered, ρ̄ projected), passive elements enforced. With the AM filter the
        projection acts on the printed density ξ = AM(ρ̃) (kept in ``self._xi`` for the chain rule)."""
        rt = self.filter.apply(x)
        if self.am is not None:
            src = rt.copy()
            src[self.passive_solid] = 1.0              # solid regions support what is printed on them
            xi = self.am.forward(src, keep=keep)
        else:
            xi = rt
        if keep:
            self._xi = xi
        rb = self.proj.project(xi) if self.s.projection else xi.copy()
        rb[self.passive_solid] = 1.0
        rb[self.passive_void] = 0.0
        return rt, rb

    def stiffness(self, rho: np.ndarray) -> sp.csr_matrix:
        e = self.s.emin_ratio
        scale = e + rho ** self.s.p_penalization * (1.0 - e)
        data = np.bincount(self.inv, weights=scale[self.entry_el] * self.entry_k, minlength=self.nnz)
        n = len(self.free)
        return sp.csr_matrix((data, self.indices, self.indptr), shape=(n, n))

    def _solve(self, K, x0, state: dict):
        n = K.shape[0]
        if n <= DIRECT_MAX_DOF or state.get('direct'):
            return spla.spsolve(K.tocsc(), self.rhs), 1
        from app.design.services.fem.solver import _amg_preconditioner, _CG_TOL_KW
        if state.get('M') is None or state.get('age', 0) >= 4 or \
                state.get('last_it', 0) > 2.5 * max(state.get('base_it', 1), 10):
            M, method = _amg_preconditioner(K, self.B)
            if M is None:                                    # no pyamg: Jacobi
                dinv = 1.0 / K.diagonal()
                M = spla.LinearOperator(K.shape, matvec=lambda v: dinv * v)
            state.update(M=M, age=0, fresh=True)
        it = [0]

        def cb(_):
            it[0] += 1
        u, info = spla.cg(K, self.rhs, x0=x0, M=state['M'], atol=0.0, maxiter=max(2000, 20 * int(np.sqrt(n))),
                          callback=cb, **{_CG_TOL_KW: self.s.cg_tol})
        if info != 0 and not state.get('fresh'):           # stale hierarchy: rebuild once and retry
            M, _ = _amg_preconditioner(K, self.B)
            if M is not None:
                state.update(M=M, age=0, fresh=True)
                it[0] = 0
                u, info = spla.cg(K, self.rhs, x0=u, M=M, atol=0.0, maxiter=max(2000, 20 * int(np.sqrt(n))),
                                  callback=cb, **{_CG_TOL_KW: self.s.cg_tol})
        if info != 0:
            # near-void regions (e.g. the AM filter early on) make K too ill-conditioned for PCG:
            # an unconverged u would poison the sensitivities, so solve directly while affordable
            if n <= DIRECT_FALLBACK_DOF:
                logger.info('SIMP CG did not converge (%d it): direct solve (%d DOF)', it[0], n)
                u = spla.spsolve(K.tocsc(), self.rhs)
                state['direct'] = True                     # stays ill-conditioned: skip PCG from now on
            else:
                logger.warning('SIMP CG did not converge (info=%s, %d it)', info, it[0])
        if state.pop('fresh', False):
            state['base_it'] = it[0]
        state['age'] += 1
        state['last_it'] = it[0]
        return u, it[0]

    def compliance_and_sensitivity(self, rb: np.ndarray, x0=None, state=None):
        """Compliance, dC/dρ̄, full displacement and solver iterations."""
        K = self.stiffness(rb)
        uf, its = self._solve(K, x0, state if state is not None else {})
        u = np.zeros(self.mesh.n_dof_structural)
        u[self.free] = uf
        ue = u[self.edofs]
        ce = np.einsum('ei,eij,ej->e', ue, self.Ke0, ue)
        p, e = self.s.p_penalization, self.s.emin_ratio
        c = float(self.rhs @ uf)
        dc = -p * rb ** (p - 1) * (1.0 - e) * ce
        return c, dc, u, uf, its

    def chain_rule(self, dc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """dC/dx and dV/dx from dC/dρ̄ (call right after ``physical(x)``): projection → AM → filter."""
        ne = self.mesh.n_elements
        chain = self.proj.sensitivity_chain(self._xi) if self.s.projection else np.ones(ne)
        dc_rt = dc * chain
        dv_rt = np.where(self.design, self.vol, 0.0) * chain
        dc_rt[~self.design] = 0.0
        if self.am is not None:                       # through the printing recursion
            dc_rt = self.am.backprop(dc_rt)
            dv_rt = self.am.backprop(dv_rt)
            dc_rt[self.passive_solid] = 0.0
            dv_rt[self.passive_solid] = 0.0
        return self.filter.backprop(dc_rt), self.filter.backprop(dv_rt)

    def volume(self, rb: np.ndarray) -> float:
        return float(self.vol[self.design] @ rb[self.design])

    def _oc(self, x, dc_dx, dv_dx):
        move = self.s.move
        d = self.design
        neg_dc = np.maximum(-dc_dx, 0.0)
        neg_dc /= max(neg_dc[d].max(), 1e-300)
        dv = np.maximum(dv_dx, 1e-300)
        dv = dv / dv[d].max()
        lo_b, hi_b = np.maximum(0.0, x - move), np.minimum(1.0, x + move)
        l1, l2 = -30.0, 30.0                      # log10 λ
        x_new = x
        for _ in range(80):
            lm = 0.5 * (l1 + l2)
            cand = x.copy()
            cand[d] = np.clip(x[d] * np.sqrt(neg_dc[d] / (dv[d] * 10.0 ** lm)), lo_b[d], hi_b[d])
            if self.volume(self.physical(cand, keep=False)[1]) > self.v_target:
                l1 = lm
            else:
                l2 = lm
            x_new = cand
            if l2 - l1 < 1e-7:
                break
        return x_new

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> dict:
        s = self.s
        ne = self.mesh.n_elements
        x = np.full(ne, s.volume_fraction)
        x[self.passive_solid] = 1.0
        x[self.passive_void] = 0.0
        history = []
        state: dict = {}
        uf = None
        converged = False
        t0 = time.perf_counter()
        it = 0
        for it in range(1, s.max_iter + 1):
            if self.check_cancel:
                self.check_cancel()
            rt, rb = self.physical(x)
            c, dc, u, uf, cg_it = self.compliance_and_sensitivity(rb, x0=uf, state=state)
            dc_dx, dv_dx = self.chain_rule(dc)
            x_new = self._oc(x, dc_dx, dv_dx)
            change = float(np.abs(x_new - x)[self.design].max())
            x = x_new
            vf = self.volume(rb) / self.v_design
            history.append({'iter': it, 'compliance': c, 'volume_fraction': vf, 'change': change,
                            'beta': self.proj.beta if s.projection else None, 'cg_iterations': cg_it,
                            'grayness': self.grayness(rb), 'wall_time': round(time.perf_counter() - t0, 3)})
            if self.progress:
                self.progress(history[-1])
            if self.snapshot and (it == 1 or it % max(1, s.snapshot_every) == 0):
                self.snapshot(it, rb)
            at_max_beta = (not s.projection) or self.proj.beta >= s.beta_max
            # OC with sharp projection oscillates in x while the design is settled: also accept a
            # stagnant compliance (5 iterations at the final β).
            stalled = False
            if at_max_beta and len(history) > 5 and history[-6]['beta'] == history[-1]['beta']:
                cs = [h['compliance'] for h in history[-6:]]
                stalled = (max(cs) - min(cs)) / abs(cs[-1]) < s.tol_compliance
            if at_max_beta and it > 5 and (change < s.tol or stalled):
                converged = True
                break
            if s.projection and not at_max_beta and (change < s.tol or it % s.beta_every == 0):
                self.proj.beta = min(2 * self.proj.beta, s.beta_max)

        rt, rb = self.physical(x)
        c, _, u, uf, _ = self.compliance_and_sensitivity(rb, x0=uf, state=state)
        # black-and-white verification: threshold at 0.5 and re-solve
        bw = (rb >= 0.5).astype(float)
        bw[self.passive_solid] = 1.0
        c_bw, _, u_bw, _, _ = self.compliance_and_sensitivity(bw, x0=uf, state=state)
        if self.snapshot:
            self.snapshot(it, rb)
        return {
            'x': x, 'rho_filtered': rt, 'densities': rb, 'u': u, 'u_bw': u_bw,
            'history': history, 'converged': converged, 'n_iterations': it,
            'compliance': c, 'compliance_initial': history[0]['compliance'] if history else None,
            'compliance_bw': c_bw, 'volume_fraction': self.volume(rb) / self.v_design,
            'volume_fraction_bw': float(self.vol[self.design] @ bw[self.design]) / self.v_design,
            'grayness': self.grayness(rb), 'filter_radius': s.filter_radius,
            'n_passive_solid': int(self.passive_solid.sum()), 'n_passive_void': int(self.passive_void.sum()),
            'n_design': int(self.design.sum()), 'beta_final': self.proj.beta if s.projection else None,
            'wall_time': round(time.perf_counter() - t0 + self.setup_s, 3),
        }

    def grayness(self, rb: np.ndarray) -> float:
        """Volume fraction of design elements with 0.1 < ρ̄ < 0.9."""
        d = self.design
        g = (rb[d] > 0.1) & (rb[d] < 0.9)
        return float(self.vol[d][g].sum() / self.v_design)
