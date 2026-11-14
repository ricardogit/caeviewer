"""FASE 4.2–4.3 — additive-manufacturing overhang filter and level-set topology optimization."""
import numpy as np
import pytest

from app.design.services.fem.constitutive import build_material
from app.design.services.fem.mesh import FEMMesh
from app.design.services.topology.am_constraints import AMConstraints, overhang_area_fraction
from app.design.services.topology.simp import SIMPOptimizer

D = build_material({'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3}).get_D_matrix()


def _grid(n=8, h=1.0):
    g = (np.arange(n) + 0.5) * h
    X, Y, Z = np.meshgrid(g, g, g, indexing='ij')
    return np.c_[X.ravel(), Y.ravel(), Z.ravel()], np.full(n ** 3, h ** 3)


def test_am_filter_supports_columns_and_45deg_walls_but_not_floating_blocks():
    c, v = _grid()
    am = AMConstraints(c, v, h_mean=1.0, build_direction=(0, 0, 1), max_overhang_angle=45.0, layer_factor=1.0)
    ix, iy, iz = (c[:, k].astype(int) for k in range(3))
    column = ((ix == 3) & (iy == 3)).astype(float)
    assert am.unsupported_fraction(column) == pytest.approx(0.0)
    stair = ((ix == iz) & (iy == 3)).astype(float)                       # 45° wall: printable
    assert am.unsupported_fraction(stair) == pytest.approx(0.0)
    shallow = ((ix == 2 * iz) & (iy == 3)).astype(float)                 # 26.6° from horizontal: not printable
    assert am.unsupported_fraction(shallow) > 0.5
    floating = ((iz == 5) & (ix < 4) & (iy < 4)).astype(float)           # slab in mid-air
    assert am.unsupported_fraction(floating) == pytest.approx(1.0)
    bridge = (((ix == 0) | (ix == 7)) & (iy == 3)).astype(float)         # two piers + a flat deck
    bridge[(iz == 7) & (iy == 3)] = 1.0
    f = am.unsupported_fraction(bridge)
    assert 0.1 < f < 0.5                                                 # the unsupported middle of the deck


def test_am_filter_backprop_is_the_exact_adjoint():
    rng = np.random.default_rng(3)
    c, v = _grid(6)
    c = c + rng.normal(scale=0.15, size=c.shape)                         # irregular layout
    am = AMConstraints(c, v, h_mean=1.0, build_direction=(0.2, 0.1, 1.0), max_overhang_angle=50.0, P=8, eps=1e-2)
    x = 0.2 + 0.6 * rng.random(len(c))
    g = rng.random(len(c))
    am.forward(x)
    grad = am.backprop(g)
    for i in rng.choice(len(c), 8, replace=False):
        h = 1e-6
        xp, xm = x.copy(), x.copy()
        xp[i] += h
        xm[i] -= h
        fd = (g @ am.forward(xp, keep=False) - g @ am.forward(xm, keep=False)) / (2 * h)
        assert fd == pytest.approx(grad[i], rel=1e-5, abs=1e-9)


def test_simp_sensitivity_with_am_filter_matches_finite_differences():
    beam = FEMMesh.generate_cantilever(0.06, 0.02, 0.01, n_along_length=8)
    opt = SIMPOptimizer(beam, D, [{'face_set': 'tip', 'force': [0, -1000, 0]}],
                        [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
                        {'volume_fraction': 0.5, 'am_constraint': True, 'build_direction': [0, 1, 0],
                         'keep_bc_load_solid': False})
    opt.proj.beta = 4.0
    opt.am.P, opt.am.eps = 10.0, 1e-3
    rng = np.random.default_rng(0)
    x = 0.3 + 0.4 * rng.random(beam.n_elements)

    def C(xx):
        _, rb = opt.physical(xx, keep=False)
        return opt.compliance_and_sensitivity(rb)[0]

    _, rb = opt.physical(x)
    _, dc, *_ = opt.compliance_and_sensitivity(rb)
    g, _ = opt.chain_rule(dc)
    for e in rng.choice(beam.n_elements, 6, replace=False):
        h = 1e-6
        xp, xm = x.copy(), x.copy()
        xp[e] += h
        xm[e] -= h
        assert (C(xp) - C(xm)) / (2 * h) == pytest.approx(g[e], rel=1e-4, abs=1e-12 * abs(C(x)))


def test_overhang_area_of_a_box_is_its_bottom_only_when_off_the_plate():
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    assert overhang_area_fraction(V, F)['overhang_area'] == 0.0              # bottom lies on the plate
    up = overhang_area_fraction(V + [0, 0, 0], F, build_direction=(0, 0, -1))  # printed upside down
    assert up['overhang_area'] == 0.0
    V2 = np.vstack([V, [[0, 0, -1]]])                                        # a lower point moves the plate
    assert overhang_area_fraction(V2, F)['overhang_area'] == pytest.approx(1.0)


def test_simp_settings_hash_is_unchanged_without_am():
    from app.design.services.topology.simp import SIMPSettings, TopologyError
    plain = SIMPSettings.from_dict({'volume_fraction': 0.3}).to_dict()
    assert not {'am_constraint', 'build_direction', 'max_overhang_angle'} & plain.keys()   # FASE 7 hashes
    am = SIMPSettings.from_dict({'am_constraint': True, 'build_direction': [0, 2, 0]}).to_dict()
    assert am['build_direction'] == pytest.approx([0, 1, 0]) and am['max_overhang_angle'] == 45.0
    with pytest.raises(TopologyError):
        SIMPSettings.from_dict({'am_constraint': True, 'build_direction': [0, 0, 0]})


def test_level_set_bridge_meets_volume_with_a_crisp_design():
    from app.design.services.topology.levelset import LevelSetOptimizer, LevelSetSettings, TopologyError
    plate = FEMMesh.generate_plate(0.2, 0.1, 0.01, 0.0075)          # the band is one element: needs resolution
    bcs = [{'face_set': 'support_left', 'dofs': [0, 1]}, {'face_set': 'support_right', 'dofs': [0, 1]},
           {'face_set': 'back', 'dofs': [2], 'keep_solid': False}]
    hist = []
    opt = LevelSetOptimizer(plate, D, [{'face_set': 'top', 'force': [0, -10000, 0]}], bcs,
                            {'volume_fraction': 0.3, 'max_iter': 120, 'ramp_iter': 30, 'dt': 0.1},
                            progress=hist.append)
    r = opt.run()
    assert r['converged']
    assert r['volume_fraction'] == pytest.approx(0.3, abs=0.005)
    assert r['volume_fraction_bw'] == pytest.approx(0.3, abs=0.005)
    assert r['compliance_bw'] < 0.8 * r['compliance_initial']       # clearly better than the uniform 30 % design
    assert r['grayness'] < 0.35                                      # only the cut band is grey
    assert hist[0]['target_volume'] > hist[-1]['target_volume'] == pytest.approx(0.3)
    assert np.all(np.abs(r['phi']) <= 1.0)
    with pytest.raises(TopologyError):
        LevelSetSettings.from_dict({'tau': 0})


def test_printability_metrics_of_a_run():
    from app.design.services.topology.runner import _printability
    from app.design.services.topology.simp import SIMPSettings
    beam = FEMMesh.generate_cantilever(0.06, 0.02, 0.01, n_along_length=8)
    st = SIMPSettings.from_dict({'volume_fraction': 0.5})
    opt = SIMPOptimizer(beam, D, [{'face_set': 'tip', 'force': [0, -1000, 0]}],
                        [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], st)
    full = {'densities': np.ones(opt.mesh.n_elements)}
    am = _printability(opt, full, st)['am']
    assert am['unsupported_volume_fraction'] == pytest.approx(0.0, abs=1e-9)  # a box stands on its own
    assert am['overhang_area_fraction'] == pytest.approx(0.0)
    assert am['build_direction'] == [0.0, 0.0, 1.0] and am['constrained'] is False
