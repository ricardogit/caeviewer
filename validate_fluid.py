"""Hito: steady Stokes flow of a Newtonian fluid (Taylor-Hood P2-P1 on T10).

  1. plane Poiseuille (pressure-driven, walls z = 0, H; slip side walls): parabolic profile, flow rate, linear
     pressure and wall force Δp·A exact (P2/P1 contain the solution)
  2. Couette (moving top wall, open ends at p = 0): linear profile and wall shear force μU/H·A exact
  3. hydrostatics in a closed box (gravity, all walls no-slip, pressure pinned): v = 0, ∇p = ρg exact
  4. square duct (no-slip on four walls) vs the series solution: error and convergence order with refinement
  5. mass balance: net flow through the whole boundary = 0 (div-free in the P1-weak sense)

Usage: python validate_fluid.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time
from math import pi, tanh

import numpy as np

MU = 1.41          # glycerine [Pa·s] → Re ≪ 1 for these sizes
RHO = 1261.0


def channel(L, W, H, n):
    from app.design.services.fem.mesh import FEMMesh
    return FEMMesh.generate_cantilever(L, W, H, n, order=2)


def solve(m, bcs, loads, mu=MU, rho=RHO):
    from app.design.services.fem.kernel import FEMKernel
    return FEMKernel()._solve(None, {'tier': 1, 'material': {'type': 'newtonian_fluid', 'mu': mu, 'rho': rho},
                                     'bcs': bcs, 'loads': loads}, None, mesh=m)


ENDS = [{'face_set': 'fixed', 'dofs': [1, 2]}, {'face_set': 'tip', 'dofs': [1, 2]}]   # fully developed in/out


def duct_flow(a, b, dpdx, mu):
    """Rectangle −a<y<a, −b<z<b (a ≥ b): Q = 4ab³/(3μ)·G·[1 − 192b/(π⁵a) Σ tanh(nπa/2b)/n⁵] (White)."""
    s = sum(tanh(k * pi * a / (2 * b)) / k ** 5 for k in range(1, 400, 2))
    return 4 * a * b ** 3 / (3 * mu) * dpdx * (1 - 192 * b / (pi ** 5 * a) * s)


def flow(r, face):
    return next(f['flow_m3_s'] for f in r['summary']['fluid']['flow_rates'] if f['face_set'] == face)


def local(check):
    L, W, H, dp = 4e-3, 2e-3, 1e-3, 100.0

    print('── 1. Poiseuille plano ─────────────────────────────────────────────────')
    m = channel(L, W, H, 8)
    r = solve(m, [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
                  {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}] + ENDS,
              [{'face_set': 'fixed', 'pressure': dp}])
    v, p = r['velocity'], r['pressure']
    z, x = m.nodes[:, 2], m.nodes[:, 0]
    u_th = dp / (2 * MU * L) * z * (H - z)
    Q_th = dp * W * H ** 3 / (12 * MU * L)
    f = r['summary']['fluid']
    errs = [np.abs(v[:, 0] - u_th).max() / u_th.max(), np.abs(v[:, 1:]).max() / u_th.max(),
            abs(flow(r, 'tip') / Q_th - 1), np.abs(p - dp * (1 - x / L)).max() / dp,
            abs(f['wall_force_N'][0] / (dp * W * H) - 1)]
    print(f'   Q = {flow(r, "tip"):.6e} m³/s (teoría {Q_th:.6e}); u máx {v[:, 0].max() * 1e3:.5f} mm/s; '
          f'F pared {f["wall_force_N"][0]:.4e} N (Δp·A {dp * W * H:.4e})')
    check(max(errs) < 1e-8, f'perfil, caudal, presión lineal y fuerza en paredes exactos (error {max(errs):.1e})')

    print('── 2. Couette (pared superior móvil) ───────────────────────────────────')
    U = 1e-3
    m = channel(L, W, H, 8)
    r = solve(m, [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2], 'values': [U, 0, 0]},
                  {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}] + ENDS, [])
    v = r['velocity']
    z = m.nodes[:, 2]
    e_u = np.abs(v[:, 0] - U * z / H).max() / U
    Fw = r['summary']['fluid']['wall_force_N'][0]           # net on both walls = 0; check the shear on z0
    from app.design.services.fem.assembler import dirichlet
    from app.design.services.fem import stokes as st
    dofs, vals = dirichlet(m, [{'face_set': 'z0', 'dofs': [0, 1, 2]},
                               {'face_set': 'z1', 'dofs': [0, 1, 2], 'values': [U, 0, 0]},
                               {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]}] + ENDS)
    _, _, info = st.solve(m, st.FluidMaterial({'mu': MU}), np.zeros(3 * m.n_nodes), dofs, vals)
    R = info['reaction']
    z0 = np.unique(m.face_sets['z0'])
    tau = -R[3 * np.asarray(z0)].sum()                       # force of the fluid on the bottom wall (x)
    e_t = abs(tau / (MU * U / H * L * W) - 1)
    print(f'   u lineal (error {e_u:.1e}); fuerza sobre la pared inferior {tau:.6e} N (μU/H·A {MU * U / H * L * W:.6e}); '
          f'neta {Fw:.1e} N')
    check(max(e_u, e_t) < 1e-8, f'perfil lineal y tensión de pared exactos (error {max(e_u, e_t):.1e})')

    print('── 3. Hidrostática (caja cerrada con gravedad) ─────────────────────────')
    m = channel(2e-3, 2e-3, 2e-3, 4)
    r = solve(m, [{'face_set': '@all', 'dofs': [0, 1, 2]}], [{'gravity': [0, 0, -9.81]}])
    v, p = r['velocity'], r['pressure']
    z = m.nodes[:, 2]
    p_th = RHO * 9.81 * (z.max() - z)
    dpn = p - p_th
    e_h = (np.abs(dpn - dpn.mean()).max()) / p_th.max()
    print(f'   |v| máx {np.abs(v).max():.1e} m/s; presión pinned = {r["summary"]["fluid"]["pressure_pinned"]}; '
          f'p − ρg(z₀−z) constante (error {e_h:.1e})')
    check(r['summary']['fluid']['pressure_pinned'] and np.abs(v).max() < 1e-12 and e_h < 1e-8,
          'reposo exacto con presión hidrostática')

    print('── 4. Conducto cuadrado (serie de Fourier) ─────────────────────────────')
    a = 0.5e-3
    Ld = 4e-3
    Q_th = duct_flow(a, a, dp / Ld, MU)
    errs, sizes = [], []
    for n in (8, 16, 24):
        m = channel(Ld, 2 * a, 2 * a, n)
        t0 = time.perf_counter()
        r = solve(m, [{'face_set': s, 'dofs': [0, 1, 2]} for s in ('y0', 'y1', 'z0', 'z1')] + ENDS,
                  [{'face_set': 'fixed', 'pressure': dp}])
        e = flow(r, 'tip') / Q_th - 1
        errs.append(abs(e))
        sizes.append(Ld / n)
        bal = r['summary']['fluid']['mass_balance_error']
        print(f'   h = {Ld / n * 1e3:.3f} mm: Q error {100 * e:+.3f} %  ({r["summary"]["n_dof"]:,} incógnitas, '
              f'{time.perf_counter() - t0:.1f} s, balance de masa {bal:.1e})')
    rate = np.log(errs[1] / errs[2]) / np.log(sizes[1] / sizes[2])
    check(errs[-1] < 0.005, f'caudal dentro del 0.5 % ({100 * errs[-1]:.3f} %)')
    check(rate > 2.5, f'orden de convergencia del caudal {rate:.2f} (P2: ≥ 3 esperado)')
    check(bal < 1e-10, f'balance de masa por toda la frontera {bal:.1e}')


def server(check, S):
    import json
    import struct
    import requests
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO fluido', 'tier': 1, 'description': 'validate_fluid.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    L, W, H, dp = 4e-3, 2e-3, 1e-3, 100.0
    try:
        geo = add('GEOMETRY', 'Canal 4×2×1', {'shape': 'beam', 'length_mm': 4, 'width_mm': 2, 'height_mm': 1,
                                               'n_div': 8, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Glicerina', {'model_type': 'newtonian_fluid', 'mu': MU, 'rho': RHO})
        bcs = [add('BC', 'Pared inf.', {'bc_type': 'fixed', 'face_set': 'z0'}),
               add('BC', 'Pared sup.', {'bc_type': 'fixed', 'face_set': 'z1'}),
               add('BC', 'Lateral y0', {'bc_type': 'roller_y', 'face_set': 'y0'}),
               add('BC', 'Lateral y1', {'bc_type': 'roller_y', 'face_set': 'y1'}),
               add('BC', 'Entrada', {'bc_type': 'roller_y', 'dofs': [1, 2], 'face_set': 'fixed'}),
               add('BC', 'Salida', {'bc_type': 'roller_y', 'dofs': [1, 2], 'face_set': 'tip'})]
        ld = add('LOAD', 'Presión de entrada', {'load_type': 'pressure', 'magnitude': dp, 'unit': 'Pa',
                                                'face_set': 'fixed'})
        edges = [(mat, geo, 'CONSTRAINS_MATERIAL'), (ld, geo, 'APPLIED_TO')] + [(b, geo, 'CONSTRAINS_BC') for b in bcs]
        for s, t, kind in edges:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Fluido' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 300:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run: {st.get('status')} {st.get('error') or ''} {r.text[:200] if not rid else ''}")
        if st.get('status') == 'done':
            surf = requests.get(f'{Vs}/{rid}/surface')
            hl = struct.unpack('<I', surf.content[:4])[0]
            hdr = json.loads(surf.content[4:4 + hl])
            ex = {x['key']: x for x in hdr.get('extra_fields', [])}
            check({'vmag', 'p'} <= set(ex) and abs(ex['p']['max'] - dp) < 1e-6 * dp,
                  f"campos extra {sorted(ex)}, p máx {ex.get('p', {}).get('max')} Pa")
            fl = hdr['summary']['fluid']
            q = next(f['flow_m3_s'] for f in fl['flow_rates'] if f['face_set'] == 'tip')
            Q_th = dp * W * H ** 3 / (12 * MU * L)
            check(abs(q / Q_th - 1) < 1e-8, f'caudal {q:.6e} m³/s (teoría {Q_th:.6e}), Re = {fl["reynolds"]:.2e}')
            rep = requests.get(f'{Vs}/{rid}/report', params={'format': 'markdown'})
            check(rep.ok, f'informe {rep.status_code}')
    finally:
        requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    args = ap.parse_args()
    fails = []

    def check(cond, msg):
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}")
        if not cond:
            fails.append(msg)

    if args.server:
        server(check, args.server.rstrip('/'))
        label = 'Hito fluido vía servidor'
    else:
        local(check)
        label = 'Hito fluido (Stokes)'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
