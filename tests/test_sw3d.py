"""FASE 10.4: 3-D hydrostatic stratified σ-layer model (multilayer shallow water with mass exchange) — exact
reductions, conservation, vertical physics in water columns, and the kernel run on a 2-D domain mesh."""
import math

import numpy as np
import pytest

from app.design.services.fem import shallow_water as sw
from app.design.services.fem import sw3d

G = sw.G


def _grid(xs, ys, bed):
    return sw.SWGrid(*sw.rect_grid(xs, ys, bed))


def _column(H):
    return _grid([0, 1000.0], [0, 1000.0], lambda x, y: H + 0 * x)


def test_unesco_density_check_values():
    assert sw3d.density_unesco(5, 0) == pytest.approx(999.96675, abs=1e-5)
    assert sw3d.density_unesco(5, 35) == pytest.approx(1027.67547, abs=1e-5)
    assert sw3d.density_unesco(25, 35) == pytest.approx(1023.34306, abs=1e-5)


def test_block_motion_reproduces_the_2d_model():
    """Uniform layers, no drag, no mixing: every layer count gives the 2-D solution to round-off."""
    g = _grid(np.linspace(0, 1000, 16), np.linspace(0, 600, 10),
              lambda x, y: 10 + 3 * np.sin(x / 200) + 2 * np.cos(y / 150))
    eta0 = 0.3 * np.exp(-((g.cen[:, 0] - 400) ** 2 + (g.cen[:, 1] - 300) ** 2) / 150 ** 2)
    U2 = sw.solve(g, {'manning': 0.0}, {}, t_end=60, eta0=eta0, n_output=1)['snaps'][-1][1]
    for L in (1, 5):
        r = sw3d.solve(g, {'layers': L, 'closure': 'constant', 'nu_v': 0.0, 'kappa_v': 0.0, 'bottom_drag': False},
                       {}, t_end=60, eta0=eta0, n_output=1)
        U3 = r['snaps'][-1][1]
        assert np.abs(U3[0] - U2[0]).max() < 1e-12
        assert np.abs(U3[1:1 + L].sum(0) - U2[1]).max() < 1e-12


def test_lake_at_rest_with_dry_island_and_uniform_tracer():
    g = _grid(np.linspace(0, 1000, 21), np.linspace(0, 1000, 21),
              lambda x, y: 2.0 - 3.0 * np.exp(-((x - 500) ** 2 + (y - 500) ** 2) / 200 ** 2))
    r = sw3d.solve(g, {'layers': 6, 'closure': 'k_epsilon', 'salinity': 30.0}, {}, t_end=600, n_output=1)
    U = r['snaps'][-1][1]
    s3 = r['solver']
    u, v, c, wet = s3.primitive(U)
    assert np.abs(u).max() < 1e-11 and np.abs(v).max() < 1e-11
    assert np.abs(U[0] + g.zb - np.maximum(g.zb, 0.0))[wet].max() < 1e-12
    assert np.abs(c[0][:, wet] - 30.0).max() < 1e-10


def test_tide_river_wetting_budgets_and_uniform_salinity():
    """Tidal flat + river, stratified by temperature only: uniform S stays uniform (inflows at the same S);
    water, heat and salt budgets close to round-off."""
    g = _grid(np.linspace(0, 2000, 17), np.linspace(0, 400, 4), lambda x, y: 3.0 - 4.0 * x / 2000.0)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'ramp': 1800.0})
    bnd = {'x0': {'kind': 'tide', 'signal': sig, 'c_in': [12.0, 20.0]},
           'x1': {'kind': 'river', 'signal': lambda t: 5.0, 'c_in': [18.0, 20.0]}}
    r = sw3d.solve(g, {'layers': 4, 'closure': 'k_epsilon', 'temperature': 12.0, 'salinity': 20.0,
                       'manning': 0.025, 'h_dry': 0.01, 'eos': {'model': 'unesco'}}, bnd, t_end=2 * 3600.0,
                   n_output=2)
    assert r['balance_error'] < 1e-12
    assert all(t['balance_error'] < 1e-12 for t in r['tracers'])
    assert (r['wet_ever'] & ~r['wet0']).sum() > 0
    s3 = r['solver']
    u, v, c, wet = s3.primitive(r['snaps'][-1][1])
    assert np.abs(c[1][:, wet] - 20.0).max() < 1e-9
    assert c[0][:, wet].max() > 12.5                          # warm river water entered


