"""FASE 6 — parametric material fits, calibration and uncertainty propagation."""
import json

import numpy as np
import pytest
from scipy import stats as st

from app.design.services.fem.mesh import FEMMesh
from app.design.services.material.calibrator import least_squares_fit, MaterialCalibrator
from app.design.services.material.parametric import (CURVE_MODELS, MaterialFitError, ParametricMaterialModel,
                                                     _hardening_curve, elastic_modulus, offset_yield,
                                                     parse_curve_csv, prepare_curve)
from app.design.services.material.uncertainty import (FullEvaluator, ROMEvaluator, UncertaintyError,
                                                      UncertaintyPropagator, sample_parameters, wilson_interval)
from app.design.services.rom.pod import PODROMBuilder


def voce_curve(E=69000.0, sy=276.0, Q=50.0, b=40.0, emax=0.08, n=800, noise=0.0, seed=0):
    e = np.linspace(0, emax, n)
    s = _hardening_curve(e, E, sy, lambda ep: sy + Q * (1 - np.exp(-b * ep)))
    if noise:
        s = s + np.random.default_rng(seed).normal(0, noise, n)
    return e, s


# ── models and fitting ────────────────────────────────────────────────────────

@pytest.mark.parametrize('key', ['bilinear', 'ramberg_osgood', 'ludwik', 'voce'])
def test_models_are_monotone_and_elastic_at_origin(key):
    m = CURVE_MODELS[key]
    e, s = voce_curve()
    p = np.array(m.initial_guess(e, s))
    y = m.predict(e, p)
    assert np.all(np.diff(y) >= -1e-9)
    assert y[1] / e[1] == pytest.approx(p[0], rel=0.02)          # initial slope = E
    assert np.allclose(m.predict(-e, p), -y)                      # odd symmetry


def test_ramberg_osgood_inversion_is_exact():
    m = CURVE_MODELS['ramberg_osgood']
    E, s0, n = 200000.0, 350.0, 12.0
    sig = np.linspace(1, 500, 50)
    eps = sig / E + 0.002 * (sig / s0) ** n
    assert np.allclose(m.predict(eps, [E, s0, n]), sig, rtol=1e-10)


def test_least_squares_recovers_line_with_standard_errors():
    rng = np.random.default_rng(3)
    x = np.linspace(0, 1, 200)
    y = 2.0 * x + 1.0 + rng.normal(0, 0.1, len(x))
    f = least_squares_fit(lambda x, p: p[0] * x + p[1], x, y, [1, 0], names=['a', 'b'])
    # classical OLS standard error of the slope
    se_a = 0.1 / np.sqrt(((x - x.mean()) ** 2).sum())
    assert f['params']['a'] == pytest.approx(2.0, abs=4 * se_a)
    assert f['std']['a'] == pytest.approx(se_a, rel=0.15)
    assert f['r2'] > 0.95


def test_offset_yield_and_modulus_on_exact_curve():
    e, s = voce_curve(n=4000)
    assert elastic_modulus(e, s) == pytest.approx(69000, rel=1e-3)
    # σ0.2 of Voce: σ = σy + Q(1 − e^{−b·0.002})
    expected = 276 + 50 * (1 - np.exp(-40 * 0.002))
    assert offset_yield(e, s, 69000) == pytest.approx(expected, rel=1e-3)


def test_fit_picks_true_law_with_noise_toe_and_necking():
    e, s = voce_curve(emax=0.1, n=1500, noise=1.5, seed=1)
    neck = e > 0.08
    s[neck] *= 1 - 4 * (e[neck] - 0.08) ** 1.5
    r = ParametricMaterialModel().fit({'strain': e + 0.0004, 'stress': s})
    assert r['best_model'] == 'voce'
    p = r['parameters']
    assert r['r_squared'] > 0.99
    assert p['E']['value'] == pytest.approx(69e9, rel=0.02)
    assert p['sigma_y']['value'] == pytest.approx(276e6, rel=0.01)
    assert p['sigma_02']['std'] > 0
    notes = ' '.join(r['specimens'][0]['notes']).lower()
    assert 'estricción' in notes and 'pie de curva' in notes


def test_multiple_specimens_give_between_specimen_scatter():
    data = []
    Es = [67000.0, 69000.0, 71000.0]
    for i, E in enumerate(Es):
        e, s = voce_curve(E=E, sy=270 + 6 * i, noise=0.5, seed=i)
        data.append({'name': f'P{i}', 'strain': e, 'stress': s})
    r = ParametricMaterialModel().fit(data, ['voce', 'ludwik'])
    assert r['std_source'] == 'specimens'
    E = r['parameters']['E']
    assert E['value'] == pytest.approx(69e9, rel=0.01)
    assert E['std'] == pytest.approx(np.std(Es, ddof=1) * 1e6, rel=0.25)


def test_calibrator_object_interface():
    e, s = voce_curve(noise=0.3)
    out = MaterialCalibrator().calibrate(CURVE_MODELS['voce'], {'strain': e, 'stress': s})
    assert out['converged'] and out['r_squared'] > 0.999
    assert out['calibrated_params']['sigma_y']['value'] == pytest.approx(276, rel=0.01)


def test_prepare_curve_rejects_garbage():
    with pytest.raises(MaterialFitError):
        prepare_curve([0, 1, 2], [0, 1, 2])


# ── CSV parsing ───────────────────────────────────────────────────────────────

