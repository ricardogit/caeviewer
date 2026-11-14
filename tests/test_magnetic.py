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
