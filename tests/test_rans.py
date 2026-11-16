"""RANS k-ε with wall functions (FASE 10.4): operators, wall law, fully developed turbulent channel, graph spec."""
import numpy as np
import pytest

from app.design.services.fem import rans
from app.design.services.fem import stokes as st
from app.design.services.fem.assembler import assemble_F
from app.design.services.fem.mesh import FEMMesh


def test_reichardt_limits_and_inverse():
    assert rans.reichardt(0.5) == pytest.approx(0.5, rel=2e-2)            # viscous sublayer u⁺ = y⁺
    yp = 1000.0
    assert rans.reichardt(yp) == pytest.approx(np.log(yp) / 0.41 + 5.6, abs=0.15)   # log law
    nu, y = 1e-5, 2e-3
    ut = np.array([1e-4, 0.01, 0.3, 2.0])
    U = ut * rans.reichardt(y * ut / nu)
    assert np.allclose(rans.utau_from_velocity(U, y, nu), ut, rtol=1e-10)
    assert rans.utau_from_velocity(np.array([0.0]), y, nu)[0] == 0.0


def _box(order=2):
    return FEMMesh.generate_grid(np.linspace(0, 1, 4), [0, 0.3, 0.7, 1.0], np.linspace(0, 0.5, 3), order=order)


def test_iso_p1_subtets():
    m = _box()
    iso = rans.IsoP1(m)
    assert iso.ml.sum() == pytest.approx(0.5, rel=1e-12)                  # lumped mass = volume
    v = m.nodes @ np.array([[1.0, 2, 0], [0, -1, 3], [4, 0, 1]])            # linear field: gradient exact
    G = iso.grad_v(v)
    assert np.allclose(G, np.array([[1.0, 0, 4], [2, -1, 0], [0, 3, 1]])[None], atol=1e-12)
    W = rans.iso_weights()
    assert np.all(W >= 0) and np.allclose(W.sum(axis=1), 1.0)


def test_viscous_operator_rigid_motion_and_symmetry():
    m = _box()
    nut = np.random.default_rng(1).random(m.n_nodes)
    A = rans.viscous(m, 1e-3, 2.0, nut)
    assert abs(A - A.T).max() < 1e-12 * abs(A).max()
    rot = np.cross([0.3, -0.2, 0.5], m.nodes) + [1.0, 2.0, -1.0]          # rigid motion: ε(v) = 0
    assert np.abs(A @ rot.ravel()).max() < 1e-12 * abs(A).max()


def _channel(Re_tau=2000.0, dplus=50.0, ny=16):
    h, rho, ut = 1.0, 1.0, 1.0
    nu = ut * h / Re_tau
    delta = dplus * nu / ut
    w = 1.15 ** np.arange(ny)
    ys = delta + (h - delta) * np.concatenate([[0], np.cumsum(w) / w.sum()])
    mesh = FEMMesh.generate_grid([0, 0.05], ys, [0, 0.05], order=2)
    f = rho * ut ** 2 / (h - delta)
    mat = st.FluidMaterial({'mu': rho * nu, 'rho': rho, 'inertia': True, 'turbulence': {'model': 'k_epsilon'}})
    F = assemble_F(mesh, [{'body_force': [f, 0, 0]}], [])
    bcs = [{'dofs': [0, 1, 2], 'values': [0, 0, 0], 'face_set': 'y0'},
           {'dofs': [1], 'values': [0], 'face_set': 'y1'},
           {'dofs': [1, 2], 'values': [0, 0], 'face_set': 'x0'},
           {'dofs': [1, 2], 'values': [0, 0], 'face_set': 'x1'},
           {'dofs': [2], 'values': [0], 'face_set': 'z0'},
           {'dofs': [2], 'values': [0], 'face_set': 'z1'}]
    turb = rans.TurbulenceSettings({'wall_distance': delta})
    v, p, info = rans.solve_rans(mesh, mat, F, bcs, turb, body=[f, 0, 0])
    return mesh, v, info, nu, delta, f


def test_turbulent_channel_wall_law_and_equilibrium():
    mesh, v, info, nu, delta, f = _channel()
    T = info['turbulence']
    assert T['converged']
    # global equilibrium: wall shear + net convective momentum outflow (x faces, ~2e-4: the Kuhn split is not
    # symmetric in x, a tiny secondary flow appears) = body force, to the solver tolerance; u_τ = 1
    area = 0.05 * 0.05
    C, _ = st.convection(mesh, v, newton=False)
    conv_x = (C @ v.ravel())[0::3].sum()
    assert T['wall_force'][0] + conv_x == pytest.approx(f * (1 - delta) * area, rel=1e-5)
    assert T['wall_force'][0] == pytest.approx(f * (1 - delta) * area, rel=1e-3)
    assert np.allclose(T['wall']['u_tau'], 1.0, atol=2e-3)
    # log region follows Reichardt's profile within 1.5 %
    y = mesh.nodes[:, 1]
    sel = (y * 1 / nu > 50) & (y * 1 / nu < 400)
    assert np.abs(v[sel, 0] / rans.reichardt(y[sel] / nu) - 1).max() < 0.015
    # wall k⁺ = 1/√C_μ (Mohammadi–Pironneau wall values from u_τ)
    kw = T['k'][T['wall']['nodes']]
    assert kw.mean() == pytest.approx(1 / np.sqrt(rans.CMU), rel=2e-3)


def test_turbulent_channel_large_wall_distance():
    """δ⁺ = 200: deep in the log layer τ ∝ U², where a lagged secant friction is a neutral 2-cycle (Newton needed)."""
    mesh, v, info, nu, delta, f = _channel(dplus=200.0)
    T = info['turbulence']
    assert T['converged']
    assert np.allclose(T['wall']['u_tau'], 1.0, atol=5e-3)


def test_graph_spec_rans_material_and_inlet():
    from app.design.services.graph_to_solver_spec import _turbulence_settings
    t = _turbulence_settings({'wall_distance_mm': 0.5, 'inlet_intensity': 3, 'inlet_length_mm': 10}, 'agua')
    assert t == {'model': 'k_epsilon', 'wall_distance': 5e-4, 'inlet_intensity': 0.03, 'inlet_length_scale': 0.01}
    assert _turbulence_settings({}, 'agua') == {'model': 'k_epsilon'}
    with pytest.raises(Exception):
        _turbulence_settings({'inlet_intensity': 150}, 'agua')
    with pytest.raises(ValueError):
        st.FluidMaterial({'mu': 1e-3, 'rho': 1000, 'turbulence': {'model': 'k_epsilon'}})   # needs inertia


def test_rans_needs_walls():
    m = _box()
    mat = st.FluidMaterial({'mu': 1e-3, 'rho': 1000, 'inertia': True})
    with pytest.raises(ValueError, match='paredes'):
        rans.solve_rans(m, mat, np.zeros(3 * m.n_nodes), [{'dofs': [0, 1, 2], 'values': [1, 0, 0], 'face_set': 'x0'}],
                        rans.TurbulenceSettings({}))
