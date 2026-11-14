"""Steady Stokes flow (Taylor-Hood P2-P1): exact polynomial flows, enclosed-flow pressure pin, graph entries."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import stokes as st
from app.design.services.fem.constitutive import NewtonianFluid, build_material
from app.design.services.fem.mesh import FEMMesh
from validate_fluid import ENDS, MU, RHO, channel, duct_flow, flow, solve

L, W, H, DP = 4e-3, 2e-3, 1e-3, 100.0
WALLS = [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
         {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}]


def test_material_validation():
    assert isinstance(build_material({'type': 'newtonian_fluid', 'mu': 1e-3}), NewtonianFluid)
    for bad in ({}, {'mu': 0}, {'mu': 1e-3, 'rho': -1}):
        with pytest.raises(ValueError):
            st.FluidMaterial(bad)


def test_plane_poiseuille_is_exact():
    m = channel(L, W, H, 6)
    r = solve(m, WALLS + ENDS, [{'face_set': 'fixed', 'pressure': DP, 'label': 'in'}])
    z, x = m.nodes[:, 2], m.nodes[:, 0]
    u_th = DP / (2 * MU * L) * z * (H - z)
    assert np.abs(r['velocity'][:, 0] - u_th).max() < 1e-8 * u_th.max()
    assert np.abs(r['pressure'] - DP * (1 - x / L)).max() < 1e-8 * DP
    assert flow(r, 'tip') == pytest.approx(DP * W * H ** 3 / (12 * MU * L), rel=1e-8)
    s = r['summary']
    assert s['physics'] == ['fluid'] and s['converged'] and not s['fluid']['pressure_pinned']
    assert s['fluid']['wall_force_N'][0] == pytest.approx(DP * W * H, rel=1e-8)
    assert s['fluid']['mass_balance_error'] < 1e-10
    assert {e['key'] for e in s['extra_fields']} == set(r['extra_fields']) == {'vmag', 'vx', 'vy', 'vz', 'p'}
    assert 'warnings' not in s                               # glycerine, Re ≪ 1


def test_enclosed_flow_pins_the_pressure_and_hydrostatics_is_exact():
    m = channel(2e-3, 2e-3, 2e-3, 3)
    r = solve(m, [{'face_set': '@all', 'dofs': [0, 1, 2]}], [{'gravity': [0, 0, -9.81]}])
    assert r['summary']['fluid']['pressure_pinned']
    assert np.abs(r['velocity']).max() < 1e-12
    dp = r['pressure'] - RHO * 9.81 * (m.nodes[:, 2].max() - m.nodes[:, 2])
    assert np.ptp(dp) < 1e-8 * RHO * 9.81 * 2e-3


def test_square_duct_flow_rate():
    a, Ld = 0.5e-3, 4e-3
    m = channel(Ld, 2 * a, 2 * a, 16)
    r = solve(m, [{'face_set': s, 'dofs': [0, 1, 2]} for s in ('y0', 'y1', 'z0', 'z1')] + ENDS,
              [{'face_set': 'fixed', 'pressure': DP}])
    assert flow(r, 'tip') == pytest.approx(duct_flow(a, a, DP / Ld, MU), rel=0.01)


def test_high_reynolds_warns_and_t4_is_rejected():
    r = solve(channel(L, W, H, 4), WALLS + ENDS, [{'face_set': 'fixed', 'pressure': 1e4}], mu=1e-3, rho=1000.0)
    assert r['summary']['fluid']['reynolds'] > 1 and r['summary']['warnings']
    with pytest.raises(ValueError, match='T10'):
        solve(FEMMesh.generate_cantilever(L, W, H, 4, order=1), WALLS, [])


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_graph_velocity_bc_and_beam_pressure():
    e = g2s._bc_node_to_entry({}, _node('in', bc_type='velocity', vx=5, unit='mm/s', face_set='fixed'))
    assert e['dofs'] == [0, 1, 2] and e['values'] == pytest.approx([5e-3, 0, 0]) and e['face_set'] == 'fixed'
    ld = g2s._load_node_to_entry({}, _node('p', load_type='pressure', magnitude=2, unit='kPa', face_set='fixed'))
    assert ld['face_set'] == 'fixed' and ld['pressure'] == pytest.approx(2000)
    with pytest.raises(g2s.GraphSpecError):
        g2s._load_node_to_entry({}, _node('p', load_type='pressure', magnitude=2))
