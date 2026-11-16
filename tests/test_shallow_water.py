"""FASE 10.3: 2-D shallow water (finite volumes, HLL + hydrostatic reconstruction) — exact / analytic cases,
conditions from the graph, and the kernel run on a 2-D domain mesh."""
import math
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import brentq

from app.design.services.fem import shallow_water as sw

G = sw.G


def _grid(xs, ys, bed):
    return sw.SWGrid(*sw.rect_grid(xs, ys, bed))


def stoker(x, t, hl=1.0, hr=0.1, x0=500.0):
    """Dam break on a wet bed (Stoker): rarefaction + constant state + bore."""
    cl = math.sqrt(G * hl)

    def jump(cm):
        hm, um = cm * cm / G, 2 * (cl - cm)
        return (hm * um * um + 0.5 * G * (hm * hm - hr * hr)) * (hm - hr) - (hm * um) ** 2
    cm = brentq(jump, math.sqrt(G * hr) * 1.0001, cl * 0.9999)
    hm, um = cm * cm / G, 2 * (cl - cm)
    s = hm * um / (hm - hr)
    xi = (x - x0) / t
    return np.where(xi < -cl, hl, np.where(xi < um - cm, (2 * cl - xi) ** 2 / (9 * G), np.where(xi < s, hm, hr)))


@pytest.mark.parametrize('order', [1, 2])
def test_lake_at_rest_with_dry_island(order):
    """Well-balanced and positive: still water around an emerging bump stays still (round-off)."""
    bed = lambda x, y: 2.0 - 3.0 * np.exp(-((x - 50) ** 2 + (y - 25) ** 2) / 100) + 0.3 * np.sin(x / 7)
    g = _grid(np.linspace(0, 100, 41), np.linspace(0, 50, 21), bed)
    r = sw.solve(g, {'order': order}, {}, t_end=30.0, eta0=0.0, n_output=1)
    U = r['snaps'][-1][1]
    wet = U[0] > 0
    assert (~wet).sum() > 10                                    # the island is dry
    assert np.abs(U[1:]).max() < 1e-12
    assert np.abs((U[0] + g.zb)[wet]).max() < 1e-12
    assert r['balance_error'] < 1e-13


def test_stoker_dam_break_order2():
    g = _grid(np.linspace(0, 1000, 101), np.linspace(0, 20, 3), None)
    eta0 = np.where(g.cen[:, 0] < 500, 1.0, 0.1)
    r = sw.solve(g, {'order': 2}, {}, t_end=40.0, eta0=eta0, n_output=1)
    U = r['snaps'][-1][1]
    he = stoker(g.cen[:, 0], 40.0)
    err = np.sum(np.abs(U[0] - he) * g.area) / np.sum(g.area * he)
    assert err < 0.01                                           # 0.76 % at nx 100 (0.30 % at 400)
    assert r['balance_error'] < 1e-13


def test_coriolis_inertial_oscillation_exact():
    """Uniform current, transmissive sides: the current rotates clockwise (f > 0) at frequency f, exactly."""
    g = _grid(np.linspace(0, 1e4, 6), np.linspace(0, 1e4, 6), lambda x, y: 10.0 + 0 * x)
    f = 1e-4
    U0 = np.zeros((3, g.nc))
    U0[0], U0[1] = 10.0, 10.0 * 0.2
    free = {k: {'kind': 'free', 'signal': None} for k in ('x0', 'x1', 'y0', 'y1')}
    t = 0.3 * 2 * math.pi / f
    r = sw.solve(g, {'order': 2, 'coriolis_f': f}, free, t_end=t, U0=U0, n_output=1)
    U = r['snaps'][-1][1]
    tt = r['snaps'][-1][0]
    assert np.allclose(U[1] / U[0], 0.2 * math.cos(f * tt), atol=1e-12)
    assert np.allclose(U[2] / U[0], -0.2 * math.sin(f * tt), atol=1e-12)
    assert np.allclose(U[0], 10.0, atol=1e-12)


