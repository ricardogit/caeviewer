"""FASE 3 adaptive meshing: ZZ/SPR estimator, Dörfler marking, conforming T4/T10 refinement, adaptive loop.

Run: python -m pytest tests/test_adaptive.py -q   (needs gmsh; no database)
"""
from math import factorial

import numpy as np
import pytest

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.constitutive import build_material
from app.design.services.fem.error_estimator import QUAD_PTS, QUAD_W, mark_dorfler, zz_estimate
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh
from app.design.services.fem.mesh_adaptivity import refine_mesh

MAT = {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800.0}
D = build_material(MAT).get_D_matrix()


@pytest.fixture(scope='module', params=[1, 2], ids=['T4', 'T10'])
def box(request):
    return FEMMesh.generate_cantilever(0.05, 0.01, 0.01, 6, order=request.param)


def test_quadrature_is_exact_to_degree_5():
    for a in range(6):
        for b in range(6 - a):
            for c in range(6 - a - b):
                exact = factorial(a) * factorial(b) * factorial(c) / factorial(a + b + c + 3)
                q = sum(w * p[0] ** a * p[1] ** b * p[2] ** c for p, w in zip(QUAD_PTS, QUAD_W))
                assert q == pytest.approx(exact, rel=1e-12)


def _field(X, quadratic):
    x, y, z = X[:, 0], X[:, 1], X[:, 2]
    u = np.stack([1e-4 * x + 2e-4 * y, -3e-4 * z + 1e-4 * x, 2e-4 * y + 1e-4 * z], axis=1)
    if quadratic:
        u += np.stack([0.3 * x * y, 0.2 * y * z - 0.1 * x * x, 0.4 * x * z], axis=1)
    return u.ravel()


def test_estimator_is_zero_when_the_recovery_is_exact(box):
    """Constant stress (linear u): any recovery is exact. T10 + linear stress (quadratic u): SPR fits
    quadratics (linear on thin boundary patches), so it reproduces it too: η ≈ 0."""
    for quadratic in ([False, True] if box.element_type == 'T10' else [False]):
        est = zz_estimate(box.nodes, box.elements, _field(box.nodes, quadratic), D)
        assert est['solution_energy'] > 0
        assert est['relative_error'] < 1e-6, (box.element_type, quadratic, est['relative_error'])


def test_dorfler_marks_the_fewest_elements_with_theta_of_the_error():
    eta2 = np.array([1.0, 5.0, 0.5, 3.0, 0.5])
    m = mark_dorfler(eta2, 0.6)                       # total 10 → need ≥ 6: 5 + 3
    assert m.tolist() == [False, True, False, True, False]
    assert not mark_dorfler(np.zeros(3)).any()


def test_refinement_is_conforming_and_keeps_volume_sets_and_curved_mids(box):
    rng = np.random.default_rng(0)
    marked = rng.random(box.n_elements) < 0.3
    nodes, els, sets, faces = refine_mesh(box.nodes, box.elements, marked, box.node_sets)
    assert len(els) > box.n_elements
    assert tb.volumes(nodes, els).sum() == pytest.approx(tb.volumes(box.nodes, box.elements).sum(), rel=1e-12)
    # conforming: every face is shared by two elements or lies on the (unchanged) boundary
    bf = tb.boundary_faces(els)
    area = lambda n, t: 0.5 * np.linalg.norm(np.cross(n[t[:, 1]] - n[t[:, 0]], n[t[:, 2]] - n[t[:, 0]]), axis=1).sum()  # noqa: E731
    assert area(nodes, bf) == pytest.approx(area(box.nodes, tb.boundary_faces(box.elements)), rel=1e-12)
    for name in ('fixed', 'tip'):                     # carried face sets still cover the end faces
        assert area(nodes, faces[name]) == pytest.approx(1e-4, rel=1e-9)
        assert np.allclose(nodes[sets[name], 0], 0.0 if name == 'fixed' else 0.05)
    assert len(np.unique(els)) == len(nodes)          # no orphan nodes
    if els.shape[1] == 10:                            # straight mesh: every mid node is its edge's midpoint
        mids = (nodes[els[:, tb.T10_EDGES[:, 0]]] + nodes[els[:, tb.T10_EDGES[:, 1]]]) / 2
        assert np.allclose(nodes[els[:, 4:]], mids)
    FEMMesh(nodes, els, mids_known=True)              # positive orientation / valid mesh


def test_refinement_puts_split_nodes_on_the_curved_mid_node():
    """A split edge's new corner goes where the old (curved) mid node was, not on the chord."""
    m = FEMMesh.generate_cantilever(0.05, 0.01, 0.01, 4, order=2)
    e = int(np.argmax(tb.volumes(m.nodes, m.elements)))
    X = m.nodes[m.elements[e, :4]]
    lengths = [np.linalg.norm(X[j] - X[i]) for i, j in tb.T10_EDGES]
    k = int(np.argmax(lengths))                       # the longest edge is the one bisected
    mid = m.elements[e, 4 + k]
    nodes = m.nodes.copy()
    nodes[mid] += 2e-5 * np.array([0.0, 0.0, 1.0])    # bend it (keeps all elements valid)
    marked = np.zeros(m.n_elements, dtype=bool)
    marked[e] = True
    new_nodes, els, _, _ = refine_mesh(nodes, m.elements, marked, {})
    corners = new_nodes[np.unique(els[:, :4])]
    assert np.linalg.norm(corners - nodes[mid], axis=1).min() < 1e-15


def _beam_spec(n_div, order=2):
    return {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.2, 'width': 0.01, 'height': 0.01, 'n_along_length': n_div,
                            'order': order},
            'material': MAT, 'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
            'loads': [{'face_set': 'tip', 'force': [0, -1000, 0]}]}


def test_adaptive_loop_reduces_the_error_and_keeps_loads_and_equilibrium():
    log = []
    r = FEMKernel().solve_adaptive(_beam_spec(8), {'target_error': 0.06, 'max_cycles': 6, 'theta': 0.5},
                                   progress=log.append)
    assert [e['cycle'] for e in log] == list(range(len(log))) and len(log) >= 3
    errs = [e['global_error'] for e in log]
    assert all(b < a for a, b in zip(errs, errs[1:]))           # monotone decrease
    assert all(b['n_nodes'] > a['n_nodes'] for a, b in zip(log, log[1:]))
    a = r['summary']['adaptive']
    assert a['converged'] and a['final_error'] < 0.06 and a['cycles'] == len(log)
    s = r['summary']
    assert s['element_type'] == 'T10'
    assert s['applied_load_N'][1] == pytest.approx(-1000.0, rel=1e-9)   # tip face set carried over
    assert s['equilibrium_error'] < 1e-6
    assert s['n_nodes'] == log[-1]['n_nodes']


def test_adaptive_loop_stops_at_the_tier_limit():
    spec = {**_beam_spec(30), 'tier': 0}                         # Tier 0: ≤ 30K DOF
    r = FEMKernel().solve_adaptive(spec, {'target_error': 0.001, 'max_cycles': 12, 'theta': 0.9})
    a = r['summary']['adaptive']
    assert a['stopped'] == 'tier' and not a['converged']
    assert r['adaptive_log'][-1]['n_dof'] <= 30_000
