"""Neo-Hookean hyperelasticity (total Lagrangian): tangent, exact homogeneous states, small-load limit.

Run: python -m pytest tests/test_hyperelastic.py -q   (no database)
"""
import numpy as np
import pytest
from scipy.optimize import brentq

from app.design.services.fem import hyperelastic as he
from app.design.services.fem import tet_batch as tb
from app.design.services.fem.assembler import dirichlet
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.mesh import FEMMesh

NH = he.NeoHookean(10e6, 0.45)


@pytest.mark.parametrize('order', [1, 2])
def test_tangent_matches_finite_differences(order):
    m = FEMMesh.generate_cantilever(0.02, 0.01, 0.01, 2, order=order)
    op = he.TLOperator(m.nodes, m.elements)
    rng = np.random.default_rng(0)
    u = 1e-5 * rng.normal(size=m.n_dof_structural)
    du = 1e-3 * rng.normal(size=m.n_dof_structural)
    _, K, *_ = op.assemble(NH, u, m.n_dof_structural)
    h = 1e-6
    fd = (op.assemble(NH, u + h * du, m.n_dof_structural, need_K=False)[0]
          - op.assemble(NH, u - h * du, m.n_dof_structural, need_K=False)[0]) / (2 * h)
    assert np.linalg.norm(fd - K @ du) / np.linalg.norm(fd) < 1e-7


def test_reduces_to_linear_elasticity_at_small_strain():
    F = np.eye(3)[None] + 1e-7 * np.random.default_rng(1).normal(size=(1, 3, 3))
    _, D, J = NH.stress_tangent(F)
    lam, mu = NH.lam, NH.mu
    D_lin = np.zeros((6, 6))
    D_lin[:3, :3] = lam
    D_lin[[0, 1, 2], [0, 1, 2]] += 2 * mu
    D_lin[[3, 4, 5], [3, 4, 5]] = mu
    assert np.allclose(D[0], D_lin, rtol=1e-5, atol=1e-5 * mu)


@pytest.mark.parametrize('l1', [1.5, 0.7])
def test_uniaxial_stretch_is_exact(l1):
    L = 0.05
    m = FEMMesh.generate_cantilever(L, 0.01, 0.01, 3, order=1)
    m.node_sets['p0'] = np.array([int(np.argmin(np.linalg.norm(m.nodes, axis=1)))])
    m.node_sets['p1'] = np.array([int(np.argmin(np.linalg.norm(m.nodes - [0, 0.01, 0], axis=1)))])
    dofs, vals = dirichlet(m, [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'p0', 'dofs': [1, 2]},
                               {'node_set': 'p1', 'dofs': [2]},
                               {'face_set': 'tip', 'dofs': [0], 'values': [(l1 - 1) * L]}])
    r = he.solve_hyperelastic(m, NH, np.zeros(m.n_dof_structural), dofs, vals, n_steps=4)
    assert r['info']['converged']
    mu, lm = NH.mu, NH.lam
    l2 = brentq(lambda x: mu * (1 - 1 / x ** 2) + lm * np.log(l1 * x * x) / x ** 2, 0.2, 2.0)
    P = l1 * (mu * (1 - 1 / l1 ** 2) + lm * np.log(l1 * l2 * l2) / l1 ** 2) * 1e-4
    assert r['f_int'][3 * m.node_sets['tip']].sum() == pytest.approx(P, rel=1e-8)


def test_simple_shear_cauchy_stress_is_exact():
    m = FEMMesh.generate_cantilever(0.01, 0.01, 0.01, 2, order=2)
    gam = 0.5
    bnd = np.unique(tb.boundary_faces(m.elements))
    dofs = np.sort(np.concatenate([3 * bnd, 3 * bnd + 1, 3 * bnd + 2]))
    target = np.zeros((m.n_nodes, 3))
    target[:, 0] = gam * m.nodes[:, 1]
    r = he.solve_hyperelastic(m, NH, np.zeros(m.n_dof_structural), dofs, target.ravel()[dofs], n_steps=3)
    sig = he.cauchy(r['F_gp'].reshape(-1, 3, 3), r['S_gp'].reshape(-1, 3, 3))
    assert np.allclose(sig, [NH.mu * gam ** 2, 0, 0, NH.mu * gam, 0, 0], atol=1e-8 * NH.mu)


def test_kernel_small_load_matches_linear_and_rejects_thermal():
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.1, 'width': 0.01, 'height': 0.01, 'n_along_length': 8, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -1e-3, 0]}]}
    k = FEMKernel()
    lin = k._solve(None, {**spec, 'material': {'type': 'linear_elastic_isotropic', 'E': 1e7, 'nu': 0.3}}, None)
    nl = k._solve(None, {**spec, 'material': {'type': 'hyperelastic_neohookean', 'E': 1e7, 'nu': 0.3},
                         'n_load_steps': 1}, None)
    s = nl['summary']
    assert s['material_model'] == 'hyperelastic_neohookean' and s['converged']
    assert s['max_displacement_m'] == pytest.approx(lin['summary']['max_displacement_m'], rel=1e-4)
    assert s['equilibrium_error'] < 1e-8
    with pytest.raises(ValueError, match='térmico'):
        k._solve(None, {**spec, 'physics': ['structural', 'thermal'],
                        'material': {'type': 'hyperelastic_neohookean', 'E': 1e7, 'nu': 0.3, 'k': 1.0, 'alpha': 1e-5},
                        'bcs': spec['bcs'] + [{'face_set': '@all', 'temperature': 30.0}]}, None)
