"""Uncertainty propagation — Monte Carlo through a ROM or full FEM solves (FASE 6).

Inputs are independent random parameters of the study (``E``, ``nu``, ``rho``, ``load_<i>``,
the same keys as the ROM) with normal distributions truncated to their physical range, plus an
optional random yield strength for the failure criterion  g = σy − max σvM.

Evaluation:
  - ``ROMEvaluator``: POD-Galerkin ROM (FASE 5), < 1 ms per sample. Valid when every random
    parameter was varied when the ROM was trained (E is always exact: u ∝ 1/E at fixed ν).
    Samples outside the trained box are counted and reported.
  - ``FullEvaluator``: exact solves reusing the affine operators K = λK_λ + μK_μ (no reassembly).

Outputs: statistics and histograms of max σvM / max |u|, confidence intervals, probability of
failure with its Wilson interval, reliability index β (Cornell: μ_g/σ_g, and −Φ⁻¹(Pf)),
rank-correlation sensitivities, running convergence, and surface fields (mean, std and the
upper confidence quantile) for the 3D band view.

Tier limits (plan 6.2): full solves 100 (tier 0/1), 500 (tier 2), 2000 (tier 3); ROM ≤ 2000.
"""
from __future__ import annotations

import logging
import math
import time

import numpy as np
from scipy import stats as st

from app.design.services.rom.pod import (lame, stress_from_strain, von_mises_voigt, evaluate_arrays,
                                         surface_operator, load_scales_from, CENTROID)

logger = logging.getLogger(__name__)

TIER_MC_SAMPLES = {0: 100, 1: 100, 2: 500, 3: 2000}
MAX_ROM_SAMPLES = 2000
PARAM_LIMITS = {'E': (0.0, None), 'rho': (0.0, None), 'nu': (0.0, 0.499), 'yield': (0.0, None)}


class UncertaintyError(ValueError):
    """User-facing problem with the propagation setup."""


# ── Sampling ──────────────────────────────────────────────────────────────────

def sample_parameters(distributions: dict, n: int, seed: int = 0) -> tuple[list, np.ndarray]:
    """Independent truncated normals. distributions: {key: {mean, std}} → (keys, X (n × k)).

    Inverse-CDF sampling with one generator per variable (seeded by seed and the key), so the
    first m samples are the same for any n ≥ m and adding a variable does not reshuffle others.
    """
    import zlib
    keys = sorted(distributions)
    X = np.empty((n, len(keys)))
    for j, k in enumerate(keys):
        d = distributions[k]
        mu, sd = float(d['mean']), float(d.get('std') or 0.0)
        lo, hi = PARAM_LIMITS.get(k, (None, None))
        if sd <= 0:
            X[:, j] = mu
            continue
        a = -np.inf if lo is None else (lo - mu) / sd
        b = np.inf if hi is None else (hi - mu) / sd
        if not a < b:
            raise UncertaintyError(f"Distribución de '{k}' fuera de su rango físico.")
        rng = np.random.default_rng([int(seed), zlib.crc32(k.encode())])
        X[:, j] = st.truncnorm.ppf(rng.random(n), a, b, loc=mu, scale=sd)
    return keys, X


