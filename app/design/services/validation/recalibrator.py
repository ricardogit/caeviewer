"""Model recalibration from new experimental data (FASE 8, plan 8.3).

Material test (tensile):
  1. the current constitutive model of the material predicts the new curve → "before" metrics
  2. the new curve is fitted (FASE 6 machinery: toe offset, AICc model choice) → E, σ0.2, law
  3. update: ``replace`` (the test supersedes the previous values — default) or ``bayes``
     (inverse-variance combination of the previous value and the test, per parameter; a previous
     value without std is given a 5 % datasheet-like std)
  4. new parameters + δ (old → new, relative change) stored in the material (calibration history)
     and in the SimExperimentCorrelation.

Structural test (sensors on the part): only the stiffness scale is identifiable from one load
case, and it is exact for linear elasticity: u, ε ∝ 1/E at fixed ν, so with s = simulated at
E_run, the least-squares scale k = Σ w s m / Σ w s² gives E* = E_run / k (an *effective* E: it
also absorbs fixture compliance or load errors — a poor R² after the scale correction means the
mismatch is not a stiffness problem: check BCs and loads).
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from app.design.services.validation.correlator import correlation_metrics

MPA = 1e6
DEFAULT_PRIOR_CV = 0.05


def predict_material_curve(material, strain, strain_offset: float = 0.0) -> tuple[np.ndarray, str]:
    """σ [MPa] predicted by a material's current model at the given (test) strains."""
    from app.design.services.material.parametric import CURVE_MODELS
    eps = np.maximum(np.asarray(strain, float) - strain_offset, 0.0)
    cal = material.calibration or {}
    P = material.parameters or {}
    key = cal.get('best_model')
    if key in CURVE_MODELS and cal.get('fit_parameters'):
        m = CURVE_MODELS[key]
        fp = cal['fit_parameters']
        p = np.array([fp[n]['value'] / (MPA if m.param_units.get(n) == 'MPa' else 1) for n in m.param_names])
        return m.predict(eps, p), m.label
    E = P.get('E', {}).get('value')
    if not E:
        raise ValueError('El material no tiene E.')
    sy = P.get('sigma_y', {}).get('value')
    if sy:
        return np.minimum(E * eps, sy) / MPA, 'Elástico-perfectamente plástico (E, σy)'
    return E * eps / MPA, 'Elástico lineal (E)'


def combine(prior: dict | None, new: dict, mode: str) -> dict:
    """One parameter: {'value', 'std'} prior + new → updated {'value', 'std'} (replace | bayes)."""
    if mode != 'bayes' or not prior or prior.get('value') is None:
        return {'value': float(new['value']), 'std': float(new.get('std') or 0.0)}
    v0 = float(prior['value'])
    s0 = float(prior.get('std') or 0.0) or DEFAULT_PRIOR_CV * abs(v0)
    v1 = float(new['value'])
    s1 = float(new.get('std') or 0.0) or 1e-9 * abs(v1)
    w0, w1 = 1 / s0 ** 2, 1 / s1 ** 2
    return {'value': (w0 * v0 + w1 * v1) / (w0 + w1), 'std': math.sqrt(1 / (w0 + w1))}


def delta_of(old: dict, new: dict, keys) -> dict:
    out = {}
    for k in keys:
        o = (old.get(k) or {}).get('value')
        n = (new.get(k) or {}).get('value')
        if n is None:
            continue
        out[k] = {'old': o, 'new': n, 'rel_change': (n - o) / o if o else None,
                  'old_std': (old.get(k) or {}).get('std'), 'new_std': (new.get(k) or {}).get('std')}
    return out


