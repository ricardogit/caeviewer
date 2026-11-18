"""FASE 2 FEM validation (no database needed; requires gmsh).

Test 1: axial bar — uniaxial stress is reproduced exactly by T4 and T10.
Test 2: cantilever T4 vs T10 against Timoshenko (shear-corrected beam theory).
        Hito FASE 2: T10 within ±1 % on a slender beam (L/h = 20).
Test 3: stubby beam (L/h = 5): shows the 3D clamp effect (~1-2 % stiffer than
        either beam theory) so the hito is not judged on a case where the
        reference itself is off.

Run: python validate_fem.py
"""
import sys
import time

import numpy as np
import scipy.sparse.linalg as spla

sys.path.insert(0, '.')
from app.design.services.fem.assembler import assemble_F, assemble_K, dirichlet, reduce_system  # noqa: E402
from app.design.services.fem.constitutive import LinearElasticIsotropic  # noqa: E402
from app.design.services.fem.mesh import FEMMesh  # noqa: E402

E, NU, H, P = 210e9, 0.3, 0.010, 1000.0
D = LinearElasticIsotropic(E, NU).get_D_matrix()


def solve(mesh, loads, bcs=None):
    K = assemble_K(mesh, D)
    F = assemble_F(mesh, loads)
    dofs, vals = dirichlet(mesh, bcs or [{'face_set': 'fixed', 'dofs': [0, 1, 2]}])
    Kf, rhs, free = reduce_system(K, F, dofs, vals)
    u = np.zeros(K.shape[0])
    u[free] = spla.spsolve(Kf.tocsc(), rhs)
    return u


def tip_mean(mesh, u, comp):
    return u[comp::3][np.unique(mesh.face_sets['tip'])].mean()


def refs(L):
    I = H ** 4 / 12
    G = E / (2 * (1 + NU))
    k = 10 * (1 + NU) / (12 + 11 * NU)
    eb = P * L ** 3 / (3 * E * I)
    return eb, eb + P * L / (k * G * H * H)


print('\n=== TEST 1: barra a tensión, apoyo isostático (debe ser exacta) ===')
L = 0.05
exact = 1e4 * L / (E * H * H)
for order in (1, 2):
    m = FEMMesh.generate_cantilever(L, H, H, 5, order=order)
    # ux = 0 on the face, plus the minimum to stop rigid motion: no Poisson restraint
    x0 = np.unique(m.face_sets['fixed'])
    m.node_sets['n0'] = x0[[np.argmin(np.linalg.norm(m.nodes[x0], axis=1))]]
    m.node_sets['n1'] = x0[[np.argmax(m.nodes[x0, 1] - m.nodes[x0, 2])]]
    u = solve(m, [{'face_set': 'tip', 'force': [1e4, 0, 0]}],
              [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'n0', 'dofs': [1, 2]},
               {'node_set': 'n1', 'dofs': [2]}])
    ux = tip_mean(m, u, 0)
    print(f'  {m.element_type:>3}: ux = {ux:.6e} m  analítico {exact:.6e}  error {abs(ux - exact) / exact * 100:.4f} %')

ok = True
for title, L, nds in (('TEST 2: viga esbelta L/h = 20 (hito FASE 2: T10 dentro de ±1 % de Timoshenko)', 0.2, (10, 20, 40)),
                      ('TEST 3: viga corta L/h = 5 (efecto 3D del empotramiento)', 0.05, (5, 10, 20))):
    eb, timo = refs(L)
    print(f'\n=== {title} ===')
    print(f'  Euler-Bernoulli {eb * 1e3:.5f} mm   Timoshenko {timo * 1e3:.5f} mm')
    print(f"  {'elem':>4} {'n_div':>5} {'nodos':>7} {'uy [mm]':>10} {'vs EB':>8} {'vs Timo':>8} {'t [s]':>6}")
    for order in (1, 2):
        for nd in nds:
            t0 = time.perf_counter()
            m = FEMMesh.generate_cantilever(L, H, H, nd, order=order)
            uy = -tip_mean(m, solve(m, [{'face_set': 'tip', 'force': [0, -P, 0]}]), 1)
            e_eb, e_ti = (uy - eb) / eb * 100, (uy - timo) / timo * 100
            print(f'  {m.element_type:>4} {nd:>5} {m.n_nodes:>7} {uy * 1e3:>10.5f} {e_eb:>+7.2f}% {e_ti:>+7.2f}% '
                  f'{time.perf_counter() - t0:>6.2f}')
            if L == 0.2 and order == 2 and nd == 20:
                ok = abs(e_ti) < 1.0

print('\n=== RESUMEN FASE 2 ===')
print(f"  Hito (T10, L/h=20, n_div=20, ±1 % vs Timoshenko): {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
print('  T4 bloquea por cortante en flexión; T10 es el elemento por defecto para geometría CAD.')
sys.exit(0 if ok else 1)
