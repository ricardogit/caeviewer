"""Hito: compressible Neo-Hookean hyperelasticity (total Lagrangian, large deformations).

  1. uniaxial tension (λ = 1.5) and compression (λ = 0.7), displacement controlled, free lateral contraction:
     the reaction force equals the exact nominal stress λ₁S₁₁(λ₁, λ₂)·A₀ with λ₂ from S₂₂ = 0 (homogeneous
     deformation, exact for any mesh)
  2. simple shear γ = 0.5 (all boundary nodes prescribed): Cauchy σxy = μγ, σxx = μγ², σyy = σzz = 0
  3. small loads: the same cantilever as the linear kernel (difference ≪ 1 %)
  4. large-deflection cantilever with a dead tip load, α = PL²/EI = 2: tip displacements vs the Euler
     elastica (solved here as a boundary-value problem); the linear solution is far off (shown)
  5. Newton converges quadratically

Usage: python validate_hyperelastic.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time

import numpy as np

E, NU = 10e6, 0.45            # rubber-like (Pa)


def elastica(alpha: float):
    """Cantilever with a dead vertical tip load: EI θ'' = −P cos θ, θ(0) = 0, θ'(1) = 0 (s ∈ [0, 1]).
    Returns (horizontal shortening, vertical deflection) / L."""
    from scipy.integrate import solve_bvp, quad
    s = np.linspace(0, 1, 200)
    sol = solve_bvp(lambda s, y: np.vstack([y[1], -alpha * np.cos(y[0])]),
                    lambda a, b: np.array([a[0], b[1]]), s, np.vstack([0.3 * s, 0.3 * (1 - s)]), tol=1e-10,
                    max_nodes=100000)
    assert sol.success
    dx = 1 - quad(lambda t: np.cos(sol.sol(t)[0]), 0, 1, epsabs=1e-12)[0]
    dy = quad(lambda t: np.sin(sol.sol(t)[0]), 0, 1, epsabs=1e-12)[0]
    return dx, dy


def nh_mat(**kw):
    return {'type': 'hyperelastic_neohookean', 'E': E, 'nu': NU, 'rho': 1100.0, **kw}


def local(check):
    from scipy.optimize import brentq
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.mesh import FEMMesh
    from app.design.services.fem import hyperelastic as he
    from app.design.services.fem import tet_batch as tb
    k = FEMKernel()
    nh = he.NeoHookean(E, NU)
    mu, lm = nh.mu, nh.lam

    print('── 1. Tracción / compresión uniaxial (control de desplazamiento) ───────────')
    L, A = 0.05, 1e-4
    worst = 0.0
    for l1 in (1.5, 0.7):
        m = FEMMesh.generate_cantilever(L, 0.01, 0.01, 4, order=2)
        m.node_sets['p0'] = np.array([int(np.argmin(np.linalg.norm(m.nodes, axis=1)))])
        m.node_sets['p1'] = np.array([int(np.argmin(np.linalg.norm(m.nodes - [0, 0.01, 0], axis=1)))])
        bcs = [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'p0', 'dofs': [1, 2]},
               {'node_set': 'p1', 'dofs': [2]}, {'face_set': 'tip', 'dofs': [0], 'values': [(l1 - 1) * L]}]
        from app.design.services.fem.assembler import dirichlet
        dofs, vals = dirichlet(m, bcs)
        r = he.solve_hyperelastic(m, nh, np.zeros(m.n_dof_structural), dofs, vals, n_steps=5)
        force = float(r['f_int'][3 * m.node_sets['tip']].sum())      # internal force on the pulled face
        l2 = brentq(lambda l2: mu * (1 - 1 / l2 ** 2) + lm * np.log(l1 * l2 * l2) / l2 ** 2, 0.2, 2.0)
        P = l1 * (mu * (1 - 1 / l1 ** 2) + lm * np.log(l1 * l2 * l2) / l1 ** 2) * A
        u = r['u'].reshape(-1, 3)
        top, bot = np.isclose(m.nodes[:, 1], 0.01), np.isclose(m.nodes[:, 1], 0.0)
        l2_fe = 1 + (u[top, 1].mean() - u[bot, 1].mean()) / 0.01
        e = max(abs(force / P - 1), abs(l2_fe / l2 - 1))
        worst = max(worst, e)
        print(f'   λ₁ = {l1}: fuerza {force:9.3f} N (exacta {P:9.3f})  λ₂ = {l2_fe:.6f} '
              f'(exacta {l2:.6f})  {r["info"]["n_iterations"]} it.')
    check(worst < 1e-7, f'fuerza y contracción lateral exactas (error máx {worst:.1e})')

    print('── 2. Cizalla simple γ = 0.5 ───────────────────────────────────────────────')
    m = FEMMesh.generate_cantilever(0.01, 0.01, 0.01, 3, order=2)
    gam = 0.5
    bnd = np.unique(tb.boundary_faces(m.elements))
    dofs = np.sort(np.concatenate([3 * bnd, 3 * bnd + 1, 3 * bnd + 2]))
    target = np.zeros((m.n_nodes, 3))
    target[:, 0] = gam * m.nodes[:, 1]
    vals = target.ravel()[dofs]
    r = he.solve_hyperelastic(m, nh, np.zeros(m.n_dof_structural), dofs, vals, n_steps=4)
    sig = he.cauchy(r['F_gp'].reshape(-1, 3, 3), r['S_gp'].reshape(-1, 3, 3))
    exp = np.array([mu * gam ** 2, 0, 0, mu * gam, 0, 0])
    e = float(np.abs(sig - exp).max() / (mu * gam))
    print(f'   σxy = {sig[:, 3].mean():.6e} Pa (μγ = {mu * gam:.6e});  σxx = {sig[:, 0].mean():.6e} (μγ² = {mu * gam ** 2:.6e})')
    check(e < 1e-9, f'tensiones de Cauchy exactas en todos los puntos de Gauss (error {e:.1e})')

    print('── 3. Cargas pequeñas = elasticidad lineal ────────────────────────────────')
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.2, 'width': 0.01, 'height': 0.01, 'n_along_length': 20, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}]}
    Psmall = 1e-3
    lin = k._solve(None, {**spec, 'loads': [{'face_set': 'tip', 'force': [0, -Psmall, 0]}],
                          'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': NU}}, None)
    nl = k._solve(None, {**spec, 'loads': [{'face_set': 'tip', 'force': [0, -Psmall, 0]}], 'material': nh_mat(),
                         'n_load_steps': 1}, None)
    d = abs(nl['summary']['max_displacement_m'] / lin['summary']['max_displacement_m'] - 1)
    check(d < 1e-3, f'flecha con carga pequeña: diferencia {100 * d:.4f} % frente al kernel lineal')

    print('── 4. Voladizo con gran flecha (carga muerta, α = PL²/EI = 2) vs elástica ─')
    Lb, h = 0.5, 0.01
    I = h ** 4 / 12
    alpha = 2.0
    P = alpha * E * I / Lb ** 2
    dx, dy = elastica(alpha)
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': Lb, 'width': h, 'height': h, 'n_along_length': 50, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -P, 0]}]}
    t0 = time.perf_counter()
    r = k._solve(None, {**spec, 'material': nh_mat(nu=0.0), 'n_load_steps': 10}, None)
    t = time.perf_counter() - t0
    mm = r['mesh']
    u = np.asarray(r['displacement'])[mm.node_sets['tip']].mean(axis=0)
    lin = k._solve(None, {**spec, 'material': {'type': 'linear_elastic_isotropic', 'E': E, 'nu': 0.0}}, None)
    ul = np.asarray(lin['displacement'])[lin['mesh'].node_sets['tip']].mean(axis=0)
    ey, ex = -u[1] / Lb / dy - 1, -u[0] / Lb / dx - 1
    print(f'   flecha  v/L = {-u[1] / Lb:.4f}  elástica {dy:.4f} ({100 * ey:+.2f} %)   lineal {-ul[1] / Lb:.4f}')
    print(f'   acortamiento Δx/L = {-u[0] / Lb:.4f}  elástica {dx:.4f} ({100 * ex:+.2f} %)   lineal {-ul[0] / Lb:.4f}')
    print(f'   {r["summary"]["hyperelastic"]["n_steps"]} pasos, {r["summary"]["n_iterations"]} iteraciones, '
          f'ε Green máx {r["summary"]["hyperelastic"]["max_green_strain"]:.3f}, {t:.1f} s')
    check(abs(ey) < 0.01 and abs(ex) < 0.02, 'flecha ±1 % y acortamiento ±2 % de la elástica de Euler')
    check(r['summary']['equilibrium_error'] < 1e-6, f"equilibrio reacción/carga {r['summary']['equilibrium_error']:.1e}")

    print('── 5. Convergencia de Newton ───────────────────────────────────────────────')
    log = r['solve_info']['convergence_log']
    last = max(e['step'] for e in log)
    res = [e['residual'] for e in log if e['step'] == last]
    rates = [np.log(res[i + 1]) / np.log(res[i]) for i in range(len(res) - 1) if 1e-14 < res[i] < 0.1]
    print('   último paso: ' + ' → '.join(f'{x:.1e}' for x in res))
    check(rates and max(rates) > 1.7, f'orden de convergencia ≈ {max(rates) if rates else 0:.2f} (cuadrático = 2)')


def server(check, S):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO Neo-Hookean', 'tier': 1,
                                       'description': 'validate_hyperelastic.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        Lb, h, alpha = 0.5, 0.01, 2.0
        P = alpha * E * (h ** 4 / 12) / Lb ** 2
        geo = add('GEOMETRY', 'Viga 500×10×10', {'shape': 'beam', 'length_mm': 500, 'width_mm': 10, 'height_mm': 10,
                                                  'n_div': 50, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Caucho', {'model_type': 'hyperelastic_neohookean', 'E': E, 'nu': 0.0, 'rho': 1100,
                                          'load_steps': 10})
        bc = add('BC', 'Empotramiento', {'bc_type': 'fixed'})
        ld = add('LOAD', 'Carga', {'load_type': 'force', 'magnitude': P, 'unit': 'N', 'dir_x': 0, 'dir_y': -1, 'dir_z': 0})
        for s, t, kind in ((mat, geo, 'CONSTRAINS_MATERIAL'), (bc, geo, 'CONSTRAINS_BC'), (ld, geo, 'APPLIED_TO')):
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        pf = requests.get(f'{V}/{gid}/preflight').json()
        check('Neo-Hookean' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        rom = requests.post(f'{S}/api/design/rom/{gid}/build', json={})
        check(rom.status_code == 422, f'ROM rechaza el material no lineal → {rom.status_code}')
        r = requests.post(f'{V}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 600:
            st = requests.get(f'{V}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run: {st.get('status')} {st.get('error') or ''} "
                                          f'({time.perf_counter() - t0:.1f} s)')
        if st.get('status') == 'done':
            runs = requests.get(f'{V}/runs', params={'graph_id': gid}).json()
            runs = {x['run_id']: x for x in (runs.get('runs') if isinstance(runs, dict) else runs)}
            umax = runs[rid]['max_displacement_mm'] / 1000
            dx, dy = elastica(alpha)
            ref = Lb * np.hypot(dx, dy)
            check(abs(umax / ref - 1) < 0.02, f'|u| máx {umax * 1000:.1f} mm vs elástica {ref * 1000:.1f} mm')
            surf = requests.get(f'{V}/{rid}/surface')
            check(surf.ok and len(surf.content) > 1000, f'pack de superficie ({len(surf.content):,} B)')
    finally:
        requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)

    if args.server:
        server(check, args.server.rstrip('/'))
    else:
        import logging
        logging.disable(logging.WARNING)
        local(check)
    print(f"\nHito Neo-Hookean{' vía servidor' if args.server else ''}: {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
