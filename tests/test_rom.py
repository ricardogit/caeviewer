"""FASE 5 — POD-Galerkin ROM."""
import json
import time

import numpy as np
import pytest

from app.design.services.fem.constitutive import build_material
from app.design.services.fem.mesh import FEMMesh
from app.design.services.rom.online_solver import ROMOnlineSolver
from app.design.services.rom.pod import (D_LAMBDA, D_MU, PODROMBuilder, ROMError, describe_parameters,
                                         evaluate_arrays, lame, latin_hypercube)

SPEC = {
    'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7850},
    'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
    'loads': [{'face_set': 'tip', 'force': [0, -1000, 0], 'label': 'Punta'},
              {'gravity': [0, 0, -9.81], 'label': 'Peso'}],
}
SPACE = {'E': [70e9, 210e9], 'nu': [0.25, 0.35], 'load_0': [100, 1000], 'rho': [2700, 7850]}


@pytest.fixture(scope='module')
def built():
    mesh = FEMMesh.generate_cantilever(0.2, 0.01, 0.01, n_along_length=12, order=2)
    b = PODROMBuilder(mesh, SPEC, SPACE, {'n_snapshots': 16, 'n_test': 3})
    rom = b.build()
    return mesh, b, rom


@pytest.mark.parametrize('E,nu', [(210e9, 0.3), (70e9, 0.33), (1e6, 0.45)])
def test_affine_decomposition_of_D(E, nu):
    lam, mu = lame(E, nu)
    D = build_material({'type': 'linear_elastic_isotropic', 'E': E, 'nu': nu}).get_D_matrix()
    assert np.allclose(D, lam * D_LAMBDA + mu * D_MU, rtol=1e-12)


def test_latin_hypercube_strata():
    s = latin_hypercube({'a': [0, 1], 'b': [10, 20]}, 10, seed=3)
    a = np.sort([x['a'] for x in s])
    b = np.sort([(x['b'] - 10) / 10 for x in s])
    for v in (a, b):                                  # exactly one sample per tenth
        assert np.array_equal(np.floor(v * 10), np.arange(10))
    assert latin_hypercube({'a': [0, 1]}, 5, 1) == latin_hypercube({'a': [0, 1]}, 5, 1)


def test_describe_parameters():
    ps = {p['key']: p for p in describe_parameters(SPEC)}
    assert set(ps) == {'E', 'nu', 'load_0', 'load_1', 'rho'}
    assert ps['load_0']['nominal'] == 1000 and ps['load_0']['unit'] == 'N'
    assert ps['load_1']['nominal'] == pytest.approx(9.81)


def test_rom_matches_full_model(built):
    mesh, b, rom = built
    assert 1 <= rom['r'] <= 16
    for v in rom['validation']:
        assert v['error_u'] < 1e-5, v
        assert v['error_max_vm'] < 1e-4, v
    # an explicit point, including gravity through rho
    p = {'E': 100e9, 'nu': 0.27, 'load_0': 300.0, 'rho': 3000.0}
    u_fom = b.full_solve(p)
    ev = evaluate_arrays(rom, b.full_params(p), with_u=True)
    assert np.linalg.norm(ev['u_free'] - u_fom) / np.linalg.norm(u_fom) < 1e-5


def test_rom_linear_in_load_and_inverse_in_E(built):
    _, b, rom = built
    base = b.full_params({'E': 140e9, 'nu': 0.3, 'load_0': 500.0, 'rho': 0.0 + 2700})
    a = evaluate_arrays(rom, base)
    c = evaluate_arrays(rom, {**base, 'E': 70e9})
    assert c['max_displacement_m'] == pytest.approx(2 * a['max_displacement_m'], rel=1e-6)
    assert c['max_von_mises_pa'] == pytest.approx(a['max_von_mises_pa'], rel=1e-6)   # stress independent of E


def test_online_solver_fast_and_flags_range(built, tmp_path):
    _, b, rom = built
    path = tmp_path / 'rom.npz'
    np.savez(path, **{k: v for k, v in rom.items() if k not in ('validation', 'samples', 'build_s')},
             meta_json=np.array(json.dumps({'validation_max_error_u': 1e-6})))
    s = ROMOnlineSolver()
    s.load_rom('x', str(path))
    times = []
    for _ in range(30):
        out = s.evaluate('x', {'E': 150e9, 'load_0': 450})
        times.append(out['response_ms'])
    assert np.median(times) < 100
    assert out['within_range'] and len(out['coefficients']) == rom['r']
    assert out['params']['nu'] == 0.3                 # missing → nominal
    assert not s.evaluate('x', {'E': 300e9})['within_range']
    assert s.get_parameter_ranges('x')['E'] == [70e9, 210e9]


def test_setup_errors():
    mesh = FEMMesh.generate_cantilever(0.05, 0.01, 0.01, n_along_length=4)
    with pytest.raises(ROMError):
        PODROMBuilder(mesh, SPEC, {'thickness': [1, 2]})
    with pytest.raises(ROMError):
        PODROMBuilder(mesh, SPEC, {'E': [2e11, 1e11]})
    with pytest.raises(ROMError):
        PODROMBuilder(mesh, SPEC, {})
    bad = {**SPEC, 'bcs': [{'face_set': 'fixed', 'dofs': [0], 'values': [1e-3]}]}
    with pytest.raises(ROMError):
        PODROMBuilder(mesh, bad, {'E': [1e11, 2e11]}, {'n_snapshots': 2, 'n_test': 0}).build()
