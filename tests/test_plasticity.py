"""FASE 2.5 — J2 elastoplasticity (radial return, consistent tangent, Newton-Raphson).

Analytic references, bar along x (homogeneous uniaxial stress, free lateral contraction):
  ε = σ/E + εp,  σ = σy(εp)  →  linear hardening: εp = (σ − σy)/H; after unloading εp stays.
Run: python -m pytest tests/test_plasticity.py -q   (needs gmsh; no database)
"""
import math

import numpy as np
import pytest

from app.design.services.fem import plasticity as pl
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh

E, NU, SY, H = 200e9, 0.3, 250e6, 2e9
L, W = 0.05, 0.01
AREA = W * W


def test_return_map_consistent_tangent_matches_finite_differences():
    for hard in ({'type': 'linear', 'H': H}, {'type': 'voce', 'Q': 100e6, 'b': 30.0, 'H': 1e9},
                 {'type': 'perfect'}):
        mat = pl.J2Material(E, NU, SY, hard)
        rng = np.random.default_rng(1)
        eps = rng.normal(size=(5, 6)) * 5e-3
        eps_p = rng.normal(size=(5, 6)) * 1e-4
        eps_p[:, :3] -= eps_p[:, :3].mean(axis=1, keepdims=True)          # plastic strain is deviatoric
        ep = np.abs(rng.normal(size=5)) * 1e-3
        sig, C, _, _, plastic = mat.return_map(eps, eps_p, ep)
        assert plastic.all()
        h = 1e-9
        for j in range(6):
            d = np.zeros(6)
            d[j] = h
            sp_, _, _, _, _ = mat.return_map(eps + d, eps_p, ep)
            sm_, _, _, _, _ = mat.return_map(eps - d, eps_p, ep)
            assert np.allclose((sp_ - sm_) / (2 * h), C[:, :, j], rtol=1e-5, atol=1e-6 * E), (hard, j)
        # stress stays on the updated yield surface
        _, _, _, ep_new, _ = mat.return_map(eps, eps_p, ep)
        assert np.allclose(pl.von_mises(sig), mat.sy(ep_new), rtol=1e-10)


def test_hardening_table_interpolates_and_is_flat_beyond():
    mat = pl.J2Material(E, NU, SY, {'type': 'table', 'ep': [0, 0.01, 0.05], 'sy': [SY, 300e6, 320e6]})
    assert mat.sy(0.005) == pytest.approx(275e6)
    assert mat.dsy(np.array([0.005]))[0] == pytest.approx(5e9)
    assert mat.sy(0.2) == pytest.approx(320e6) and mat.dsy(np.array([0.2]))[0] == 0.0


@pytest.fixture(scope='module')
def bar():
    m = FEMMesh.generate_cantilever(length=L, width=W, height=W, n_along_length=6, order=2)
    X = m.nodes
    return {'nodes': X, 'elements': m.elements, 'face_sets': m.face_sets,
            'node_sets': {**m.node_sets, 'origin': [int(np.argmin(np.linalg.norm(X, axis=1)))],
                          'corner_y': [int(np.argmin(np.linalg.norm(X - [0, W, 0], axis=1)))]}}


SUPPORTS = [{'face_set': 'fixed', 'dofs': [0], 'values': [0.0]},
            {'node_set': 'origin', 'dofs': [1, 2], 'values': [0.0, 0.0]},
            {'node_set': 'corner_y', 'dofs': [2], 'values': [0.0]}]


def _tension(bar, stress, hardening, **kw):
    spec = {'mesh_source': 'inline', 'tier': 1, **bar, 'bcs': SUPPORTS,
            'loads': [{'face_set': 'tip', 'force': [stress * AREA, 0, 0]}],
            'material': {'type': 'elastoplastic_vonmises', 'E': E, 'nu': NU, 'rho': 7850, 'sigma_y': SY,
                         'hardening': hardening}, **kw}
    r = FEMKernel().solve_sync(spec)
    X = np.asarray(r['nodes'])
    tip = X[:, 0] > L - 1e-9
    return r, float(np.asarray(r['displacement'])[tip, 0].mean())


