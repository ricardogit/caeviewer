"""Proper Orthogonal Decomposition — offline ROM construction (FASE 5).

Parametric linear elasticity with an *exact affine decomposition*:

    D(E, ν) = λ·m mᵀ + μ·diag(2,2,2,1,1,1)          (engineering shear strains)
    K(E, ν) = λ K_λ + μ K_μ,      F(p) = Σ_i (p_i / p_i⁰) F_i

so after POD the reduced operators Φᵀ K_λ Φ, Φᵀ K_μ Φ, Φᵀ F_i are computed once and the
online problem is an r×r solve. Parameters:

    E [Pa], nu [-], rho [kg/m³] (scales gravity loads), load_<i> (magnitude of load i in its
    own units: N for total force, Pa for pressure, m/s² for gravity; direction fixed).

Offline:
  1. Latin Hypercube samples of the parameter box, full FEM solve for each (snapshots)
  2. SVD of the normalized snapshot matrix; keep the modes reaching ``energy_threshold``
  3. Galerkin projection of the affine terms; strain modes per element (centroid) and on
     the surface nodes for fast stress recovery
  4. Validation at fresh LHS points against full solves (error estimate)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.assembler import assemble_F, assemble_K, dirichlet

logger = logging.getLogger(__name__)

M_VOL = np.array([1, 1, 1, 0, 0, 0], float)
D_LAMBDA = np.outer(M_VOL, M_VOL)
D_MU = np.diag([2.0, 2, 2, 1, 1, 1])
CENTROID = np.array([0.25, 0.25, 0.25])


class ROMError(ValueError):
    """User-facing problem with the ROM setup."""


def lame(E: float, nu: float) -> tuple[float, float]:
    return E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))


def von_mises_voigt(s: np.ndarray) -> np.ndarray:
    """s (..., 6) [xx, yy, zz, xy, yz, xz] → von Mises."""
    xx, yy, zz, xy, yz, xz = np.moveaxis(s, -1, 0)
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (xy ** 2 + yz ** 2 + xz ** 2))


def stress_from_strain(eps: np.ndarray, lam: float, mu: float) -> np.ndarray:
    """eps (..., 6) engineering strains → stress (..., 6)."""
    tr = eps[..., :3].sum(-1, keepdims=True)
    s = mu * eps.copy()
    s[..., :3] = lam * tr + 2 * mu * eps[..., :3]
    return s


def latin_hypercube(bounds: dict, n: int, seed: int = 0) -> list[dict]:
    """n samples, one per stratum in every dimension (randomly paired)."""
    rng = np.random.default_rng(seed)
    names = sorted(bounds)
    out = np.empty((n, len(names)))
    for j, _ in enumerate(names):
        out[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return [{k: bounds[k][0] + u * (bounds[k][1] - bounds[k][0]) for k, u in zip(names, row)} for row in out]


@dataclass
class ROMSettings:
    n_snapshots: int = 20
    energy_threshold: float = 1 - 1e-12        # on σ²: keeps modes down to σ_k/σ_1 ≈ 1e-6
    max_modes: int = 60
    n_test: int = 3
    seed: int = 0
    solver_tol: float = 1e-10

    @classmethod
    def from_dict(cls, d: dict | None) -> 'ROMSettings':
        d = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__ and v is not None}
        s = cls(**d)
        s.n_snapshots = int(max(2, min(s.n_snapshots, 400)))
        s.n_test = int(max(0, min(s.n_test, 50)))
        s.max_modes = int(max(1, min(s.max_modes, 200)))
        if not 0.9 <= s.energy_threshold < 1.0:
            raise ROMError('energy_threshold debe estar en [0.9, 1)')
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def describe_parameters(spec: dict) -> list[dict]:
    """Candidate parameters of a solver spec with nominal values, units and default ranges."""
    mat = spec.get('material') or {}
    E0, nu0 = float(mat.get('E', 210e9)), float(mat.get('nu', 0.3))
    out = [
        {'key': 'E', 'label': 'Módulo de Young E', 'unit': 'Pa', 'display_unit': 'GPa', 'display_scale': 1e-9,
         'nominal': E0, 'default_range': [0.8 * E0, 1.2 * E0], 'default_on': True},
        {'key': 'nu', 'label': 'Coeficiente de Poisson ν', 'unit': '', 'display_unit': '', 'display_scale': 1,
         'nominal': nu0, 'default_range': [max(0.0, nu0 - 0.05), min(0.49, nu0 + 0.05)], 'default_on': False},
    ]
    has_gravity = False
    for i, ld in enumerate(spec.get('loads') or []):
        name = ld.get('label') or f'Carga {i + 1}'
        if 'gravity' in ld:
            has_gravity = True
            g = float(np.linalg.norm(ld['gravity']))
            out.append({'key': f'load_{i}', 'label': f'{name} (aceleración)', 'unit': 'm/s²', 'display_unit': 'm/s²',
                        'display_scale': 1, 'nominal': g, 'default_range': [0.0, 2 * g], 'default_on': False})
        elif 'pressure' in ld:
            p = float(ld['pressure'])
            out.append({'key': f'load_{i}', 'label': f'{name} (presión)', 'unit': 'Pa', 'display_unit': 'kPa',
                        'display_scale': 1e-3, 'nominal': p, 'default_range': sorted([0.5 * p, 1.5 * p]),
                        'default_on': True})
        elif 'force' in ld or 'force_per_node' in ld:
            f = float(np.linalg.norm(ld.get('force', ld.get('force_per_node'))))
            out.append({'key': f'load_{i}', 'label': f'{name} (fuerza)', 'unit': 'N', 'display_unit': 'N',
                        'display_scale': 1, 'nominal': f, 'default_range': [0.5 * f, 1.5 * f], 'default_on': True})
    if has_gravity:
        rho0 = float(mat.get('rho', 7800.0))
        out.append({'key': 'rho', 'label': 'Densidad ρ', 'unit': 'kg/m³', 'display_unit': 'kg/m³', 'display_scale': 1,
                    'nominal': rho0, 'default_range': [0.8 * rho0, 1.2 * rho0], 'default_on': False})
    return out


class PODROMBuilder:
    """Build a POD-Galerkin ROM for a linear-elastic study."""

    def __init__(self, mesh, spec: dict, parameter_space: dict, settings: ROMSettings | dict | None = None,
                 progress=None, check_cancel=None):
        self.mesh = mesh
        self.spec = spec
        self.s = settings if isinstance(settings, ROMSettings) else ROMSettings.from_dict(settings)
        self.progress = progress or (lambda *a, **k: None)
        self.check_cancel = check_cancel
        self.params = {p['key']: p for p in describe_parameters(spec)}
        if not parameter_space:
            raise ROMError('Define al menos un parámetro con su rango.')
        self.space = {}
        for k, rng in parameter_space.items():
            if k not in self.params:
                raise ROMError(f"Parámetro '{k}' no existe en el estudio (disponibles: {', '.join(self.params)})")
            lo, hi = float(rng[0]), float(rng[1])
            if not hi > lo:
                raise ROMError(f"Rango de '{k}' vacío: [{lo}, {hi}]")
            if k == 'nu' and not (0 <= lo and hi < 0.5):
                raise ROMError('ν debe estar en [0, 0.5)')
            if k == 'E' and lo <= 0:
                raise ROMError('E debe ser positivo')
            self.space[k] = [lo, hi]
        mat = spec.get('material') or {}
        if str(mat.get('type', 'linear_elastic_isotropic')) != 'linear_elastic_isotropic':
            raise ROMError('El ROM (FASE 5) cubre elasticidad lineal isótropa.')

    # ── full-order pieces ─────────────────────────────────────────────────────

    def _setup(self):
        m = self.mesh
        t0 = time.perf_counter()
        self.K_lam = assemble_K(m, D_LAMBDA)
        self.K_mu = assemble_K(m, D_MU)
        dofs, vals = dirichlet(m, self.spec.get('bcs', []))
        if not len(dofs):
            raise ROMError('Sin condiciones de frontera.')
        if np.any(vals != 0):
            raise ROMError('Desplazamientos prescritos distintos de cero no están soportados en el ROM.')
        free = np.ones(m.n_dof_structural, bool)
        free[dofs] = False
        self.free = np.flatnonzero(free)
        self.Kl_f = self.K_lam[self.free][:, self.free].tocsr()
        self.Km_f = self.K_mu[self.free][:, self.free].tocsr()
        mat = self.spec.get('material') or {}
        self.rho0 = float(mat.get('rho', 7800.0) or 0.0)
        cols = []
        for i, ld in enumerate(self.spec.get('loads') or []):
            ld = {**ld, 'density': ld.get('density', self.rho0)} if 'gravity' in ld else ld
            cols.append(assemble_F(m, [ld])[self.free])
        if not cols:
            raise ROMError('Sin cargas.')
        self.F_f = np.column_stack(cols)                         # (n_free, n_loads) at nominal
        self.is_gravity = np.array(['gravity' in ld for ld in self.spec['loads']])
        from app.design.services.fem.solver import rigid_body_modes
        self.B = rigid_body_modes(m.nodes)[self.free]
        self.setup_s = time.perf_counter() - t0

    def full_params(self, p: dict) -> dict:
        """Fill missing parameters with nominal values."""
        return {k: float(p.get(k, v['nominal'])) for k, v in self.params.items()}

    def load_scales(self, p: dict) -> np.ndarray:
        q = self.full_params(p)
        sc = np.ones(self.F_f.shape[1])
        for i in range(len(sc)):
            key = f'load_{i}'
            if key in self.params and self.params[key]['nominal']:
                sc[i] = q[key] / self.params[key]['nominal']
            if self.is_gravity[i] and self.rho0:
                sc[i] *= q['rho'] / self.rho0 if 'rho' in q else 1.0
        return sc

    def full_solve(self, p: dict) -> np.ndarray:
        from app.design.services.fem.solver import FEMSolverDispatcher
        q = self.full_params(p)
        lam, mu = lame(q['E'], q['nu'])
        K = (lam * self.Kl_f + mu * self.Km_f).tocsr()
        F = self.F_f @ self.load_scales(p)
        u, info = FEMSolverDispatcher().solve_linear(K, F, tier=3, tol=self.s.solver_tol, near_nullspace=self.B)
        if not info.get('converged', True):
            logger.warning('ROM snapshot solve did not converge: %s', info.get('final_residual'))
        return u

    # ── build ────────────────────────────────────────────────────────────────

    def build(self) -> dict:
        t0 = time.perf_counter()
        self.progress(2, 'Ensamblando operadores afines (K_λ, K_μ)')
        self._setup()
        samples = latin_hypercube(self.space, self.s.n_snapshots, self.s.seed)
        snaps = []
        for k, p in enumerate(samples):
            if self.check_cancel:
                self.check_cancel()
            u = self.full_solve(p)
            snaps.append(u / max(np.linalg.norm(u), 1e-300))
            self.progress(5 + 70 * (k + 1) / len(samples), f'Snapshot {k + 1}/{len(samples)}')
        S = np.column_stack(snaps)
        U, sv, _ = np.linalg.svd(S, full_matrices=False)
        energy = np.cumsum(sv ** 2) / np.sum(sv ** 2)
        r = int(min(np.searchsorted(energy, self.s.energy_threshold) + 1, len(sv), self.s.max_modes))
        Phi_f = np.ascontiguousarray(U[:, :r])
        self.progress(78, f'POD: {r} modos ({100 * energy[r - 1]:.6f} % de energía)')

        rom = self._project(Phi_f)
        rom['singular_values'] = sv
        rom['energy'] = energy
        rom['samples'] = samples

        # validation against full solves at fresh LHS points
        errs = []
        tests = latin_hypercube(self.space, self.s.n_test, self.s.seed + 1) if self.s.n_test else []
        for k, p in enumerate(tests):
            if self.check_cancel:
                self.check_cancel()
            u_fom = self.full_solve(p)
            ev = evaluate_arrays(rom, self.full_params(p), with_u=True)
            u_rom = ev['u_free']
            e_u = float(np.linalg.norm(u_rom - u_fom) / max(np.linalg.norm(u_fom), 1e-300))
            u_full = np.zeros(self.mesh.n_dof_structural)
            u_full[self.free] = u_fom
            vm_fom = self._max_vm(u_full, p)
            errs.append({'params': p, 'error_u': e_u, 'max_vm_rom_pa': ev['max_von_mises_pa'],
                         'max_vm_fom_pa': vm_fom,
                         'error_max_vm': abs(ev['max_von_mises_pa'] - vm_fom) / max(vm_fom, 1e-300),
                         'residual': ev['residual']})
            self.progress(80 + 18 * (k + 1) / max(len(tests), 1), f'Validación {k + 1}/{len(tests)}')
        rom['validation'] = errs
        rom['build_s'] = time.perf_counter() - t0
        return rom

    def _max_vm(self, u_full, p):
        q = self.full_params(p)
        lam, mu = lame(q['E'], q['nu'])
        eps = tb.strain_at(self.mesh.nodes, self.mesh.elements, u_full, CENTROID)
        return float(von_mises_voigt(stress_from_strain(eps, lam, mu)).max())

    def _project(self, Phi_f: np.ndarray) -> dict:
        m = self.mesh
        r = Phi_f.shape[1]
        KlPhi = self.Kl_f @ Phi_f
        KmPhi = self.Km_f @ Phi_f
        Phi = np.zeros((m.n_dof_structural, r))
        Phi[self.free] = Phi_f
        # strain modes at element centroids (n_el, 6, r)
        strain = np.stack([tb.strain_at(m.nodes, m.elements, Phi[:, k], CENTROID) for k in range(r)], axis=2)
        # surface: nodes, triangles, displacement and (volume-averaged) strain modes
        tris = np.asarray(m.extract_surface_triangles(), dtype=np.int64).reshape(-1, 3)
        snodes, tri_local = np.unique(tris, return_inverse=True)
        tri_local = tri_local.reshape(-1, 3)
        vol = tb.volumes(m.nodes, m.elements)
        el = m.elements
        A = sp.csr_matrix((np.repeat(vol, el.shape[1]), (el.ravel(), np.repeat(np.arange(len(el)), el.shape[1]))),
                          shape=(m.n_nodes, len(el)))
        A = A[snodes]
        A = sp.diags(1.0 / np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1e-300)) @ A
        s_strain = (A @ strain.reshape(len(el), -1)).reshape(len(snodes), 6, r)
        s_phi = Phi.reshape(-1, 3, r)[snodes]
        return {
            'r': r, 'free': self.free, 'Phi': Phi,
            'Kl_r': Phi_f.T @ KlPhi, 'Km_r': Phi_f.T @ KmPhi,
            'KlPhi': KlPhi, 'KmPhi': KmPhi,
            'F_f': self.F_f, 'F_r': Phi_f.T @ self.F_f,
            'is_gravity': self.is_gravity, 'rho0': np.float64(self.rho0),
            'strain_modes': strain.astype(np.float32),
            'surf_nodes': snodes, 'surf_tris': tri_local, 'surf_xyz': m.nodes[snodes],
            'surf_phi': s_phi.astype(np.float32), 'surf_strain': s_strain.astype(np.float32),
            'params_json': json.dumps(list(self.params.values())),
            'space_json': json.dumps(self.space),
        }


def load_scales_from(rom: dict, q: dict) -> np.ndarray:
    params = {p['key']: p for p in json.loads(str(rom['params_json']))}
    n = rom['F_r'].shape[1]
    sc = np.ones(n)
    rho0 = float(rom['rho0'])
    for i in range(n):
        key = f'load_{i}'
        if key in params and params[key]['nominal']:
            sc[i] = q.get(key, params[key]['nominal']) / params[key]['nominal']
        if rom['is_gravity'][i] and rho0 and 'rho' in params:
            sc[i] *= q.get('rho', params['rho']['nominal']) / rho0
    return sc


def evaluate_arrays(rom: dict, q: dict, with_u: bool = False) -> dict:
    """Online evaluation on in-memory ROM arrays. q must contain E and nu (full params)."""
    lam, mu = lame(q['E'], q['nu'])
    sc = load_scales_from(rom, q)
    Kr = lam * rom['Kl_r'] + mu * rom['Km_r']
    Fr = rom['F_r'] @ sc
    ur = np.linalg.solve(Kr, Fr)
    # residual of the full equations restricted to free DOFs (error indicator)
    F = rom['F_f'] @ sc
    res = lam * (rom['KlPhi'] @ ur) + mu * (rom['KmPhi'] @ ur) - F
    residual = float(np.linalg.norm(res) / max(np.linalg.norm(F), 1e-300))
    u = rom['Phi'] @ ur
    disp = np.sqrt((u.reshape(-1, 3) ** 2).sum(1))
    eps = rom['strain_modes'] @ ur.astype(np.float32)            # (n_el, 6)
    vm = von_mises_voigt(stress_from_strain(eps.astype(np.float64), lam, mu))
    out = {'ur': ur, 'lambda': lam, 'mu': mu, 'residual': residual,
           'max_displacement_m': float(disp.max()), 'max_von_mises_pa': float(vm.max()),
           'argmax_von_mises': int(vm.argmax())}
    if with_u:
        out['u_free'] = u[rom['free']]
    return out
