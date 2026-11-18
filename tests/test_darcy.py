"""Groundwater flow (FASE 10.6): fem.darcy, porous-medium transport, kernel and graph conversion."""
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.special import exp1

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import darcy as dc
from app.design.services.fem import tet_batch as tb
from app.design.services.fem import transport as tr
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh
from validate_transport import ogata_banks


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def sector(P):
    r, t = P[:, 0], P[:, 1]
    return np.column_stack([r * np.cos(t), r * np.sin(t), P[:, 2]])


@pytest.fixture(scope='module')
def bar():
    return FEMMesh.generate_cantilever(1.0, 0.05, 0.05, 20, order=2)


def test_grid_mesh():
    m = FEMMesh.generate_grid([0, 0.5, 2], [0, 1], [0, 0.3, 1], order=2)
    assert m.element_type == 'T10' and tb.volumes(m.nodes, m.elements).sum() == pytest.approx(2.0, rel=1e-12)
    assert {k: len(v) for k, v in m.face_sets.items()} == {'x0': 4, 'x1': 4, 'y0': 8, 'y1': 8, 'z0': 4, 'z1': 4}
    w = FEMMesh.generate_grid(np.geomspace(1, 10, 9), np.linspace(0, np.pi / 2, 7), [0, 1], transform=sector)
    assert tb.volumes(w.nodes, w.elements).sum() == pytest.approx(np.pi / 4 * 99, rel=1e-4)
    with pytest.raises(ValueError):
        FEMMesh.generate_grid([0, 0], [0, 1], [0, 1])


def test_thiem_well():
    rw, R, b, K, Q = 0.1, 100.0, 5.0, 1e-4, 0.01
    m = FEMMesh.generate_grid(np.geomspace(rw, R, 21), np.linspace(0, np.pi / 2, 7), [0, b], transform=sector)
    snaps, info = dc.solve(m, dc.PorousMedium({'K': K}), [{'hydraulic_head': 0.0, 'face_set': 'x1'}],
                           [{'well': {'rate': Q / 4}, 'face_set': 'x0'}])
    r = np.hypot(m.nodes[:, 0], m.nodes[:, 1])
    ex = -Q / (2 * np.pi * K * b) * np.log(R / r)
    assert np.abs(snaps[0][1] - ex).max() < 0.01 * np.abs(ex).max()
    assert info['rates']['well_out'] == pytest.approx(Q / 4) and info['rates']['boundary_in'] == pytest.approx(Q / 4)
    assert info['balance_error'] < 1e-10


def test_recharge_and_leakage_column_is_exact():
    """Recharge R on top drains through a leaky bed (C, h_ext) at the bottom: h = h_ext + R/C + R z/K."""
    K, R, C, he = 1e-4, 1e-7, 1e-6, 3.0
    m = FEMMesh.generate_grid([0, 1, 2], [0, 1, 2], np.linspace(0, 10, 6), order=2)
    snaps, info = dc.solve(m, dc.PorousMedium({'K': K}), [],
                           [{'recharge': R, 'face_set': 'z1'}, {'leakage': {'conductance': C, 'head': he}, 'face_set': 'z0'}])
    ex = he + R / C + R * m.nodes[:, 2] / K
    assert np.abs(snaps[0][1] - ex).max() < 1e-9
    assert info['rates']['recharge'] == pytest.approx(4 * R) and info['rates']['leakage_in'] == pytest.approx(-4 * R)
    with pytest.raises(ValueError):            # no head and no leakage: undetermined
        dc.solve(m, dc.PorousMedium({'K': K}), [], [{'recharge': R, 'face_set': 'z1'}])


