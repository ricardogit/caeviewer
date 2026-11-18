"""Thermo-piezoelectricity (one-way thermal → piezo): exact homogeneous states, graph spec, error paths."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import piezo as pz
from app.design.services.fem.constitutive import ThermoPiezoelectric, build_material
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh
from validate_thermopiezo import ALPHA, DT, H, L, P3, TREF, W, material, open_circuit_voltage


@pytest.fixture(scope='module')
def plate():
    m = FEMMesh.generate_cantilever(L, W, H, 3, order=2)
    m.node_sets['all'] = np.arange(m.n_nodes)
    return m


def _run(m, bcs, mat=None, physics=('thermal', 'piezoelectric')):
    return FEMKernel()._solve(None, {'tier': 1, 'physics': list(physics), 'material': mat or material(),
                                     'bcs': list(bcs), 'loads': []}, None, mesh=m)


SHORTED = [{'face_set': 'z0', 'voltage': 0.0}, {'face_set': 'z1', 'voltage': 0.0}]


def test_material_requires_alpha_and_p3():
    assert isinstance(build_material(material()), ThermoPiezoelectric)
    with pytest.raises(ValueError, match='piroeléctrico'):
        build_material({k: v for k, v in material().items() if k != 'p3'})


def test_clamped_uniform_heating_stress_and_pyroelectric_charge(plate):
    r = _run(plate, [{'face_set': '@all', 'temperature': TREF + DT}, {'node_set': 'all', 'dofs': [0, 1, 2]}] + SHORTED)
    pm = pz.PiezoMaterial(material())
    s_ex = -(pm.C @ (ALPHA * DT * np.array([1, 1, 1, 0, 0, 0])))
    assert np.abs(np.array(r['sigma_elemental']) - s_ex).max() < 1e-9 * np.abs(s_ex).max()
    q = [e['charge_C'] for e in r['summary']['piezo']['electrodes']]
    assert q[1] == pytest.approx(-P3 * DT * L * W, rel=1e-10)
    assert q[0] == pytest.approx(P3 * DT * L * W, rel=1e-10)
    assert r['summary']['physics'] == ['thermal', 'piezoelectric']
    assert r['summary']['material_model'] == 'thermopiezoelectric'
    assert 'T' in r['extra_fields']


def test_free_plate_open_circuit_voltage(plate):
    r = _run(plate, [{'face_set': '@all', 'temperature': TREF + DT}, {'face_set': 'z0', 'voltage': 0.0},
                     {'face_set': 'fixed', 'dofs': [0]}, {'face_set': 'y0', 'dofs': [1]},
                     {'face_set': 'z0', 'dofs': [2]}])
    top = np.isclose(plate.nodes[:, 2], H)
    phi = np.asarray(r['extra_fields']['phi'])[top]
    assert phi == pytest.approx(open_circuit_voltage(), rel=1e-10)


def test_linear_temperature_gives_quadratic_potential(plate):
    r = _run(plate, [{'face_set': 'z0', 'temperature': TREF}, {'face_set': 'z1', 'temperature': TREF + DT},
                     {'node_set': 'all', 'dofs': [0, 1, 2]}] + SHORTED)
    z = plate.nodes[:, 2]
    k33 = pz.PiezoMaterial(material()).kappa[2, 2]
    ex = (P3 * DT / k33) * (z ** 2 / (2 * H) - z / 2)
    assert np.abs(np.asarray(r['extra_fields']['phi']) - ex).max() < 1e-10 * np.abs(ex).max()


def test_plain_piezo_with_temperature_is_rejected(plate):
    plain = {k: v for k, v in material().items() if k not in ('alpha', 'p3', 'T_ref', 'k')}
    plain['type'] = 'piezoelectric'
    with pytest.raises(ValueError, match='termo-piezoeléctrico'):
        _run(plate, [{'face_set': '@all', 'temperature': TREF + DT}] + SHORTED, mat=plain)


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_graph_thermopiezo_material_and_physics():
    props = {**pz.PZT5H, 'p3': P3, 'alpha': ALPHA, 'k': 1.5}
    spec = {'material': {'type': 'thermopiezoelectric', 'rho': 7500.0},
            'bcs': [{'temperature': 70.0, 'face_set': 'z1'}, {'voltage': 0.0, 'face_set': 'z0'}], 'loads': []}
    g2s._piezo_material(spec, _node('PZT', **props))
    assert spec['material']['p3'] == P3
    g2s._set_physics(spec, _node('PZT', **props))
    g2s._finalize_physics(spec)
    assert spec['physics'] == ['thermal', 'piezoelectric']
    assert spec['material']['alpha'] == ALPHA and spec['material']['k'] == 1.5 and spec['material']['T_ref'] == 20.0
    with pytest.raises(g2s.GraphSpecError, match='p3'):
        g2s._piezo_material({'material': {'type': 'thermopiezoelectric', 'rho': 1.0}}, _node('PZT', **pz.PZT5H))


def test_graph_thermopiezo_without_thermal_conditions_is_plain_piezo():
    spec = {'material': {'type': 'thermopiezoelectric', **pz.PZT5H, 'p3': P3, 'rho': 7500.0},
            'physics': ['structural'], 'bcs': [{'voltage': 0.0, 'face_set': 'z0'}], 'loads': []}
    g2s._finalize_physics(spec)
    assert spec['physics'] == ['piezoelectric'] and spec['material']['type'] == 'piezoelectric'
    assert 'p3' not in spec['material']


def test_graph_piezo_with_electrodes_is_accepted_and_thermal_is_redirected():
    spec = {'material': {'type': 'piezoelectric'}, 'physics': ['structural'],
            'bcs': [{'voltage': 100.0, 'face_set': 'z1'}], 'loads': [{'surface_charge': 1e-6, 'face_set': 'z1'}]}
    g2s._finalize_physics(spec)                   # used to raise "el material no es piezoeléctrico"
    assert spec['physics'] == ['piezoelectric']
    with pytest.raises(g2s.GraphSpecError, match='Termo-piezoeléctrico'):
        g2s._finalize_physics({'material': {'type': 'piezoelectric'}, 'physics': ['structural', 'thermal'],
                               'bcs': [], 'loads': []})
    with pytest.raises(g2s.GraphSpecError, match='no es piezoeléctrico'):
        g2s._finalize_physics({'material': {'type': 'linear_elastic_isotropic'}, 'physics': ['structural'],
                               'bcs': [{'voltage': 1.0}], 'loads': []})
