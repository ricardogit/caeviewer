"""FASE 3 hito — adaptive meshing (ZZ/SPR estimator + Dörfler marking + conforming T10 bisection).

Plan: "la viga anterior (FASE 2) con refinamiento adaptativo converge en ≤ 3 ciclos". The beam is the FASE 2
cantilever (L/h = 20, 200 × 10 × 10 mm, steel, clamped, 1 kN at the tip), T10. The error is the relative
energy-norm error ‖u − u_h‖_E / ‖u‖_E; its estimate comes from SPR recovery.

The true error needs the exact energy U = Fᵀu (the clamp has a 3-D edge singularity, no closed form): a long
adaptive run is extrapolated with U(N) = U∞ − C·N^(−a) (energy-norm error² = (U∞ − U_h)/U∞ for this
problem, Galerkin orthogonality with homogeneous Dirichlet BCs).

  1. plan: from a coarse beam (n_div = 10, estimate ≈ 6 %) the loop reaches estimate < 5 % in ≤ 3 cycles
  2. the estimator is reliable: effectivity (estimate / true error) in 0.6–1.5 on every cycle, and
     0.8–1.25 on the finest one (it tends to 1)
  3. adaptivity pays: energy convergence rate a ≥ 1.1 (optimal for T10: 4/3) and more than twice the uniform
     refinement rate (the clamp singularity slows uniform refinement down)
  4. for the accuracy of the uniform n_div = 80 mesh the adaptive mesh needs ≥ 5× fewer DOF

Measured (2026-11-14, ~2 min): coarse start estimate 6.05 → 5.62 → 4.80 % in 3 cycles, but the true error is
8.6 → 7.0 → 6.5 %: on coarse meshes the estimate is optimistic (effectivity 0.70–0.77; it reaches ~1 above
~15K DOF). For a guaranteed true 5 % ask ~3.5 %. Energy rate a ≈ 1.3–1.4 vs uniform 0.41; the accuracy of
uniform n_div 80 (37.6K DOF, 2.46 %) is reached by the adaptive mesh at 5.5K DOF (6.8× fewer).

--server URL: the same through the API and the job queue (study with a parametric beam, POST run-adaptive,
one adaptive_log entry per cycle, final estimate below the target, surface pack of the refined mesh,
reproduction gives the same result hash bit for bit).

Usage: python validate_adaptive.py [--server http://127.0.0.1:8080] [--keep]
"""
import argparse
import sys
import time

import numpy as np

L, W, H, P = 0.2, 0.01, 0.01, 1000.0
MAT = {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800.0}


def beam_spec(n_div):
    return {'physics': ['structural'], 'mesh_source': 'cantilever', 'tier': 2,
            'mesh_params': {'length': L, 'width': W, 'height': H, 'n_along_length': n_div, 'order': 2},
            'material': MAT, 'bcs': [{'face_set': 'fixed', 'dofs': [0, 1, 2]}],
            'loads': [{'face_set': 'tip', 'force': [0, -P, 0]}]}


def local(check):
    from scipy.optimize import curve_fit
    from app.design.services.fem.kernel import FEMKernel
    k = FEMKernel()

    def run(n_div, target, cycles, quiet=False):
        def show(e):
            if not quiet:
                print(f"   ciclo {e['cycle']}: {e['n_dof']:>7,} DOF  error estimado {100 * e['global_error']:5.2f} %"
                      f"  ({e['wall_time_s']:.1f} s)", flush=True)
        return k.solve_adaptive(beam_spec(n_div), {'target_error': target, 'max_cycles': cycles, 'theta': 0.5},
                                progress=show)

    print('── Referencia: adaptativo largo desde n_div = 20, extrapolado ─────────────')
    t0 = time.perf_counter()
    long_log = run(20, 0.004, 13)['adaptive_log']
    N = np.array([e['n_dof'] for e in long_log], float)
    U = np.array([e['solution_energy'] for e in long_log])
    (U_inf, C, a), _ = curve_fit(lambda n, u, c, a: u - c * n ** (-a), N[-5:], U[-5:], p0=(U[-1] * 1.0002, 10, 1.0),
                                 maxfev=20000)
    print(f'   U∞ = {U_inf:.7f} J   tasa adaptativa a = {a:.3f} (óptima T10: 4/3)   ({time.perf_counter() - t0:.0f} s)')
    true = lambda u: float(np.sqrt(max(U_inf - u, 0.0) / U_inf))   # noqa: E731

    print('── 1. Plan: viga gruesa (n_div = 10), objetivo 5 % ───────────────────────')
    r = run(10, 0.05, 6)
    log = r['adaptive_log']
    for e in log:
        print(f"   ciclo {e['cycle']}: error real {100 * true(e['solution_energy']):5.2f} %")
    check(r['summary']['adaptive']['converged'] and len(log) <= 3,
          f"estimado < 5 % en {len(log)} ciclos (≤ 3); error real final {100 * true(log[-1]['solution_energy']):.2f} %")

    print('── 2. Fiabilidad del estimador (efectividad = estimado / real) ───────────')
    eff = [e['global_error'] / true(e['solution_energy']) for e in long_log[:-1]]   # last point anchors the fit
    print('   ' + ' '.join(f'{x:.2f}' for x in eff))
    check(all(0.6 <= x <= 1.5 for x in eff), f'todas en 0.6–1.5 (mín {min(eff):.2f}, máx {max(eff):.2f})')
    check(0.8 <= eff[-1] <= 1.25, f'malla más fina: {eff[-1]:.2f} (0.8–1.25)')

    print('── 3–4. Uniforme vs adaptativo ───────────────────────────────────────────')
    from app.design.services.fem.constitutive import build_material
    from app.design.services.fem.error_estimator import zz_estimate
    D = build_material(MAT).get_D_matrix()
    uniform = []
    for nd in (20, 40, 80):
        res = k._solve(None, beam_spec(nd), None)
        m = res['mesh']
        Uh = zz_estimate(m.nodes, m.elements, np.asarray(res['displacement']).ravel(), D)['solution_energy']
        uniform.append((m.n_dof_structural, Uh))
        print(f'   uniforme n_div {nd:>3}: {m.n_dof_structural:>7,} DOF  error real {100 * true(Uh):5.2f} %', flush=True)
    (n1, u1), (n2, u2) = uniform[-2], uniform[-1]
    a_uni = np.log((U_inf - u1) / (U_inf - u2)) / np.log(n2 / n1)
    check(a >= 1.1 and a > 2 * a_uni, f'tasa de energía: adaptativo {a:.2f} vs uniforme {a_uni:.2f}')
    e80 = true(u2)
    hit = next((e['n_dof'] for e in long_log if true(e['solution_energy']) <= e80), None)
    check(hit is not None and hit * 5 <= n2,
          f'precisión de n_div = 80 ({100 * e80:.2f} %, {n2:,} DOF): adaptativo con {hit:,} DOF '
          f'({n2 / hit:.1f}× menos)' if hit else 'el adaptativo no alcanzó la precisión uniforme')