def summarize(x: np.ndarray, confidence: float, bins: int = 30) -> dict:
    x = np.asarray(x, float)
    a = (1 - confidence) / 2
    counts, edges = np.histogram(x, bins=bins)
    return {
        'mean': float(x.mean()), 'std': float(x.std(ddof=1)) if len(x) > 1 else 0.0,
        'cv': float(x.std(ddof=1) / x.mean()) if len(x) > 1 and x.mean() else 0.0,
        'min': float(x.min()), 'max': float(x.max()),
        'p05': float(np.quantile(x, 0.05)), 'p50': float(np.quantile(x, 0.5)), 'p95': float(np.quantile(x, 0.95)),
        'ci_low': float(np.quantile(x, a)), 'ci_high': float(np.quantile(x, 1 - a)),
        'sem': float(x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else 0.0,
        'histogram': {'counts': counts.tolist(), 'edges': edges.tolist()},
    }


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z = st.norm.ppf(0.5 + confidence / 2)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def reliability(max_vm: np.ndarray, yield_samples: np.ndarray, confidence: float) -> dict:
    g = yield_samples - max_vm
    n = len(g)
    k = int((g <= 0).sum())
    pf = k / n
    lo, hi = wilson_interval(k, n, confidence)
    sd = float(g.std(ddof=1)) if n > 1 else 0.0
    out = {
        'criterion': 'von Mises máx. ≥ límite elástico', 'n_failures': k, 'p_failure': pf,
        'p_failure_ci': [lo, hi], 'g_mean': float(g.mean()), 'g_std': sd,
        'beta_cornell': float(g.mean() / sd) if sd > 0 else (math.inf if g.mean() > 0 else -math.inf),
        'beta_from_pf': float(-st.norm.ppf(pf)) if 0 < pf < 1 else None,
        'beta_pf_upper_bound': float(-st.norm.ppf(hi)) if 0 < hi < 1 else None,
        'safety_factor_mean': float(np.mean(yield_samples) / np.mean(max_vm)),
        'safety_factor_p05': float(np.quantile(yield_samples / max_vm, 0.05)),
    }
    if k == 0:
        out['note'] = (f'Ningún fallo en {n} muestras: Pf < {hi:.2e} con {confidence:.0%} de confianza '
                       '(β de Cornell supone g normal).')
    return out


def sensitivities(keys, X, y) -> dict:
    """Spearman rank correlation of the output with each random input, and the normalized ρ²."""
    out = {}
    for j, k in enumerate(keys):
        if np.ptp(X[:, j]) == 0:
            continue
        rho = st.spearmanr(X[:, j], y).statistic
        out[k] = float(rho) if np.isfinite(rho) else 0.0
    tot = sum(v * v for v in out.values()) or 1.0
    return {k: {'spearman': v, 'share': v * v / tot} for k, v in out.items()}


def convergence(y: np.ndarray, fail: np.ndarray | None, points: int = 40) -> dict:
    n = len(y)
    idx = np.unique(np.geomspace(min(10, n), n, points).astype(int))
    cs, cs2 = np.cumsum(y), np.cumsum(y * y)
    mean = cs[idx - 1] / idx
    var = np.maximum(cs2[idx - 1] / idx - mean ** 2, 0) * idx / np.maximum(idx - 1, 1)
    out = {'n': idx.tolist(), 'mean': mean.tolist(), 'std': np.sqrt(var).tolist(),
           'sem': (np.sqrt(var / idx)).tolist()}
    if fail is not None:
        out['p_failure'] = (np.cumsum(fail)[idx - 1] / idx).tolist()
    return out


# ── Evaluators ────────────────────────────────────────────────────────────────

class ROMEvaluator:
    method = 'rom'

    def __init__(self, rom: dict):
        self.rom = rom
        self.params = {p['key']: p for p in rom['params']}
        self.space = rom['space']
        self.surf_xyz = rom['surf_xyz']
        self.surf_tris = rom['surf_tris']
        self.n_surface = len(rom['surf_nodes'])
        self._Q_el = None

    def _quad_forms(self):
        """σvM² = μ² · uᵣᵀ Q uᵣ per element / surface node (λ drops out of the deviatoric part):
        with engineering strains, σvM² = μ² [2 Σ(εi − εj)² + 3 Σ γ²] = μ² εᵀ W ε and ε = M uᵣ."""
        if self._Q_el is None:
            W = np.zeros((6, 6))
            for i, j in ((0, 1), (1, 2), (2, 0)):
                W[i, i] += 2
                W[j, j] += 2
                W[i, j] -= 2
                W[j, i] -= 2
            W[3, 3] = W[4, 4] = W[5, 5] = 3
            r = int(self.rom['r'])
            for name, M in (('_Q_el', self.rom['strain_modes']), ('_Q_s', self.rom['surf_strain'])):
                M = M.astype(np.float64)
                Q = np.einsum('nci,cd,ndj->nij', M, W, M, optimize=True)
                setattr(self, name, np.ascontiguousarray(Q.reshape(len(M), r * r)))
        return self._Q_el, self._Q_s

    def check(self, keys):
        bad = [k for k in keys if k not in self.space and k != 'E']
        missing = [k for k in keys if k not in self.params]
        if missing:
            raise UncertaintyError(f"El ROM no tiene los parámetros: {', '.join(missing)}")
        if bad:
            raise UncertaintyError(
                f"El ROM se entrenó con {', '.join(self.space) or '—'} fijos/variables; "
                f"{', '.join(bad)} no varió en su entrenamiento: construye un ROM que los incluya o usa solves completos.")

    def in_range(self, q: dict) -> bool:
        # E is exact outside its trained range (K ∝ E at fixed ν → u ∝ 1/E stays in the basis)
        return all(lo - 1e-9 * abs(hi - lo) <= q[k] <= hi + 1e-9 * abs(hi - lo) for k, (lo, hi) in self.space.items()
                   if k in q and k != 'E')

    def evaluate(self, q: dict):
        full = {k: float(q.get(k, p['nominal'])) for k, p in self.params.items()}
        ev = evaluate_arrays(self.rom, full)
        ur = ev['ur'].astype(np.float32)
        disp = self.rom['surf_phi'] @ ur                                   # (n_s, 3)
        eps = (self.rom['surf_strain'] @ ur).astype(np.float64)            # (n_s, 6)
        vm = von_mises_voigt(stress_from_strain(eps, ev['lambda'], ev['mu']))
        return ev['max_von_mises_pa'], ev['max_displacement_m'], disp, vm

    def evaluate_batch(self, qs: list):
        """Vectorized evaluate() for a block of samples: one GEMM per field instead of B small ones.
        Returns max_vm (B,), max_u (B,), disp (B, n_s, 3), vm (B, n_s)."""
        rom = self.rom
        full = [{k: float(q.get(k, p['nominal'])) for k, p in self.params.items()} for q in qs]
        lm = np.array([lame(f['E'], f['nu']) for f in full])                  # (B, 2)
        lam, mu = lm[:, 0], lm[:, 1]
        sc = np.stack([load_scales_from(rom, f) for f in full], axis=1)        # (n_loads, B)
        Kr = lam[:, None, None] * rom['Kl_r'] + mu[:, None, None] * rom['Km_r']
        UR = np.linalg.solve(Kr, (rom['F_r'] @ sc).T[..., None])[..., 0]     # (B, r)
        U = (rom['Phi'] @ UR.T).reshape(-1, 3, len(qs))                       # (n_nodes, 3, B)
        max_u = np.sqrt((U ** 2).sum(1)).max(0)
        r = UR.shape[1]
        Q_el, Q_s = self._quad_forms()
        UU = np.einsum('bi,bj->ijb', UR, UR).reshape(r * r, len(qs))           # uᵣ ⊗ uᵣ
        max_vm = mu * np.sqrt(np.maximum((Q_el @ UU).max(0), 0.0))
        vm = (mu * np.sqrt(np.maximum(Q_s @ UU, 0.0))).T                       # (B, n_s)
        disp = np.moveaxis((rom['surf_phi'].reshape(-1, r) @ UR.T.astype(np.float32)).reshape(-1, 3, len(qs)), 2, 0)
        return max_vm, max_u, disp, vm


class FullEvaluator:
    method = 'full'

    def __init__(self, builder):
        from app.design.services.fem import tet_batch as tb
        self.b = builder
        self.tb = tb
        builder._setup()
        m = builder.mesh
        snodes, tris, A = surface_operator(m)
        self.snodes, self.A = snodes, A
        self.surf_xyz = m.nodes[snodes]
        self.surf_tris = tris
        self.n_surface = len(snodes)
        self.params = builder.params

    def check(self, keys):
        missing = [k for k in keys if k not in self.params]
        if missing:
            raise UncertaintyError(f"El estudio no tiene los parámetros: {', '.join(missing)}")

    def in_range(self, q):
        return True

    def evaluate(self, q: dict):
        b = self.b
        full = b.full_params(q)
        u = np.zeros(b.mesh.n_dof_structural)
        u[b.free] = b.full_solve(q)
        lam, mu = lame(full['E'], full['nu'])
        eps_el = self.tb.strain_at(b.mesh.nodes, b.mesh.elements, u, CENTROID)
        vm_el = von_mises_voigt(stress_from_strain(eps_el, lam, mu))
        U = u.reshape(-1, 3)
        disp = U[self.snodes]
        vm = von_mises_voigt(stress_from_strain(self.A @ eps_el, lam, mu))
        return float(vm_el.max()), float(np.sqrt((U ** 2).sum(1)).max()), disp, vm


# ── Propagator ────────────────────────────────────────────────────────────────

class UncertaintyPropagator:
    """Monte Carlo propagation (plan 6.2)."""

    def __init__(self, progress=None, check_cancel=None):
        self.progress = progress or (lambda *a, **k: None)
        self.check_cancel = check_cancel

    def propagate_monte_carlo(self, evaluator, distributions: dict, n_samples: int, confidence: float = 0.95,
                              seed: int = 0, failure: dict | None = None) -> dict:
        t0 = time.perf_counter()
        varied = {k: d for k, d in distributions.items() if float(d.get('std') or 0) > 0}
        if not varied:
            raise UncertaintyError('Ninguna variable aleatoria: indica al menos una desviación estándar > 0.')
        if not 0.5 <= confidence < 1:
            raise UncertaintyError('El nivel de confianza debe estar en [0.5, 1).')
        evaluator.check(list(distributions))
        dists = dict(distributions)
        has_yield = bool(failure and failure.get('yield_mean'))
        if has_yield:
            dists['yield'] = {'mean': float(failure['yield_mean']), 'std': float(failure.get('yield_std') or 0)}
        keys, X = sample_parameters(dists, n_samples, seed)
        jy = keys.index('yield') if has_yield else None
        pkeys = [k for k in keys if k != 'yield']

        ns = evaluator.n_surface
        max_vm = np.empty(n_samples)
        max_u = np.empty(n_samples)
        vm_s = np.empty((n_samples, ns), np.float32)
        um_s = np.empty((n_samples, ns), np.float32)
        disp_sum = np.zeros((ns, 3))
        out_of_range = 0
        t_last = time.perf_counter()
        block = 100 if hasattr(evaluator, 'evaluate_batch') else 1
        cols = [keys.index(k) for k in pkeys]
        for i0 in range(0, n_samples, block):
            if self.check_cancel:
                self.check_cancel()
            i1 = min(i0 + block, n_samples)
            qs = [dict(zip(pkeys, map(float, X[i, cols]))) for i in range(i0, i1)]
            out_of_range += sum(not evaluator.in_range(q) for q in qs)
            if block > 1:
                mv, mu_, disp, vm = evaluator.evaluate_batch(qs)
            else:
                mv, mu_, d1, v1 = evaluator.evaluate(qs[0])
                mv, mu_, disp, vm = np.array([mv]), np.array([mu_]), d1[None], v1[None]
            max_vm[i0:i1], max_u[i0:i1] = mv, mu_
            vm_s[i0:i1] = vm
            um_s[i0:i1] = np.sqrt((disp.astype(np.float64) ** 2).sum(2))
            disp_sum += disp.sum(0)
            now = time.perf_counter()
            if now - t_last > 0.5 or i1 == n_samples:         # progress costs a DB write: ≤ 2 per s
                t_last = now
                self.progress(100 * i1 / n_samples, f'Muestra {i1}/{n_samples}')

        a = (1 - confidence) / 2
        fail = None
        result = {
            'method': evaluator.method, 'n_samples': n_samples, 'confidence': confidence, 'seed': seed,
            'random_variables': {k: dists[k] for k in keys if float(dists[k].get('std') or 0) > 0},
            'max_von_mises': summarize(max_vm, confidence),
            'max_displacement': summarize(max_u, confidence),
            'sensitivity': {'max_von_mises': sensitivities(pkeys, X[:, [keys.index(k) for k in pkeys]], max_vm),
                            'max_displacement': sensitivities(pkeys, X[:, [keys.index(k) for k in pkeys]], max_u)},
            'out_of_range': out_of_range,
        }
        if has_yield:
            ys = X[:, jy]
            fail = (ys - max_vm) <= 0
            result['reliability'] = reliability(max_vm, ys, confidence)
        result['convergence'] = convergence(max_vm, fail.astype(float) if fail is not None else None)
        surface = {
            'xyz': evaluator.surf_xyz, 'tris': evaluator.surf_tris,
            'vm_mean': vm_s.mean(0), 'vm_std': vm_s.std(0, ddof=1) if n_samples > 1 else np.zeros(ns),
            **dict(zip(('vm_low', 'vm_high'), np.quantile(vm_s, [a, 1 - a], axis=0))),
            'u_mean': um_s.mean(0), 'u_std': um_s.std(0, ddof=1) if n_samples > 1 else np.zeros(ns),
            'u_high': np.quantile(um_s, 1 - a, axis=0),
            'disp_mean': disp_sum / n_samples,
        }
        result['wall_time_s'] = time.perf_counter() - t0
        samples = {'keys': keys, 'X': X, 'max_vm': max_vm, 'max_u': max_u}
        return {'result': result, 'surface': surface, 'samples': samples}

    @staticmethod
    def compute_reliability_index(result_distribution, failure_criterion: dict) -> float:
        """β = (threshold − μ) / σ of the max von Mises distribution (positive = safe)."""
        x = np.asarray(result_distribution, float)
        sd = x.std(ddof=1)
        return float((failure_criterion['threshold'] - x.mean()) / sd) if sd > 0 else math.inf