def test_vertical_diffusion_cosine_mode():
    g = _column(10.0)
    ka = 1e-3
    r = sw3d.solve(g, {'layers': 40, 'closure': 'constant', 'nu_v': 1e-3, 'kappa_v': ka, 'bottom_drag': False,
                       'temperature': lambda d: 10 + np.cos(math.pi * (10 - d) / 10), 'horizontal': False,
                       'dt': 10.0}, {}, t_end=20000, n_output=1)
    s3 = r['solver']
    c = s3.primitive(r['snaps'][-1][1])[2][0][:, 0]
    z = s3.sc * 10
    amp = np.sum((c - 10) * np.cos(math.pi * z / 10)) * 2 / 40
    assert amp == pytest.approx(math.exp(-ka * (math.pi / 10) ** 2 * 20000), rel=5e-3)
    assert r['tracers'][0]['balance_error'] < 1e-12


def test_open_channel_k_epsilon_log_law():
    """Uniform open-channel flow driven by g·S: bed stress = gHS, bottom layer on the log law, depth mean within
    5 % of the log-law integral (k-ε gives +3.3 %, the usual wake), k ≈ u*²(1 − z/H)/√c_μ."""
    H, S, z0 = 10.0, 1e-5, 1e-3
    r = sw3d.solve(_column(H), {'layers': 20, 'closure': 'k_epsilon', 'bottom_roughness': z0,
                                'body_force': (G * S, 0), 'horizontal': False, 'dt': 10.0}, {},
                   t_end=12 * 3600, n_output=1)
    s3 = r['solver']
    u = s3.primitive(r['snaps'][-1][1])[0][:, 0]
    us = math.sqrt(G * S * H)
    cd = s3._drag(np.array([H]), None)[0]
    assert cd * u[0] ** 2 == pytest.approx(us ** 2, rel=1e-4)                    # steady: bed stress = gHS
    assert u[0] == pytest.approx(us / 0.41 * math.log((s3.sc[0] * H + z0) / z0), rel=1e-3)
    assert (s3.frac * u).sum() == pytest.approx(us / 0.41 * (math.log(H / z0) - 1), rel=0.05)
    zi = s3.s[1:-1] * H
    k = s3.k[1:-1, 0]
    assert np.interp(0.3 * H, zi, k) * math.sqrt(0.09) / us ** 2 / 0.7 == pytest.approx(1.0, abs=0.05)


def test_kato_phillips_mixed_layer_deepening():
    """Wind stress on a linearly stratified column: mixed-layer depth ≈ 1.05 u* √(t/N₀) (Price 1979)."""
    H, N0, us, rho0, al = 50.0, 0.01, 0.01, 1025.0, 2e-4
    dTdz = N0 ** 2 / (G * al)
    r = sw3d.solve(_column(H), {'layers': 50, 'closure': 'k_epsilon', 'rho': rho0, 'bottom_drag': False,
                                'eos': {'model': 'linear', 'alpha': al, 'beta': 0, 'rho_ref': rho0},
                                'temperature': lambda d: 20 - dTdz * d, 'surface_stress': (rho0 * us ** 2, 0),
                                'horizontal': False, 'dt': 20.0}, {}, t_end=10 * 3600, n_output=1)
    s3 = r['solver']
    T = s3.primitive(r['snaps'][-1][1])[2][0][:, 0]
    zi = s3.s[1:-1] * H
    D = H - zi[np.argmax(np.diff(T))]
    assert D == pytest.approx(1.05 * us * math.sqrt(36000 / N0), rel=0.08)
    assert r['tracers'][0]['balance_error'] < 1e-12


