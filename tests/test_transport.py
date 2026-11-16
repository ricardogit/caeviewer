"""Advection–diffusion–reaction transport (FASE 10.1 + 10.2): fem.transport + kernel + graph conversion."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services import graph_to_solver_spec as g2s
from app.design.services.fem import transport as tr
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh
from app.design.services.traceability.hasher import canonical_inputs
from validate_transport import ogata_banks


@pytest.fixture(scope='module')
def box():
    return FEMMesh.generate_cantilever(0.1, 0.05, 0.05, 3, order=2)


@pytest.fixture(scope='module')
def bar():
    return FEMMesh.generate_cantilever(1.0, 0.05, 0.05, 20, order=2)


def _node(label, **props):
    return SimpleNamespace(label=label, properties=props)


def test_model_validation():
    with pytest.raises(ValueError):
        tr.TransportModel({'species': [{'D': -1}]})
    with pytest.raises(ValueError):
        tr.TransportModel({'species': [{'D': 1e-3}], 'reaction': {'model': 'streeter_phelps', 'kd': 1, 'ka': 1}})
    with pytest.raises(ValueError):
        tr.TransportModel({'species': [{}], 'stabilization': 'upwind'})
    m = tr.TransportModel({'species': [{'name': 'A', 'decay': 0.2}, {'name': 'B'}],
                           'reactions': [{'from': 'A', 'to': 'B', 'rate': 0.1, 'yield': 0.5}]})
    assert m.R.tolist() == [[pytest.approx(0.3), 0.0], [pytest.approx(-0.05), 0.0]]
    assert m.index('B') == 1 and m.index(None) == 0
    with pytest.raises(ValueError):
        m.index('C')


def test_flux_exchange_linear_profile_is_exact(box):
    D, q, k = 2e-3, 0.5, 0.1
    snaps, info = tr.solve(box, tr.TransportModel({'species': [{'D': D}]}), [],
                           [{'species_flux': q, 'face_set': 'tip'}, {'exchange': {'k': k, 'c_ext': 1.0}, 'face_set': 'fixed'}])
    ce = 1.0 + q / k + q * box.nodes[:, 0] / D
    assert np.abs(snaps[0][1] - ce).max() < 1e-10 * ce.max()
    assert info['mass_balance_error'] < 1e-12


def test_source_with_decay_and_history(box):
    """Uniform source S in a closed box with decay λ: c = S/λ (1 − e^(−λt)); switched off by a history."""
    S, lam = 2.0, 0.5
    m = tr.TransportModel({'species': [{'D': 1e-4, 'decay': lam}]})
    snaps, info = tr.solve(box, m, [], [{'species_source': S}], time={'t_end': 2.0, 'n_steps': 200, 'scheme': 'cn'})
    assert np.abs(snaps[-1][1] - S / lam * (1 - np.exp(-lam * 2.0))).max() < 1e-4
    assert info['mass_balance_error'] < 1e-12
    V = 0.1 * 0.05 * 0.05
    m0 = tr.TransportModel({'species': [{'D': 1e-4}]})
    snaps, info = tr.solve(box, m0, [], [{'species_source': S, 'history': [[0, 1], [1, 1], [1 + 1e-9, 0]]}],
                           time={'t_end': 2.0, 'n_steps': 20, 'scheme': 'be'})
    assert info['mass_final'][0] == pytest.approx(S * V * 1.0, rel=1e-10)
    assert info['budget']['source'][0] == pytest.approx(S * V, rel=1e-10)


def test_ogata_banks_short(bar):
    v, D, T = 1.0, 4e-3, 0.4
    for stab in ('supg', 'none'):
        snaps, info = tr.solve(bar, tr.TransportModel({'species': [{'D': D}], 'velocity': [v, 0, 0],
                                                       'stabilization': stab}),
                               [{'concentration': 1.0, 'face_set': 'fixed'}], [],
                               time={'t_end': T, 'n_steps': 200, 'n_output': 4})
        assert len(snaps) == 5 and snaps[0][0] == 0.0 and snaps[-1][0] == pytest.approx(T)
        assert np.abs(snaps[-1][1] - ogata_banks(bar.nodes[:, 0], T, v, D)).max() < 0.01
        assert info['mass_balance_error'] < 1e-10
        # initial field kept at t = 0 (boundary value switches on at 0⁺)
        assert np.abs(snaps[0][1]).max() == 0.0


def test_streeter_phelps_reactor(box):
    kd, ka, L0, D0, T = 0.3, 0.7, 20.0, 1.0, 5.0
    m = tr.TransportModel({'species': [{'name': 'DBO'}, {'name': 'déficit'}],
                           'reaction': {'model': 'streeter_phelps', 'kd': kd, 'ka': ka, 'do_sat': 9.0}})
    snaps, info = tr.solve(box, m, [], [], time={'t_end': T, 'n_steps': 100, 'scheme': 'cn'},
                           initial=[{'value': L0}, {'value': D0}])
    n = box.n_nodes
    Le = L0 * np.exp(-kd * T)
    De = kd * L0 / (ka - kd) * (np.exp(-kd * T) - np.exp(-ka * T)) + D0 * np.exp(-ka * T)
    assert snaps[-1][1][:n] == pytest.approx(Le, rel=1e-4)
    assert snaps[-1][1][n:] == pytest.approx(De, rel=1e-4)


def test_locate_and_point_source_errors(box):
    loc = tr.locate(box, [[0.05, 0.025, 0.025], [0.5, 0.0, 0.0]])
    assert loc[0]['inside'] and loc[0]['distance_m'] < 1e-12
    assert not loc[1]['inside'] and loc[1]['distance_m'] > 0.3
    c = 3.0 + box.nodes[:, 0] ** 2                                   # quadratic: T10 interpolates it exactly
    assert tr.interpolate(box, c, loc[0]) == pytest.approx(3.0 + 0.05 ** 2, rel=1e-12)
    with pytest.raises(Exception):
        tr.solve(box, tr.TransportModel({'species': [{'D': 1e-3}]}), [],
                 [{'point_source': {'point': [1.0, 0, 0], 'rate': 1.0}}])


def test_kernel_transient_summary_and_series():
    spec = {'physics': ['transport'], 'tier': 1, 'mesh_source': 'cantilever',
            'mesh_params': {'length': 1.0, 'width': 0.05, 'height': 0.05, 'n_along_length': 20, 'order': 2},
            'material': {'type': 'scalar_transport', 'species': [{'name': 'Trazador', 'D': 4e-3, 'threshold': 0.5}],
                         'velocity': [1.0, 0.0, 0.0]},
            'bcs': [{'concentration': 1.0, 'face_set': 'fixed', 'label': 'entrada'}], 'loads': [],
            'time': {'t_end': 0.4, 'n_steps': 100, 'n_output': 5},
            'probes': [{'label': 'P', 'point': [0.4, 0.025, 0.025]}]}
    r = FEMKernel()._solve(None, spec, None)
    s = r['summary']
    t = s['transport']
    assert s['physics'] == ['transport'] and s['converged'] and t['mass_balance_error'] < 1e-10
    assert len(t['times']) == 6 and r['time_series']['fields']['c0'].shape == (6, r['mesh'].n_nodes)
    assert {f['key'] for f in s['extra_fields']} == {'c0', 'cmax0'}
    sp0 = t['species'][0]
    assert 0 < sp0['volume_above_m3'] < 1.0 * 0.05 * 0.05 and sp0['volume_above_max_m3'] >= sp0['volume_above_m3']
    p = t['probes'][0]
    assert p['inside'] and p['curve'][-1][1] == pytest.approx(ogata_banks(0.4, 0.4, 1.0, 4e-3), abs=0.01)
    # mechanical conditions are rejected
    with pytest.raises(ValueError):
        FEMKernel()._solve(None, {**spec, 'loads': [{'force': [1, 0, 0], 'node_set': 'tip'}]}, None)


def test_graph_conversion():
    spec = {'material': {}, 'bcs': [], 'loads': [], 'physics': ['structural']}
    node = _node('Vertido', model_type='scalar_transport',
                 species=[{'name': 'E. coli', 'D': 1e-4, 'decay': 2, 'decay_unit': 'T90_h', 'unit': 'UFC/100mL'},
                          {'name': 'B', 'D': 0, 'pulse_center_mm': [10, 20, 30], 'pulse_sigma_mm': 5, 'pulse_peak': 3}],
                 vx=0.1, transient=True, t_end=2, time_unit='h', time_steps=40,
                 probes=[{'label': 'playa', 'x': 100, 'y': 0, 'z': 0}])
    g2s._transport_material(spec, node)
    m = spec['material']
    assert m['species'][0]['decay'] == pytest.approx(np.log(10) / 7200)
    assert m['velocity'] == [0.1, 0.0, 0.0] and 'stabilization' not in m
    assert m['initial'][1]['gaussian'] == {'center': [0.01, 0.02, 0.03], 'sigma': 0.005, 'peak': 3.0}
    assert spec['time'] == {'t_end': 7200.0, 'n_steps': 40, 'scheme': 'bdf2'}
    assert spec['probes'] == [{'label': 'playa', 'point': [0.1, 0.0, 0.0]}]
    spec['bcs'].append(g2s._bc_node_to_entry({}, _node('Entrada', bc_type='concentration', concentration=5,
                                                     species=1, history=[[0, 1], [1, 0]])))
    spec['loads'].append(g2s._load_node_to_entry({}, _node('Emisario', load_type='point_source', magnitude=0.2,
                                                           x=50, y=10, z=10, t_off=0.5)))
    g2s._finalize_physics(spec)
    assert spec['physics'] == ['transport']
    assert spec['bcs'][0] == {'concentration': 5.0, 'species': 1, 'label': 'Entrada', 'face_set': 'fixed',
                              'history': [[0.0, 1.0], [3600.0, 0.0]]}
    ld = spec['loads'][0]
    assert ld['point_source'] == {'point': [0.05, 0.01, 0.01], 'rate': 0.2}
    assert ld['history'][1] == [1800.0, 1.0]
    # Streeter–Phelps needs two species; mixed physics are rejected both ways
    with pytest.raises(g2s.GraphSpecError):
        g2s._transport_material({'material': {}}, _node('SP', reaction_model='streeter_phelps', kd=0.3, ka=0.6,
                                                       species=[{'name': 'DBO'}]))
    with pytest.raises(g2s.GraphSpecError):
        g2s._finalize_physics({**spec, 'bcs': spec['bcs'] + [{'dofs': [0, 1, 2], 'values': [0, 0, 0]}]})
    with pytest.raises(g2s.GraphSpecError):
        g2s._finalize_physics({'material': {'type': 'linear_elastic_isotropic'}, 'physics': ['structural'],
                               'bcs': [{'concentration': 1.0}], 'loads': []})
    with pytest.raises(g2s.GraphSpecError):
        g2s._finalize_physics({'material': {'type': 'scalar_transport', 'species': [{}]}, 'physics': [],
                               'bcs': [{'concentration': 1.0, 'species': 2}], 'loads': []})


def test_hash_uses_velocity_run_content_not_id():
    base = {'physics': ['transport'], 'material': {'type': 'scalar_transport', 'species': [{'D': 1e-3}],
                                                   'velocity': {'run_id': '00000000-0000-0000-0000-000000000001'}}}
    ci = canonical_inputs(base)
    assert 'run_id' in ci['material']['velocity'] or 'run_result_hash' in ci['material']['velocity']
    assert canonical_inputs(base) == ci
