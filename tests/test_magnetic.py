"""Linear magnetostatics (scalar potential): fem.magnetic + kernel + graph conversion."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import magnetic as mg
from app.design.services.fem.constitutive import LinearMagnetic, build_material
from validate_magnetic import B_of, H, L, W, bar, solve


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_material_validation():
    m = build_material({'type': 'linear_magnetic', 'mu_r': 4000})
    assert isinstance(m, LinearMagnetic) and m.get_D_matrix()[0, 0] == pytest.approx(mg.MU0 * 4000)
    for bad in ({'mu_r': 0}, {'mu_r': 1, 'Br': [1, 2]}, {}):
        with pytest.raises(ValueError):
            mg.MagneticMaterial(bad)


def test_bar_circuit_permeance_is_exact():
    r = solve(bar(4, order=1), [{'face_set': 'fixed', 'magnetic_potential': 100.0},
                                {'face_set': 'tip', 'magnetic_potential': 0.0}], [], 1000.0)
    g = r['summary']['magnetic']
    assert g['permeance_H'] == pytest.approx(mg.MU0 * 1000 * W * H / L, rel=1e-10)
    assert B_of(r)[:, 0] == pytest.approx(mg.MU0 * 1000 * 100 / L, rel=1e-10)
    assert r['summary']['physics'] == ['magnetic'] and 'displacement' not in r


def test_magnet_short_and_open_circuit():
    r = solve(bar(4), [{'face_set': 'fixed', 'magnetic_potential': 0.0},
                       {'face_set': 'tip', 'magnetic_potential': 0.0}], [], 1.05, (1.3, 0, 0))
    assert B_of(r)[:, 0] == pytest.approx(1.3, rel=1e-10)
    Br = np.array([0.8, -0.5, 0.6])
    r = solve(bar(4), [], [], 1.05, Br)                     # flux walls everywhere: B = 0, H = −Br/μ
    assert np.abs(B_of(r)).max() < 1e-10 and r['summary']['magnetic']['potential_pinned']


def test_unbalanced_flux_without_potential_is_rejected():
    with pytest.raises(ValueError, match='balance'):
        solve(bar(4), [], [{'face_set': 'tip', 'magnetic_flux': 0.5}], 50.0)
    with pytest.raises(ValueError, match='mecánicas'):
        solve(bar(4), [{'node_set': 'fixed', 'dofs': [0, 1, 2]}], [], 50.0)


def test_graph_conversion():
    e = g2s._bc_node_to_entry({}, _node('N', bc_type='magnetic_potential', magnetic_potential=50))
    assert e == {'magnetic_potential': 50.0, 'label': 'N', 'face_set': 'fixed'}
    ld = g2s._load_node_to_entry({}, _node('Bn', load_type='magnetic_flux', magnitude=200, unit='mT'))
    assert ld['magnetic_flux'] == pytest.approx(0.2) and ld['face_set'] == 'tip'
    with pytest.raises(g2s.GraphSpecError):
        g2s._bc_node_to_entry({}, _node('N', bc_type='magnetic_potential'))


# ── saturation and coils ─────────────────────────────────────────────────────

from validate_magnetic import BH_TABLE, BH_TANH, coil_run  # noqa: E402


@pytest.mark.parametrize('bh', [BH_TANH, BH_TABLE], ids=['tanh', 'table'])
def test_bh_tangent_matches_finite_differences(bh):
    m = bar(3)
    c = mg.BHCurve(bh)
    rng = np.random.default_rng(1)
    psi, d = rng.normal(size=m.n_nodes) * 500, rng.normal(size=m.n_nodes)
    K = mg.nonlinear_system(m, c, psi)[1]
    fd = (mg.nonlinear_system(m, c, psi + 1e-3 * d, tangent=False)[0]
          - mg.nonlinear_system(m, c, psi - 1e-3 * d, tangent=False)[0]) / 2e-3
    assert np.abs(K @ d - fd).max() < 1e-7 * np.abs(fd).max()


@pytest.mark.parametrize('bh', [BH_TANH, BH_TABLE], ids=['tanh', 'table'])
def test_saturating_coil_bar_is_exact(bh):
    c = mg.BHCurve(bh)
    N, I = 100, 2.0
    r = coil_run(bar(3), bh, N, I, 4)
    mag = r['summary']['magnetic']
    assert r['summary']['material_model'] == 'saturable_magnetic' and len(mag['curve']) == 4
    for row in mag['curve']:
        h = N * row['current_A'] / L
        assert row['flux_linkage_Wb'] == pytest.approx(N * float(c.b(h)) * W * H, rel=1e-9)
        assert row['L_incremental_H'] == pytest.approx(N * N * float(c.db(h)) * W * H / L, rel=1e-8)
        assert row['energy_J'] + row['coenergy_J'] == pytest.approx(row['flux_linkage_Wb'] * row['current_A'], rel=1e-9)
    assert 'mur' in r['extra_fields']


def test_linear_coil_inductance():
    r = coil_run(bar(3), None, 50, 1.0, 1)
    co = r['summary']['magnetic']['coils'][0]
    Lth = 50 ** 2 * mg.MU0 * 2000 * W * H / L
    assert co['L_secant_H'] == pytest.approx(Lth, rel=1e-10)
    assert co['L_incremental_H'] == pytest.approx(Lth, rel=1e-10)


def test_bh_curve_validation():
    for spec in ({'model': 'tanh', 'mu_r': 1, 'Js': 2}, {'model': 'tanh', 'mu_r': 1000},
                 {'model': 'table', 'points': [[100, 0.5]]}, {'model': 'table', 'points': [[100, 0.5], [200, 0.4]]},
                 {'model': 'table', 'points': [[100, 1e-6], [200, 2e-6]]}, {'model': 'x'}):
        with pytest.raises(ValueError):
            mg.BHCurve(spec)
    with pytest.raises(ValueError, match='imán'):
        mg.MagneticMaterial({'Br': [0, 0, 1.2], 'bh_curve': BH_TANH})
    assert mg.MagneticMaterial({'bh_curve': BH_TANH}).mu_r == pytest.approx(2000)
    c = mg.BHCurve(BH_TABLE)
    assert float(c.b(30000)) == pytest.approx(1.9 + mg.MU0 * 10000)          # slope μ₀ after the last point


def _mnode(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_graph_coil_and_saturation():
    e = g2s._bc_node_to_entry({}, _mnode('Bobina', bc_type='coil', turns=200, current=1.5, current_steps=5))
    assert e['magnetic_potential'] == 300.0 and e['coil'] == {'turns': 200.0, 'current': 1.5, 'steps': 5}
    assert e['face_set'] == 'tip'
    with pytest.raises(g2s.GraphSpecError, match='vueltas'):
        g2s._bc_node_to_entry({}, _mnode('B', bc_type='coil', turns=0, current=1))
    spec = {'material': {'type': 'linear_magnetic', 'mu_r': 3000.0, 'Br': [0, 0, 0], 'rho': 7650.0}}
    g2s._magnetic_saturation(spec, _mnode('Fe', saturation='tanh', Js=2.0))
    assert spec['material']['bh_curve'] == {'model': 'tanh', 'mu_r': 3000.0, 'Js': 2.0}
    spec = {'material': {'type': 'linear_magnetic', 'mu_r': 1.0, 'Br': [0, 0, 0], 'rho': 1.0}}
    g2s._magnetic_saturation(spec, _mnode('Fe', saturation='table', bh_points=BH_TABLE['points']))
    assert spec['material']['bh_curve']['model'] == 'table' and spec['material']['mu_r'] > 1000
    with pytest.raises(g2s.GraphSpecError, match='imán'):
        g2s._magnetic_saturation({'material': {'mu_r': 1.05, 'Br': [0, 0, 1.2]}}, _mnode('M', saturation='tanh', Js=1))
    spec = {'material': {'type': 'linear_magnetic'}, 'physics': ['structural'], 'loads': [],
            'bcs': [{'magnetic_potential': 100.0, 'coil': {'turns': 100, 'current': 1}}]}
    with pytest.raises(g2s.GraphSpecError, match='referencia'):
        g2s._finalize_physics(spec)