def test_wind_setup_closed_basin():
    """Steady wind over a closed basin: g d(H²/2)/dx = τ/ρ → H² linear, set-up between the ends."""
    L, d, W = 2000.0, 2.0, 15.0
    g = _grid(np.linspace(0, L, 41), np.linspace(0, 100, 3), lambda x, y: d + 0 * x)
    k = sw.RHO_AIR / 1025.0 * sw.wind_drag(W) * W * W         # τ/ρ [m²/s²]
    x = g.cen[:, 0]
    # exact profile with the basin's volume: H² = C + 2k x/g, ∫H dx = d L
    C = brentq(lambda c: np.mean(np.sqrt(c + 2 * k * np.linspace(0, L, 4001) / G)) - d, 0.5 * d * d, 2 * d * d)
    He = np.sqrt(C + 2 * k * x / G)
    U0 = np.zeros((3, g.nc))
    U0[0] = He                                                  # discrete equilibrium ≈ exact profile (no seiche)
    wind = sw.wind_vector({'speed': W, 'direction': 270.0})   # from the west → blows towards +x
    r = sw.solve(g, {'order': 2, 'manning': 0.05}, {}, t_end=3600.0, U0=U0, wind=wind, n_output=1)
    U = r['snaps'][-1][1]
    setup = U[0][x > L - 60].mean() - U[0][x < 60].mean()
    exact = He[x > L - 60].mean() - He[x < 60].mean()
    assert abs(setup / exact - 1) < 0.02
    assert np.abs(U[1] / U[0]).max() < 2e-3                    # at rest
    assert r['balance_error'] < 1e-13


def test_manning_normal_depth_with_river_inflow():
    """River discharge into a sloping channel with a free outlet → uniform flow at the Manning normal depth."""
    S, n, B, Q, L = 1e-3, 0.03, 40.0, 40.0, 2000.0
    hn = (n * Q / B / math.sqrt(S)) ** 0.6
    g = _grid(np.linspace(0, L, 81), np.linspace(0, B, 3), lambda x, y: 5.0 + S * x)
    U0 = np.zeros((3, g.nc))
    U0[0], U0[1] = hn, Q / B
    bnd = {'x0': {'kind': 'river', 'signal': lambda t: Q}, 'x1': {'kind': 'free', 'signal': None}}
    r = sw.solve(g, {'order': 2, 'manning': n}, bnd, t_end=3000.0, U0=U0, n_output=1)
    U = r['snaps'][-1][1]
    mid = (g.cen[:, 0] > 0.3 * L) & (g.cen[:, 0] < 0.7 * L)
    assert abs(U[0][mid].mean() / hn - 1) < 0.01
    assert abs(U[1][mid].mean() * B / Q - 1) < 0.01
    assert abs(r['boundary_volume_in']['x0'] / (Q * 3000.0) - 1) < 1e-12   # exact imposed inflow
    assert r['balance_error'] < 1e-12


def test_standing_tidal_wave():
    """Closed channel forced by a tide at x = 0: η = A cos(k(L − x))/cos(kL) cos ωt (frictionless, linear)."""
    from app.geodata.forcing import period_s
    L, d, A = 50e3, 5.0, 0.05
    T = period_s('M2')
    w = 2 * math.pi / T
    k = w / math.sqrt(G * d)
    nx = 25
    g = _grid(np.linspace(0, L, nx + 1), np.linspace(0, 2 * L / nx, 3), lambda x, y: d + 0 * x)
    U0 = np.zeros((3, g.nc))
    U0[0] = d + A * np.cos(k * (L - g.cen[:, 0])) / math.cos(k * L)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': A, 'phase': 0}]})
    pr = [{'xy': [L - 0.5 * L / nx, L / nx]}]
    r = sw.solve(g, {'order': 2}, {'x0': {'kind': 'tide', 'signal': sig}}, t_end=3 * T, U0=U0, n_output=1,
                 probes=pr)
    P = np.asarray(r['probe_rows'])
    m = P[:, 0] > T                                             # harmonic fit after one period (start-up seiche)
    X = np.column_stack([np.ones(m.sum()), np.cos(w * P[m, 0]), np.sin(w * P[m, 0])])
    c = np.linalg.lstsq(X, P[m, 1], rcond=None)[0]
    xp = g.cen[r['probe_cells'][0], 0]
    amp = A * abs(math.cos(k * (L - xp)) / math.cos(k * L))
    assert abs(math.hypot(c[1], c[2]) / amp - 1) < 0.01        # 0.24 % at nx 25
    assert abs(math.degrees(math.atan2(c[2], c[1]))) < 1.0
    assert r['balance_error'] < 1e-13


