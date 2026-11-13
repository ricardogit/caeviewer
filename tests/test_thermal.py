"""FASE 2 multiphysics — steady conduction and one-way thermo-mechanical coupling.

Analytic references (bar along x, length L, insulated sides unless stated):
  * fixed T at both ends → linear T, heat flow k A ΔT / L
  * uniform source Q, T = 0 at both ends → T = Q x (L − x) / (2k)  (T10 reproduces it exactly)
  * heat flux q at the tip, T = 0 at x = 0 → T(L) = q L / k
  * convection (h, T∞) at the tip → T(L) = (k T0 / L + h T∞) / (k / L + h)
  * fin with lateral convection → θ/θ0 = cosh(m (L − x)) / cosh(m L), m² = h P / (k A)
  * free bar, uniform ΔT → no stress, tip displacement α ΔT L
  * bar with both ends held in x → σxx = −E α ΔT

Run: python -m pytest tests/test_thermal.py -q   (needs gmsh; no database)
"""
import math

import numpy as np
import pytest

from app.design.services.fem import tet_batch as tb
from app.design.services.fem import thermal as th
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh

L, W, H = 0.10, 0.01, 0.01
K_COND = 50.0
E, NU, ALPHA = 200e9, 0.3, 12e-6


@pytest.fixture(scope='module')
def bar():
    m = FEMMesh.generate_cantilever(length=L, width=W, height=H, n_along_length=10, order=2)
    X = m.nodes
    tris = tb.boundary_faces(m.elements)
    xs = X[tris[:, :3], 0]
    lateral = tris[~((xs < 1e-9).all(1) | (xs > L - 1e-9).all(1))]
    origin = int(np.argmin(np.linalg.norm(X, axis=1)))
    corner_y = int(np.argmin(np.linalg.norm(X - [0, W, 0], axis=1)))
    return {'nodes': X, 'elements': m.elements, 'face_sets': {**m.face_sets, 'lateral': lateral},
            'node_sets': {**m.node_sets, 'origin': [origin], 'corner_y': [corner_y]}}


def _spec(bar, physics, bcs, loads, **mat):
    return {'mesh_source': 'inline', 'physics': physics, 'tier': 1,
            'nodes': bar['nodes'], 'elements': bar['elements'], 'face_sets': bar['face_sets'],
            'node_sets': bar['node_sets'], 'bcs': bcs, 'loads': loads,
            'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': NU, 'rho': 7800.0,
                         'k': K_COND, 'alpha': ALPHA, 'T_ref': 20.0, **mat}}


def _solve(spec):
    r = FEMKernel().solve_sync(spec)
    return r, np.asarray(r['temperature']), np.asarray(r['nodes'])


TFIX = lambda face, t: {'face_set': face, 'temperature': t}  # noqa: E731


def test_conduction_linear_profile_and_heat_balance(bar):
    r, T, X = _solve(_spec(bar, ['thermal'], [TFIX('fixed', 100.0), TFIX('tip', 0.0)], []))
    assert np.allclose(T, 100.0 * (1 - X[:, 0] / L), atol=1e-8)
    s = r['summary']['thermal']
    q = K_COND * W * H * 100.0 / L
    assert s['heat_balance_W']['fixed_T_in'] == pytest.approx(0.0, abs=1e-9 * q)   # in at hot = out at cold
    assert s['max_heat_flux_w_m2'] == pytest.approx(K_COND * 100.0 / L, rel=1e-8)
    assert r['summary']['physics'] == ['thermal'] and 'displacement' not in r


def test_internal_source_parabolic_profile(bar):
    Q = 1e6
    r, T, X = _solve(_spec(bar, ['thermal'], [TFIX('fixed', 0.0), TFIX('tip', 0.0)],
                           [{'heat_source': Q}]))
    x = X[:, 0]
    assert np.allclose(T, Q * x * (L - x) / (2 * K_COND), atol=1e-8 * Q * L * L / K_COND)
    hb = r['summary']['thermal']['heat_balance_W']
    assert hb['source'] == pytest.approx(Q * L * W * H, rel=1e-10)
    assert hb['fixed_T_in'] == pytest.approx(-Q * L * W * H, rel=1e-8)
    assert r['summary']['thermal']['heat_balance_error'] < 1e-9


def test_heat_flux_and_tip_convection(bar):
    q = 2e4
    _, T, X = _solve(_spec(bar, ['thermal'], [TFIX('fixed', 0.0)], [{'face_set': 'tip', 'heat_flux': q}]))
    assert T[X[:, 0] > L - 1e-9].mean() == pytest.approx(q * L / K_COND, rel=1e-9)
    h, Tinf, T0 = 500.0, 20.0, 200.0
    r, T, X = _solve(_spec(bar, ['thermal'], [TFIX('fixed', T0)],
                           [{'face_set': 'tip', 'convection': {'h': h, 'T_inf': Tinf}}]))
    tip = (K_COND * T0 / L + h * Tinf) / (K_COND / L + h)
    assert T[X[:, 0] > L - 1e-9].mean() == pytest.approx(tip, rel=1e-9)
    hb = r['summary']['thermal']['heat_balance_W']
    assert hb['convection_out'] == pytest.approx(h * W * H * (tip - Tinf), rel=1e-8)
    assert hb['fixed_T_in'] == pytest.approx(hb['convection_out'], rel=1e-8)


