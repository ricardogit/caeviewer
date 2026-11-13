"""
Hito FASE 2.5 — no-linealidad del material: plasticidad J2 (von Mises) con Newton-Raphson.

A. Barra en tracción uniaxial (T10, apoyos isostáticos, contracción lateral libre), E = 200 GPa, σy = 250 MPa:
   1. endurecimiento lineal H = 2 GPa: alargamiento L (σ/E + (σ − σy)/H), carga y descarga → εp residual exacto
   2. endurecimiento Voce: εp = −ln(1 − (σ − σy)/Q)/b
   3. convergencia cuadrática de Newton (tangente consistente) y plasticidad perfecta → carga límite σ = σy
B. Cilindro de pared gruesa (deformación plana, a = 10 mm, b = 20 mm), elastoplástico perfecto:
   4. presión de primera plastificación (Lamé + von Mises con σz = 2νA)
   5. radio de la zona plástica para p = 0.8 p_lím vs Hill: p = k [1 − c²/b² + 2 ln(c/a)], k = σy/√3
   6. presión de colapso p_lím = (2/√3) σy ln(b/a)
C. (--server) estudio por HTTP: viga paramétrica con material elastoplástico → run en la cola → /surface con εp;
   topología/ROM rechazan el estudio no lineal (422). Se borra al final (--keep para conservarlo).

Uso:  python validate_plasticity.py [--server http://127.0.0.1:8080] [--keep]
"""
import argparse
import json
import math
import struct
import sys
import time

import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

E, NU, SY, H = 200e9, 0.3, 250e6, 2e9
ok = True


def check(cond, msg):
    global ok
    ok &= bool(cond)
    print(f"   {'OK   ' if cond else 'FALLA'} {msg}")


def bar_cases():
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.mesh import FEMMesh
    L, W = 0.05, 0.01
    m = FEMMesh.generate_cantilever(length=L, width=W, height=W, n_along_length=6, order=2)
    X = m.nodes
    ns = {**m.node_sets, 'origin': [int(np.argmin(np.linalg.norm(X, axis=1)))],
          'corner_y': [int(np.argmin(np.linalg.norm(X - [0, W, 0], axis=1)))]}
    sup = [{'face_set': 'fixed', 'dofs': [0], 'values': [0.0]},
           {'node_set': 'origin', 'dofs': [1, 2], 'values': [0.0, 0.0]},
           {'node_set': 'corner_y', 'dofs': [2], 'values': [0.0]}]
    tip = X[:, 0] > L - 1e-9

    def tension(stress, hardening, **kw):
        r = FEMKernel().solve_sync({
            'mesh_source': 'inline', 'tier': 1, 'nodes': X, 'elements': m.elements, 'face_sets': m.face_sets,
            'node_sets': ns, 'bcs': sup, 'loads': [{'face_set': 'tip', 'force': [stress * W * W, 0, 0]}],
            'material': {'type': 'elastoplastic_vonmises', 'E': E, 'nu': NU, 'rho': 7850, 'sigma_y': SY,
                         'hardening': hardening}, **kw})
        return r, float(np.asarray(r['displacement'])[tip, 0].mean())

    print('── A1. Tracción con endurecimiento lineal, carga y descarga ────────────')
    s = 300e6
    ep = (s - SY) / H
    r, ux = tension(s, {'type': 'linear', 'H': H}, n_load_steps=5)
    ex = L * (s / E + ep)
    check(abs(ux - ex) / ex < 1e-7, f'alargamiento {ux * 1e3:.6f} mm (exacto {ex * 1e3:.6f} mm)')
    check(abs(r['summary']['max_equivalent_plastic_strain'] - ep) / ep < 1e-7, f'εp = {ep:.4%}')
    r, ux = tension(s, {'type': 'linear', 'H': H}, n_load_steps=5, load_path=[1.0, 0.0])
    check(abs(ux - L * ep) / (L * ep) < 1e-7 and max(r['von_mises_nodal']) < 1e-6 * SY,
          f'tras descargar: alargamiento permanente {ux * 1e3:.6f} mm (L εp = {L * ep * 1e3:.6f} mm), sin tensión residual')

    print('── A2. Endurecimiento Voce ─────────────────────────────────────────────')
    Q, b = 120e6, 40.0
    s = 330e6
    ep = -math.log(1 - (s - SY) / Q) / b
    _, ux = tension(s, {'type': 'voce', 'Q': Q, 'b': b}, n_load_steps=8)
    ex = L * (s / E + ep)
    check(abs(ux - ex) / ex < 1e-7, f'alargamiento {ux * 1e3:.6f} mm (exacto {ex * 1e3:.6f} mm)')

    print('── A3. Convergencia de Newton y carga límite ───────────────────────────')
    r, _ = tension(300e6, {'type': 'linear', 'H': H}, n_load_steps=2)
    res = [x['residual'] for x in r['solve_info']['convergence_log'] if x['step'] == 2]
    print('      residuos del paso 2: ' + ', '.join(f'{x:.1e}' for x in res))
    rates = [math.log(c) / math.log(b_) for b_, c in zip(res[1:-1], res[2:]) if 0 < b_ < 0.1 and c > 1e-15]
    check(len(res) <= 6 and (not rates or max(rates) > 1.6), f'{len(res)} iteraciones, orden ≈ {max(rates or [2]):.2f}')
    r, _ = tension(1.2 * SY, {'type': 'perfect'}, n_load_steps=6)
    p = r['summary']['plasticity']
    check(p['limit_load_reached'] and abs(1.2 * p['load_factor'] - 1) < 0.01,
          f"plasticidad perfecta: se detiene en σ = {1.2 * p['load_factor'] * SY / 1e6:.1f} MPa (σy = {SY / 1e6:.0f})")


