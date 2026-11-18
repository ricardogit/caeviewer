"""FASE 2 — kernel FEM: T10, cargas consistentes, BC por eliminación, hito ±1 %.

Run: python -m pytest tests/test_fem_fase2.py -q   (needs gmsh; no database)
"""
import numpy as np
import pytest
import scipy.sparse.linalg as spla

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.assembler import (assemble_F, assemble_K, dirichlet, reduce_system,
                                               BoundaryConditionError)
from app.design.services.fem.constitutive import LinearElasticIsotropic
from app.design.services.fem.mesh import FEMMesh
from app.design.services.fem.solver import solve_cg, solve_direct

E, NU = 210e9, 0.3
D = LinearElasticIsotropic(E, NU).get_D_matrix()


def _t10_reference():
    c = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float) * 0.01 + 0.002
    X = np.vstack([c, (c[tb.T10_EDGES[:, 0]] + c[tb.T10_EDGES[:, 1]]) / 2])
    return X, np.arange(10)[None, :]


def _solve(mesh, loads, bcs):
    K = assemble_K(mesh, D)
    info = []
    F = assemble_F(mesh, loads, info)
    dofs, vals = dirichlet(mesh, bcs)
    Kf, rhs, free = reduce_system(K, F, dofs, vals)
    u = np.zeros(K.shape[0])
    u[free] = spla.spsolve(Kf.tocsc(), rhs)
    u[dofs] = vals
    return u, info


# ── element ──────────────────────────────────────────────────────────────────

def test_t10_rigid_body_modes_and_symmetry():
    X, el = _t10_reference()
    Ke = tb.stiffness_batch(X, el, D)[0]
    ev = np.linalg.eigvalsh(Ke)
    assert int((np.abs(ev) < 1e-8 * ev.max()).sum()) == 6
    assert np.abs(Ke - Ke.T).max() <= 1e-12 * np.abs(Ke).max()


def test_t10_reproduces_quadratic_displacement_exactly():
    X, el = _t10_reference()
    u = np.stack([1e-4 * X[:, 0] ** 2, 2e-4 * X[:, 0] * X[:, 1], -1e-4 * X[:, 2]], 1).ravel()
    p = (0.2, 0.3, 0.1)
    P = np.array([1 - sum(p), *p]) @ X[:4]
    exact = [2e-4 * P[0], 2e-4 * P[0], -1e-4, 2e-4 * P[1], 0, 0]
    assert np.allclose(tb.strain_at(X, el, u, p)[0], exact, rtol=1e-10, atol=1e-16)


def test_canonicalize_fixes_gmsh_order_and_inversion():
    X, el = _t10_reference()
    Ke = tb.stiffness_batch(X, el, D)[0]
    shuffled = el[:, tb.GMSH_TET10_TO_INTERNAL][:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]
    assert np.allclose(tb.stiffness_batch(X, tb.canonicalize(X, shuffled), D)[0], Ke)


# ── loads ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def cube_t10():
    return FEMMesh.generate_cantilever(0.01, 0.01, 0.01, 3, order=2)


def test_surface_force_resultant_and_area(cube_t10):
    F = assemble_F(cube_t10, [{'face_set': 'tip', 'force': [10.0, -20.0, 5.0]}])
    assert np.allclose([F[0::3].sum(), F[1::3].sum(), F[2::3].sum()], [10, -20, 5], rtol=1e-12)
    _, _, area = tb.surface_integrals(cube_t10.nodes, cube_t10.face_sets['tip'])
    assert area.sum() == pytest.approx(1e-4, rel=1e-12)


def test_pressure_pushes_into_body(cube_t10):
    # tip face at x = L, outward normal +x: p > 0 must push in -x with |F| = p A
    F = assemble_F(cube_t10, [{'face_set': 'tip', 'pressure': 1e6}])
    assert F[0::3].sum() == pytest.approx(-1e6 * 1e-4, rel=1e-10)
    assert abs(F[1::3].sum()) < 1e-9 and abs(F[2::3].sum()) < 1e-9


def test_gravity_equals_weight(cube_t10):
    F = assemble_F(cube_t10, [{'gravity': [0, 0, -9.81], 'density': 7800.0}])
    assert F[2::3].sum() == pytest.approx(-7800 * 1e-6 * 9.81, rel=1e-10)


def test_missing_face_set_is_an_error(cube_t10):
    with pytest.raises(BoundaryConditionError):
        assemble_F(cube_t10, [{'face_set': 'F_999', 'force': [1, 0, 0]}])