def test_zones_in_series_exact():
    K1, K2, L = 1e-4, 1e-5, 2.0
    m = FEMMesh.generate_grid(np.linspace(0, L, 9), [0, 0.5], [0, 0.5], order=1)
    med = dc.PorousMedium({'K': K1, 'K_zones': [{'box': [[1.0, -1, -1], [3, 1, 1]], 'K': K2}]})
    snaps, _ = dc.solve(m, med, [{'hydraulic_head': 1.0, 'face_set': 'x0'}, {'hydraulic_head': 0.0, 'face_set': 'x1'}], [])
    q = 1.0 / (1.0 / K1 + 1.0 / K2)                    # L1 = L2 = 1
    x = m.nodes[:, 0]
    ex = np.where(x <= 1.0, 1.0 - q * x / K1, q * (L - x) / K2)
    assert np.abs(snaps[0][1] - ex).max() < 1e-12
    Ke, zone = med.element_K(m)
    assert (zone == 0).sum() == m.n_elements // 2
    assert dc.face_flow(m, Ke, snaps[0][1], 'x1') == pytest.approx(q * 0.25, rel=1e-10)


def test_anisotropic_flux_on_linear_head():
    med = dc.PorousMedium({'K': [1e-3, 2e-4, 5e-5], 'axis_1': [1, 1, 0], 'axis_2': [-1, 1, 1]})
    m = FEMMesh.generate_grid([0, 0.5, 1], [0, 1], [0, 0.5, 1], order=2)
    g = np.array([0.3, -0.2, 0.1])
    Ke, _ = med.element_K(m)
    _, q = dc.darcy_flux(m, Ke, m.nodes @ g)
    assert np.allclose(q, -(med.K @ g)[None], rtol=0, atol=1e-15)
    assert np.allclose(med.K, med.K.T) and np.linalg.eigvalsh(med.K) == pytest.approx([5e-5, 2e-4, 1e-3])
    with pytest.raises(ValueError):
        dc.PorousMedium({'K': -1})


def test_theis_transient_and_budget():
    rw, R, b, K, Ss, Q = 0.1, 5000.0, 10.0, 1e-4, 1e-5, 0.01
    T, S = K * b, Ss * b
    m = FEMMesh.generate_grid(np.geomspace(rw, R, 31), np.linspace(0, np.pi / 2, 7), [0, b], transform=sector)
    snaps, info = dc.solve(m, dc.PorousMedium({'K': K, 'Ss': Ss}), [{'hydraulic_head': 0.0, 'face_set': 'x1'}],
                           [{'well': {'rate': Q / 4}, 'face_set': 'x0'}],
                           time={'t_end': 20000.0, 'n_steps': 50, 'dt_growth': 1.1, 'n_output': 5},
                           probes=[{'point': [7.0, 7.0, 5.0]}])
    assert len(snaps) == 6 and info['time']['dt_last'] > 50 * info['time']['dt_first']
    r = np.hypot(7.0, 7.0)
    for t, s_num in info['curves'][20:]:
        assert -s_num == pytest.approx(Q / (4 * np.pi * T) * exp1(r * r * S / (4 * T * t)), rel=0.02)
    assert info['balance_error'] < 1e-10
    assert info['budget']['storage_change'] < 0          # pumping depletes storage
    for scheme in ('be', 'cn'):
        _, inf2 = dc.solve(m, dc.PorousMedium({'K': K, 'Ss': Ss}), [{'hydraulic_head': 0.0, 'face_set': 'x1'}],
                           [{'well': {'rate': Q / 4}, 'face_set': 'x0'}],
                           time={'t_end': 20000.0, 'n_steps': 20, 'dt_growth': 1.2, 'scheme': scheme})
        assert inf2['balance_error'] < 1e-10
    with pytest.raises(ValueError):
        dc.solve(m, dc.PorousMedium({'K': K}), [], [], time={'t_end': 1, 'n_steps': 1})


