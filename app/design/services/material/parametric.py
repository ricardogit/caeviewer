"""Parametric material models fitted to tensile-test data (FASE 6).

The user uploads one or more σ-ε curves (CSV); every candidate model is fitted by least squares
(calibrator.least_squares_fit) and the best one is chosen by AICc (penalizes extra parameters).
Internally strain is dimensionless and stress in MPa; results are reported in SI (Pa).

Monotonic uniaxial models (engineering σ-ε, fitted up to the ultimate tensile strength —
necking is a structural effect, not a material law):

  linear           σ = E ε
  bilinear         σ = E ε  (ε ≤ σy/E),  σy + Et (ε − σy/E)  after yield
  ramberg_osgood   ε = σ/E + 0.002 (σ/σ0.2)^n
  ludwik           σ = σy + K εpⁿ,              ε = σ/E + εp      (power-law hardening)
  voce             σ = σy + Q (1 − e^(−b εp)),  ε = σ/E + εp      (saturating hardening)
  polynomial_3     σ = a₁ε + a₂ε² + a₃ε³

Implicit laws are inverted for σ(ε) with vectorized bisection (monotone, always converges).
With several specimens the parameters are reported as mean ± std across specimens (real
material scatter); with one, the std is the fit's standard error.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re

import numpy as np

from app.design.services.material.calibrator import least_squares_fit, prediction_band

logger = logging.getLogger(__name__)

OFFSET = 0.002          # 0.2 % offset for the conventional yield strength
MPA = 1e6


class MaterialFitError(ValueError):
    """User-facing problem with the test data."""


# ── σ(ε) inversion helpers ────────────────────────────────────────────────────

def _bisect(f, lo, hi, iters: int = 64):
    """Vectorized bisection for increasing f on [lo, hi] (f(lo) ≤ 0 ≤ f(hi))."""
    lo, hi = np.array(lo, float), np.array(hi, float)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        pos = f(mid) > 0
        hi = np.where(pos, mid, hi)
        lo = np.where(pos, lo, mid)
    return 0.5 * (lo + hi)


def _hardening_curve(eps, E, sy, h):
    """σ(ε) for ε = σ/E + εp, σ = h(εp) after yield (h(0) = σy, h increasing)."""
    eps = np.asarray(eps, float)
    a = np.abs(eps)
    out = E * a
    pl = a > sy / E
    if np.any(pl):
        e = a[pl]
        ep = _bisect(lambda x: h(x) - E * (e - x), np.zeros_like(e), e - sy / E)
        out[pl] = h(ep)
    return np.sign(eps) * out


# ── Models ────────────────────────────────────────────────────────────────────

class CurveModel:
    key = ''
    label = ''
    param_names: list = []
    param_units: dict = {}          # internal units ('MPa' or '')
    elastoplastic = True
    description = ''

    def predict(self, eps, p):
        raise NotImplementedError

    def initial_guess(self, eps, sig):
        raise NotImplementedError

    def bounds(self, eps, sig):
        raise NotImplementedError

    def E(self, p):
        return float(p[0])


def _data_props(eps, sig):
    E = elastic_modulus(eps, sig)
    i = int(np.argmax(sig))
    sy = offset_yield(eps, sig, E) or 0.7 * sig[i]
    return E, sy, float(sig[i]), float(eps[i])


class Linear(CurveModel):
    key, label = 'linear', 'Elástico lineal'
    param_names, param_units = ['E'], {'E': 'MPa'}
    elastoplastic = False
    description = 'σ = E ε'

    def predict(self, eps, p):
        return p[0] * np.asarray(eps, float)

    def initial_guess(self, eps, sig):
        return [elastic_modulus(eps, sig)]

    def bounds(self, eps, sig):
        return [1e-3], [1e8]


class Bilinear(CurveModel):
    key, label = 'bilinear', 'Elastoplástico bilineal'
    param_names, param_units = ['E', 'sigma_y', 'E_t'], {'E': 'MPa', 'sigma_y': 'MPa', 'E_t': 'MPa'}
    description = 'σ = Eε hasta σy, luego pendiente tangente Et'

    def predict(self, eps, p):
        E, sy, Et = p
        eps = np.asarray(eps, float)
        a = np.abs(eps)
        ey = sy / E
        return np.sign(eps) * np.where(a <= ey, E * a, sy + Et * (a - ey))

    def initial_guess(self, eps, sig):
        E, sy, su, eu = _data_props(eps, sig)
        Et = max((su - sy) / max(eu - sy / E, 1e-9), 1e-3 * E)
        return [E, sy, Et]

    def bounds(self, eps, sig):
        smax = float(np.max(sig))
        return [1e-3, 1e-6, 0.0], [1e8, 2 * smax, 1e8]


class RambergOsgood(CurveModel):
    key, label = 'ramberg_osgood', 'Ramberg-Osgood'
    param_names, param_units = ['E', 'sigma_02', 'n'], {'E': 'MPa', 'sigma_02': 'MPa', 'n': ''}
    description = 'ε = σ/E + 0.002 (σ/σ0.2)ⁿ'

    def predict(self, eps, p):
        E, s0, n = p
        eps = np.asarray(eps, float)
        a = np.abs(eps)
        sig = _bisect(lambda s: s / E + OFFSET * np.power(np.maximum(s, 0) / s0, n) - a,
                      np.zeros_like(a), E * a)
        return np.sign(eps) * sig

    def initial_guess(self, eps, sig):
        E, sy, su, eu = _data_props(eps, sig)
        ep_u = max(eu - su / E, 1e-6)
        n = math.log(ep_u / OFFSET) / math.log(max(su / sy, 1.0001)) if su > sy and ep_u > OFFSET else 10.0
        return [E, sy, float(np.clip(n, 1.5, 80))]

    def bounds(self, eps, sig):
        return [1e-3, 1e-6, 1.0], [1e8, 3 * float(np.max(sig)), 200.0]


class Ludwik(CurveModel):
    key, label = 'ludwik', 'Elastoplástico Ludwik (potencial)'
    param_names = ['E', 'sigma_y', 'K', 'n']
    param_units = {'E': 'MPa', 'sigma_y': 'MPa', 'K': 'MPa', 'n': ''}
    description = 'σ = σy + K εpⁿ'

    def predict(self, eps, p):
        E, sy, K, n = p
        return _hardening_curve(eps, E, sy, lambda ep: sy + K * np.power(np.maximum(ep, 0), n))

    def initial_guess(self, eps, sig):
        E, sy, su, eu = _data_props(eps, sig)
        ep_u = max(eu - su / E, 1e-4)
        n = 0.3
        return [E, sy, max(su - sy, 1.0) / ep_u ** n, n]

    def bounds(self, eps, sig):
        smax = float(np.max(sig))
        return [1e-3, 1e-6, 0.0, 0.01], [1e8, 2 * smax, 1e3 * smax, 1.5]


class Voce(CurveModel):
    key, label = 'voce', 'Elastoplástico Voce (saturación)'
    param_names = ['E', 'sigma_y', 'Q', 'b']
    param_units = {'E': 'MPa', 'sigma_y': 'MPa', 'Q': 'MPa', 'b': ''}
    description = 'σ = σy + Q (1 − e^(−b εp))'

    def predict(self, eps, p):
        E, sy, Q, b = p
        return _hardening_curve(eps, E, sy, lambda ep: sy + Q * (1 - np.exp(-b * np.maximum(ep, 0))))

    def initial_guess(self, eps, sig):
        E, sy, su, eu = _data_props(eps, sig)
        ep_u = max(eu - su / E, 1e-4)
        return [E, sy, max(su - sy, 1.0) * 1.1, 3.0 / ep_u]

    def bounds(self, eps, sig):
        smax = float(np.max(sig))
        return [1e-3, 1e-6, 0.0, 1e-3], [1e8, 2 * smax, 5 * smax, 1e5]


class Polynomial3(CurveModel):
    key, label = 'polynomial_3', 'Polinomio cúbico'
    param_names, param_units = ['a1', 'a2', 'a3'], {'a1': 'MPa', 'a2': 'MPa', 'a3': 'MPa'}
    elastoplastic = False
    description = 'σ = a₁ε + a₂ε² + a₃ε³ (empírico, sin límite elástico)'

    def predict(self, eps, p):
        e = np.asarray(eps, float)
        return p[0] * e + p[1] * e ** 2 + p[2] * e ** 3

    def initial_guess(self, eps, sig):
        A = np.column_stack([eps, eps ** 2, eps ** 3])
        return list(np.linalg.lstsq(A, sig, rcond=None)[0])

    def bounds(self, eps, sig):
        return [-np.inf] * 3, [np.inf] * 3


CURVE_MODELS = {m.key: m for m in (Linear(), Bilinear(), RambergOsgood(), Ludwik(), Voce(), Polynomial3())}
CANDIDATE_MODELS = list(CURVE_MODELS)


# ── Data handling ─────────────────────────────────────────────────────────────

def elastic_modulus(eps, sig) -> float:
    """Slope of the linear part of the curve.

    Linear regressions over stress windows spanning 20 % of the UTS, sliding between 5 % and 70 %
    of the UTS on the loading branch; the steepest window that is genuinely linear (R² ≥ 0.995)
    wins. Windows defined in stress (not in number of points) keep the noise influence small.
    """
    eps, sig = np.asarray(eps, float), np.asarray(sig, float)
    su = float(np.max(sig))
    first_hi = int(np.argmax(sig > 0.7 * su)) if np.any(sig > 0.7 * su) else len(sig)
    e, s = eps[:max(first_hi, 3)], sig[:max(first_hi, 3)]
    slopes, best_any = [], 0.0
    for lo in np.arange(0.05, 0.51, 0.05):
        m = (s >= lo * su) & (s <= (lo + 0.2) * su)
        if m.sum() < 4 or np.ptp(e[m]) <= 0:
            continue
        A = np.column_stack([e[m], np.ones(m.sum())])
        coef, res, *_ = np.linalg.lstsq(A, s[m], rcond=None)
        sst = float(((s[m] - s[m].mean()) ** 2).sum())
        r2 = 1 - float(res[0]) / sst if len(res) and sst > 0 else 1.0
        best_any = max(best_any, coef[0])
        if r2 >= 0.995:
            slopes.append(coef[0])
    # the max of noisy windows is biased upward: take the median of the windows near the max
    # (toe and early plasticity give clearly lower slopes and drop out)
    slopes = np.array(slopes)
    best = float(np.median(slopes[slopes >= 0.9 * slopes.max()])) if len(slopes) else best_any
    if best <= 0:
        k = max(2, len(eps) // 10)
        best = float(np.polyfit(eps[:k], sig[:k], 1)[0])
    return float(best)


def offset_yield(eps, sig, E: float, offset: float = OFFSET):
    """Conventional yield strength: first crossing of the curve with σ = E (ε − offset)."""
    d = sig - E * (eps - offset)
    k = np.flatnonzero((d[:-1] > 0) & (d[1:] <= 0))
    if not len(k):
        return None
    i = k[0]
    t = d[i] / (d[i] - d[i + 1])
    return float(sig[i] + t * (sig[i + 1] - sig[i]))


def prepare_curve(strain, stress, truncate_at_uts: bool = True, toe_compensation: bool = True,
                  max_points: int = 400) -> dict:
    """Clean a test curve: finite values, up to UTS, arc-length resampling.

    The toe (slack, seating) is not removed here: every model is fitted as σ = f(ε − ε0) with the
    offset ε0 as an extra parameter, consistent with E. ``toe_guess`` is only its starting value.
    """
    eps = np.asarray(strain, float)
    sig = np.asarray(stress, float)
    ok = np.isfinite(eps) & np.isfinite(sig)
    eps, sig = eps[ok], sig[ok]
    if len(eps) < 8:
        raise MaterialFitError('La curva necesita al menos 8 puntos válidos.')
    notes = []
    i_u = int(np.argmax(sig))
    if truncate_at_uts and i_u < len(sig) - 1:
        notes.append(f'Datos tras la resistencia máxima descartados ({len(sig) - 1 - i_u} puntos: estricción/fractura).')
        eps, sig = eps[:i_u + 1], sig[:i_u + 1]
    keep = sig >= 0
    eps, sig = eps[keep], sig[keep]
    if len(eps) < 8 or np.max(sig) <= 0:
        raise MaterialFitError('La curva no tiene un tramo de carga positivo.')
    E = elastic_modulus(eps, sig)
    toe = 0.0
    if toe_compensation:
        # starting value of ε0: intercept of the elastic line, σ = E (ε − ε0)
        su = np.max(sig)
        m = (sig >= 0.05 * su) & (sig <= 0.25 * su)
        if m.sum() >= 2:
            toe = float(np.clip(np.median(eps[m] - sig[m] / E), 0.0, 0.05 * np.max(eps)))
    # resample uniformly along the normalized arc length (elastic and plastic parts weigh alike)
    if len(eps) > max_points:
        u = np.r_[0, np.cumsum(np.hypot(np.diff(eps) / np.ptp(eps), np.diff(sig) / np.ptp(sig)))]
        t = np.linspace(0, u[-1], max_points)
        j = np.unique(np.searchsorted(u, t).clip(0, len(u) - 1))
        eps, sig = eps[j], sig[j]
    E = elastic_modulus(eps, sig)
    i_u = int(np.argmax(sig))
    props = {'E': E * MPA, 'sigma_02': (offset_yield(eps - toe, sig, E) or float('nan')) * MPA,
             'uts': float(sig[i_u]) * MPA, 'uniform_elongation': float(eps[i_u] - toe)}
    return {'strain': eps, 'stress': sig, 'notes': notes, 'properties': props, 'toe_guess': toe}


_UNIT_STRESS = {'gpa': 1e3, 'mpa': 1.0, 'kpa': 1e-3, 'pa': 1e-6, 'ksi': 6.894757, 'psi': 6.894757e-3,
                'n/mm2': 1.0, 'n/mm²': 1.0}
_UNIT_FORCE = {'kn': 1e3, 'n': 1.0, 'lbf': 4.448222, 'kgf': 9.80665}


def _num(s: str, decimal_comma: bool):
    s = s.strip().replace('﻿', '')
    if decimal_comma:
        s = s.replace('.', '').replace(',', '.') if s.count(',') == 1 and s.count('.') >= 1 else s.replace(',', '.')
    return float(s)


def _unit_in(header: str, table: dict):
    h = header.lower().replace(' ', '')
    for u in sorted(table, key=len, reverse=True):
        if re.search(r'[\[(/_\s]?' + re.escape(u) + r'[\])]?$', h) or f'[{u}]' in h or f'({u})' in h:
            return u
    return None


def parse_curve_csv(text: str, strain_unit: str = 'auto', stress_unit: str = 'auto',
                    area_mm2: float | None = None, gauge_mm: float | None = None) -> dict:
    """Parse a tensile-test CSV into strain [-] and stress [MPa].

    Accepts σ-ε columns (strain in mm/mm or %, stress in Pa/kPa/MPa/GPa/psi/ksi) or force-
    displacement columns (needs the cross-section area [mm²] and the gauge length [mm]).
    Columns are identified by their header (English or Spanish); without a header the first
    two numeric columns are strain, stress.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise MaterialFitError('Archivo vacío.')
    sample = '\n'.join(lines[:50])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=',;\t ').delimiter
    except csv.Error:
        delim = ';' if sample.count(';') > sample.count(',') else ','
    decimal_comma = delim in (';', '\t', ' ') and bool(re.search(r'\d,\d', sample))
    rows = list(csv.reader(lines, delimiter=delim))
    rows = [[c for c in r if c.strip() != ''] if delim == ' ' else r for r in rows]
    header, data = None, []
    for r in rows:
        try:
            vals = [_num(c, decimal_comma) for c in r if c.strip() != '']
        except ValueError:
            if not data:
                header = r            # last non-numeric line before the data is the header
            continue
        if len(vals) >= 2:
            data.append(vals)
    if len(data) < 8:
        raise MaterialFitError('No se encontraron al menos 8 filas numéricas con 2 columnas.')
    ncol = min(len(r) for r in data)
    arr = np.array([r[:ncol] for r in data], float)
    notes = []
    names = [h.strip() for h in header] if header else [f'col{i}' for i in range(ncol)]
    low = [h.lower() for h in names]

    def find(*keys):            # keys match at the start of a word ('tensi' ≠ 'extension')
        for i, h in enumerate(low[:ncol]):
            if any(re.search(r'(?<![a-z])' + re.escape(k), h) for k in keys):
                return i
        return None

    i_eps = find('strain', 'deform', 'ε', 'epsilon', 'elong')
    i_sig = find('stress', 'esfuerzo', 'tensi', 'σ', 'sigma')
    i_f = find('force', 'fuerza', 'carga', 'load')
    i_d = find('displ', 'desplaz', 'extens', 'alarg', 'position', 'posici')
    if i_sig is None and i_f is not None:
        if i_d is None:
            raise MaterialFitError('Hay columna de fuerza pero no de desplazamiento/extensión.')
        if not area_mm2 or not gauge_mm:
            raise MaterialFitError('Datos fuerza-desplazamiento: indica el área de la sección [mm²] y la '
                                   'longitud calibrada [mm].')
        fu = _unit_in(names[i_f], _UNIT_FORCE) or 'n'
        stress = arr[:, i_f] * _UNIT_FORCE[fu] / float(area_mm2)
        strain = arr[:, i_d] / float(gauge_mm)                 # displacement in mm
        notes.append(f'σ = F/A con A = {area_mm2} mm², ε = ΔL/L0 con L0 = {gauge_mm} mm (fuerza en {fu.upper()}).')
    else:
        if i_eps is None or i_sig is None:
            i_eps, i_sig = 0, 1
            if header:
                notes.append(f"Columnas no identificadas por encabezado: se usan '{names[0]}' (ε) y '{names[1]}' (σ).")
        strain, stress = arr[:, i_eps].copy(), arr[:, i_sig].copy()
        # stress unit
        su = stress_unit.lower() if stress_unit and stress_unit != 'auto' else _unit_in(names[i_sig], _UNIT_STRESS)
        if su is None:
            su = 'pa' if np.nanmax(np.abs(stress)) > 1e5 else 'mpa'
            notes.append(f"Unidad de esfuerzo supuesta: {'Pa' if su == 'pa' else 'MPa'}.")
        stress = stress * _UNIT_STRESS[su]
        # strain unit
        if strain_unit and strain_unit != 'auto':
            pct = strain_unit in ('%', 'percent', 'pct')
        else:
            pct = '%' in names[i_eps] or 'percent' in low[i_eps] or 'porcent' in low[i_eps]
            if not pct and np.nanmax(np.abs(strain)) > 1.5:
                pct = True
                notes.append('Deformación > 1.5: se interpreta en %.')
        if pct:
            strain = strain / 100.0
    return {'strain': strain, 'stress': stress, 'notes': notes, 'columns': names[:ncol], 'n_rows': len(arr)}


