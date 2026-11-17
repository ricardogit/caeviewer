"""Transient Navier–Stokes (BDF2 / BE, Taylor-Hood P2-P1): time order, start-up flow, Taylor–Green, kernel."""
import numpy as np
import pytest

from app.design.services.fem import ns_transient as nt
from app.design.services.fem import stokes as st
from app.design.services.fem.mesh import FEMMesh

H, MU, RHO, F = 1e-3, 1e-3, 1000.0, 100.0
# walls z = 0, H (no slip); slip on y faces; ends open ("do nothing", p = 0) and a uniform body force → the flow is
# independent of x: Stokes' start-up of plane Poiseuille flow
WALLS = [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
         {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}]
LOADS = [{'body_force': [F, 0, 0]}]
T_END = 0.05 * H * H * RHO / MU                     # 5 % of the viscous time: far from steady


@pytest.fixture(scope='module')
def channel():
    return FEMMesh.generate_cantilever(2e-3, 1e-3, H, 4, order=2)


def startup_exact(z, t):
    nu = MU / RHO
    u = np.zeros_like(z)
    for k in range(1, 400, 2):
        u += (4 * F * H * H / (MU * np.pi ** 3) / k ** 3 * np.sin(k * np.pi * z / H)
              * (1 - np.exp(-(k * np.pi / H) ** 2 * nu * t)))
    return u


def _ux(m, n, scheme):
    mat = st.FluidMaterial({'mu': MU, 'rho': RHO, 'inertia': True})
    time = {'t_end': T_END, 'n_steps': n, 'scheme': scheme, 'n_output': 1}
    snaps, _ = nt.solve_transient(m, mat, WALLS, LOADS, time)
    return snaps[-1][1][:, 0]


def test_time_order_bdf2_and_be(channel):
    ref = _ux(channel, 320, 'bdf2')
    for scheme, order in (('bdf2', 2.0), ('be', 1.0)):
        e = [np.abs(_ux(channel, n, scheme) - ref).max() for n in (10, 20, 40)]
        rates = np.log2(np.array(e[:-1]) / np.array(e[1:]))
        assert np.all(np.abs(rates - order) < 0.15), (scheme, rates)


def test_startup_poiseuille_vs_series():
    m = FEMMesh.generate_cantilever(2e-3, 1e-3, H, 8, order=2)            # 4 elements across the gap
    u = _ux(m, 40, 'bdf2')
    ue = startup_exact(m.nodes[:, 2], T_END)
    assert np.abs(u - ue).max() < 0.02 * ue.max()          # 1.4 % (spatial: 4 P2 elements across)


def test_kernel_transient_series_probes_and_forces(channel):
    from app.design.services.fem.kernel import FEMKernel
    m = channel
    t_end = 0.6 * H * H * RHO / MU                  # several viscous times → close to the steady parabola
    spec = {'tier': 1, 'material': {'type': 'newtonian_fluid', 'mu': MU, 'rho': RHO, 'inertia': True},
            'bcs': [{**b, 'label': f'b{i}'} for i, b in enumerate(WALLS)], 'loads': LOADS,
            'time': {'t_end': t_end, 'n_steps': 30, 'n_output': 6},
            'probes': [{'label': 'centro', 'point': [1e-3, 0.5e-3, 0.5 * H]}]}
    r = FEMKernel()._solve(None, spec, None, mesh=m)
    s = r['summary']
    tr = s['fluid']['transient']
    assert s['fluid']['model'] == 'navier_stokes' and s['converged']
    assert len(tr['times']) == 7 and tr['times'][0] == 0.0 and tr['times'][-1] == pytest.approx(t_end)
    ser = r['time_series']
    assert ser['fields']['vx'].shape == (7, m.n_nodes) and set(ser['fields']) >= {'vmag', 'vx', 'p'}
    assert any(f['key'] == 'vx' and f.get('series') for f in s['extra_fields'])
    # probe at mid-gap: rises monotonically towards F H²/(8μ)
    pc = tr['probes'][0]['curve']
    ux = np.array([row[1] for row in pc])
    assert np.all(np.diff(ux) > 0) and 0.95 < ux[-1] / (F * H * H / (8 * MU) * 1e0) < 1.0
    # forces on the two no-slip walls balance the body force once (nearly) steady
    fx = sum(f['final_N'][0] for f in tr['forces'] if f['label'] in ('b0', 'b1'))
    vol = 2e-3 * 1e-3 * H
    assert fx == pytest.approx(F * vol, rel=0.02)
    assert tr['courant_max'] > 0 and 'navier_stokes' not in s['fluid']


def test_steady_start_stays_steady(channel):
    """initial 'steady' + constant data: the transient keeps the steady Navier–Stokes solution."""
    mat = st.FluidMaterial({'mu': MU, 'rho': RHO, 'inertia': True})
    snaps, _ = nt.solve_transient(channel, mat, WALLS, LOADS, {'t_end': 0.01, 'n_steps': 5}, initial='steady')
    assert np.abs(snaps[-1][1] - snaps[0][1]).max() < 1e-9 * np.abs(snaps[0][1]).max()