def cylinder_cases():
    from app.design.services.fem.kernel import FEMKernel
    a, b, t = 0.010, 0.020, 0.002
    k = SY / math.sqrt(3)
    p_lim = 2 * k * math.log(b / a)
    # first yield at r = a (Lamé, plane strain σz = 2νA)
    A_ = a * a / (b * b - a * a)
    sr, st, sz = -1.0, A_ + A_ * b * b / (a * a), 2 * NU * A_
    q1 = math.sqrt(0.5 * ((sr - st) ** 2 + (st - sz) ** 2 + (sz - sr) ** 2))
    p_e = SY / q1

    def run(p, n_steps, h=None, nu=NU):
        return FEMKernel().solve_sync({
            'mesh_source': 'ring', 'tier': 1,
            'mesh_params': {'inner_radius': a, 'outer_radius': b, 'thickness': t, 'order': 2,
                            **({'mesh_size': h} if h else {})},
            'material': {'type': 'elastoplastic_vonmises', 'E': E, 'nu': nu, 'rho': 7850, 'sigma_y': SY,
                         'hardening': {'type': 'perfect'}},
            'bcs': [{'face_set': 'x0', 'dofs': [0], 'values': [0.0]}, {'face_set': 'y0', 'dofs': [1], 'values': [0.0]},
                    {'face_set': ['z0', 'z1'], 'dofs': [2], 'values': [0.0]}],
            'loads': [{'face_set': 'inner', 'pressure': p}], 'n_load_steps': n_steps})

    print('── B4. Primera plastificación ──────────────────────────────────────────')
    r1 = run(0.97 * p_e, 1)
    r2 = run(1.03 * p_e, 1)
    print(f"      malla: {r1['summary']['n_nodes']} nodos, {r1['summary']['n_elements']} T10")
    check(r1['summary']['max_equivalent_plastic_strain'] == 0 and r2['summary']['max_equivalent_plastic_strain'] > 0,
          f'elástico a 0.97 p_e, plástico a 1.03 p_e (p_e = {p_e / 1e6:.2f} MPa)')

    print('── B5. Zona plástica (Hill, sólido casi incompresible) ─────────────────')
    p = 0.8 * p_lim
    c = _bisect(lambda c: k * (1 - c * c / (b * b) + 2 * math.log(c / a)) - p, a, b)
    h = (b - a) / 10
    r = run(p, 10, h=h, nu=0.49)                     # Hill's closed form is for an incompressible solid
    X = np.asarray(r['nodes'])
    el = np.asarray(r['elements'])
    cen = X[el[:, :4]].mean(axis=1)
    rr = np.hypot(cen[:, 0], cen[:, 1])
    th_ = np.arctan2(cen[:, 1], cen[:, 0])
    sg = np.asarray(r['sigma_elemental'])
    s_t = sg[:, 0] * np.sin(th_) ** 2 + sg[:, 1] * np.cos(th_) ** 2 - 2 * sg[:, 3] * np.sin(th_) * np.cos(th_)
    elastic = rr > c + 1.5 * h
    hill = k * c * c / (b * b) * (1 + b * b / rr[elastic] ** 2)
    err = float(np.mean(s_t[elastic]) / np.mean(hill) - 1)
    epe = np.asarray(r['equivalent_plastic_strain_elemental'])
    c_any = float(rr[epe > 0].max())
    check(r['summary']['converged'] and abs(err) < 0.02,
          f'σθ en la zona elástica {np.mean(s_t[elastic]) / 1e6:.1f} MPa vs Hill {np.mean(hill) / 1e6:.1f} MPa '
          f'({100 * err:+.2f} %; frontera plástica c = {c * 1e3:.2f} mm, ν = 0.49)')
    print(f'      elemento plástico más alejado: centroide a {c_any * 1e3:.2f} mm (elementos de {h * 1e3:.1f} mm)')

    print('── B6. Presión de colapso ──────────────────────────────────────────────')
    r = run(1.1 * p_lim, 20)
    pl_ = r['summary']['plasticity']
    p_fe = 1.1 * pl_['load_factor'] * 1.0
    err = (p_fe * p_lim - p_lim) / p_lim
    check(pl_['limit_load_reached'] and abs(err) < 0.03,
          f"colapso a p = {p_fe * p_lim / 1e6:.1f} MPa (p_lím = {p_lim / 1e6:.1f} MPa, {100 * err:+.2f} %); "
          f"{pl_['n_steps']} pasos, {pl_['cutbacks']} recortes")
    curve = pl_['curve']
    print('      curva p [MPa] → u_máx [µm]: ' + ', '.join(
        f"{1.1 * c_['load_factor'] * p_lim / 1e6:.0f}→{c_['max_displacement_m'] * 1e6:.1f}" for c_ in curve[1::3]))