# ── Fitting ───────────────────────────────────────────────────────────────────

def _to_si(model: CurveModel, name: str, v: float) -> float:
    return v * MPA if model.param_units.get(name) == 'MPa' else v


def model_yield(model: CurveModel, p, eps_max: float) -> float | None:
    """σ0.2 of a fitted model (offset construction on a dense curve), MPa."""
    if not model.elastoplastic:
        return None
    if model.key == 'ramberg_osgood':
        return float(p[1])
    e = np.linspace(0, max(eps_max, 3 * OFFSET), 4000)
    return offset_yield(e, model.predict(e, p), model.E(p))


def arc_weights(eps, sig) -> np.ndarray:
    """Weight of each point = its share of the normalized (ε/ε_max, σ/σ_max) arc length, so a
    short, sparsely sampled elastic branch weighs what it spans on the curve, not its point count."""
    e = np.asarray(eps, float) / max(np.ptp(eps), 1e-300)
    s = np.asarray(sig, float) / max(np.ptp(sig), 1e-300)
    seg = np.hypot(np.diff(e), np.diff(s))
    w = np.zeros(len(e))
    w[:-1] += seg / 2
    w[1:] += seg / 2
    w = np.maximum(w, 1e-3 * w.mean())
    return w / w.mean()


def shifted(model: CurveModel):
    """σ = f(ε − ε0; p) with q = [p…, ε0] (zero stress before the toe offset)."""
    k = len(model.param_names)
    return lambda x, q: model.predict(np.maximum(np.asarray(x, float) - q[k], 0.0), q[:k])