def test_taylor_green_decay():
    """2-D Taylor–Green vortex (exact Navier–Stokes solution, convection balanced by pressure), Re 100."""
    from app.design.services.fem import tet_batch as tb
    n, L = 8, np.pi
    xs = np.linspace(0, L, n + 1)
    m = FEMMesh.generate_grid(xs, xs, np.linspace(0, L / n, 2), order=2)
    mu, rho, T = 0.01, 1.0, 2.0
    X = m.nodes
    u0 = np.column_stack([-np.cos(X[:, 0]) * np.sin(X[:, 1]), np.sin(X[:, 0]) * np.cos(X[:, 1]), 0 * X[:, 0]])
    ts = np.linspace(0, T, 2001)
    hist = np.column_stack([ts, np.exp(-2 * mu / rho * ts)]).tolist()
    bnd = np.unique(tb.boundary_faces(m.elements))
    side = bnd[(np.minimum(X[bnd, 0], L - X[bnd, 0]) < 1e-12) | (np.minimum(X[bnd, 1], L - X[bnd, 1]) < 1e-12)]
    bcs = [{'face_set': 'z0', 'dofs': [2]}, {'face_set': 'z1', 'dofs': [2]}]
    for i in side:
        m.node_sets[f'n{i}'] = np.array([i])
        bcs.append({'node_set': f'n{i}', 'dofs': [0, 1], 'values': u0[i, :2].tolist(), 'history': hist})
    mat = st.FluidMaterial({'mu': mu, 'rho': rho, 'inertia': True})
    snaps, info = nt.solve_transient(m, mat, bcs, [], {'t_end': T, 'n_steps': 20, 'n_output': 1}, initial=u0)
    ue = u0 * np.exp(-2 * mu / rho * T)
    assert np.abs(snaps[-1][1] - ue).max() < 0.05 * np.abs(ue).max()
    assert info['pressure_pinned']


def test_stokes_with_time_is_rejected(channel):
    from app.design.services.fem.kernel import FEMKernel
    spec = {'tier': 1, 'material': {'type': 'newtonian_fluid', 'mu': MU, 'rho': RHO}, 'bcs': WALLS, 'loads': LOADS,
            'time': {'t_end': 1.0, 'n_steps': 2}}
    with pytest.raises(ValueError, match='transitorio'):
        FEMKernel()._solve(None, spec, None, mesh=channel)


def test_graph_spec_transient_fluid():
    from app.design.services.graph_to_solver_spec import GraphSpecError, _finalize_physics, _fluid_transient
    mat = {'type': 'newtonian_fluid', 'mu': MU, 'rho': RHO, 'inertia': True}
    spec = {'material': dict(mat), 'loads': [], 'physics': ['structural'],
            'bcs': [{'dofs': [0, 1, 2], 'values': [1, 0, 0], 'label': 'in', 'history': [[0.0, 0.0], [2.0, 1.0]]}]}
    _fluid_transient(spec, {'transient': True, 't_end': 10, 'time_unit': 'min', 'time_steps': 60,
                            'probes': [{'x': 1, 'y': 2, 'z': 3}]}, 'agua', 'navier_stokes')
    _finalize_physics(spec)
    assert spec['time'] == {'t_end': 600.0, 'n_steps': 60, 'scheme': 'bdf2'}
    assert spec['bcs'][0]['history'] == [[0.0, 0.0], [120.0, 1.0]]          # ramp in minutes → s
    assert spec['probes'][0]['point'] == [1e-3, 2e-3, 3e-3] and 'fluid_time_scale' not in spec
    steady = {'material': dict(mat), 'loads': [], 'physics': ['structural'],
              'bcs': [{'dofs': [0], 'values': [1], 'history': [[0, 0], [1, 1]]}]}
    _finalize_physics(steady)
    assert 'history' not in steady['bcs'][0] and 'time' not in steady         # steady: hash unchanged
    with pytest.raises(GraphSpecError, match='SUPG'):
        _fluid_transient({'material': {**mat, 'stabilization': 'supg'}}, {'transient': True, 't_end': 1}, 'a',
                         'navier_stokes')
    urans = {'material': {**mat, 'turbulence': {'model': 'k_epsilon'}}, 'loads': [], 'physics': ['structural'],
             'bcs': [{'dofs': [0], 'values': [1], 'history': [[0, 0], [1, 1]]}]}
    _fluid_transient(urans, {'transient': True, 't_end': 1, 'inner_iterations': 5, 'steady_tol': 1e-5,
                             'urans_initial': 'steady', 'average_from': 2, 'time_unit': 'min'}, 'a', 'rans_k_epsilon')
    assert urans['time']['inner_iterations'] == 5 and urans['time']['steady_tol'] == 1e-5
    assert urans['time']['initial'] == 'steady' and urans['time']['average_from'] == 120.0
    with pytest.raises(GraphSpecError, match='RANS transitorio'):
        _finalize_physics(urans)
