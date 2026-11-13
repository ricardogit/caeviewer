"""Least-squares calibration engine (FASE 6).

``least_squares_fit`` fits y ≈ f(x; p) with scipy.optimize.least_squares (trust-region
reflective, bounds, numerical Jacobian) and returns the parameters with their standard
errors from the asymptotic covariance  Σ = s² (JᵀJ)⁻¹,  s² = SSR / (n − k),  plus the quality
metrics used for model selection (R², RMSE, AICc).

``MaterialCalibrator`` is the object interface of the plan (6.3): calibrate any model that
exposes ``predict(x, params)`` against experimental data.
"""
from __future__ import annotations

import logging
import math

import numpy as np
from scipy import optimize

logger = logging.getLogger(__name__)


def fit_metrics(y: np.ndarray, y_fit: np.ndarray, k: int) -> dict:
    y, y_fit = np.asarray(y, float), np.asarray(y_fit, float)
    n = len(y)
    res = y - y_fit
    ssr = float(res @ res)
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ssr / sst if sst > 0 else float('nan')
    rmse = math.sqrt(ssr / n) if n else float('nan')
    # AICc (Gaussian errors): small-sample corrected Akaike criterion for model selection
    if n > k + 1 and ssr > 0:
        aic = n * math.log(ssr / n) + 2 * k
        aicc = aic + 2 * k * (k + 1) / (n - k - 1)
    else:
        aicc = float('inf')
    return {'r2': r2, 'rmse': rmse, 'ssr': ssr, 'aicc': aicc, 'n': n, 'k': k}


def least_squares_fit(fun, x, y, p0, bounds=None, names=None, x_scale='jac', max_nfev: int = 2000,
                      weights=None) -> dict:
    """fun(x, p) → y_model. Returns {params, std, cov, metrics…, converged, nfev, y_fit}.

    ``weights`` (normalized to mean 1) weight the squared residuals; the covariance uses the
    weighted residual variance. Quality metrics (R², RMSE) are reported unweighted.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    p0 = np.asarray(p0, float)
    k = len(p0)
    names = list(names or [f'p{i}' for i in range(k)])
    lo, hi = (np.full(k, -np.inf), np.full(k, np.inf)) if bounds is None else map(np.asarray, bounds)
    span = np.where(np.isfinite(hi - lo), hi - lo, np.abs(p0) + 1.0)
    p0 = np.clip(p0, np.where(np.isfinite(lo), lo + 1e-9 * span, lo), np.where(np.isfinite(hi), hi - 1e-9 * span, hi))

    sw = np.ones_like(y) if weights is None else np.sqrt(np.asarray(weights, float) / np.mean(weights))

    def resid(p):
        r = (fun(x, p) - y) * sw
        return np.where(np.isfinite(r), r, 1e30)

    sol = optimize.least_squares(resid, p0, bounds=(lo, hi), x_scale=x_scale, max_nfev=max_nfev,
                                 ftol=1e-12, xtol=1e-12, gtol=1e-12)
    y_fit = fun(x, sol.x)
    m = fit_metrics(y, y_fit, k)
    cov = np.full((k, k), np.nan)
    dof = len(y) - k
    if dof > 0:
        J = sol.jac
        try:
            # column scaling: parameters of very different magnitude (E ~1e5 MPa, ε0 ~1e-4) make
            # JᵀJ numerically singular; invert in scaled variables and scale back
            sc = np.where(np.abs(sol.x) > 0, np.abs(sol.x), 1.0)
            Js = J * sc
            JtJ_inv = np.linalg.pinv(Js.T @ Js, rcond=1e-12) * np.outer(sc, sc)
            wssr = float(np.sum(sol.fun ** 2))
            cov = JtJ_inv * (wssr / dof)
        except np.linalg.LinAlgError:
            pass
    std = np.sqrt(np.clip(np.diag(cov), 0, None))
    return {
        'names': names,
        'params': dict(zip(names, map(float, sol.x))),
        'std': dict(zip(names, map(float, std))),
        'p': sol.x, 'cov': cov,
        'converged': bool(sol.success), 'nfev': int(sol.nfev), 'message': str(sol.message),
        'y_fit': y_fit, **m,
    }


def prediction_band(fun, x, p, cov, confidence: float = 0.95, s2: float = 0.0, rel_step: float = 1e-6):
    """Delta-method confidence band of the fitted curve (s2 > 0 → prediction band).

    var(ŷ(x)) = g Σ gᵀ with g = ∂f/∂p by central differences. Returns (lower, upper, std).
    """
    from scipy.stats import norm
    x = np.asarray(x, float)
    p = np.asarray(p, float)
    G = np.empty((len(x), len(p)))
    for j in range(len(p)):
        h = rel_step * max(abs(p[j]), 1e-12)
        dp = np.zeros_like(p)
        dp[j] = h
        G[:, j] = (fun(x, p + dp) - fun(x, p - dp)) / (2 * h)
    cov = np.nan_to_num(np.asarray(cov, float))
    var = np.einsum('ij,jk,ik->i', G, cov, G) + s2
    sd = np.sqrt(np.clip(var, 0, None))
    z = norm.ppf(0.5 + confidence / 2)
    y = fun(x, p)
    return y - z * sd, y + z * sd, sd


class MaterialCalibrator:
    """Adjust constitutive model parameters to minimise the model–experiment residual.

    ``model`` must expose ``param_names``, ``bounds(x, y)``, ``initial_guess(x, y)`` and
    ``predict(x, p)`` (see parametric.CURVE_MODELS). Uncertainty: covariance from the
    Gauss-Newton Hessian at the optimum.
    """
    max_iterations: int = 2000

    def calibrate(self, model, experimental_data: dict, initial_params: dict | None = None) -> dict:
        x = np.asarray(experimental_data['strain'], float)
        y = np.asarray(experimental_data['stress'], float)
        guess = model.initial_guess(x, y)
        if initial_params:
            guess = [float(initial_params.get(n, g)) for n, g in zip(model.param_names, guess)]
        fit = least_squares_fit(model.predict, x, y, guess, model.bounds(x, y), model.param_names,
                                max_nfev=self.max_iterations)
        return {
            'calibrated_params': {n: {'value': fit['params'][n], 'std': fit['std'][n]} for n in fit['names']},
            'r_squared': fit['r2'], 'residual_norm': math.sqrt(fit['ssr']), 'rmse': fit['rmse'],
            'aicc': fit['aicc'], 'n_evaluations': fit['nfev'], 'converged': fit['converged'],
            '_fit': fit,
        }
