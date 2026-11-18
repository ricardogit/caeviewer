"""FASE 7 — traceability and reproducibility.

Hito: two runs with the same parameters produce the same SHA-256 hash.
"""
import copy
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.design.services.traceability import hasher as H
from app.design.services.traceability.reporter import AutoReporter

SPEC = {
    'graph_id': str(uuid.uuid4()),
    'tier': 1,
    'mesh_source': 'cantilever',
    'mesh_params': {'length': 0.2, 'width': 0.01, 'height': 0.01, 'n_along_length': 6, 'order': 2},
    'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
    'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2], 'values': [0, 0, 0], 'label': 'Empotre'}],
    'loads': [{'face_set': 'tip', 'force': [0, -1000, 0], 'label': 'Punta'}],
}


def _hash(spec):
    return H.fingerprint(spec)['hash']


def test_same_parameters_same_hash():
    """Hito FASE 7, at the hash level: graph id, tier, labels, key order and int/float do not matter."""
    other = copy.deepcopy(SPEC)
    other['graph_id'] = str(uuid.uuid4())
    other['tier'] = 3
    other['bcs'][0]['label'] = 'otro nombre'
    other['loads'][0]['label'] = 'F'
    other['material'] = {'rho': 7850.0, 'nu': 0.3, 'E': 210000000000, 'type': 'linear_elastic_isotropic'}
    assert _hash(SPEC) == _hash(other)
    assert len(_hash(SPEC)) == 64


def test_defaults_explicit_or_omitted():
    a = copy.deepcopy(SPEC)
    b = copy.deepcopy(SPEC)
    b['tolerance'] = 1e-8
    b['physics'] = ['structural']
    assert _hash(a) == _hash(b)


def test_bc_and_load_order_irrelevant():
    a = copy.deepcopy(SPEC)
    a['loads'].append({'gravity': [0, 0, -9.81]})
    b = copy.deepcopy(a)
    b['loads'].reverse()
    assert _hash(a) == _hash(b)


@pytest.mark.parametrize('path,value', [
    (('material', 'E'), 200e9),
    (('material', 'nu'), 0.29),
    (('mesh_params', 'order'), 1),
    (('mesh_params', 'n_along_length'), 7),
    (('loads', 0, 'force'), [0, -1001, 0]),
    (('bcs', 0, 'dofs'), [0, 1]),
    (('tolerance',), 1e-10),
])
def test_any_physical_change_changes_hash(path, value):
    other = copy.deepcopy(SPEC)
    target = other
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    assert _hash(other) != _hash(SPEC)


def test_environment_is_part_of_the_hash():
    inp = H.canonical_inputs(SPEC)
    env = H.numerical_environment()
    env2 = dict(env, scipy='0.0.0')
    assert H.compute_run_hash(inp, env) != H.compute_run_hash(inp, env2)
    assert H.environment_diff(env, env2) == {'scipy': [env['scipy'], '0.0.0']}
    assert H.environment_diff(env, env) == {}
    assert env['fem_kernel'] == H.FEM_KERNEL_VERSION


def test_canonical_inputs_strip_bookkeeping():
    inp = H.canonical_inputs(SPEC)
    text = json.dumps(inp)
    assert 'graph_id' not in inp and 'tier' not in inp
    assert 'label' not in text and 'Empotre' not in text
    assert inp['material']['E'] == 210e9


def test_inline_mesh_hashed_by_content():
    nodes = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
    a = {'mesh_source': 'inline', 'nodes': nodes, 'elements': [[0, 1, 2, 3]]}
    b = {'mesh_source': 'inline', 'nodes': np.array(nodes, float), 'elements': np.array([[0, 1, 2, 3]])}
    c = {'mesh_source': 'inline', 'nodes': [[0, 0, 0], [2, 0, 0], [0, 1, 0], [0, 0, 1]],
         'elements': [[0, 1, 2, 3]]}
    assert _hash(a) == _hash(b) != _hash(c)


def test_parameter_delta():
    a = H.canonical_inputs(SPEC)
    other = copy.deepcopy(SPEC)
    other['material']['E'] = 70e9
    other['loads'][0]['force'] = [0, -500, 0]
    d = H.parameter_delta(a, H.canonical_inputs(other))
    assert d == {'material.E': [210e9, 70e9], 'loads.0.force': [[0.0, -1000.0, 0.0], [0.0, -500.0, 0.0]]}


def test_mesh_and_array_hash_are_exact():
    n = np.random.default_rng(0).random((10, 3))
    e = np.arange(8).reshape(2, 4)
    assert H.mesh_hash(n, e) == H.mesh_hash(n.copy(), e.astype(np.int32))
    n2 = n.copy()
    n2[3, 1] = np.nextafter(n2[3, 1], 2)            # one ulp
    assert H.mesh_hash(n2, e) != H.mesh_hash(n, e)
    assert H.array_hash(n) != H.array_hash(n2)