def test_internal_seiche_frequency():
    """Mode-1 internal seiche in a linearly stratified closed basin: ω = N H/L (hydrostatic, first mode)."""
    Lx, H, N, al, rho0, nx, L = 1000.0, 20.0, 0.02, 2e-4, 1000.0, 10, 8
    g = _grid(np.linspace(0, Lx, nx + 1), np.linspace(0, 2 * Lx / nx, 3), lambda x, y: H + 0 * x)
    p = {'layers': L, 'closure': 'constant', 'nu_v': 0.0, 'kappa_v': 0.0, 'bottom_drag': False, 'rho': rho0,
         'order': 1, 'eos': {'model': 'linear', 'alpha': al, 'beta': 0, 'T_ref': 10, 'rho_ref': rho0},
         'temperature': 10.0}
    s3 = sw3d.Stratified3D(g, p, {})
    U = s3.initial_state(0.0)
    zp = s3.sc[:, None] * H
    basis = np.cos(math.pi * g.cen[:, 0] / Lx)[None] * np.sin(math.pi * zp / H)
    dTdz = N ** 2 / (G * al)
    U[1 + 2 * L:] = s3.frac[:, None] * U[0][None] * (10 + dTdz * (zp - H / 2) + 0.2 * basis)
    w = N * H / Lx
    r = sw3d.solve(g, p, {}, t_end=0.5 * 2 * math.pi / w, n_output=10, U0=U)
    amp = []
    for _, Ux in r['snaps']:
        pert = s3.primitive(Ux)[2][0] - (10 + dTdz * (zp - H / 2))
        amp.append(np.sum(pert * basis * g.area) / np.sum(basis ** 2 * g.area) / 0.2)
    amp = np.array(amp)
    assert amp[-1] < -0.8                                     # half a period later: reversed
    i = np.flatnonzero(np.diff(np.sign(amp)))[0]               # quarter period: zero crossing
    t = np.array([t_ for t_, _ in r['snaps']])
    tz = t[i] - amp[i] * (t[i + 1] - t[i]) / (amp[i + 1] - amp[i])
    assert tz * w == pytest.approx(math.pi / 2, rel=0.05)


def test_kernel_run_on_domain_mesh_3d(monkeypatch):
    from app.design.services.fem import sw_run
    from app.design.services.fem.solver import check_tier_limits
    from app.geodata import service
    from app.geodata.crs import LocalFrame
    from app.geodata.mesh2d import Mesh2D
    nodes, tris, depth, bnd = sw.rect_grid(np.linspace(0, 4000, 13), np.linspace(0, 1000, 4),
                                           lambda x, y: 6.0 - 4.0 * x / 4000.0)
    b = {'edge0': bnd['x0'], 'edge2': bnd['x1'], 'coast': np.vstack([bnd['y0'], bnd['y1']])}
    info = [{'id': 'edge0', 'kind': 'open', 'label': 'Mar', 'length_m': 1000.0},
            {'id': 'edge2', 'kind': 'river', 'label': 'Río', 'length_m': 1000.0},
            {'id': 'coast', 'kind': 'coast', 'label': 'Costa', 'length_m': 8000.0}]
    mesh = Mesh2D(nodes, tris, depth, LocalFrame(32630, (440000.0, 4800000.0)), b, info,
                  np.full(len(tris), -1), [], {'has_bathymetry': True}, 'k')
    monkeypatch.setattr(service, 'get_or_build_mesh', lambda spec, progress=None: (mesh, True))
    lon, lat = mesh.frame.to_lonlat([1500.0], [500.0])
    spec = {'mesh_source': 'domain_2d', 'domain_2d': {}, 'physics': ['shallow_water'],
            'material': {'type': 'shallow_water', 'manning': 0.025, 'coriolis': True, 'h_dry': 0.01, 'order': 2,
                         'layers': 5, 'closure': 'k_epsilon', 'temperature': 14.0, 'salinity': 35.0,
                         'tracers': [{'name': 'E. coli', 'unit': 'UFC', 'D': 1.0, 'decay': 1e-5, 'threshold': 100.0}]},
            'time': {'t_end': 2 * 3600.0, 'n_output': 4},
            'bcs': [{'sw_bc': 'tide', 'boundaries': ['edge0'], 'label': 'Marea', 'ramp_s': 1800.0,
                     'tide': {'constituents': [{'name': 'M2', 'amplitude': 0.8, 'phase': 0}], 'z0': 0.0}},
                    {'sw_bc': 'river', 'boundaries': ['edge2'], 'label': 'Río', 'discharge': 30.0, 'c_in': [0.0],
                     'T_in': 18.0, 'S_in': 0.0}],
            'loads': [{'wind': {'speed': 6, 'direction': 270}, 'label': 'Viento'},
                      {'outfall': {'lon': float(lon[0]), 'lat': float(lat[0]), 'Q': 1.0, 'c': [1e5],
                                   'release': 'bottom'}, 'label': 'Emisario'}],
            'probes': [{'label': 'P1', 'lon': float(lon[0]), 'lat': float(lat[0])}]}
    res = sw_run.run(spec, lambda p, m: None, 1, check_tier_limits)
    s = res['summary']
    d = s['shallow_water']
    st = d['stratified']
    assert s['material_model'] == 'shallow_water_3d' and s['converged']
    assert d['balance_error'] < 1e-12 and d['tracer_balance_error'] < 1e-12
    assert s['n_dof'] == (1 + 2 * 5 + 3 * 5) * len(tris)
    assert st['layers'] == 5 and st['active'] == ['T', 'S'] and st['stratification_max_kg_m3'] > 0.5
    riv = next(r for r in d['boundaries'] if r['id'] == 'edge2')
    assert riv['volume_in_m3'] == pytest.approx(30.0 * 2 * 3600.0, rel=1e-12)
    keys = {f['key'] for f in s['extra_fields']}
    assert keys >= {'eta', 'speed', 'speed_s', 'T_s', 'T_b', 'S_s', 'S_b', 'strat', 'c0', 'c0_s', 'c0_b', 'cmax0'}
    assert res['time_series']['fields']['S_s'].shape == (5, len(nodes))
    assert np.nanmin(res['extra_fields']['S_s']) < 35.0 - 1.0      # fresh river water at the surface
    pr = d['probes'][0]
    assert pr['profiles'] and len(pr['profiles'][-1]['S']) == 5 and len(pr['tracer_columns']) == 7
    assert d['outfalls'][0]['release'] == 'bottom'
    assert d['tracers'][0]['source'] == pytest.approx(1e5 * d['source_volume_m3'], rel=1e-12)