# ── patch tests (uniaxial stress must be exact for T4 and T10) ───────────────

@pytest.mark.parametrize('order', [1, 2])
def test_uniaxial_patch(order):
    L, A, P = 0.05, 1e-4, 1e4
    m = FEMMesh.generate_cantilever(L, 0.01, 0.01, 5, order=order)
    x0 = np.unique(m.face_sets['fixed'])
    # statically determinate support: ux on the face, uy/uz on one node, uz on a second
    n0 = x0[np.argmin(np.linalg.norm(m.nodes[x0], axis=1))]
    n1 = x0[np.argmax(m.nodes[x0, 1] - m.nodes[x0, 2])]
    m.node_sets['n0'] = np.array([n0])
    m.node_sets['n1'] = np.array([n1])
    u, _ = _solve(m, [{'face_set': 'tip', 'force': [P, 0, 0]}],
                  [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'n0', 'dofs': [1, 2]},
                   {'node_set': 'n1', 'dofs': [2]}])
    ux = u[0::3]
    assert np.allclose(ux, P * m.nodes[:, 0] / (E * A), rtol=1e-8, atol=1e-15)


# ── solver ───────────────────────────────────────────────────────────────────

def test_cg_matches_direct():
    m = FEMMesh.generate_cantilever(0.05, 0.01, 0.01, 6, order=2)
    K = assemble_K(m, D)
    F = assemble_F(m, [{'face_set': 'tip', 'force': [0, -1000, 0]}])
    dofs, vals = dirichlet(m, [{'face_set': 'fixed'}])
    Kf, rhs, _ = reduce_system(K, F, dofs, vals)
    ud, _ = solve_direct(Kf, rhs)
    uc, info = solve_cg(Kf, rhs, tol=1e-10)
    assert info['converged']
    assert np.abs(uc - ud).max() <= 1e-8 * np.abs(ud).max()


# ── hito FASE 2 ──────────────────────────────────────────────────────────────

def test_hito_fase2_t10_slender_cantilever_within_1pct_of_timoshenko():
    L, h, P = 0.2, 0.01, 1000.0
    m = FEMMesh.generate_cantilever(L, h, h, 20, order=2)
    u, _ = _solve(m, [{'face_set': 'tip', 'force': [0, -P, 0]}], [{'face_set': 'fixed'}])
    tip = -u[1::3][np.unique(m.face_sets['tip'])].mean()
    I = h ** 4 / 12
    G = E / (2 * (1 + NU))
    k = 10 * (1 + NU) / (12 + 11 * NU)
    timo = P * L ** 3 / (3 * E * I) + P * L / (k * G * h * h)
    assert abs(tip - timo) / timo < 0.01


def test_t4_locks_on_the_same_mesh():
    """Documents why T10 is the default: T4 on the same mesh is far off (shear locking)."""
    L, h, P = 0.2, 0.01, 1000.0
    m = FEMMesh.generate_cantilever(L, h, h, 20, order=1)
    u, _ = _solve(m, [{'face_set': 'tip', 'force': [0, -P, 0]}], [{'face_set': 'fixed'}])
    tip = -u[1::3][np.unique(m.face_sets['tip'])].mean()
    eb = P * L ** 3 / (3 * E * h ** 4 / 12)
    assert tip < 0.8 * eb


# ── adaptive refinement (FASE 3 regression, fixed in FASE 2) ─────────────────

def test_bisection_is_conforming_and_keeps_sets():
    from app.design.services.fem.mesh_adaptivity import refine_marked_elements_bisection
    m = FEMMesh.generate_cantilever(0.05, 0.01, 0.01, 6, order=1)
    rng = np.random.default_rng(0)
    nodes, els = m.nodes, m.elements
    for _ in range(3):
        mark = rng.random(len(els)) < 0.3
        nodes, els = refine_marked_elements_bisection(nodes, els, mark)
    els = tb.canonicalize(nodes, els)               # raises on zero-volume tets
    vol = tb.volumes(nodes, els)
    assert vol.min() > 0 and vol.sum() == pytest.approx(0.05 * 0.01 * 0.01, rel=1e-10)
    # conforming: the boundary is exactly the box surface (a hanging node would add crack faces)
    _, _, area = tb.surface_integrals(nodes, tb.boundary_faces(els))
    assert area.sum() == pytest.approx(2 * (0.05 * 0.01 * 2 + 0.01 * 0.01), rel=1e-10)