def fit_curve(model: CurveModel, eps, sig, confidence: float = 0.95, e0_guess: float = 0.0) -> dict:
    eps = np.asarray(eps, float)
    k = len(model.param_names)
    e_g = np.maximum(eps - e0_guess, 0.0)
    lo, hi = model.bounds(e_g, sig)
    emax = float(np.max(eps))
    fit = least_squares_fit(shifted(model), eps, sig, list(model.initial_guess(e_g, sig)) + [e0_guess],
                            (list(lo) + [-0.01 * emax], list(hi) + [0.1 * emax]),
                            model.param_names + ['strain_offset'], weights=arc_weights(eps, sig))
    q = fit['p']
    p = q[:k]
    cov_p = fit['cov'][:k, :k]
    sy = model_yield(model, p, float(np.max(eps)))
    sy_std = None
    if sy and model.key != 'ramberg_osgood' and np.all(np.isfinite(cov_p)):
        # delta method on the derived σ0.2 (central differences)
        g = np.zeros(len(p))
        for j in range(len(p)):
            h = 1e-5 * max(abs(p[j]), 1e-9)
            dp = np.zeros(len(p))
            dp[j] = h
            a1 = model_yield(model, p + dp, float(np.max(eps)))
            a0 = model_yield(model, p - dp, float(np.max(eps)))
            g[j] = (a1 - a0) / (2 * h) if a1 is not None and a0 is not None else 0.0
        sy_std = float(np.sqrt(max(g @ cov_p @ g, 0.0)))
    return {
        'model': model.key, 'label': model.label, 'description': model.description,
        'elastoplastic': model.elastoplastic,
        'params': {n: _to_si(model, n, fit['params'][n]) for n in model.param_names},
        'std': {n: _to_si(model, n, fit['std'][n]) for n in model.param_names},
        'units': {n: ('Pa' if model.param_units.get(n) == 'MPa' else '') for n in model.param_names},
        'r2': fit['r2'], 'rmse_pa': fit['rmse'] * MPA, 'aicc': fit['aicc'], 'converged': fit['converged'],
        'nfev': fit['nfev'], 'E': (model.E(p) if model.key != 'polynomial_3' else float(p[0])) * MPA,
        'sigma_02': sy * MPA if sy else None,
        'sigma_02_std': sy_std * MPA if sy_std is not None else None,
        'strain_offset': float(q[k]), 'strain_offset_std': float(fit['std']['strain_offset']),
        '_p': p, '_q': q, '_cov': fit['cov'], '_s2': fit['ssr'] / max(fit['n'] - fit['k'], 1),
    }


