"""Orthotropic materials: material axes, D rotation, conduction tensor, thermal expansion, kernel solves.

Run: python -m pytest tests/test_orthotropic.py -q   (no database)
"""
import numpy as np
import pytest

from app.design.services.fem import thermal as th
from app.design.services.fem.constitutive import (build_material, conductivity, material_axes, rotate_tensor,
                                                  strain_rotation, thermal_expansion)
from app.design.services.fem.kernel import FEMKernel
from validate_orthotropic import CFRP, axes_xy, bar_bcs, bar_mesh, ortho


def _voigt(t):
    return np.array([t[0, 0], t[1, 1], t[2, 2], 2 * t[0, 1], 2 * t[1, 2], 2 * t[0, 2]])


def _tensor(v):
    return np.array([[v[0], v[3] / 2, v[5] / 2], [v[3] / 2, v[1], v[4] / 2], [v[5] / 2, v[4] / 2, v[2]]])


def test_material_axes_are_orthonormal_and_validated():
    R = material_axes({'axis_1': [2, 0, 0], 'axis_2': [1, 3, 0]})
    assert np.allclose(R, np.eye(3))
    R = material_axes({'axis_1': [1, 2, 3], 'axis_2': [0, 1, -1]})
    assert np.allclose(R @ R.T, np.eye(3)) and np.linalg.det(R) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        material_axes({'axis_1': [1, 0, 0], 'axis_2': [2, 0, 0]})


def test_strain_rotation_matches_tensor_rotation():
    R = material_axes({'axis_1': [1, 1, 0.2], 'axis_2': [-1, 1, 0.3]})
    eps = np.random.default_rng(1).normal(size=6)
    assert np.allclose(strain_rotation(R) @ eps, _voigt(R @ _tensor(eps) @ R.T), atol=1e-14)


def test_isotropic_constants_give_the_isotropic_D_for_any_axes():
    E, nu = 200e9, 0.28
    G = E / (2 * (1 + nu))
    iso = build_material({'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu}).get_D_matrix()
    o = build_material({'type': 'linear_elastic_orthotropic', 'E1': E, 'E2': E, 'E3': E, 'G12': G, 'G13': G,
                        'G23': G, 'nu12': nu, 'nu13': nu, 'nu23': nu, 'axis_1': [1, 2, 3], 'axis_2': [0, 1, -1]})
    assert np.allclose(o.get_D_matrix(), iso, rtol=0, atol=1e-6 * iso.max())


@pytest.mark.parametrize('deg', [0, 30, 45, 90])
def test_off_axis_modulus(deg):
    S = np.linalg.inv(build_material(ortho(**axes_xy(deg))).get_D_matrix())
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    Ex = 1 / (c ** 4 / CFRP['E1'] + s ** 4 / CFRP['E2'] + (1 / CFRP['G12'] - 2 * CFRP['nu12'] / CFRP['E1']) * s * s * c * c)
    assert 1 / S[0, 0] == pytest.approx(Ex, rel=1e-12)


def test_inadmissible_constants_and_missing_keys_are_rejected():
    with pytest.raises(ValueError, match='definida'):
        build_material(ortho(nu12=3.5))
    with pytest.raises(ValueError, match='faltan'):
        build_material({'type': 'linear_elastic_orthotropic', 'E1': 1e9})


def test_thermal_helpers_keep_isotropic_scalars_and_rotate_tensors():
    assert conductivity({'k': 45}) == 45.0 and thermal_expansion({'alpha': 1.2e-5}) == 1.2e-5
    m = {'k': [10.0, 2.0, 1.0], 'alpha': [1e-6, 2e-5, 3e-5], **axes_xy(40)}
    R = material_axes(m)
    assert np.allclose(conductivity(m), R.T @ np.diag([10, 2, 1]) @ R)
    assert np.allclose(_tensor(thermal_expansion(m)), rotate_tensor(m['alpha'], R))


def test_off_axis_tension_is_exact_in_the_kernel():
    m = bar_mesh(order=1)
    mat = ortho(**axes_xy(30))
    r = FEMKernel()._solve(None, {'physics': ['structural'], 'tier': 1, 'material': mat, 'bcs': bar_bcs(),
                                  'loads': [{'face_set': 'tip', 'force': [1000.0, 0, 0]}]}, None, mesh=m)
    u = np.asarray(r['displacement']).reshape(-1, 3)
    S = np.linalg.inv(build_material(mat).get_D_matrix())
    eps = u[m.node_sets['tip'], 0].mean() / 0.05
    assert eps == pytest.approx(S[0, 0] * 1e7, rel=1e-9)


def test_rotated_conduction_patch_and_free_expansion():
    m = bar_mesh(order=2)
    mat = ortho(**axes_xy(30), k=[200.0, 5.0, 1.0], alpha=[-5e-7, 3e-5, 3e-5], T_ref=20.0)
    K = conductivity(mat)
    g = np.array([1000.0, -400.0, 250.0])
    _, qn = th.heat_flux(m.nodes, m.elements, 50 + m.nodes @ g, K)
    assert np.allclose(qn, -K @ g, rtol=1e-12)
    r = FEMKernel()._solve(None, {'physics': ['structural', 'thermal'], 'tier': 1, 'material': mat,
                                  'bcs': bar_bcs() + [{'face_set': '@all', 'temperature': 120.0}], 'loads': []},
                           None, mesh=m)
    u = np.asarray(r['displacement']).reshape(-1, 3)
    X = np.hstack([np.ones((m.n_nodes, 1)), m.nodes])
    coef, *_ = np.linalg.lstsq(X, u, rcond=None)
    eps = 0.5 * (coef[1:].T + coef[1:])
    assert np.allclose(eps, rotate_tensor(mat['alpha'], material_axes(mat)) * 100.0, rtol=0, atol=1e-12)