def test_fin_with_lateral_convection(bar):
    h, T0, Tinf = 25.0, 100.0, 0.0
    r, T, X = _solve(_spec(bar, ['thermal'], [TFIX('fixed', T0)],
                           [{'face_set': 'lateral', 'convection': {'h': h, 'T_inf': Tinf}}]))
    m = math.sqrt(h * 2 * (W + H) / (K_COND * W * H))
    x = X[:, 0]
    exact = T0 * np.cosh(m * (L - x)) / math.cosh(m * L)
    # 1-D fin theory (Biot = hW/2k = 0.0025): the 3-D solution agrees to well below 0.5 %
    assert np.abs(T - exact).max() / T0 < 5e-3
    hb = r['summary']['thermal']['heat_balance_W']
    q_fin = math.sqrt(h * 2 * (W + H) * K_COND * W * H) * T0 * math.tanh(m * L)
    assert hb['fixed_T_in'] == pytest.approx(q_fin, rel=1e-2)
    assert r['summary']['thermal']['heat_balance_error'] < 1e-8


def test_convection_matrix_integrates_quadratic_products_exactly():
    X = np.array([[0, 0, 0], [2, 0, 0], [0, 1, 0], [1, 0, 0], [1, 0.5, 0], [0, 0.5, 0]], float)
    M, NdA = th.convection_batch(X, np.arange(6)[None], 1.0)
    assert M[0].sum() == pytest.approx(1.0)                      # ∫ 1 dA = area
    assert NdA[0].sum() == pytest.approx(1.0)
    assert np.allclose(M[0].sum(1), NdA[0])                      # partition of unity


def test_no_thermal_condition_is_an_error(bar):
    with pytest.raises(ValueError, match='indeterminada'):
        FEMKernel().solve_sync(_spec(bar, ['thermal'], [], [{'heat_source': 1.0}]))
    with pytest.raises(ValueError, match='k'):
        FEMKernel().solve_sync(_spec(bar, ['thermal'], [TFIX('fixed', 0.0)], [], k=0))


def _supports():
    """Statically determinate supports that let the bar expand freely."""
    return [{'face_set': 'fixed', 'dofs': [0], 'values': [0.0]},
            {'node_set': 'origin', 'dofs': [1, 2], 'values': [0.0, 0.0]},
            {'node_set': 'corner_y', 'dofs': [2], 'values': [0.0]}]


def test_free_thermal_expansion_is_stress_free(bar):
    dT = 80.0
    r, T, X = _solve(_spec(bar, ['thermal', 'structural'],
                           [TFIX('fixed', 20.0 + dT), TFIX('tip', 20.0 + dT)] + _supports(), []))
    assert np.allclose(T, 20.0 + dT)
    u = np.asarray(r['displacement'])
    assert np.allclose(u[:, 0], ALPHA * dT * X[:, 0], atol=1e-12)
    assert np.allclose(u[:, 1], ALPHA * dT * X[:, 1], atol=1e-12)
    assert max(r['von_mises_nodal']) < 1e-3 * E * ALPHA * dT
    assert r['summary']['max_temperature'] == pytest.approx(20.0 + dT)


def test_constrained_bar_compressive_stress(bar):
    dT = 50.0
    bcs = [TFIX('fixed', 20.0 + dT), TFIX('tip', 20.0 + dT)] + _supports() + \
          [{'face_set': 'tip', 'dofs': [0], 'values': [0.0]}]
    r, _, _ = _solve(_spec(bar, ['thermal', 'structural'], bcs, []))
    s = np.asarray(r['sigma_elemental'])
    assert np.allclose(s[:, 0], -E * ALPHA * dT, rtol=1e-8)
    assert np.abs(s[:, 1:]).max() < 1e-6 * E * ALPHA * dT
    assert max(r['von_mises_nodal']) == pytest.approx(E * ALPHA * dT, rel=1e-8)


def test_structural_only_unchanged_by_thermal_entries(bar):
    """A purely structural spec ignores nothing and gives the same bytes as before."""
    spec = _spec(bar, ['structural'], _supports() + [{'face_set': 'tip', 'dofs': [0], 'values': [0.0]}],
                 [{'face_set': 'tip', 'force': [0, 0, -10.0]}])
    a = FEMKernel().solve_sync(spec)
    spec2 = {**spec, 'physics': None}
    b = FEMKernel().solve_sync(spec2)
    assert a['summary']['result_hash'] == b['summary']['result_hash']
    assert 'temperature' not in a


def test_free_faces_alias_is_the_rest_of_the_surface(bar):
    conv = {'h': 25.0, 'T_inf': 0.0}
    _, Ta, _ = _solve(_spec(bar, ['thermal'], [TFIX('fixed', 100.0)], [{'face_set': '@free', 'convection': conv}]))
    _, Tb, _ = _solve(_spec(bar, ['thermal'], [TFIX('fixed', 100.0)],
                            [{'face_set': ['lateral', 'tip'], 'convection': conv}]))
    assert np.allclose(Ta, Tb, rtol=1e-12)


def test_coupled_equilibrium_metric_uses_gross_thermal_load(bar):
    bcs = [TFIX('fixed', 70.0), TFIX('tip', 70.0)] + _supports() + [{'face_set': 'tip', 'dofs': [0], 'values': [0.0]}]
    r, _, _ = _solve(_spec(bar, ['thermal', 'structural'], bcs, []))
    assert r['summary']['equilibrium_error'] < 1e-8
    assert r['summary']['physics'] == ['structural', 'thermal']