def _public(fr: dict) -> dict:
    return {k: v for k, v in fr.items() if not k.startswith('_')}


class ParametricMaterialModel:
    """Fit every candidate to the test curves, keep the best by AICc (plan 6.1)."""

    def __init__(self):
        self.best = None
        self.model = None
        self.specimens = []
        self.results = []

    def fit(self, experimental_data, model_candidates: list | None = None, confidence: float = 0.95,
            truncate_at_uts: bool = True) -> dict:
        """experimental_data: {'strain': [...], 'stress': [... MPa]} or a list of them (specimens).

        Returns {best_model, parameters {name: {value, std, unit}}, r_squared, all_results,
        specimens, properties, curves}.
        """
        datasets = experimental_data if isinstance(experimental_data, list) else [experimental_data]
        cands = [CURVE_MODELS[k] for k in (model_candidates or CANDIDATE_MODELS) if k in CURVE_MODELS]
        if not cands:
            raise MaterialFitError('Ningún modelo candidato válido.')
        specs = []
        for i, d in enumerate(datasets):
            c = prepare_curve(d['strain'], d['stress'], truncate_at_uts=truncate_at_uts)
            c['name'] = d.get('name') or f'Probeta {i + 1}'
            specs.append(c)
        results = []
        for m in cands:
            per = []
            for c in specs:
                try:
                    per.append(fit_curve(m, c['strain'], c['stress'], confidence, c['toe_guess']))
                except Exception as e:                      # one bad model must not sink the rest
                    logger.warning('fit %s failed: %s', m.key, e)
                    per = None
                    break
            if not per:
                continue
            agg = self._aggregate(m, per)
            results.append({'model': m.key, 'label': m.label, 'description': m.description,
                            'elastoplastic': m.elastoplastic,
                            'r2': min(f['r2'] for f in per), 'r2_per_specimen': [f['r2'] for f in per],
                            'aicc': float(sum(f['aicc'] for f in per)),
                            'rmse_mpa': float(np.sqrt(np.mean([f['rmse_pa'] ** 2 for f in per])) / MPA),
                            'parameters': agg, 'converged': all(f['converged'] for f in per),
                            '_per': per})
        if not results:
            raise MaterialFitError('Ningún modelo pudo ajustarse.')
        results.sort(key=lambda r: r['aicc'])
        best = results[0]
        self.best, self.model, self.specimens, self.results = best, CURVE_MODELS[best['model']], specs, results
        for c, f in zip(specs, best['_per']):
            c['strain_offset'] = f['strain_offset']
            if f['strain_offset'] > 1e-3 * np.ptp(c['strain']):
                c['notes'].append(f"Pie de curva (holgura/asentamiento): ε0 = {100 * f['strain_offset']:.4f} % "
                                  'ajustado junto con el modelo.')
        props = self._properties(specs, best)
        curves = self.curves(confidence)
        return {
            'best_model': best['model'], 'label': best['label'],
            'parameters': best['parameters'], 'r_squared': best['r2'],
            'properties': props,
            'all_results': [{k: v for k, v in r.items() if not k.startswith('_')} for r in results],
            'specimens': [{'name': c['name'], 'n_points': int(len(c['strain'])), 'notes': c['notes'],
                           'properties': c['properties']} for c in specs],
            'curves': curves, 'confidence': confidence,
            'std_source': 'specimens' if len(specs) > 1 else 'fit',
        }

    @staticmethod
    def _aggregate(m: CurveModel, per: list) -> dict:
        out = {}
        names = list(m.param_names)
        extra = ['sigma_02'] if m.elastoplastic and 'sigma_02' not in names else []
        for n in names + extra:
            vals = np.array([f['params'][n] if n in f['params'] else (f['sigma_02'] or np.nan) for f in per], float)
            if len(per) > 1:
                std = float(np.nanstd(vals, ddof=1))
            else:
                std = float(per[0]['std'][n]) if n in per[0]['std'] else float(per[0].get('sigma_02_std') or np.nan)
            unit = per[0]['units'].get(n, 'Pa' if n == 'sigma_02' else '')
            out[n] = {'value': float(np.nanmean(vals)), 'std': std, 'unit': unit, 'derived': n in extra}
        return out

    @staticmethod
    def _properties(specs, best) -> dict:
        def agg(key):
            v = np.array([c['properties'][key] for c in specs], float)
            return {'value': float(np.nanmean(v)), 'std': float(np.nanstd(v, ddof=1)) if len(v) > 1 else None}
        props = {k: agg(k) for k in ('E', 'sigma_02', 'uts', 'uniform_elongation')}
        props['source'] = 'datos (pendiente elástica y desplazamiento 0.2 %)'
        return props

    def predict(self, strain, temperature: float = 293.0, params: dict | None = None) -> dict:
        """σ [Pa] and tangent dσ/dε [Pa] of the fitted model (temperature: isothermal fit)."""
        if self.model is None:
            raise MaterialFitError('Modelo sin ajustar.')
        p = self._p(params)
        e = np.atleast_1d(np.asarray(strain, float))
        h = 1e-7
        s = self.model.predict(e, p)
        t = (self.model.predict(e + h, p) - self.model.predict(np.maximum(e - h, 0), p)) / (e + h - np.maximum(e - h, 0))
        return {'stress': (s * MPA).tolist(), 'tangent_modulus': (t * MPA).tolist(), 'temperature': temperature}

    def _p(self, params=None, result=None):
        r = result or self.best
        m = CURVE_MODELS[r['model']]
        src = params or {n: v['value'] for n, v in r['parameters'].items()}
        return np.array([src[n] / (MPA if m.param_units.get(n) == 'MPa' else 1) for n in m.param_names])

    def get_uncertainty_bounds(self, strain, confidence: float = 0.95, prediction: bool = False):
        """Delta-method band of the fitted mean curve (first specimen's covariance), Pa."""
        per = self.best['_per'][0]
        x = np.asarray(strain, float) + per['strain_offset']
        lo, hi, _ = prediction_band(shifted(self.model), x, per['_q'], per['_cov'], confidence,
                                    per['_s2'] if prediction else 0.0)
        return lo * MPA, hi * MPA

    def curves(self, confidence: float = 0.95, n: int = 120) -> dict:
        """Data and fitted curve(s) for the UI chart (strain [-], stress [MPa])."""
        emax = max(float(np.max(c['strain'] - c.get('strain_offset', 0.0))) for c in self.specimens)
        e = np.linspace(0, emax, n)
        out = {'strain': e.tolist(), 'specimens': [], 'fits': {}}
        for c in self.specimens:                 # data shown with the fitted toe offset removed
            step = max(1, len(c['strain']) // 200)
            out['specimens'].append({'name': c['name'],
                                     'strain': (c['strain'][::step] - c.get('strain_offset', 0.0)).tolist(),
                                     'stress': c['stress'][::step].tolist()})
        for r in self.results:
            m = CURVE_MODELS[r['model']]
            p = self._p(result=r)
            per = r['_per'][0]
            lo, hi, _ = prediction_band(shifted(m), e + per['strain_offset'], per['_q'], per['_cov'], confidence,
                                        per['_s2'])
            out['fits'][r['model']] = {'stress': m.predict(e, p).tolist(), 'lower': lo.tolist(), 'upper': hi.tolist()}
        return out