def test_csv_spanish_decimal_comma_percent():
    e, s = voce_curve(n=50)
    txt = 'Ensayo de tracción\nDeformación (%);Esfuerzo (MPa)\n' + '\n'.join(
        f'{a * 100:.6f};{b:.4f}'.replace('.', ',') for a, b in zip(e, s))
    d = parse_curve_csv(txt)
    assert np.allclose(d['strain'], e, atol=1e-8) and np.allclose(d['stress'], s, atol=1e-4)


def test_csv_pa_and_force_displacement():
    e, s = voce_curve(n=40)
    txt = 'strain,stress [Pa]\n' + '\n'.join(f'{a},{b * 1e6}' for a, b in zip(e, s))
    d = parse_curve_csv(txt)
    assert np.allclose(d['stress'], s)
    A, L0 = 20.0, 50.0
    txt = 'Force (kN),Extension (mm)\n' + '\n'.join(f'{b * A / 1000},{a * L0}' for a, b in zip(e, s))
    with pytest.raises(MaterialFitError):
        parse_curve_csv(txt)
    d = parse_curve_csv(txt, area_mm2=A, gauge_mm=L0)
    assert np.allclose(d['stress'], s) and np.allclose(d['strain'], e)


# ── uncertainty ───────────────────────────────────────────────────────────────

def test_sampling_prefix_stable_and_truncated():
    d = {'E': {'mean': 200e9, 'std': 20e9}, 'nu': {'mean': 0.45, 'std': 0.1}}
    k1, X1 = sample_parameters(d, 50, seed=4)
    k2, X2 = sample_parameters(d, 500, seed=4)
    assert k1 == k2 == ['E', 'nu']
    assert np.array_equal(X1, X2[:50])
    assert X2[:, 1].max() < 0.5 and X2[:, 1].min() >= 0
    # adding a variable does not change the others
    _, X3 = sample_parameters({**d, 'rho': {'mean': 7800, 'std': 100}}, 50, seed=4)
    assert np.array_equal(X3[:, 0], X1[:, 0])


def test_wilson_interval_zero_failures():
    lo, hi = wilson_interval(0, 1000, 0.95)
    assert lo == pytest.approx(0, abs=1e-12) and 0.002 < hi < 0.005


SPEC = {'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
        'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
        'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}


@pytest.fixture(scope='module')
def cantilever_rom():
    mesh = FEMMesh.generate_cantilever(0.5, 0.025, 0.025, n_along_length=10, order=2)
    b = PODROMBuilder(mesh, SPEC, {'E': [150e9, 270e9], 'load_0': [500, 1500]}, {'n_snapshots': 10, 'n_test': 0})
    rom = b.build()
    rom['params'] = json.loads(str(rom['params_json']))
    rom['space'] = json.loads(str(rom['space_json']))
    return mesh, rom


def test_rom_and_full_monte_carlo_agree_sample_by_sample(cantilever_rom):
    mesh, rom = cantilever_rom
    d = {'E': {'mean': 210e9, 'std': 15e9}, 'load_0': {'mean': 1000, 'std': 100}}
    P = UncertaintyPropagator()
    a = P.propagate_monte_carlo(ROMEvaluator(rom), d, 30, seed=2)
    b = P.propagate_monte_carlo(FullEvaluator(PODROMBuilder(mesh, SPEC, {'E': [1e11, 3e11]}, {'n_snapshots': 2})),
                                d, 30, seed=2)
    assert np.allclose(a['samples']['max_u'], b['samples']['max_u'], rtol=1e-6)
    assert np.allclose(a['samples']['max_vm'], b['samples']['max_vm'], rtol=1e-4)
    assert np.allclose(a['surface']['vm_mean'], b['surface']['vm_mean'], rtol=1e-3)


def test_reliability_matches_analytic_normal_case(cantilever_rom):
    """max σvM is linear in the load (statically determinate) → g = Y − c·F is normal:
    Pf = Φ(−(μY − c μF) / sqrt(σY² + c² σF²))."""
    _, rom = cantilever_rom
    ev = ROMEvaluator(rom)
    c = ev.evaluate({'load_0': 1000.0})[0] / 1000.0
    muF, sdF = 1000.0, 150.0
    muY = c * muF * 1.4
    sdY = 0.1 * muY
    d = {'load_0': {'mean': muF, 'std': sdF}}
    r = UncertaintyPropagator().propagate_monte_carlo(ev, d, 2000, 0.95, seed=1,
                                                      failure={'yield_mean': muY, 'yield_std': sdY})['result']
    beta = (muY - c * muF) / np.hypot(sdY, c * sdF)
    pf = st.norm.cdf(-beta)
    rel = r['reliability']
    lo, hi = rel['p_failure_ci']
    assert lo <= pf <= hi
    assert rel['beta_cornell'] == pytest.approx(beta, rel=0.05)
    sens = r['sensitivity']['max_von_mises']
    assert sens['load_0']['spearman'] > 0.999


def test_rom_refuses_variables_it_was_not_trained_on(cantilever_rom):
    _, rom = cantilever_rom
    with pytest.raises(UncertaintyError):
        UncertaintyPropagator().propagate_monte_carlo(ROMEvaluator(rom), {'nu': {'mean': 0.3, 'std': 0.02}}, 20)
    with pytest.raises(UncertaintyError):
        UncertaintyPropagator().propagate_monte_carlo(ROMEvaluator(rom), {'E': {'mean': 2e11, 'std': 0}}, 20)