def test_tide_and_river_mass_budget():
    """Tidal flat with a river: volumes through each boundary close the budget to round-off, the flat floods."""
    bed = lambda x, y: 3.0 - 4.0 * x / 2000.0                  # deep at the sea (x = 0), dry flat at x > 1500
    g = _grid(np.linspace(0, 2000, 21), np.linspace(0, 400, 5), bed)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'ramp': 3600.0})
    bnd = {'x0': {'kind': 'tide', 'signal': sig}, 'x1': {'kind': 'river', 'signal': lambda t: 5.0}}
    r = sw.solve(g, {'order': 2, 'manning': 0.025, 'h_dry': 0.01}, bnd, t_end=3 * 3600.0, eta0=0.0, n_output=3)
    assert r['balance_error'] < 1e-12
    assert (r['wet_ever'] & ~r['wet0']).sum() > 0               # intertidal cells
    assert r['boundary_volume_in']['x1'] == pytest.approx(5.0 * 3 * 3600.0, rel=1e-12)
    assert all(np.all(U[0] >= 0) for _, U in r['snaps'])


def test_signals_and_wind_direction():
    s = sw.make_signal({'series': {'t': [0, 10], 'v': [1, 3]}, 'ramp': 0})
    assert s(5) == pytest.approx(2.0)
    s = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 2.0, 'phase': 0}], 'z0': 0.5, 'ramp': 100})
    assert s(0) == pytest.approx(0.5)
    wx, wy = sw.wind_vector({'speed': 10, 'direction': 0})(0)
    assert (wx, wy) == pytest.approx((0.0, -10.0))             # from the north → blows south
    wx, wy = sw.wind_vector({'speed': 10, 'direction': 90})(0)
    assert (wx, wy) == pytest.approx((-10.0, 0.0), abs=1e-12)


# ── graph conditions ─────────────────────────────────────────────────────────

def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_graph_conditions_and_default_sides():
    from app.design.services import graph_to_solver_spec as gs
    tide = gs._sw_bc(_node('Marea', bc_type='tide', constituents=[{'name': 'm2', 'amplitude': 1.2, 'phase': 30}],
                           ramp_h=6))
    river = gs._sw_bc(_node('Río', bc_type='river_inflow', discharge=50, unit='m3/s'))
    assert tide['tide']['constituents'][0]['name'] == 'M2' and tide['ramp_s'] == 6 * 3600
    assert river['discharge'] == 50
    wind = gs._sw_wind(_node('Viento', load_type='wind', speed=8, direction=225))
    spec = {'material': {'type': 'shallow_water'}, 'mesh_source': 'domain_2d',
            'domain_2d': {'segments': ['open', 'coast', 'river', 'open']}, 'bcs': [tide, river], 'loads': [wind]}
    gs._finalize_shallow_water(spec)
    assert spec['physics'] == ['shallow_water']
    assert tide['boundaries'] == ['edge0', 'edge3'] and river['boundaries'] == ['edge2']
    with pytest.raises(gs.GraphSpecError):                     # unknown constituent
        gs._sw_bc(_node('X', bc_type='tide', constituents=[{'name': 'ZZ9', 'amplitude': 1}]))
    with pytest.raises(gs.GraphSpecError):                     # shallow water needs a 2-D domain
        gs._finalize_shallow_water({'material': {'type': 'shallow_water'}, 'bcs': [], 'loads': []})
    with pytest.raises(gs.GraphSpecError):                     # mechanical load on a water study
        gs._finalize_shallow_water({'material': {'type': 'shallow_water'}, 'mesh_source': 'domain_2d',
                                    'domain_2d': {'segments': []}, 'bcs': [], 'loads': [{'force': [0, 0, 1]}]})


