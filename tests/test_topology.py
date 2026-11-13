"""FASE 4 — SIMP topology optimization."""
import numpy as np
import pytest

from app.design.services.fem.constitutive import build_material
from app.design.services.fem.mesh import FEMMesh
from app.design.services.topology.filter import DensityFilter, HeavisideProjection
from app.design.services.topology.isosurface import extract_isosurface
from app.design.services.topology.simp import SIMPOptimizer, SIMPSettings, TopologyError, to_t4

D = build_material({'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}).get_D_matrix()
BCS = [{'face_set': 'fixed', 'dofs': [0, 1, 2]}]
LOADS = [{'face_set': 'tip', 'force': [0, -1000, 0]}]


@pytest.fixture(scope='module')
def beam():
    return FEMMesh.generate_cantilever(0.06, 0.02, 0.01, n_along_length=8)


def test_filter_preserves_constants_and_backprop_is_adjoint():
    rng = np.random.default_rng(1)
    c = rng.random((200, 3))
    v = rng.random(200) + 0.5
    f = DensityFilter(0.3).build_weight_matrix(c, v)
    assert np.allclose(f.apply(np.full(200, 0.37)), 0.37)
    x, g = rng.random(200), rng.random(200)
    # <g, F x> == <F^T g, x>
    assert np.isclose(g @ f.apply(x), f.backprop(g) @ x)


def test_heaviside_derivative():
    p = HeavisideProjection(beta=8, eta=0.5)
    r = np.linspace(0.01, 0.99, 50)
    h = 1e-6
    fd = (p.project(r + h) - p.project(r - h)) / (2 * h)
    assert np.allclose(fd, p.sensitivity_chain(r), rtol=1e-5, atol=1e-8)
    assert np.isclose(p.project(np.array([0.0]))[0], 0.0) and np.isclose(p.project(np.array([1.0]))[0], 1.0)


@pytest.mark.parametrize('projection', [False, True])
def test_compliance_sensitivity_matches_finite_differences(beam, projection):
    opt = SIMPOptimizer(beam, D, LOADS, BCS, {'volume_fraction': 0.5, 'projection': projection,
                                             'keep_bc_load_solid': False})
    opt.proj.beta = 4.0
    rng = np.random.default_rng(0)
    x = 0.3 + 0.4 * rng.random(beam.n_elements)

    def C(xx):
        _, rb = opt.physical(xx)
        return opt.compliance_and_sensitivity(rb)[0]

    rt, rb = opt.physical(x)
    _, dc, *_ = opt.compliance_and_sensitivity(rb)
    chain = opt.proj.sensitivity_chain(rt) if projection else 1.0
    g = opt.filter.backprop(dc * chain)
    for e in rng.choice(beam.n_elements, 6, replace=False):
        h = 1e-6
        xp, xm = x.copy(), x.copy()
        xp[e] += h
        xm[e] -= h
        fd = (C(xp) - C(xm)) / (2 * h)
        assert np.isclose(fd, g[e], rtol=2e-4, atol=1e-12 * abs(C(x))), (e, fd, g[e])


def test_oc_meets_volume_and_compliance_drops(beam):
    opt = SIMPOptimizer(beam, D, LOADS, BCS, {'volume_fraction': 0.4, 'max_iter': 30})
    r = opt.run()
    assert abs(r['volume_fraction'] - 0.4) < 0.01
    assert r['compliance'] < r['compliance_initial']
    assert r['n_passive_solid'] > 0
    assert np.all((r['densities'] >= 0) & (r['densities'] <= 1))
    hist = [h['compliance'] for h in r['history']]
    assert hist[-1] < 0.9 * hist[0]


def test_settings_validation_and_errors(beam):
    with pytest.raises(TopologyError):
        SIMPSettings.from_dict({'volume_fraction': 1.5})
    with pytest.raises(TopologyError):
        SIMPOptimizer(beam, D, [{'gravity': [0, 0, -9.81]}], BCS)
    with pytest.raises(TopologyError):
        SIMPOptimizer(beam, D, LOADS, [{'face_set': 'fixed', 'dofs': [0], 'values': [1e-3]}])
    s = SIMPSettings.from_dict({'volume_fraction': 0.3, 'unknown': 1, 'max_iter': None})
    assert s.volume_fraction == 0.3 and s.max_iter == 150


def test_symmetry_bc_is_not_passive(beam):
    bcs = BCS + [{'face_set': 'tip', 'dofs': [2], 'symmetry': True}]
    a = SIMPOptimizer(beam, D, LOADS, BCS)
    b = SIMPOptimizer(beam, D, LOADS, bcs)
    assert a.passive_solid.sum() == b.passive_solid.sum()


def test_t10_mesh_is_reduced_to_t4():
    m = FEMMesh.generate_cantilever(0.06, 0.02, 0.01, n_along_length=6, order=2)
    m4 = to_t4(m)
    assert m4.element_type == 'T4' and m4.n_elements == m.n_elements
    assert m4.n_nodes < m.n_nodes
    assert set(m4.face_sets) >= {'fixed', 'tip'} and m4.face_sets['tip'].shape[1] == 3


def test_isosurface_watertight_volume():
    trimesh = pytest.importorskip('trimesh')
    m = FEMMesh.generate_cantilever(0.1, 0.1, 0.1, n_along_length=12)
    c = m.nodes[m.elements].mean(axis=1)
    rho = ((np.linalg.norm(c - 0.05, axis=1) < 0.03) | (c[:, 0] < 0.02)).astype(float)
    s = extract_isosurface(m.nodes, m.elements, rho, 0.5)
    tm = trimesh.Trimesh(s['vertices'], s['faces'], process=True)
    assert tm.is_watertight and tm.is_winding_consistent
    assert s['volume'] > 0                                  # outward orientation
    exact = 4 / 3 * np.pi * 0.03 ** 3 + 0.02 * 0.01
    assert abs(s['volume'] - exact) / exact < 0.05


def test_plate_face_sets():
    m = FEMMesh.generate_plate(0.2, 0.1, 0.01, 0.01, hole_radius=0.02)
    assert {'top', 'bottom', 'support_left', 'support_right', 'back', 'front', 'hole'} <= set(m.face_sets)
    yb = m.nodes[np.unique(m.face_sets['support_left'])]
    assert np.allclose(yb[:, 1], 0) and yb[:, 0].max() <= 0.01 + 1e-9