def server(check, S, keep, timeout):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    g = requests.post(f'{G}/', json={'name': 'HITO F3 adaptativo', 'tier': 1, 'description': 'validate_adaptive.py'}).json()
    gid = g['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Viga 200×10×10', {'shape': 'beam', 'length_mm': 200, 'width_mm': 10, 'height_mm': 10,
                                                  'n_div': 10, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Acero', {'model_type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800})
        bc = add('BC', 'Empotramiento', {'bc_type': 'fixed'})
        ld = add('LOAD', 'Carga', {'load_type': 'force', 'magnitude': P, 'unit': 'N', 'dir_x': 0, 'dir_y': -1, 'dir_z': 0})
        for s, t, kind in ((mat, geo, 'CONSTRAINS_MATERIAL'), (bc, geo, 'CONSTRAINS_BC'), (ld, geo, 'APPLIED_TO')):
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        bad = requests.post(f'{V}/{gid}/run-adaptive', json={'max_cycles': 99})
        check(bad.status_code == 422, f'ajustes fuera de rango → {bad.status_code}')
        r = requests.post(f'{V}/{gid}/run-adaptive', json={'target_error': 0.05, 'max_cycles': 5})
        check(r.status_code == 202, f'POST run-adaptive → {r.status_code}')
        run_id = r.json().get('run_id')
        t1, status = time.perf_counter(), 'queued'
        while run_id and time.perf_counter() - t1 < timeout:
            status = requests.get(f'{V}/{run_id}/status').json().get('status')
            if status in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(status == 'done', f'run {str(run_id)[:8]}: {status} en {time.perf_counter() - t1:.1f} s (worker)')
        if status == 'done':
            run = requests.get(f'{V}/{run_id}/status').json()
            log = run.get('adaptive_log') or []
            summ = run.get('adaptive') or {}
            for e in log:
                print(f"   ciclo {e['cycle']}: {e['n_dof']:,} DOF  error estimado {100 * e['global_error']:.2f} %")
            check(run.get('purpose') == 'adaptive' and len(log) >= 2 and summ.get('converged')
                  and log[-1]['global_error'] < 0.05, f"{len(log)} ciclos, final {100 * summ.get('final_error', 1):.2f} %")
            surf = requests.get(f'{V}/{run_id}/surface')
            check(surf.ok and len(surf.content) > 1000, f'pack de superficie de la malla refinada ({len(surf.content):,} B)')
            rep = requests.post(f'{V}/{run_id}/reproduce', json={'force': True}).json()
            t2, rs = time.perf_counter(), {}
            while rep.get('run_id') and time.perf_counter() - t2 < timeout:
                rs = requests.get(f"{V}/{rep['run_id']}/status").json()
                if rs.get('status') in ('done', 'failed', 'cancelled'):
                    break
                time.sleep(1)
            check(rs.get('status') == 'done' and rs.get('result_hash') == run.get('result_hash')
                  and len(rs.get('adaptive_log') or []) == len(log),
                  f"reproducción: mismo hash de resultado bit a bit ({str(rs.get('result_hash'))[:12]})")
    finally:
        if keep:
            print(f'Estudio conservado: {gid}')
        else:
            requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--timeout', type=float, default=300)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)

    if args.server:
        server(check, args.server.rstrip('/'), args.keep, args.timeout)
    else:
        import logging
        logging.disable(logging.WARNING)
        local(check)
    print(f"\nHito FASE 3 (mallado adaptativo{' vía servidor' if args.server else ''}): "
          f"{'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
