"""Hito: linear piezoelectricity (coupled displacement + electric potential), PZT-5H.

Homogeneous states, exact for any mesh (statically determinate supports, electrodes on whole faces):
  0. derived constants d = e·Sᴱ and κᵀ = κˢ + e·Sᴱ·eᵀ match the PZT-5H datasheet (d31 −274, d33 593,
     d15 741 pC/N, ε33ᵀ ≈ 3400 ε0)
  1. converse effect: block poled along z, V across the thickness → ε33 = d33 E3, ε11 = d31 E3, electrode charge
     = free capacitance κ33ᵀ A/t · V
  2. direct effect (open-circuit sensor): compressive force on the top face, bottom grounded, top without
     electrode condition → V = d33 σ3 t / κ33ᵀ
  3. shear mode: V across x on a block poled along z → γxz = d15 E1
  4. blocked actuator: thickness strain prevented → blocking stress σ3 = d33 E3 / s33ᴱ (lateral faces free)
  5. poling along x (material axes rotated): same thickness strain along x

Usage: python validate_piezo.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time

import numpy as np

L, W, H = 0.01, 0.01, 0.002          # 10 × 10 × 2 mm


def block(order=2, L=L, W=W, H=H):
    from app.design.services.fem.mesh import FEMMesh
    m = FEMMesh.generate_cantilever(L, W, H, 4, order=order)
    near = lambda p: np.array([int(np.argmin(np.linalg.norm(m.nodes - p, axis=1)))])   # noqa: E731
    m.node_sets['p0'], m.node_sets['p1'], m.node_sets['p2'] = near([0, 0, 0]), near([L, 0, 0]), near([0, W, 0])
    return m


SUPPORTS = [{'node_set': 'p0', 'dofs': [0, 1, 2]}, {'node_set': 'p1', 'dofs': [1, 2]}, {'node_set': 'p2', 'dofs': [2]}]


def affine_strain(m, u):
    X = np.hstack([np.ones((m.n_nodes, 1)), m.nodes])
    coef, *_ = np.linalg.lstsq(X, u, rcond=None)
    G = coef[1:].T
    return 0.5 * (G + G.T), float(np.abs(X @ coef - u).max() / max(np.abs(u).max(), 1e-30))


def local(check):
    from app.design.services.fem import piezo as pz
    from app.design.services.fem.kernel import FEMKernel
    k = FEMKernel()
    mat = {'type': 'piezoelectric', **pz.PZT5H}
    pm = pz.PiezoMaterial(mat)
    d = pm.d_matrix()
    kT = pm.free_permittivity()
    S = np.linalg.inv(pm.C)

    print('── 0. Constantes derivadas (PZT-5H) ─────────────────────────────────────')
    vals = {'d31': d[2, 0] * 1e12, 'd33': d[2, 2] * 1e12, 'd15': d[0, 5] * 1e12, 'eps33T': kT[2, 2] / pz.EPS0}
    ref = {'d31': -274, 'd33': 593, 'd15': 741, 'eps33T': 3400}
    print('   ' + '  '.join(f'{k_} = {v:.1f} (ficha {ref[k_]})' for k_, v in vals.items()))
    check(all(abs(vals[k_] / ref[k_] - 1) < 0.005 for k_ in ref), 'd31, d33, d15 y ε33ᵀ dentro del 0.5 % de la ficha')

    def run(m, bcs, loads=(), material=mat):
        return k._solve(None, {'physics': ['piezoelectric'], 'tier': 1, 'material': material,
                               'bcs': list(bcs), 'loads': list(loads)}, None, mesh=m)

    V = 100.0
    print('── 1. Efecto inverso (actuador): V a través del espesor ────────────────────')
    m = block()
    r = run(m, SUPPORTS + [{'face_set': 'z0', 'voltage': 0.0, 'label': 'tierra'},
                           {'face_set': 'z1', 'voltage': V, 'label': 'electrodo'}])
    eps, res = affine_strain(m, np.asarray(r['displacement']))
    E3 = -V / H
    el = r['summary']['piezo']['electrodes']
    Q = el[1]['charge_C']
    C = kT[2, 2] * L * W / H
    e1 = max(abs(eps[2, 2] / (d[2, 2] * E3) - 1), abs(eps[0, 0] / (d[2, 0] * E3) - 1), abs(Q / (C * V) - 1), res)
    print(f'   ε33 = {eps[2, 2]:.6e} (d33·E3 = {d[2, 2] * E3:.6e})  ε11 = {eps[0, 0]:.6e} (d31·E3 = {d[2, 0] * E3:.6e})')
    print(f'   carga del electrodo {Q * 1e9:.4f} nC = C·V {C * V * 1e9:.4f} nC  (C = {C * 1e12:.2f} pF)')
    check(e1 < 1e-8, f'deformaciones y capacidad libre exactas (error {e1:.1e})')

    print('── 2. Efecto directo (sensor en circuito abierto) ─────────────────────────')
    m = block()
    P = 100.0
    # uniform compression: roller on the whole bottom face (a point support would concentrate the reaction)
    r = run(m, [{'face_set': 'z0', 'dofs': [2]}, {'node_set': 'p0', 'dofs': [0, 1]}, {'node_set': 'p1', 'dofs': [1]},
                {'face_set': 'z0', 'voltage': 0.0}], [{'face_set': 'z1', 'force': [0, 0, -P]}])
    phi_top = r['summary']['piezo']['max_potential_V'] if d[2, 2] * (-P) > 0 else r['summary']['piezo']['min_potential_V']
    sig3 = -P / (L * W)
    V_th = d[2, 2] * sig3 * H / kT[2, 2]
    e2 = abs(phi_top / V_th - 1)
    print(f'   V(top) = {phi_top:.6f} V  (d33·σ3·t/ε33ᵀ = {V_th:.6f} V)')
    check(e2 < 1e-8, f'tensión del sensor exacta (error {e2:.1e})')

    print('── 3. Modo de cizalla d15 (campo perpendicular a la polarización) ─────────')
    m = block()
    r = run(m, SUPPORTS + [{'face_set': 'fixed', 'voltage': 0.0}, {'face_set': 'tip', 'voltage': V}])
    eps, _ = affine_strain(m, np.asarray(r['displacement']))
    E1 = -V / L
    e3 = abs(2 * eps[0, 2] / (d[0, 5] * E1) - 1)
    print(f'   γxz = {2 * eps[0, 2]:.6e}  (d15·E1 = {d[0, 5] * E1:.6e})')
    check(e3 < 1e-8, f'deformación de cizalla exacta (error {e3:.1e})')

    print('── 4. Actuador bloqueado (espesor impedido, caras laterales libres) ───────')
    m = block()
    r = run(m, [{'face_set': 'z0', 'dofs': [2]}, {'face_set': 'z1', 'dofs': [2]}, {'node_set': 'p0', 'dofs': [0, 1]},
                {'node_set': 'p1', 'dofs': [1]}, {'face_set': 'z0', 'voltage': 0.0}, {'face_set': 'z1', 'voltage': V}])
    Fz = r['summary']['reaction_N'][2]
    sig_b = -d[2, 2] * E3 / S[2, 2]
    sig_el = np.asarray(r['sigma_elemental'])[:, 2]
    e4 = float(np.abs(sig_el / sig_b - 1).max())
    print(f'   σ3 = {sig_el.mean() / 1e6:.4f} MPa  (−d33·E3/s33ᴱ = {sig_b / 1e6:.4f} MPa); ΣFz = {Fz:.1e} N')
    check(e4 < 1e-8, f'tensión de bloqueo exacta en todos los elementos (error {e4:.1e})')

    print('── 5. Polarización a lo largo de x (ejes del material girados) ───────────')
    m = block(L=H, W=W, H=L)                     # thin along x now
    near = lambda p: np.array([int(np.argmin(np.linalg.norm(m.nodes - p, axis=1)))])   # noqa: E731
    m.node_sets['p1'] = near([0, 0, L])
    r = run(m, [{'node_set': 'p0', 'dofs': [0, 1, 2]}, {'node_set': 'p1', 'dofs': [0, 1]},
                {'node_set': 'p2', 'dofs': [0]},
                {'face_set': 'fixed', 'voltage': 0.0}, {'face_set': 'tip', 'voltage': V}],
            material={**mat, 'axis_1': [0, 1, 0], 'axis_2': [0, 0, 1]})
    eps, _ = affine_strain(m, np.asarray(r['displacement']))
    e5 = abs(eps[0, 0] / (d[2, 2] * (-V / H)) - 1)
    print(f'   εxx = {eps[0, 0]:.6e}  (d33·E = {d[2, 2] * (-V / H):.6e})')
    check(e5 < 1e-8, f'giro de e y κ correcto (error {e5:.1e})')


def server(check, S):
    import requests
    from app.design.services.fem.piezo import PZT5H, PiezoMaterial
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO piezo', 'tier': 1, 'description': 'validate_piezo.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Placa 10×10×2', {'shape': 'beam', 'length_mm': 10, 'width_mm': 10, 'height_mm': 2,
                                                 'n_div': 4, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'PZT-5H', {'model_type': 'piezoelectric', **PZT5H})
        bc = add('BC', 'Apoyo', {'bc_type': 'roller_z', 'face_set': 'z0'})
        bcx = add('BC', 'Apoyo x', {'bc_type': 'roller_x', 'face_set': 'fixed'})
        bcy = add('BC', 'Apoyo y', {'bc_type': 'roller_y', 'face_set': 'y0'})
        g0 = add('BC', 'Tierra', {'bc_type': 'voltage', 'voltage': 0, 'face_set': 'z0'})
        g1 = add('BC', 'Electrodo', {'bc_type': 'voltage', 'voltage': 100, 'face_set': 'z1'})
        edges = [(mat, geo, 'CONSTRAINS_MATERIAL')] + [(b, geo, 'CONSTRAINS_BC') for b in (bc, bcx, bcy, g0, g1)]
        for s, t, kind in edges:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Piezoeléctrico' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 300:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run: {st.get('status')} {st.get('error') or ''}")
        if st.get('status') == 'done':
            surf = requests.get(f'{Vs}/{rid}/surface')
            import json
            import struct
            hl = struct.unpack('<I', surf.content[:4])[0]
            hdr = json.loads(surf.content[4:4 + hl])
            keys = [x['key'] for x in hdr.get('extra_fields', [])]
            phi = next((x for x in hdr['extra_fields'] if x['key'] == 'phi'), {})
            check('phi' in keys and abs(phi.get('max', 0) - 100) < 1e-6 and abs(phi.get('min', 1)) < 1e-6,
                  f"campos extra {keys}, φ {phi.get('min')} … {phi.get('max')} V")
            pm = PiezoMaterial({'type': 'piezoelectric', **PZT5H})
            d = pm.d_matrix()
            uz = hdr['max_u_mm'] / 1000
            # rollers on z0, x = 0, y = 0: free expansion → |u|max at the far corner (x = L, y = W, z = t)
            e = np.array([d[2, 0], d[2, 0], d[2, 2]]) * (-100 / 0.002) * np.array([0.01, 0.01, 0.002])
            check(abs(uz / np.linalg.norm(e) - 1) < 1e-6, f'|u| máx {uz * 1e9:.3f} nm (teoría {np.linalg.norm(e) * 1e9:.3f} nm)')
            rep = requests.get(f'{Vs}/{rid}/report', params={'format': 'markdown'})
            check(rep.ok, f'informe {rep.status_code}')
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
    print(f"\nHito piezoeléctrico{' vía servidor' if args.server else ''}: {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