def _bisect(f, lo, hi):
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def parse_pack(buf):
    n = struct.unpack('<I', buf[:4])[0]
    head = json.loads(buf[4:4 + n])
    start = 4 + n + (-(4 + n)) % 4
    return head, {a['name']: np.frombuffer(buf, dtype=a['dtype'], count=int(np.prod(a['shape'])),
                                           offset=start + a['offset']).reshape(a['shape']) for a in head['arrays']}


def server_cases(S, keep, timeout):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO plasticidad', 'tier': 1,
                                       'description': 'validate_plasticity.py'}).json()['id']
    try:
        print('── C. Estudio elastoplástico por HTTP ──────────────────────────────────')
        Lb, Bb = 200.0, 20.0
        F_y = SY * Bb ** 3 / 6 / 1e9 / (Lb / 1000) * 1.0       # first yield at the root (elastic beam), N
        for t, label, props in [
                ('GEOMETRY', 'Viga', {'shape': 'beam', 'length_mm': Lb, 'width_mm': Bb, 'height_mm': Bb,
                                      'n_div': 16, 'element_order': 2}),
                ('MATERIAL', 'Acero S250', {'model_type': 'elastoplastic_vonmises', 'E': E, 'nu': NU, 'rho': 7850,
                                            'yield_strength': SY, 'hardening_type': 'linear', 'H': H}),
                ('BC', 'Empotramiento', {'bc_type': 'fixed'}),
                ('LOAD', 'Carga', {'load_type': 'force', 'magnitude': 1.3 * F_y, 'unit': 'N', 'dir_z': -1})]:
            requests.post(f'{G}/{gid}/nodes', json={'node_type': t, 'label': label, 'properties': props})
        pf = requests.get(f'{V}/{gid}/preflight').json()
        check('plástic' in pf['physics_label'].lower(), f"preflight: {pf['physics_label']}")
        rid = requests.post(f'{V}/{gid}/run', json={}).json()['run_id']
        t0 = time.time()
        st = {}
        while time.time() - t0 < timeout:
            st = requests.get(f'{V}/{rid}/status').json()
            if st['status'] in ('done', 'failed'):
                break
            time.sleep(0.5)
        check(st.get('status') == 'done', f"run {rid[:8]} → {st.get('status')}")
        if st.get('status') == 'done':
            head, a = parse_pack(requests.get(f'{V}/{rid}/surface').content)
            s = head['summary']
            check('ep' in head['fields'] and float(a['ep'].max()) > 0,
                  f"pack con εp (máx. {float(a['ep'].max()):.2e}); zona plástica "
                  f"{100 * s['plasticity']['plastic_volume_fraction']:.1f} % del volumen")
            near_root = a['xyz'][:, 0] < 0.25 * Lb
            check(float(a['ep'][~near_root].max()) == 0.0, 'la plastificación se concentra junto al empotramiento')
        r = requests.post(f'{S}/api/design/rom/{gid}/build', json={})
        check(r.status_code == 422, f'ROM rechaza el estudio no lineal: {r.status_code}')
    finally:
        if not keep:
            requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--timeout', type=float, default=300)
    args = ap.parse_args()
    t0 = time.perf_counter()
    bar_cases()
    cylinder_cases()
    if args.server:
        server_cases(args.server.rstrip('/'), args.keep, args.timeout)
    print(f"\nHito plasticidad: {'CUMPLIDO' if ok else 'NO CUMPLIDO'} ({time.perf_counter() - t0:.1f} s)")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
