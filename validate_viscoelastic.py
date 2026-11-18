"""Hito: linear viscoelasticity, generalized Maxwell (Prony series), quasi-static time stepping.

  1. relaxation (strain step held, 2 Prony terms): σ(t)/ε₀ = E(t) = E₀[g∞ + Σgᵢe^{−t/τᵢ}] — exact
  2. creep of the standard linear solid (1 term) under a constant stress: ε(t) = σ₀J(t),
     J(t) = 1/E∞ − (1/E∞ − 1/E₀) e^{−t/τc}, τc = τE₀/E∞; error O(Δt²) (halving Δt divides it by ≈ 4)
  3. creep and recovery (load removed at t₁): ε(t) = σ₀[J(t) − J(t − t₁)]
  4. cantilever under a constant tip load (correspondence principle, ν constant): u(t) = u_el(E₀)·E₀J(t)

Usage: python validate_viscoelastic.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time

import numpy as np

E0, NU = 3e9, 0.35                       # polymer-like (Pa)
SLS = [{'g': 0.5, 'tau': 5.0}]           # E∞ = E₀/2, τ = 5 s


def creep_J(t, E0=E0, terms=SLS):
    g = terms[0]['g']
    Einf = E0 * (1 - g)
    tc = terms[0]['tau'] * E0 / Einf
    t = np.asarray(t, float)
    return np.where(t >= 0, 1 / Einf - (1 / Einf - 1 / E0) * np.exp(-np.maximum(t, 0) / tc), 0.0)


def bar(L=0.05, order=2):
    from app.design.services.fem.mesh import FEMMesh
    m = FEMMesh.generate_cantilever(L, 0.01, 0.01, 4, order=order)
    m.node_sets['p0'] = np.array([int(np.argmin(np.linalg.norm(m.nodes, axis=1)))])
    m.node_sets['p1'] = np.array([int(np.argmin(np.linalg.norm(m.nodes - [0, 0.01, 0], axis=1)))])
    return m


BASE_BCS = [{'face_set': 'fixed', 'dofs': [0]}, {'node_set': 'p0', 'dofs': [1, 2]}, {'node_set': 'p1', 'dofs': [2]}]


def local(check):
    from app.design.services.fem.viscoelastic import PronySeries, solve_viscoelastic
    from app.design.services.fem.assembler import dirichlet, assemble_K, assemble_F
    from app.design.services.fem.constitutive import LinearElasticIsotropic
    from app.design.services.fem.kernel import FEMKernel
    D0 = LinearElasticIsotropic(E0, NU).get_D_matrix()
    L, A = 0.05, 1e-4

    print('── 1. Relajación (escalón de deformación mantenido, 2 términos de Prony) ───')
    pr = PronySeries(E0, NU, [{'g': 0.4, 'tau': 2.0}, {'g': 0.3, 'tau': 20.0}])
    m = bar()
    K0 = assemble_K(m, D0)
    eps0 = 1e-3
    dofs, vals = dirichlet(m, BASE_BCS + [{'face_set': 'tip', 'dofs': [0], 'values': [eps0 * L]}])
    worst = 0.0
    for t_end in (0.5, 2.0, 10.0, 60.0, 300.0):
        r = solve_viscoelastic(m, pr, D0, K0, np.zeros(m.n_dof_structural), dofs, vals, [[0, 1], [t_end, 1]],
                               t_end, 10)
        Et = r['f_int'][3 * m.node_sets['tip']].sum() / A / eps0
        ex = E0 * float(pr.relaxation(t_end))
        worst = max(worst, abs(Et / ex - 1))
        print(f'   t = {t_end:6.1f} s: E(t) = {Et / 1e9:.6f} GPa  (exacto {ex / 1e9:.6f})')
    check(worst < 1e-9, f'módulo de relajación exacto (error máx {worst:.1e})')

    print('── 2. Fluencia del sólido lineal estándar (σ₀ constante) ──────────────────')
    pr1 = PronySeries(E0, NU, SLS)
    dofs, vals = dirichlet(m, BASE_BCS)
    F = assemble_F(m, [{'face_set': 'tip', 'force': [100.0, 0, 0]}], [])
    s0 = 100.0 / A
    errs = []
    for n in (10, 20, 40, 80):
        r = solve_viscoelastic(m, pr1, D0, K0, F, dofs, vals, [[0, 1], [30, 1]], 30, n)
        eps = r['u'].reshape(-1, 3)[m.node_sets['tip'], 0].mean() / L
        errs.append(abs(eps / (s0 * creep_J(30.0)) - 1))
        print(f'   Δt = {30 / n:5.3f} s: ε(30 s) = {eps:.7e}  exacto {s0 * creep_J(30.0):.7e}  error {errs[-1]:.2e}')
    rates = [np.log2(errs[i] / errs[i + 1]) for i in range(len(errs) - 1)]
    check(min(rates) > 1.9 and errs[-1] < 2e-5, f"orden temporal {' '.join(f'{x:.2f}' for x in rates)} (2 = O(Δt²))")

    print('── 3. Fluencia y recuperación (carga retirada en t₁ = 15 s) ───────────────')
    r = solve_viscoelastic(m, pr1, D0, K0, F, dofs, vals, [[0, 1], [15, 1], [15, 0], [40, 0]], 40, 160)
    # reconstruct ε(t) from the max displacement curve (uniform field: max |u| ∝ tip axial strain)
    t = np.array([c['time_s'] for c in r['curve']])
    lam = np.array([c['load_factor'] for c in r['curve']])
    eps_end = r['u'].reshape(-1, 3)[m.node_sets['tip'], 0].mean() / L
    exact_end = s0 * (creep_J(40.0) - creep_J(25.0))
    e3 = abs(eps_end / exact_end - 1)
    print(f'   ε(40 s) = {eps_end:.6e}  exacto {exact_end:.6e}  ({100 * e3:.3f} %); deformación residual '
          f'{100 * eps_end / (s0 * creep_J(15.0)):.1f} % de la de t₁')
    check(e3 < 1e-3 and lam[-1] == 0 and len(t) > 160, f'recuperación tras descarga (error {100 * e3:.3f} %)')

    print('── 4. Voladizo con carga constante (principio de correspondencia) ─────────')
    spec = {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 1,
            'mesh_params': {'length': 0.2, 'width': 0.01, 'height': 0.01, 'n_along_length': 20, 'order': 2},
            'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}], 'loads': [{'face_set': 'tip', 'force': [0, -10, 0]}]}
    k = FEMKernel()
    t0 = time.perf_counter()
    rv = k._solve(None, {**spec, 'material': {'type': 'viscoelastic_maxwell', 'E': E0, 'nu': NU, 'prony': SLS},
                         'time': {'t_end': 60.0, 'n_steps': 120}}, None)
    tv = time.perf_counter() - t0
    rl = k._solve(None, {**spec, 'material': {'type': 'linear_elastic_isotropic', 'E': E0, 'nu': NU}}, None)
    u_el = rl['summary']['max_displacement_m']
    curve = rv['summary']['viscoelastic']['curve']
    errs = [abs(c['max_displacement_m'] / (u_el * E0 * float(creep_J(c['time_s']))) - 1) for c in curve]
    print(f"   t = 0: {curve[0]['max_displacement_m'] * 1e3:.4f} mm (elástico E₀ {u_el * 1e3:.4f}); t = 60 s: "
          f"{curve[-1]['max_displacement_m'] * 1e3:.4f} mm (teoría {u_el * E0 * float(creep_J(60.0)) * 1e3:.4f}); "
          f"{len(curve)} pasos, {tv:.1f} s")
    check(max(errs) < 2e-4, f'flecha en todos los instantes (error máx {100 * max(errs):.4f} %)')
    check(rv['summary']['equilibrium_error'] < 1e-8, f"equilibrio final {rv['summary']['equilibrium_error']:.1e}")


def server(check, S):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO viscoelástico', 'tier': 1,
                                       'description': 'validate_viscoelastic.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Viga 200×10×10', {'shape': 'beam', 'length_mm': 200, 'width_mm': 10, 'height_mm': 10,
                                                  'n_div': 20, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Polímero', {'model_type': 'viscoelastic_maxwell', 'E': E0, 'nu': NU, 'rho': 1200,
                                            'prony_terms': SLS, 't_end': 60, 'time_steps': 120,
                                            'load_history': 'creep'})
        bc = add('BC', 'Empotramiento', {'bc_type': 'fixed'})
        ld = add('LOAD', 'Carga', {'load_type': 'force', 'magnitude': 10, 'unit': 'N', 'dir_x': 0, 'dir_y': -1, 'dir_z': 0})
        for s, t, kind in ((mat, geo, 'CONSTRAINS_MATERIAL'), (bc, geo, 'CONSTRAINS_BC'), (ld, geo, 'APPLIED_TO')):
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        pf = requests.get(f'{V}/{gid}/preflight').json()
        check('viscoelástico' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        bad = requests.put(f'{G}/{gid}/nodes/{mat}', json={'properties': {
            'model_type': 'viscoelastic_maxwell', 'E': E0, 'nu': NU, 'prony_terms': [{'g': 1.2, 'tau': 5}]}})
        pf2 = requests.post(f'{V}/{gid}/run', json={})
        check(pf2.status_code == 422, f'Σg ≥ 1 rechazado → {pf2.status_code}')
        requests.put(f'{G}/{gid}/nodes/{mat}', json={'properties': {
            'model_type': 'viscoelastic_maxwell', 'E': E0, 'nu': NU, 'rho': 1200, 'prony_terms': SLS, 't_end': 60,
            'time_steps': 120, 'load_history': 'creep'}})
        _ = bad
        r = requests.post(f'{V}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 600:
            st = requests.get(f'{V}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run: {st.get('status')} {st.get('error') or ''} ({time.perf_counter() - t0:.1f} s)")
        if st.get('status') == 'done':
            rep = requests.get(f'{V}/{rid}/report', params={'format': 'jsonld'}).json()
            txt = str(rep)
            ratio_th = float(creep_J(60.0)) * E0
            check('creep_ratio' in txt or 'viscoelastic' in txt, 'el informe incluye el resumen viscoelástico')
            runs = requests.get(f'{V}/runs', params={'graph_id': gid}).json()
            runs = {x['run_id']: x for x in (runs.get('runs') if isinstance(runs, dict) else runs)}
            print(f"   |u| máx final {runs[rid]['max_displacement_mm']:.4f} mm; fluencia teórica ×{ratio_th:.4f}")
            rep2 = requests.post(f'{V}/{rid}/reproduce', json={'force': True}).json()
            t2, rs = time.perf_counter(), {}
            while rep2.get('run_id') and time.perf_counter() - t2 < 600:
                rs = requests.get(f"{V}/{rep2['run_id']}/status").json()
                if rs.get('status') in ('done', 'failed', 'cancelled'):
                    break
                time.sleep(1)
            check(rs.get('result_hash') == st.get('result_hash'), 'reproducción bit a bit (mismo hash de resultado)')
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
    print(f"\nHito viscoelasticidad{' vía servidor' if args.server else ''}: {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
