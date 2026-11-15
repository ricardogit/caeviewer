"""Steady Navier–Stokes (Taylor-Hood P2-P1, Picard + Newton): exactness, convergence, graph spec, hashing."""
import numpy as np
import pytest

from app.design.services.fem import stokes as st
from app.design.services.fem.mesh import FEMMesh


@pytest.fixture(scope='module')
def channel():
    return FEMMesh.generate_cantilever(4e-3, 2e-3, 1e-3, 6, order=2)


WALLS = [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
         {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]},
         {'face_set': 'fixed', 'dofs': [1, 2]}, {'face_set': 'tip', 'dofs': [1, 2]}]


def _run(m, mat, bcs, loads):
    from app.design.services.fem.kernel import FEMKernel
    return FEMKernel()._solve(None, {'tier': 1, 'material': mat, 'bcs': bcs, 'loads': loads}, None, mesh=m)


def test_poiseuille_exact_with_inertia(channel):
    m, dp, mu, L, H = channel, 2.0, 1e-3, 4e-3, 1e-3
    r = _run(m, {'type': 'newtonian_fluid', 'mu': mu, 'rho': 1000.0, 'inertia': True}, WALLS,
             [{'face_set': 'fixed', 'pressure': dp}])
    z = m.nodes[:, 2]
    u = dp / (2 * mu * L) * z * (H - z)
    assert np.abs(r['velocity'][:, 0] - u).max() < 1e-8 * u.max()
    f = r['summary']['fluid']
    assert f['model'] == 'navier_stokes' and r['summary']['converged'] and 20 < f['reynolds'] < 200
    assert 'warnings' not in r['summary']


def test_convection_operators_match_finite_differences(channel):
    """C(v)v is the convective force and C + J its exact Jacobian."""
    m = channel
    rng = np.random.default_rng(0)
    v = rng.normal(size=(m.n_nodes, 3))
    dv = rng.normal(size=(m.n_nodes, 3))
    C, J = st.convection(m, v)
    c0 = C @ v.ravel()
    h = 1e-6
    C1, _ = st.convection(m, v + h * dv, newton=False)
    fd = (C1 @ (v + h * dv).ravel() - c0) / h
    an = (C + J) @ dv.ravel()
    assert np.linalg.norm(fd - an) < 1e-5 * np.linalg.norm(an)


def test_kovasznay_coarse_and_newton_quadratic():
    import validate_navier_stokes as v
    ev, ep, ns, _ = v.kovasznay(4)
    assert ev < 0.06 and ep < 0.08
    rr = ns['newton_residuals']
    assert rr[-1] < 1e-12 and ns['picard_iterations'] >= 1


def test_no_convergence_raises_after_continuation():
    from app.design.services.fem.assembler import dirichlet
    m = FEMMesh.generate_cantilever(1.0, 1.0, 0.25, 4, order=2)
    bcs = ([{'face_set': 'y1', 'dofs': [0, 1, 2], 'values': [1.0, 0, 0]}]
           + [{'face_set': f, 'dofs': [0, 1, 2]} for f in ('fixed', 'tip', 'y0')]
           + [{'face_set': f, 'dofs': [2]} for f in ('z0', 'z1')])
    dofs, vals = dirichlet(m, bcs)
    mat = st.FluidMaterial({'mu': 0.01, 'rho': 1.0, 'inertia': True})
    with pytest.raises(ValueError, match='no converge'):
        st.solve_ns(m, mat, np.zeros(3 * m.n_nodes), dofs, vals, max_iter=1)


def test_inertia_needs_density():
    with pytest.raises(ValueError, match='densidad'):
        st.FluidMaterial({'mu': 1e-3, 'rho': 0, 'inertia': True})


def test_stokes_hash_unchanged_and_inertia_hashed():
    from app.design.services.traceability.hasher import canonical_inputs
    base = {'material': {'type': 'newtonian_fluid', 'mu': 1e-3, 'rho': 998.0}, 'physics': ['fluid'], 'bcs': [],
            'loads': []}
    ns = {**base, 'material': {**base['material'], 'inertia': True}}
    assert 'inertia' not in canonical_inputs(base)['material']
    assert canonical_inputs(ns) != canonical_inputs(base)


# ── SUPG stabilisation ───────────────────────────────────────────────────────

def test_supg_jacobian_matches_finite_differences():
    m = FEMMesh.generate_cantilever(1.0, 1.0, 0.25, 3, order=2)
    corners, _ = st.pressure_index(m)
    rng = np.random.default_rng(3)
    v, ph = rng.normal(size=(m.n_nodes, 3)), rng.normal(size=len(corners))
    dv, dp = rng.normal(size=(m.n_nodes, 3)), rng.normal(size=len(corners))
    f = np.array([0.3, -1.0, 0.2])
    _, Jvv, Jvp = st.supg(m, v, ph, 50.0, f, 'newton')
    e = 1e-6
    fd = (st.supg(m, v + e * dv, ph + e * dp, 50.0, f, 'residual')[0]
          - st.supg(m, v - e * dv, ph - e * dp, 50.0, f, 'residual')[0]) / (2 * e)
    assert np.abs(Jvv @ dv.ravel() + Jvp @ dp - fd).max() < 1e-8 * np.abs(fd).max()
    _, P, Pp = st.supg(m, v, ph, 50.0, None, 'picard')                # Oseen operator reproduces the residual
    R = st.supg(m, v, ph, 50.0, None, 'residual')[0]
    assert np.abs(P @ v.ravel() + Pp @ ph - R).max() < 1e-12 * np.abs(R).max()


def test_supg_is_consistent_poiseuille_exact(channel):
    m, dp, mu, L, H = channel, 2.0, 1e-3, 4e-3, 1e-3
    r = _run(m, {'type': 'newtonian_fluid', 'mu': mu, 'rho': 1000.0, 'inertia': True, 'stabilization': 'supg'},
             WALLS, [{'face_set': 'fixed', 'pressure': dp}])
    z = m.nodes[:, 2]
    u = dp / (2 * mu * L) * z * (H - z)
    assert np.abs(r['velocity'][:, 0] - u).max() < 1e-8 * u.max()
    assert r['summary']['fluid']['navier_stokes']['stabilization'] == 'supg'


def test_supg_option_validation_and_hash():
    from app.design.services.traceability.hasher import canonical_inputs
    with pytest.raises(ValueError, match='SUPG'):
        st.FluidMaterial({'mu': 1e-3, 'rho': 1000, 'stabilization': 'supg'})          # Stokes
    with pytest.raises(ValueError, match='desconocida'):
        st.FluidMaterial({'mu': 1e-3, 'rho': 1000, 'inertia': True, 'stabilization': 'gls'})
    base = {'material': {'type': 'newtonian_fluid', 'mu': 1e-3, 'rho': 998.0, 'inertia': True}, 'physics': ['fluid'],
            'bcs': [], 'loads': []}
    stab = {**base, 'material': {**base['material'], 'stabilization': 'supg'}}
    assert canonical_inputs(stab) != canonical_inputs(base)