# ── kernel run on a (synthetic) 2-D domain mesh ──────────────────────────────

def test_kernel_run_on_domain_mesh(monkeypatch):
    from app.design.services.fem import sw_run
    from app.design.services.fem.solver import check_tier_limits
    from app.geodata import service
    from app.geodata.crs import LocalFrame
    from app.geodata.mesh2d import Mesh2D
    nodes, tris, depth, bnd = sw.rect_grid(np.linspace(0, 4000, 21), np.linspace(0, 1000, 6),
                                           lambda x, y: 4.0 - 6.0 * x / 4000.0)
    b = {'edge0': bnd['x0'], 'edge2': bnd['x1'], 'coast': np.vstack([bnd['y0'], bnd['y1']])}
    info = [{'id': 'edge0', 'kind': 'open', 'label': 'Mar', 'length_m': 1000.0},
            {'id': 'edge2', 'kind': 'river', 'label': 'Río', 'length_m': 1000.0},
            {'id': 'coast', 'kind': 'coast', 'label': 'Costa', 'length_m': 8000.0}]
    zone = np.where(nodes[tris].mean(1)[:, 0] > 2000, 0, -1)
    mesh = Mesh2D(nodes, tris, depth, LocalFrame(32630, (440000.0, 4800000.0)), b, info, zone,
                  [{'label': 'marisma', 'props': {'manning': 0.06}}], {'has_bathymetry': True}, 'k')
    monkeypatch.setattr(service, 'get_or_build_mesh', lambda spec, progress=None: (mesh, True))
    lon, lat = mesh.frame.to_lonlat([1000.0], [500.0])
    spec = {'mesh_source': 'domain_2d', 'domain_2d': {}, 'physics': ['shallow_water'],
            'material': {'type': 'shallow_water', 'manning': 0.025, 'coriolis': True, 'h_dry': 0.01, 'order': 2},
            'time': {'t_end': 3 * 3600.0, 'n_output': 6},
            'bcs': [{'sw_bc': 'tide', 'boundaries': ['edge0'], 'label': 'Marea', 'ramp_s': 3600.0,
                     'tide': {'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'z0': 0.0}},
                    {'sw_bc': 'river', 'boundaries': ['edge2'], 'label': 'Río', 'discharge': 20.0}],
            'loads': [{'wind': {'speed': 5, 'direction': 0}, 'label': 'Viento'}],
            'probes': [{'label': 'P1', 'lon': float(lon[0]), 'lat': float(lat[0])}]}
    res = sw_run.run(spec, lambda p, m: None, 1, check_tier_limits)
    s = res['summary']
    d = s['shallow_water']
    assert s['physics'] == ['shallow_water'] and s['converged']
    assert d['balance_error'] < 1e-12
    assert d['manning_zones'][0]['manning'] == 0.06 and d['manning_zones'][0]['n_cells'] == len(tris) // 2
    assert {r['kind'] for r in d['boundaries']} == {'tide', 'river', 'wall'}
    riv = next(r for r in d['boundaries'] if r['id'] == 'edge2')
    assert riv['volume_in_m3'] == pytest.approx(20.0 * 3 * 3600.0, rel=1e-12)
    assert len(d['probes']) == 1 and d['probes'][0]['curve']
    assert len(res['time_series']['times']) == 7
    assert res['time_series']['fields']['eta'].shape == (7, len(nodes))
    assert np.isfinite(res['extra_fields']['eta']).all()
    assert len(res['nodes']) == len(nodes) and res['nodes'][0][2] == 0.0
    with pytest.raises(ValueError):                            # river side without a discharge
        sw_run.run({**spec, 'bcs': spec['bcs'][:1]}, lambda p, m: None, 1, check_tier_limits)
