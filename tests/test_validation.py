"""FASE 8: continuous validation — sensors, probe, metrics, recalibration."""
import numpy as np
import pytest

from app.design.services.fem.mesh import FEMMesh
from app.design.services.validation.sensors import (MeshProbe, SensorError, gauge_strain, parse_sensor_csv,
                                                    simulate_sensors)
from app.design.services.validation.correlator import confidence_factor, correlation_metrics, similarity, study_signature
from app.design.services.validation.recalibrator import ModelRecalibrator, combine, predict_material_curve


# ── sensor files ──────────────────────────────────────────────────────────────

def test_parse_sensor_csv_spanish_semicolon_decimal_comma():
    text = ("sensor;x;y;z;tipo;medido;incertidumbre;dx;dy;dz\n"
            "LVDT1;500;12,5;12,5;uy;-0,84;0,01;;;\n"
            "G1;100;25;12,5;galga;-310;5;1;0;0\n")
    s = parse_sensor_csv(text)
    assert [x['label'] for x in s] == ['LVDT1', 'G1']
    assert s[0]['quantity'] == 'uy' and s[0]['value'] == pytest.approx(-0.84) and s[0]['std'] == pytest.approx(0.01)
    assert s[1]['quantity'] == 'strain' and s[1]['direction'] == [1.0, 0.0, 0.0]


def test_parse_sensor_csv_units_and_errors():
    s = parse_sensor_csv("label,x,y,z,quantity,value [m]\nA,0,0,0,uz,0.002\n")
    assert s[0]['value'] == pytest.approx(2.0)                      # m → mm
    s = parse_sensor_csv("label,x,y,z,quantity,value [mm/mm],dx,dy,dz\nG,0,0,0,strain,0.0005,0,1,0\n")
    assert s[0]['value'] == pytest.approx(500.0)                    # absolute → µε
    with pytest.raises(SensorError, match='dirección'):
        parse_sensor_csv("label,x,y,z,quantity,value\nG,0,0,0,strain,100\n")
    with pytest.raises(SensorError, match='desconocida'):
        parse_sensor_csv("label,x,y,z,quantity,value\nG,0,0,0,temperatura,100\n")
    with pytest.raises(SensorError, match='Falta la columna'):
        parse_sensor_csv("label,x,y,quantity,value\nG,0,0,uz,1\n")


# ── probe ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('order', [1, 2])
def test_probe_interpolates_linear_field_exactly(order):
    mesh = FEMMesh.generate_cantilever(0.1, 0.02, 0.02, n_along_length=4, order=order)
    probe = MeshProbe(mesh.nodes, mesh.elements)
    A = np.array([[1e-3, 2e-3, -1e-3], [0.5e-3, -2e-3, 1e-3], [3e-3, 0.0, 1e-3]])
    u = mesh.nodes @ A.T                                              # u = A x  → ε constant
    rng = np.random.default_rng(0)
    pts = rng.uniform([0.005, 0.002, 0.002], [0.095, 0.018, 0.018], (20, 3))
    el, nat, dist = probe.locate(pts)
    assert np.all(dist == 0)
    assert np.allclose(probe.displacement(u, el, nat), pts @ A.T, atol=1e-12)
    eps = probe.strain(u.ravel(), el, nat)
    exact = np.array([A[0, 0], A[1, 1], A[2, 2], A[0, 1] + A[1, 0], A[1, 2] + A[2, 1], A[0, 2] + A[2, 0]])
    assert np.allclose(eps, exact, atol=1e-10)
    d = np.array([1, 1, 0]) / np.sqrt(2)
    assert gauge_strain(exact, d) == pytest.approx(d @ (0.5 * (A + A.T)) @ d)


def test_probe_reports_points_outside_the_part():
    mesh = FEMMesh.generate_cantilever(0.1, 0.02, 0.02, n_along_length=4, order=1)
    probe = MeshProbe(mesh.nodes, mesh.elements)
    u = np.zeros_like(mesh.nodes)
    sim = simulate_sensors(probe, u, [{'x': 50, 'y': 10, 'z': 10, 'quantity': 'uy', 'value': 0},
                                      {'x': 50, 'y': 40, 'z': 10, 'quantity': 'uy', 'value': 0}])
    assert not sim['outside'][0] and sim['outside'][1]
    assert 20 - 1e-9 <= sim['distance_mm'][1] < 22               # upper bound of the true 20 mm


# ── metrics ───────────────────────────────────────────────────────────────────

def test_correlation_metrics_and_confidence():
    m = np.array([1.0, 2.0, 3.0, 4.0])
    perfect = correlation_metrics(m, m)
    assert perfect['r2'] == pytest.approx(1) and perfect['max_rel_error'] == 0 and perfect['slope'] == pytest.approx(1)
    off = correlation_metrics(m, 1.1 * m)
    assert off['slope'] == pytest.approx(1 / 1.1) and off['max_rel_error'] == pytest.approx(0.1)
    assert off['r2'] < 1 and off['confidence_factor'] < perfect['confidence_factor']
    single = correlation_metrics([2.0], [2.2])
    assert single['r2_kind'] == 'respecto a cero' and single['r2'] == pytest.approx(0.99)
    assert confidence_factor(1.0, 0.0, 30) == pytest.approx(1.0, abs=1e-4)
    assert confidence_factor(1.0, 0.0, 1) < 0.3                      # one sensor is weak evidence