def test_porous_transport_ogata_banks_with_retardation(bar):
    v, aL, Rt, ne, T = 1e-4, 0.01, 2.0, 0.3, 4000.0
    model = tr.TransportModel({'species': [{'D': 0.0, 'retardation': Rt}], 'velocity': [v, 0, 0],
                               'porous': {'porosity': ne, 'alpha_L': aL, 'alpha_T': aL / 10}})
    snaps, info = tr.solve(bar, model, [{'concentration': 1.0, 'face_set': 'fixed'}], [],
                           time={'t_end': T, 'n_steps': 200})
    DL = aL * v
    ex = ogata_banks(bar.nodes[:, 0], T, v / Rt, DL / Rt)
    assert np.abs(snaps[-1][1] - ex).max() < 0.01
    assert info['mass_balance_error'] < 1e-10
    # total (dissolved + sorbed) mass = n_e R ∫c
    M1 = tr.lumped_volume(bar) @ snaps[-1][1]
    assert info['mass_final'][0] == pytest.approx(ne * Rt * M1, rel=1e-6)
    with pytest.raises(ValueError):
        tr.TransportModel({'species': [{'retardation': 2}]})
    with pytest.raises(ValueError):
        tr.TransportModel({'species': [{}], 'porous': {'porosity': 0}})


def test_darcy_velocity_drives_transport(bar):
    """Head drop along a column → uniform pore velocity → Ogata–Banks front (local coupling, no server)."""
    K, ne = 1e-3, 0.25
    med = dc.PorousMedium({'K': K, 'porosity': ne})
    snaps, _ = dc.solve(bar, med, [{'hydraulic_head': 1.0, 'face_set': 'fixed'}, {'hydraulic_head': 0.0, 'face_set': 'tip'}], [])
    Ke, _ = med.element_K(bar)
    _, q = dc.darcy_flux(bar, Ke, snaps[0][1])
    v = q / ne
    assert np.allclose(v, [K / ne, 0, 0], rtol=1e-8, atol=1e-12)
    model = tr.TransportModel({'species': [{'D': 1e-9}], 'porous': {'porosity': ne, 'alpha_L': 0.01}})
    T = 0.4 / (K / ne)
    out, info = tr.solve(bar, model, [{'concentration': 1.0, 'face_set': 'fixed'}], [], velocity=v,
                         time={'t_end': T, 'n_steps': 200})
    ex = ogata_banks(bar.nodes[:, 0], T, K / ne, 1e-9 + 0.01 * K / ne)
    assert np.abs(out[-1][1] - ex).max() < 0.01


def test_kernel_darcy_summary():
    spec = {'physics': ['darcy'], 'tier': 1, 'mesh_source': 'cantilever',
            'mesh_params': {'length': 1.0, 'width': 0.1, 'height': 0.1, 'n_along_length': 10, 'order': 2},
            'material': {'type': 'porous_medium', 'K': 1e-4, 'Ss': 1e-4, 'porosity': 0.2, 'initial_head': 2.0},
            'bcs': [{'hydraulic_head': 2.0, 'face_set': 'fixed', 'label': 'lago'}],
            'loads': [{'well': {'rate': 1e-6, 'point': [0.8, 0.05, 0.05]}, 'label': 'pozo'}],
            'time': {'t_end': 3600.0, 'n_steps': 20, 'dt_growth': 1.1, 'n_output': 4},
            'probes': [{'label': 'Pz', 'point': [0.5, 0.05, 0.05]}]}
    r = FEMKernel()._solve(None, spec, None)
    s = r['summary']
    d = s['darcy']
    assert s['physics'] == ['darcy'] and s['converged'] and d['balance_error'] < 1e-10
    assert {f['key'] for f in s['extra_fields']} == {'h', 's', 'qmag', 'vmag', 'vx', 'vy', 'vz'}
    assert next(f for f in s['extra_fields'] if f['key'] == 'vx')['unit'] == 'm/d'
    assert r['time_series']['fields']['h'].shape == (5, r['mesh'].n_nodes) and len(d['times']) == 5
    w = d['wells'][0]
    assert w['drawdown_m'] > 0 and d['max_drawdown_m'] >= w['drawdown_m'] * 0.999
    assert d['probes'][0]['inside'] and d['probes'][0]['head_m'] < 2.0
    with pytest.raises(ValueError):
        FEMKernel()._solve(None, {**spec, 'loads': [{'force': [1, 0, 0], 'node_set': 'tip'}]}, None)