def test_uniaxial_linear_hardening_load_and_unload(bar):
    s = 300e6
    ep = (s - SY) / H
    r, ux = _tension(bar, s, {'type': 'linear', 'H': H}, n_load_steps=5)
    assert r['summary']['converged']
    assert ux == pytest.approx(L * (s / E + ep), rel=1e-8)
    assert r['summary']['max_equivalent_plastic_strain'] == pytest.approx(ep, rel=1e-8)
    assert r['summary']['plasticity']['plastic_volume_fraction'] == pytest.approx(1.0)
    assert r['summary']['equilibrium_error'] < 1e-8
    r, ux = _tension(bar, s, {'type': 'linear', 'H': H}, n_load_steps=5, load_path=[1.0, 0.0])
    assert ux == pytest.approx(L * ep, rel=1e-7)                    # residual (permanent) elongation
    assert max(r['von_mises_nodal']) < 1e-6 * SY                     # homogeneous: no residual stress
    curve = r['summary']['plasticity']['curve']
    assert curve[-1]['load_factor'] == 0.0 and len(curve) == 11


def test_uniaxial_voce_hardening(bar):
    Q, b = 120e6, 40.0
    s = 330e6
    ep = -math.log(1 - (s - SY) / Q) / b
    _, ux = _tension(bar, s, {'type': 'voce', 'Q': Q, 'b': b}, n_load_steps=8)
    assert ux == pytest.approx(L * (s / E + ep), rel=1e-7)          # Newton tolerance 1e-8 on forces


def test_newton_converges_quadratically_and_elastic_matches_linear(bar):
    r, _ = _tension(bar, 300e6, {'type': 'linear', 'H': H}, n_load_steps=2)
    log = r['solve_info']['convergence_log']
    step2 = [x['residual'] for x in log if x['step'] == 2]
    assert len(step2) <= 6
    # last iterations: e_{k+1} ≈ C e_k² (rate ≥ 1.8 once in the asymptotic range)
    a, b_, c = step2[-4:-1] if len(step2) >= 4 else step2[-3:]
    assert math.log(c) / math.log(b_) > 1.6 or c < 1e-12
    # below yield the plastic solver gives the linear-elastic answer
    rp, uxp = _tension(bar, 100e6, {'type': 'perfect'}, n_load_steps=1)
    rl = FEMKernel().solve_sync({'mesh_source': 'inline', 'tier': 1, **bar, 'bcs': SUPPORTS,
                                 'loads': [{'face_set': 'tip', 'force': [100e6 * AREA, 0, 0]}],
                                 'material': {'E': E, 'nu': NU, 'rho': 7850}})
    assert np.allclose(rp['displacement'], rl['displacement'], rtol=1e-9, atol=1e-15)
    assert rp['summary']['max_equivalent_plastic_strain'] == 0.0


def test_perfect_plasticity_stops_at_the_limit_load(bar):
    r, _ = _tension(bar, 1.2 * SY, {'type': 'perfect'}, n_load_steps=6)
    p = r['summary']['plasticity']
    assert not r['summary']['converged'] and p['limit_load_reached']
    assert p['load_factor'] * 1.2 == pytest.approx(1.0, abs=0.01)      # uniaxial limit: σ = σy


def test_hardening_table_from_fitted_curve():
    from app.design.services.material.parametric import CURVE_MODELS
    model = CURVE_MODELS['voce']
    p = np.array([200e3, 250.0, 120.0, 40.0])                           # MPa (E, σy, Q), b
    t = pl.hardening_table_from_fit(model, p, 200e3, 0.1)
    mat = pl.J2Material(E, NU, 1.0, t)
    ep = np.array([0.0, 0.01, 0.05])
    exact = 250e6 + 120e6 * (1 - np.exp(-40 * ep))
    assert np.allclose(mat.sy(ep), exact, rtol=2e-3)