class ModelRecalibrator:
    """Recalibrate material models (tensile tests) and identify effective stiffness (structural)."""

    def tensile(self, material, strain, stress_mpa, mode: str = 'replace', confidence: float = 0.95) -> dict:
        """Returns {fit, before, after, new_parameters, delta, model_label_before}. Does not commit."""
        from app.design.services.material.parametric import ParametricMaterialModel, material_parameters_from_fit
        pm = ParametricMaterialModel()
        res = pm.fit({'strain': strain, 'stress': stress_mpa}, confidence=confidence)
        spec = pm.specimens[0]
        e0 = spec.get('strain_offset', 0.0)
        eps, sig = spec['strain'], spec['stress']                   # cleaned curve (up to UTS)
        pred_old, label_old = predict_material_curve(material, eps, e0)
        before = correlation_metrics(sig, pred_old)
        sig_new = after_curve(pm, eps)
        after = correlation_metrics(sig, sig_new)
        fitted = material_parameters_from_fit(res, material.parameters)
        old = material.parameters or {}
        new = dict(old)
        for k, v in fitted.items():
            if k in ('E', 'sigma_y', 'uts'):
                new[k] = {**combine(old.get(k), v, mode), 'unit': v.get('unit', 'Pa')}
            else:
                new[k] = v                                            # law parameters: from the test
        # drop hardening parameters of a previous, different law
        prefix = f"{res['best_model']}."
        new = {k: v for k, v in new.items() if '.' not in k or k.startswith(prefix)}
        delta = delta_of(old, new, [k for k in new if k in ('E', 'sigma_y', 'uts') or '.' in k])
        return {'fit': res, 'pm': pm, 'before': before, 'after': after, 'model_before': label_old,
                'new_parameters': new, 'delta': delta, 'mode': mode,
                'curve': {'strain': (eps - e0).tolist(), 'measured': sig.tolist(), 'before': pred_old.tolist(),
                          'after': sig_new.tolist()}}

    @staticmethod
    def structural_stiffness(simulated, measured, E_run: float, std=None, groups=None) -> dict:
        """Effective E from sensor readings (u, ε ∝ 1/E). ``groups`` = quantity of each sensor: values
        are normalized per group (mm and µε pooled by relative error). Returns E*, its std and
        before/after metrics (on the normalized values)."""
        from app.design.services.validation.correlator import group_scales
        sc = group_scales(measured, groups)
        s = np.asarray(simulated, float) / sc
        m = np.asarray(measured, float) / sc
        w = np.ones_like(s) if std is None else 1.0 / np.maximum(np.asarray(std, float) / sc, 1e-12) ** 2
        ss = float((w * s * s).sum())
        if ss <= 0:
            raise ValueError('La simulación da cero en todos los sensores: no se puede identificar E.')
        k = float((w * s * m).sum() / ss)
        if k <= 0:
            raise ValueError('Medición y simulación tienen signos opuestos: revisa ejes, signos o la carga.')
        n = len(s)
        res = m - k * s
        se_k = math.sqrt(float((w * res * res).sum()) / max(n - 1, 1) / ss) if n > 1 else float('nan')
        E_new = E_run / k
        return {'k': k, 'E_old': E_run, 'E_new': E_new, 'E_std': E_run * se_k / k ** 2 if np.isfinite(se_k) else None,
                'rel_change': E_new / E_run - 1, 'before': correlation_metrics(m, s),
                'after': correlation_metrics(m, k * s), 'simulated_after': (k * s * sc).tolist()}

    def recalibrate(self, material_id, experiment_id, mode: str = 'replace') -> dict:
        """Plan interface: tensile experiment → recalibrated material parameters (not committed)."""
        import uuid
        from app.extensions import db
        from app.design.models.material import MaterialModel
        from app.design.models.validation import ExperimentalRecord
        mat = db.session.get(MaterialModel, uuid.UUID(str(material_id)))
        exp = db.session.get(ExperimentalRecord, uuid.UUID(str(experiment_id)))
        if mat is None or exp is None:
            raise ValueError('Material o experimento no encontrado.')
        raw = exp.raw_data or {}
        return self.tensile(mat, raw['strain'], raw['stress'], mode)


def after_curve(pm, eps):
    from app.design.services.material.parametric import shifted
    return shifted(pm.model)(eps, pm.best['_per'][0]['_q'])


def history_entry(experiment_id, delta: dict, mode: str, before: dict, after: dict) -> dict:
    return {'date': datetime.utcnow().isoformat(), 'experiment_id': str(experiment_id), 'mode': mode,
            'delta': delta, 'r2_before': before.get('r2'), 'r2_after': after.get('r2')}