def test_graph_3d_material_and_conditions():
    from types import SimpleNamespace
    from app.design.services import graph_to_solver_spec as gs

    def node(label, **props):
        return SimpleNamespace(label=label, properties=props)
    spec = {'material': {}, 'mesh_source': 'domain_2d', 'domain_2d': {'segments': ['open', 'coast', 'river']}}
    gs._sw_material(spec, node('Agua', t_end=6, vertical_layers=8, T_surface=18, T_bottom=12, profile_depth=30,
                               S_surface=35, bottom_z0_mm=2))
    m = spec['material']
    assert m['layers'] == 8 and m['closure'] == 'k_epsilon' and m['eos'] == 'unesco'
    assert m['temperature'] == [[0.0, 18.0], [30.0, 12.0]] and m['salinity'] == 35.0
    assert m['bottom_roughness'] == pytest.approx(0.002)
    river = gs._sw_bc(node('Río', bc_type='river_inflow', discharge=10, temperature=20, salinity=0))
    out = gs._sw_outfall(node('Emisario', load_type='outfall', lon=-8.7, lat=42.2, discharge=1, salinity=0,
                              release='bottom'))
    spec.update(bcs=[river], loads=[out])
    gs._finalize_shallow_water(spec)
    assert river['T_in'] == 20 and river['S_in'] == 0 and 'temperature' not in river
    assert out['outfall']['release'] == 'bottom' and out['outfall']['salinity'] == 0
    # 2-D study: T, S and release are dropped (hash of 2-D studies unchanged)
    spec2 = {'material': {}, 'mesh_source': 'domain_2d', 'domain_2d': {'segments': ['open', 'coast', 'river']}}
    gs._sw_material(spec2, node('Agua', t_end=6))
    assert 'layers' not in spec2['material']
    r2 = gs._sw_bc(node('Río', bc_type='river_inflow', discharge=10, temperature=20))
    o2 = gs._sw_outfall(node('E', load_type='outfall', lon=0, lat=0, discharge=1, release='surface'))
    spec2.update(bcs=[r2], loads=[o2])
    gs._finalize_shallow_water(spec2)
    assert 'T_in' not in r2 and 'release' not in o2['outfall']
    with pytest.raises(gs.GraphSpecError):
        gs._sw_material({}, node('A', t_end=1, vertical_layers=4, closure='mellor'))
    with pytest.raises(gs.GraphSpecError):
        gs._sw_material({}, node('A', t_end=1, vertical_layers=4, closure='constant'))      # needs ν_v
