"""Hito: linear magnetostatics with a magnetic scalar potential (current-free, one material region).

  1. magnetic circuit bar (ψ on two pole faces): uniform B = μ ΔΨ / L, flux, permeance μA/L and field energy exact
  2. permanent magnet between ideal iron poles (short circuit): H = 0, B = Br, flux Br·A exact
  3. magnet closed by flux walls (open circuit, Br tilted 3-D): B = 0, H = −Br/μ exact (potential pinned)
  4. imposed normal flux Bn on one face: uniform B, flux balance exact
  5. harmonic quadratic potential ψ = x² − y² (T10 contains it): exact
  6. quarter toroidal core (curved, gmsh): permeance μ t ln(b/a)/(π/2) — the coil MMF N·I enters as the jump of ψ
     across the cut; T10 convergence with refinement

Usage: python validate_magnetic.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time
from math import log, pi

import numpy as np

L, W, H = 0.04, 0.01, 0.01


def bar(n=8, order=2):
    from app.design.services.fem.mesh import FEMMesh
    return FEMMesh.generate_cantilever(L, W, H, n, order=order)


def solve(m, bcs, loads, mu_r=1000.0, Br=(0, 0, 0)):
    from app.design.services.fem.kernel import FEMKernel
    return FEMKernel()._solve(None, {'tier': 1, 'material': {'type': 'linear_magnetic', 'mu_r': mu_r, 'Br': list(Br)},
                                     'bcs': bcs, 'loads': loads}, None, mesh=m)


def B_of(r):
    x = r['extra_fields']
    return np.stack([x['Bx'], x['By'], x['Bz']], axis=1)


def local(check):
    from app.design.services.fem import magnetic as mg
    MU0 = mg.MU0

    print('── 1. Circuito magnético (barra entre dos polos) ───────────────────────')
    dpsi, mu_r = 100.0, 1000.0
    for order in (1, 2):
        r = solve(bar(order=order), [{'face_set': 'fixed', 'magnetic_potential': dpsi},
                                     {'face_set': 'tip', 'magnetic_potential': 0.0}], [], mu_r)
        g = r['summary']['magnetic']
        Bx = MU0 * mu_r * dpsi / L
        P = MU0 * mu_r * W * H / L
        e = max(np.abs(B_of(r)[:, 0] - Bx).max() / Bx, np.abs(B_of(r)[:, 1:]).max() / Bx,
                abs(g['permeance_H'] / P - 1), abs(g['field_energy_J'] / (0.5 * P * dpsi ** 2) - 1))
        print(f'   T{4 if order == 1 else 10}: B = {B_of(r)[:, 0].mean():.6f} T (μΔψ/L {Bx:.6f}); permeancia '
              f'{g["permeance_H"] * 1e6:.6f} µH (μA/L {P * 1e6:.6f}); energía {g["field_energy_J"]:.6e} J')
        check(e < 1e-10, f'campo, permeancia y energía exactos (error {e:.1e})')

    print('── 2. Imán entre polos de hierro ideal (cortocircuito) ─────────────────')
    Br = 1.3
    r = solve(bar(), [{'face_set': 'fixed', 'magnetic_potential': 0.0},
                      {'face_set': 'tip', 'magnetic_potential': 0.0}], [], 1.05, (Br, 0, 0))
    g = r['summary']['magnetic']
    phi = g['poles'][1]['flux_in_Wb']
    e = max(np.abs(B_of(r)[:, 0] - Br).max() / Br, r['summary']['magnetic']['max_H_A_m'] * MU0 / Br,
            abs(-phi / (Br * W * H) - 1))
    print(f'   B = {B_of(r)[:, 0].mean():.6f} T, |H| máx {g["max_H_A_m"]:.1e} A/m, flujo {-phi * 1e6:.4f} µWb '
          f'(Br·A {Br * W * H * 1e6:.4f})')
    check(e < 1e-10, f'B = Br, H = 0 y flujo exactos (error {e:.1e})')

    print('── 3. Imán encerrado por paredes de flujo (circuito abierto, Br inclinado) ──')
    Brv = np.array([0.8, -0.5, 0.6])
    r = solve(bar(), [], [], 1.05, Brv)
    Hs = -Brv / (MU0 * 1.05)
    e = max(np.abs(B_of(r)).max() / np.linalg.norm(Brv),
            abs(r['summary']['magnetic']['max_H_A_m'] / np.linalg.norm(Hs) - 1))
    print(f'   |B| máx {np.abs(B_of(r)).max():.1e} T; |H| = {r["summary"]["magnetic"]["max_H_A_m"]:.2f} A/m '
          f'(|Br|/μ {np.linalg.norm(Hs):.2f}); potencial fijado: {r["summary"]["magnetic"]["potential_pinned"]}')
    check(e < 1e-10 and r['summary']['magnetic']['potential_pinned'], f'B = 0, H = −Br/μ (error {e:.1e})')

    print('── 4. Flujo normal impuesto ────────────────────────────────────────────')
    r = solve(bar(), [{'face_set': 'fixed', 'magnetic_potential': 0.0}],
              [{'face_set': 'tip', 'magnetic_flux': 0.5}], 50.0)
    phi = r['summary']['magnetic']['poles'][0]['flux_in_Wb']
    e = max(np.abs(B_of(r)[:, 0] + 0.5).max() / 0.5, abs(phi + 0.5 * W * H) / (0.5 * W * H))
    print(f'   Bx = {B_of(r)[:, 0].mean():.6f} T; flujo que sale por el polo {-phi * 1e6:.4f} µWb (entra {0.5 * W * H * 1e6:.4f})')
    check(e < 1e-10, f'B uniforme y balance de flujo exactos (error {e:.1e})')

    print('── 5. Potencial armónico cuadrático ψ = x² − y² (T10) ──────────────────')
    from app.design.services.fem.assembler import reduce_system
    import scipy.sparse.linalg as spla
    m = bar(6)
    x, y = m.nodes[:, 0], m.nodes[:, 1]
    ex = (x ** 2 - y ** 2) * 1e6
    mat = mg.MagneticMaterial({'mu_r': 1.0})
    K, F = mg.assemble(m, mat, [])
    bd = np.unique(np.asarray([t for fs in ('fixed', 'tip', 'y0', 'y1', 'z0', 'z1') for t in m.face_sets[fs]]).ravel())
    Kf, rhs, free = reduce_system(K, F, bd, ex[bd])
    psi = ex.copy()
    psi[free] = spla.spsolve(Kf.tocsc(), rhs)
    Hn, _ = mg.fields(m, psi, mat)
    Hex = -np.stack([2 * x, -2 * y, 0 * x], axis=1) * 1e6
    e = max(np.abs(psi - ex).max() / np.abs(ex).max(), np.abs(Hn - Hex).max() / np.abs(Hex).max())
    check(e < 1e-9, f'ψ y H exactos (error {e:.1e})')

    print('── 6. Núcleo toroidal (cuarto de anillo, geometría curva) ──────────────')
    from app.design.services.fem.mesh import FEMMesh
    a, b, t, mu_r = 0.02, 0.03, 0.01, 2000.0
    P_th = MU0 * mu_r * t * log(b / a) / (pi / 2)
    errs, hs = [], []
    for hsz in (0.005, 0.0025, 0.00125):
        t0 = time.perf_counter()
        m = FEMMesh.generate_ring(a, b, t, mesh_size=hsz, order=2)
        r = solve(m, [{'face_set': 'y0', 'magnetic_potential': dpsi}, {'face_set': 'x0', 'magnetic_potential': 0.0}],
                  [], mu_r)
        P = r['summary']['magnetic']['permeance_H']
        errs.append(abs(P / P_th - 1))
        hs.append(hsz)
        print(f'   h = {hsz * 1e3:.2f} mm: permeancia {P * 1e6:.6f} µH (teoría {P_th * 1e6:.6f}) error '
              f'{100 * (P / P_th - 1):+.4f} %  ({m.n_nodes:,} nodos, {time.perf_counter() - t0:.1f} s)')
    rate = log(errs[1] / errs[2]) / log(hs[1] / hs[2])
    N, I = 200, 0.1
    print(f'   bobina toroidal completa, N = {N}: L = N²·P/4 = {N ** 2 * P_th / 4 * 1e3:.3f} mH '
          f'(FEM {N ** 2 * P / 4 * 1e3:.3f} mH); con I = {I} A, B medio = '
          f'{MU0 * mu_r * N * I / (2 * pi * (a + b) / 2):.3f} T')
    check(errs[-1] < 1e-3, f'permeancia del toroide dentro del 0.1 % ({100 * errs[-1]:.4f} %)')
    check(rate > 1.5, f'orden de convergencia {rate:.2f}')


def server(check, S):
    import json
    import struct
    import requests
    from app.design.services.fem.magnetic import MU0
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO magnético', 'tier': 1, 'description': 'validate_magnetic.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    dpsi, mu_r = 100.0, 1000.0
    try:
        geo = add('GEOMETRY', 'Núcleo 40×10×10', {'shape': 'beam', 'length_mm': 40, 'width_mm': 10, 'height_mm': 10,
                                                   'n_div': 8, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Hierro μr 1000', {'model_type': 'linear_magnetic', 'mu_r': mu_r, 'rho': 7650})
        bcs = [add('BC', 'Polo N', {'bc_type': 'magnetic_potential', 'magnetic_potential': dpsi, 'face_set': 'fixed'}),
               add('BC', 'Polo S', {'bc_type': 'magnetic_potential', 'magnetic_potential': 0, 'face_set': 'tip'})]
        for s, t, kind in [(mat, geo, 'CONSTRAINS_MATERIAL')] + [(b, geo, 'CONSTRAINS_BC') for b in bcs]:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Magnetostática' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
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
            Bx = MU0 * mu_r * dpsi / L
            check({'Bmag', 'psi'} <= set(ex) and abs(ex['Bmag']['max'] / Bx - 1) < 1e-6,
                  f"campos extra {sorted(ex)}, |B| máx {ex.get('Bmag', {}).get('max')} T (teoría {Bx:.6f})")
            g = hdr['summary']['magnetic']
            P = MU0 * mu_r * W * H / L
            check(abs(g['permeance_H'] / P - 1) < 1e-8, f"permeancia {g['permeance_H'] * 1e6:.6f} µH (μA/L {P * 1e6:.6f})")
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
        label = 'Hito magnético vía servidor'
    else:
        local(check)
        label = 'Hito magnético (magnetostática lineal)'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