def test_graph_conversion():
    spec = {'material': {}, 'bcs': [], 'loads': [], 'physics': ['structural']}
    g2s._porous_material(spec, _node('Acuífero', model_type='porous_medium', K=8.64, K_unit='m/d', Kz_ratio=0.1,
                                     Ss=1e-5, porosity=0.25, initial_head=10, transient=True, t_end=2, time_unit='d',
                                     time_steps=40, dt_growth=1.08,
                                     K_zones=[{'label': 'lente', 'x0': 0, 'y0': 0, 'z0': 0, 'x1': 100, 'y1': 50,
                                               'z1': 10, 'K': 0.0864}],
                                     probes=[{'label': 'Pz1', 'x': 1000, 'y': 0, 'z': 0}]))
    m = spec['material']
    assert m['K'] == pytest.approx([1e-4, 1e-4, 1e-5]) and m['porosity'] == 0.25 and m['initial_head'] == 10
    assert m['K_zones'][0]['box'] == [[0.0, 0.0, 0.0], [0.1, 0.05, 0.01]]
    assert m['K_zones'][0]['K'] == pytest.approx([1e-6, 1e-6, 1e-7])
    assert spec['time'] == {'t_end': 172800.0, 'n_steps': 40, 'scheme': 'bdf2', 'dt_growth': 1.08}
    assert spec['probes'] == [{'label': 'Pz1', 'point': [1.0, 0.0, 0.0]}]
    spec['bcs'].append(g2s._bc_node_to_entry({}, _node('Río', bc_type='hydraulic_head', head=12.5, t_off=1)))
    spec['loads'] += [
        g2s._load_node_to_entry({}, _node('Pozo', load_type='well', magnitude=36, unit='m³/h')),
        g2s._load_node_to_entry({}, _node('Pozo P', load_type='well', magnitude=2, unit='L/s', at_point=True,
                                          x=500, y=0, z=5)),
        g2s._load_node_to_entry({}, _node('Lluvia', load_type='recharge', magnitude=1, unit='mm/d')),
        g2s._load_node_to_entry({}, _node('Lecho', load_type='leakage', conductance=0.5, head=11)),
    ]
    g2s._finalize_physics(spec)
    assert spec['physics'] == ['darcy']
    assert spec['bcs'][0]['hydraulic_head'] == 12.5 and spec['bcs'][0]['face_set'] == 'fixed'
    assert spec['bcs'][0]['history'][1] == [86400.0, 1.0]
    well, wp, rech, leak = spec['loads']
    assert well['well'] == {'rate': pytest.approx(0.01)} and well['face_set'] == 'tip'
    assert wp['well'] == {'rate': pytest.approx(0.002), 'point': [0.5, 0.0, 0.005]}
    assert rech['recharge'] == pytest.approx(1e-3 / 86400) and rech['face_set'] == 'z1'
    assert leak['leakage'] == {'conductance': pytest.approx(0.5 / 86400), 'head': 11.0}
    with pytest.raises(g2s.GraphSpecError):       # head BC without the porous material
        g2s._finalize_physics({'material': {'type': 'linear_elastic_isotropic'}, 'physics': ['structural'],
                               'bcs': [{'hydraulic_head': 1.0}], 'loads': []})
    with pytest.raises(g2s.GraphSpecError):       # transient without storage
        g2s._porous_material({'material': {}}, _node('A', K=1e-4, transient=True, t_end=1))
    # transport in a porous medium: dispersivities, retardation, porosity from the Darcy run when empty
    tspec = {'material': {}}
    g2s._transport_material(tspec, _node('Pluma', model_type='scalar_transport', porous=True, alpha_L=5, alpha_T=0.5,
                                         velocity_source='run', velocity_run_id='abc',
                                         species=[{'name': 'Nitrato', 'D': 1e-9, 'retardation': 1.5}]))
    assert tspec['material']['porous'] == {'alpha_L': 5.0, 'alpha_T': 0.5}
    assert tspec['material']['species'][0]['retardation'] == 1.5
    with pytest.raises(g2s.GraphSpecError):       # uniform velocity needs the porosity
        g2s._transport_material({'material': {}}, _node('P', porous=True, vx=1e-5))
