"""Linear piezoelectricity (coupled u + φ): material constants, homogeneous exact states, graph entries."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import piezo as pz
from app.design.services.fem.constitutive import Piezoelectric, build_material
from app.design.services.fem.kernel import FEMKernel
from validate_piezo import SUPPORTS, H, L, W, affine_strain, block

MAT = {'type': 'piezoelectric', **pz.PZT5H}


def _run(m, bcs, loads=(), material=MAT):
    return FEMKernel()._solve(None, {'physics': ['piezoelectric'], 'tier': 1, 'material': material,
                                     'bcs': list(bcs), 'loads': list(loads)}, None, mesh=m)


def test_datasheet_constants_are_reproduced():
    pm = pz.PiezoMaterial(MAT)
    d = pm.d_matrix() * 1e12
    assert d[2, 2] == pytest.approx(593, rel=5e-3)
    assert d[2, 0] == pytest.approx(-274, rel=5e-3)
    assert d[0, 5] == pytest.approx(741, rel=5e-3)
    assert pm.free_permittivity()[2, 2] / pz.EPS0 == pytest.approx(3400, rel=5e-3)
    assert isinstance(build_material(MAT), Piezoelectric)


def test_missing_or_inadmissible_constants_are_rejected():
    with pytest.raises(ValueError):
        pz.PiezoMaterial({k: v for k, v in MAT.items() if k != 'e33'})
    with pytest.raises(ValueError):
        pz.PiezoMaterial({**MAT, 'eps33': -1.0})


@pytest.mark.parametrize('order', [1, 2])
def test_converse_effect_and_capacitance_are_exact(order):
    m = block(order=order)
    V = 100.0
    r = _run(m, SUPPORTS + [{'face_set': 'z0', 'voltage': 0.0}, {'face_set': 'z1', 'voltage': V}])
    pm = pz.PiezoMaterial(MAT)
    d, kT = pm.d_matrix(), pm.free_permittivity()
    eps, res = affine_strain(m, np.asarray(r['displacement']))
    assert res < 1e-8
    assert eps[2, 2] == pytest.approx(d[2, 2] * (-V / H), rel=1e-8)
    assert eps[0, 0] == pytest.approx(d[2, 0] * (-V / H), rel=1e-8)
    q = r['summary']['piezo']['electrodes'][1]['charge_C']
    assert q == pytest.approx(kT[2, 2] * L * W / H * V, rel=1e-8)
    assert r['summary']['physics'] == ['piezoelectric']
    assert set(r['extra_fields']) == {'phi', 'Emag'}
    assert float(np.max(r['extra_fields']['phi'])) == pytest.approx(V)


def test_open_circuit_sensor_voltage():
    m = block()
    P = 100.0
    r = _run(m, [{'face_set': 'z0', 'dofs': [2]}, {'node_set': 'p0', 'dofs': [0, 1]}, {'node_set': 'p1', 'dofs': [1]},
                 {'face_set': 'z0', 'voltage': 0.0}], [{'face_set': 'z1', 'force': [0, 0, -P]}])
    pm = pz.PiezoMaterial(MAT)
    V_th = pm.d_matrix()[2, 2] * (-P / (L * W)) * H / pm.free_permittivity()[2, 2]
    s = r['summary']['piezo']
    got = s['max_potential_V'] if V_th > 0 else s['min_potential_V']
    assert got == pytest.approx(V_th, rel=1e-8)


def test_surface_charge_on_an_open_electrode_matches_the_capacitance():
    """A free charge Q on the top face of a mechanically free block raises it to V = Q / Cᵀ."""
    m = block()
    sigma_q = 1e-4                                      # C/m²
    r = _run(m, SUPPORTS + [{'face_set': 'z0', 'voltage': 0.0}], [{'face_set': 'z1', 'surface_charge': sigma_q}])
    kT = pz.PiezoMaterial(MAT).free_permittivity()[2, 2]
    V_th = sigma_q * H / kT
    assert r['summary']['piezo']['max_potential_V'] == pytest.approx(V_th, rel=1e-8)


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_graph_entries_for_electrodes_and_charge():
    e = g2s._bc_node_to_entry({}, _node('top', bc_type='voltage', voltage=50, face_set='z1'))
    assert e == {'voltage': 50.0, 'label': 'top', 'face_set': 'z1'}
    e = g2s._bc_node_to_entry({}, _node('gnd', bc_type='voltage', voltage=0))
    assert e['face_set'] == 'z0'
    with pytest.raises(g2s.GraphSpecError):
        g2s._bc_node_to_entry({}, _node('x', bc_type='voltage'))
    # mechanical BCs honour face_set on the parametric beam (they used to fall back to node_set 'fixed')
    e = g2s._bc_node_to_entry({}, _node('r', bc_type='roller_z', face_set='z0'))
    assert e['face_set'] == 'z0' and e['dofs'] == [2] and 'node_set' not in e
    assert g2s._bc_node_to_entry({}, _node('f', bc_type='fixed'))['node_set'] == 'fixed'
    ld = g2s._load_node_to_entry({}, _node('q', load_type='surface_charge', magnitude=5, unit='µC/m²'))
    assert ld['surface_charge'] == pytest.approx(5e-6)
    assert ld['face_set'] == 'z1'


def test_graph_piezo_material_validation():
    spec = {'material': {'type': 'piezoelectric', 'rho': 7500.0}}
    g2s._piezo_material(spec, _node('PZT', **pz.PZT5H, axis_1=[0, 1, 0], axis_2=[0, 0, 1]))
    assert spec['material']['c33'] == pz.PZT5H['c33'] and spec['material']['axis_1'] == [0.0, 1.0, 0.0]
    with pytest.raises(g2s.GraphSpecError, match='e15'):
        g2s._piezo_material({'material': {'rho': 1.0}}, _node('PZT', **{k: v for k, v in pz.PZT5H.items() if k != 'e15'}))