def test_two_solves_bitwise_identical():
    """Same spec solved twice → same mesh hash and same displacement hash (deterministic kernel)."""
    from app.design.services.fem.kernel import FEMKernel
    spec = copy.deepcopy(SPEC)
    spec['mesh_params']['n_along_length'] = 4
    k = FEMKernel()
    s1 = k.solve_sync(copy.deepcopy(spec))['summary']
    s2 = k.solve_sync(copy.deepcopy(spec))['summary']
    assert s1['mesh_hash'] == s2['mesh_hash']
    assert s1['result_hash'] == s2['result_hash']
    spec['loads'][0]['force'] = [0, -1001, 0]
    s3 = k.solve_sync(spec)['summary']
    assert s3['mesh_hash'] == s1['mesh_hash'] and s3['result_hash'] != s1['result_hash']


def test_amg_cg_bitwise_deterministic():
    """pyamg setup uses random vectors: it is seeded, so PCG-AMG solves repeat bit for bit."""
    pytest.importorskip('pyamg')
    from app.design.services.fem.mesh import FEMMesh
    from app.design.services.fem.assembler import assemble_K, assemble_F, dirichlet, reduce_system
    from app.design.services.fem.constitutive import build_material
    from app.design.services.fem.solver import solve_cg, rigid_body_modes
    mesh = FEMMesh.generate_cantilever(0.2, 0.02, 0.02, n_along_length=12, order=2)
    D = build_material({'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}).get_D_matrix()
    K = assemble_K(mesh, D)
    F = assemble_F(mesh, [{'face_set': 'tip', 'force': [0, -1000, 0]}])
    dofs, vals = dirichlet(mesh, [{'face_set': 'fixed', 'dofs': [0, 1, 2]}])
    Kf, rhs, free = reduce_system(K, F, dofs, vals)
    B = rigid_body_modes(mesh.nodes)[free]
    state = np.random.get_state()
    u1, i1 = solve_cg(Kf, rhs, tol=1e-9, near_nullspace=B)
    u2, i2 = solve_cg(Kf, rhs, tol=1e-9, near_nullspace=B)
    assert i1['method'] == 'cg_amg' and i1['converged']
    assert H.array_hash(u1) == H.array_hash(u2)
    assert np.array_equal(np.random.get_state()[1], state[1])   # global RNG left untouched


def _fake_run(**kw):
    inputs = H.canonical_inputs(SPEC)
    base = dict(
        id=uuid.uuid4(), hash=H.compute_run_hash(inputs, H.numerical_environment()), purpose='run',
        status='done', tier=1, created_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        inputs=inputs, environment=H.numerical_environment(),
        provenance={'host': 'h', 'git_commit': 'abc123', 'python_full': '3.11.9', 'platform': 'x'},
        summary={'element_type': 'T10', 'solver_method': 'direct_spsolve', 'n_nodes': 100,
                 'n_elements': 40, 'n_dof': 300, 'converged': True, 'n_iterations': 1,
                 'max_displacement_mm': 1.23, 'max_von_mises_mpa': 45.6, 'equilibrium_error': 1e-12,
                 'applied_load_N': [0, -1000, 0], 'reaction_N': [0, 1000, 0]},
        mesh_hash='a' * 64, result_hash='b' * 64, wall_time=0.5, mesh_stats={},
        parent_run_id=None, parameter_delta={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_markdown_report_sections():
    run = _fake_run(parent_run_id=uuid.uuid4(), parameter_delta={'material.E': [200e9, 210e9]})
    md = AutoReporter().generate_markdown(run)
    for section in ('## Entradas', '## Configuración del solver', '## Resultados',
                    '## Cambios respecto a la corrida anterior', '## Reproducibilidad'):
        assert section in md
    assert run.hash in md and 'a' * 64 in md
    assert '45.6 MPa' in md and 'E = 210 GPa' in md
    assert '`material.E`' in md


def test_markdown_report_failed_and_warnings():
    run = _fake_run(status='failed', summary={}, mesh_stats={'error': 'Gmsh no pudo mallar'})
    md = AutoReporter().generate_markdown(run)
    assert 'Gmsh no pudo mallar' in md
    run = _fake_run(summary={'element_type': 'T4', 'converged': False, 'final_residual': 1e-3})
    md = AutoReporter().generate_markdown(run)
    assert '## Advertencias' in md and 'T4' in md and 'tolerancia' in md


def test_jsonld_report():
    run = _fake_run()
    doc = AutoReporter(base_url='http://x').generate_jsonld(run)
    assert doc['@context'] == 'https://schema.org' and doc['@type'] == 'Dataset'
    ids = {i['propertyID']: i['value'] for i in doc['identifier']}
    assert ids['sha256:inputs'] == run.hash and ids['sha256:displacement'] == 'b' * 64
    names = {v['name']: v for v in doc['variableMeasured']}
    assert names['maxVonMises']['value'] == 45.6 and names['maxVonMises']['unitText'] == 'MPa'
    assert doc['producer']['softwareVersion'] == str(H.FEM_KERNEL_VERSION)
    json.dumps(doc)                                  # serializable