def test_similarity_of_study_signatures():
    base = {'material': {'E': 210e9, 'nu': 0.3}, 'mesh_source': 'cantilever',
            'mesh_params': {'length': 0.5}, 'bcs': [{'face_set': 'fixed'}],
            'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}
    a = study_signature(base, 'mat-1', 3000)
    assert similarity(a, a) == pytest.approx(1.0)
    b = study_signature({**base, 'material': {'E': 70e9, 'nu': 0.33}}, 'mat-2', 3000)
    c = study_signature({**base, 'mesh_params': {'length': 0.9}}, 'mat-1', 3000)
    assert similarity(a, b) < 1 and similarity(a, c) < 1


# ── recalibration ─────────────────────────────────────────────────────────────

def test_bayes_combination_inverse_variance():
    out = combine({'value': 200.0, 'std': 4.0}, {'value': 210.0, 'std': 4.0}, 'bayes')
    assert out['value'] == pytest.approx(205.0) and out['std'] == pytest.approx(4 / np.sqrt(2))
    out = combine({'value': 200.0}, {'value': 210.0, 'std': 10.0}, 'bayes')    # prior std → 5 % = 10
    assert out['value'] == pytest.approx(205.0)
    assert combine({'value': 200.0, 'std': 4.0}, {'value': 210.0, 'std': 1.0}, 'replace')['value'] == 210.0


class _Mat:
    def __init__(self, parameters, calibration=None):
        self.parameters = parameters
        self.calibration = calibration or {}


def _curve(E=200000.0, sy=350.0, K=600.0, n=0.4, emax=0.12, npts=900, noise=0.5, seed=1):
    """Ludwik test curve [MPa] (the library's own law) with a little noise."""
    from app.design.services.material.parametric import CURVE_MODELS
    rng = np.random.default_rng(seed)
    e = np.concatenate([np.linspace(0, 0.004, npts // 3, endpoint=False),     # dense elastic range (extensometer)
                        np.linspace(0.004, emax, npts - npts // 3)])
    s = CURVE_MODELS['ludwik'].predict(e, np.array([E, sy, K, n]))
    return e, s + rng.normal(0, noise, npts)


def test_tensile_recalibration_recovers_E_and_reports_delta():
    e, s = _curve()
    old = _Mat({'E': {'value': 180e9, 'std': 0.0, 'unit': 'Pa'}, 'nu': {'value': 0.3, 'std': 0, 'unit': ''},
                'sigma_y': {'value': 300e6, 'std': 0.0, 'unit': 'Pa'}})
    assert predict_material_curve(old, [0.001])[1].startswith('Elástico-perfectamente')
    r = ModelRecalibrator().tensile(old, e, s, 'replace')
    E_new = r['new_parameters']['E']['value']
    assert abs(E_new / 200e9 - 1) < 0.02
    assert r['new_parameters']['nu']['value'] == 0.3                  # kept
    assert r['delta']['E']['old'] == 180e9 and r['delta']['E']['rel_change'] == pytest.approx(E_new / 180e9 - 1)
    assert r['after']['r2'] > 0.99 and r['after']['r2'] > r['before']['r2']


def test_structural_stiffness_identification_is_exact_for_linear_elasticity():
    from app.design.services.rom.pod import PODROMBuilder
    spec = {'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
            'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}
    mesh = FEMMesh.generate_cantilever(0.5, 0.025, 0.025, n_along_length=10, order=2)
    b = PODROMBuilder(mesh, spec, {'E': [1e11, 3e11]}, {'n_snapshots': 2})
    b._setup()

    def field(E):
        u = np.zeros(mesh.n_dof_structural)
        u[b.free] = b.full_solve({'E': E})
        return u.reshape(-1, 3)

    sensors = [{'x': 250, 'y': 12.5, 'z': 12.5, 'quantity': 'uy', 'value': 0},
               {'x': 500, 'y': 12.5, 'z': 12.5, 'quantity': 'uy', 'value': 0},
               {'x': 50, 'y': 25, 'z': 12.5, 'quantity': 'strain', 'direction': [1, 0, 0], 'value': 0}]
    probe = MeshProbe(mesh.nodes, mesh.elements)
    measured = simulate_sensors(probe, field(195e9), sensors)['simulated']     # "real" part: E = 195 GPa
    sim = simulate_sensors(probe, field(210e9), sensors)['simulated']
    r = ModelRecalibrator.structural_stiffness(sim, measured, 210e9, groups=[s['quantity'] for s in sensors])
    assert r['E_new'] == pytest.approx(195e9, rel=1e-6)
    assert r['after']['r2'] == pytest.approx(1.0, abs=1e-9) and r['before']['r2'] < r['after']['r2']
    with pytest.raises(ValueError, match='signos'):
        ModelRecalibrator.structural_stiffness(sim, -measured, 210e9)
