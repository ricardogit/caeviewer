"""Generalized Maxwell viscoelasticity: Prony validation, load histories, relaxation/creep, kernel run.

Run: python -m pytest tests/test_viscoelastic.py -q   (no database)
"""
import numpy as np
import pytest

from app.design.services.fem.assembler import assemble_F, assemble_K, dirichlet
from app.design.services.fem.constitutive import LinearElasticIsotropic, build_material
from app.design.services.fem.kernel import FEMKernel
from app.design.services.fem.viscoelastic import PronySeries, history_at, solve_viscoelastic, time_grid
from validate_viscoelastic import BASE_BCS, E0, NU, SLS, bar, creep_J


def test_prony_validation():
    with pytest.raises(ValueError, match='< 1'):
        PronySeries(1e9, 0.3, [{'g': 0.6, 'tau': 1}, {'g': 0.5, 'tau': 2}])
    with pytest.raises(ValueError, match='al menos'):
        PronySeries(1e9, 0.3, [])
    p = PronySeries(1e9, 0.3, [{'g': 0.25, 'tau': 4.0}])
    assert p.relaxation(0.0) == pytest.approx(1.0) and p.relaxation(1e6) == pytest.approx(0.75)
    assert build_material({'type': 'viscoelastic_maxwell', 'E': 1e9, 'nu': 0.3, 'prony': SLS}).is_linear() is False


def test_jump_in_the_history_is_an_instantaneous_step():
    h = [[0, 1], [5, 1], [5, 0], [10, 0]]
    g = time_grid(h, 10, 4)
    assert g.tolist() == [0, 2.5, 5, 5, 7.5, 10]
    assert history_at(h, g).tolist() == [1, 1, 1, 0, 0, 0]


def _setup():
    m = bar(order=1)
    D0 = LinearElasticIsotropic(E0, NU).get_D_matrix()
    return m, D0, assemble_K(m, D0)


def test_relaxation_is_exact():
    m, D0, K0 = _setup()
    pr = PronySeries(E0, NU, [{'g': 0.4, 'tau': 2.0}, {'g': 0.3, 'tau': 20.0}])
    dofs, vals = dirichlet(m, BASE_BCS + [{'face_set': 'tip', 'dofs': [0], 'values': [5e-5]}])
    r = solve_viscoelastic(m, pr, D0, K0, np.zeros(m.n_dof_structural), dofs, vals, [[0, 1], [7, 1]], 7.0, 5)
    E_t = r['f_int'][3 * m.node_sets['tip']].sum() / 1e-4 / 1e-3
    assert E_t == pytest.approx(E0 * float(pr.relaxation(7.0)), rel=1e-10)


def test_creep_is_second_order_in_time():
    m, D0, K0 = _setup()
    pr = PronySeries(E0, NU, SLS)
    dofs, vals = dirichlet(m, BASE_BCS)
    F = assemble_F(m, [{'face_set': 'tip', 'force': [100.0, 0, 0]}], [])
    errs = []
    for n in (10, 20):
        r = solve_viscoelastic(m, pr, D0, K0, F, dofs, vals, [[0, 1], [30, 1]], 30, n)
        eps = r['u'].reshape(-1, 3)[m.node_sets['tip'], 0].mean() / 0.05
        errs.append(abs(eps / (1e6 * float(creep_J(30.0))) - 1))
    assert errs[0] / errs[1] == pytest.approx(4.0, rel=0.05)


def test_kernel_cantilever_follows_the_correspondence_principle():
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.1, 'width': 0.01, 'height': 0.01, 'n_along_length': 8, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -10, 0]}]}
    k = FEMKernel()
    rv = k._solve(None, {**spec, 'material': {'type': 'viscoelastic_maxwell', 'E': E0, 'nu': NU, 'prony': SLS},
                         'time': {'t_end': 40.0, 'n_steps': 80}}, None)
    rl = k._solve(None, {**spec, 'material': {'type': 'linear_elastic_isotropic', 'E': E0, 'nu': NU}}, None)
    s = rv['summary']
    assert s['material_model'] == 'viscoelastic_maxwell'
    assert s['max_displacement_m'] == pytest.approx(rl['summary']['max_displacement_m'] * E0 * float(creep_J(40.0)),
                                                    rel=1e-3)
    assert s['viscoelastic']['curve'][0]['max_displacement_m'] == pytest.approx(rl['summary']['max_displacement_m'],
                                                                                rel=1e-10)
