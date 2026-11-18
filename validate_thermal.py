"""
Hito FASE 2 (multifísica) — térmico estacionario y termo-mecánico acoplado en un sentido.

A. Núcleo (sin servidor), barra 100 × 10 × 10 mm T10, k = 50 W/m·K, acero E = 200 GPa, α = 12e-6 1/K:
   1. conducción entre dos temperaturas → perfil lineal, flujo k ΔT / L, balance de calor
   2. fuente interna Q con extremos a 0 °C → T = Q x (L − x) / 2k (parabólica, T10 exacta)
   3. flujo impuesto en el extremo → T(L) = q L / k
   4. convección en el extremo → T(L) = (k T0 / L + h T∞) / (k / L + h)
   5. aleta con convección lateral → θ/θ0 = cosh m(L − x) / cosh mL (teoría 1-D, Bi = 0.0025)
   6. barra libre con ΔT uniforme → sin tensión, u = α ΔT x
   7. barra impedida en x → σxx = −E α ΔT
B. Flujo completo por HTTP (--server; servidor + worker): estudio con viga paramétrica,
   BC de temperatura + convección en el resto de la superficie → /preflight "Térmico" →
   run en la cola → /surface con T; estudio termo-mecánico (apoyos + ΔT) → σ = E α ΔT;
   el ROM rechaza el estudio térmico con 422. Los estudios se borran al final (--keep).

Uso:  python validate_thermal.py [--server http://127.0.0.1:8080] [--keep]
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

L, W, H = 0.10, 0.01, 0.01
K_COND, E, NU, ALPHA = 50.0, 200e9, 0.3, 12e-6
ok = True


def check(cond, msg):
    global ok
    ok &= bool(cond)
    print(f"   {'OK   ' if cond else 'FALLA'} {msg}")


def kernel_cases():
    from app.design.services.fem import tet_batch as tb
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.mesh import FEMMesh

    m = FEMMesh.generate_cantilever(length=L, width=W, height=H, n_along_length=10, order=2)
    X = m.nodes
    tris = tb.boundary_faces(m.elements)
    xs = X[tris[:, :3], 0]
    lateral = tris[~((xs < 1e-9).all(1) | (xs > L - 1e-9).all(1))]
    origin = int(np.argmin(np.linalg.norm(X, axis=1)))
    corner_y = int(np.argmin(np.linalg.norm(X - [0, W, 0], axis=1)))
    print(f'   malla: {m.n_nodes} nodos, {m.n_elements} T10')
    x = X[:, 0]
    tip = x > L - 1e-9

    def solve(physics, bcs, loads):
        spec = {'mesh_source': 'inline', 'physics': physics, 'tier': 1, 'nodes': X, 'elements': m.elements,
                'face_sets': {**m.face_sets, 'lateral': lateral},
                'node_sets': {**m.node_sets, 'origin': [origin], 'corner_y': [corner_y]},
                'bcs': bcs, 'loads': loads,
                'material': {'E': E, 'nu': NU, 'rho': 7800.0, 'k': K_COND, 'alpha': ALPHA, 'T_ref': 20.0}}
        r = FEMKernel().solve_sync(spec)
        return r, np.asarray(r['temperature'])

    Tf = lambda f, t: {'face_set': f, 'temperature': t}  # noqa: E731
    rel = lambda a, b: abs(a - b) / abs(b)  # noqa: E731

    print('── A1. Conducción lineal ───────────────────────────────────────────────')
    r, T = solve(['thermal'], [Tf('fixed', 100.0), Tf('tip', 0.0)], [])
    e = np.abs(T - 100 * (1 - x / L)).max()
    q = r['summary']['thermal']['max_heat_flux_w_m2']
    check(e < 1e-8, f'perfil lineal, error máx. {e:.1e} °C')
    check(rel(q, K_COND * 100 / L) < 1e-8, f'flujo {q:.6g} W/m² (exacto {K_COND * 100 / L:.6g})')

    print('── A2. Fuente interna ──────────────────────────────────────────────────')
    Q = 1e6
    r, T = solve(['thermal'], [Tf('fixed', 0.0), Tf('tip', 0.0)], [{'heat_source': Q}])
    Tmax = Q * L * L / (8 * K_COND)
    e = np.abs(T - Q * x * (L - x) / (2 * K_COND)).max() / Tmax
    hb = r['summary']['thermal']
    check(e < 1e-8, f'perfil parabólico, T máx. {T.max():.6g} °C (exacta {Tmax:.6g}), error {e:.1e}')
    check(hb['heat_balance_error'] < 1e-9, f"balance de calor: fuente {hb['heat_balance_W']['source']:.4g} W = "
          f"salida por extremos {-hb['heat_balance_W']['fixed_T_in']:.4g} W")

    print('── A3. Flujo impuesto ──────────────────────────────────────────────────')
    qin = 2e4
    _, T = solve(['thermal'], [Tf('fixed', 0.0)], [{'face_set': 'tip', 'heat_flux': qin}])
    check(rel(T[tip].mean(), qin * L / K_COND) < 1e-9, f'T(L) = {T[tip].mean():.6g} °C (exacta {qin * L / K_COND:.6g})')

    print('── A4. Convección en el extremo ────────────────────────────────────────')
    h, Tinf, T0 = 500.0, 20.0, 200.0
    _, T = solve(['thermal'], [Tf('fixed', T0)], [{'face_set': 'tip', 'convection': {'h': h, 'T_inf': Tinf}}])
    ex = (K_COND * T0 / L + h * Tinf) / (K_COND / L + h)
    check(rel(T[tip].mean(), ex) < 1e-9, f'T(L) = {T[tip].mean():.6g} °C (exacta {ex:.6g})')

    print('── A5. Aleta con convección lateral ────────────────────────────────────')
    h = 25.0
    r, T = solve(['thermal'], [Tf('fixed', 100.0)], [{'face_set': 'lateral', 'convection': {'h': h, 'T_inf': 0.0}}])
    mm = math.sqrt(h * 2 * (W + H) / (K_COND * W * H))
    e = np.abs(T - 100 * np.cosh(mm * (L - x)) / math.cosh(mm * L)).max() / 100
    qf = math.sqrt(h * 2 * (W + H) * K_COND * W * H) * 100 * math.tanh(mm * L)
    qn = r['summary']['thermal']['heat_balance_W']['fixed_T_in']
    check(e < 5e-3, f'perfil de aleta, error máx. {100 * e:.3f} % de θ0 (teoría 1-D)')
    check(rel(qn, qf) < 1e-2, f'calor disipado {qn:.5g} W (1-D {qf:.5g} W, {100 * rel(qn, qf):.2f} %)')

    sup = [{'face_set': 'fixed', 'dofs': [0], 'values': [0.0]},
           {'node_set': 'origin', 'dofs': [1, 2], 'values': [0.0, 0.0]},
           {'node_set': 'corner_y', 'dofs': [2], 'values': [0.0]}]
    print('── A6. Dilatación libre ────────────────────────────────────────────────')
    dT = 80.0
    r, _ = solve(['thermal', 'structural'], [Tf('fixed', 20 + dT), Tf('tip', 20 + dT)] + sup, [])
    u = np.asarray(r['displacement'])
    e = np.abs(u[:, 0] - ALPHA * dT * x).max()
    vm = max(r['von_mises_nodal'])
    check(e < 1e-12, f'u(L) = {u[tip, 0].mean() * 1e3:.6g} mm (α ΔT L = {ALPHA * dT * L * 1e3:.6g} mm)')
    check(vm < 1e-3 * E * ALPHA * dT, f'sin tensión: von Mises máx. {vm / 1e6:.2e} MPa')

    print('── A7. Barra impedida ──────────────────────────────────────────────────')
    dT = 50.0
    r, _ = solve(['thermal', 'structural'], [Tf('fixed', 20 + dT), Tf('tip', 20 + dT)] + sup +
                 [{'face_set': 'tip', 'dofs': [0], 'values': [0.0]}], [])
    sx = np.asarray(r['sigma_elemental'])[:, 0]
    ex = -E * ALPHA * dT
    check(np.abs(sx - ex).max() / abs(ex) < 1e-8, f'σxx = {sx.mean() / 1e6:.6g} MPa (−E α ΔT = {ex / 1e6:.6g} MPa)')
    check(r['summary']['equilibrium_error'] < 1e-8, f"equilibrio {r['summary']['equilibrium_error']:.1e}")


def parse_pack(buf):
    n = struct.unpack('<I', buf[:4])[0]
    head = json.loads(buf[4:4 + n])
    start = 4 + n + (-(4 + n)) % 4
    arrays = {a['name']: np.frombuffer(buf, dtype=a['dtype'], count=int(np.prod(a['shape'])),
                                       offset=start + a['offset']).reshape(a['shape']) for a in head['arrays']}
    return head, arrays


def server_cases(S, keep, timeout):
    import requests
    G, V = f'{S}/api/design/graph', f'{S}/api/design/solver'
    created = []

    def study(name, nodes):
        gid = requests.post(f'{G}/', json={'name': name, 'tier': 1, 'description': 'validate_thermal.py'}).json()['id']
        created.append(gid)
        ids = {}
        for t, label, props in nodes:
            ids[label] = requests.post(f'{G}/{gid}/nodes', json={'node_type': t, 'label': label,
                                                                 'properties': props}).json()['node_id']
        return gid

    def run(gid):
        r = requests.post(f'{V}/{gid}/run', json={})
        if r.status_code not in (200, 201, 202):
            return None, r.json()
        rid = r.json()['run_id']
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = requests.get(f'{V}/{rid}/status').json()
            if st['status'] in ('done', 'failed'):
                return rid, st
            time.sleep(0.5)
        return rid, {'status': 'timeout'}

    Lb, Bb = 200.0, 20.0                  # mm
    beam = ('GEOMETRY', 'Barra', {'shape': 'beam', 'length_mm': Lb, 'width_mm': Bb, 'height_mm': Bb,
                                  'n_div': 16, 'element_order': 2})
    steel = ('MATERIAL', 'Acero', {'E': E, 'nu': NU, 'rho': 7850, 'k': K_COND, 'alpha': ALPHA, 'T_ref': 20})
    try:
        print('── B1. Estudio térmico (aleta) ─────────────────────────────────────────')
        h, T0, Tinf = 20.0, 120.0, 20.0
        gid = study('HITO térmico aleta', [beam, steel,
                    ('BC', 'Base 120 °C', {'bc_type': 'temperature', 'temperature': T0}),
                    ('LOAD', 'Convección aire', {'load_type': 'convection', 'h': h, 'T_inf': Tinf})])
        pf = requests.get(f'{V}/{gid}/preflight').json()
        check(pf['physics'] == ['thermal'] and pf['ready'], f"preflight: {pf['physics_label']}, listo={pf['ready']}")
        rid, st = run(gid)
        check(st.get('status') == 'done', f"run {str(rid)[:8]} → {st.get('status')} {st.get('error') or ''}")
        if st.get('status') == 'done':
            head, a = parse_pack(requests.get(f'{V}/{rid}/surface').content)
            Lm, Bm = Lb / 1000, Bb / 1000
            P, A = 4 * Bm, Bm * Bm
            mm = math.sqrt(h * P / (K_COND * A))
            r_ = h / (mm * K_COND)                # convective tip, 1-D fin theory
            tip_theta = (T0 - Tinf) / (math.cosh(mm * Lm) + r_ * math.sinh(mm * Lm))
            tipT = float(a['T'][a['xyz'][:, 0] > Lb - 1e-3].mean())
            check('T' in head['fields'] and len(a['T']) == head['n_surface_nodes'],
                  f"pack con campos {head['fields']}, T {head['min_T']:.4g} … {head['max_T']:.4g} °C")
            check(abs(tipT - Tinf - tip_theta) / tip_theta < 0.01,
                  f'T extremo {tipT:.5g} °C (aleta 1-D con extremo convectivo {Tinf + tip_theta:.5g} °C)')
            r = requests.post(f'{S}/api/design/rom/{gid}/build', json={})
            check(r.status_code == 422, f'ROM rechaza el estudio térmico: {r.status_code} {r.json().get("error", "")[:60]}')

        print('── B2. Estudio termo-mecánico (barra impedida) ─────────────────────────')
        dT = 60.0
        gid = study('HITO termo-mecánico', [beam, steel,
                    ('BC', 'T base', {'bc_type': 'temperature', 'temperature': 20 + dT}),
                    ('BC', 'T extremo', {'bc_type': 'temperature', 'temperature': 20 + dT, 'node_set': 'tip'}),
                    ('BC', 'Empotramiento', {'bc_type': 'fixed'}),
                    ('BC', 'Tope axial', {'bc_type': 'roller_x', 'node_set': 'tip'})])
        pf = requests.get(f'{V}/{gid}/preflight').json()
        check(pf['physics'] == ['structural', 'thermal'], f"preflight: {pf['physics_label']}")
        rid, st = run(gid)
        check(st.get('status') == 'done', f"run {str(rid)[:8]} → {st.get('status')} {st.get('error') or ''}")
        if st.get('status') == 'done':
            head, a = parse_pack(requests.get(f'{V}/{rid}/surface').content)
            xm = a['xyz'][:, 0]
            mid = (xm > 0.3 * Lb) & (xm < 0.7 * Lb)
            vm = float(np.median(a['vm'][mid]))
            # the same model solved directly in the kernel (graph → queue → worker must reproduce it)
            from app.design.services.fem.kernel import FEMKernel
            ref = FEMKernel().solve_sync({
                'physics': ['structural', 'thermal'], 'mesh_source': 'cantilever', 'tier': 1,
                'mesh_params': {'length': Lb / 1e3, 'width': Bb / 1e3, 'height': Bb / 1e3, 'n_along_length': 16,
                                'order': 2},
                'material': {'E': E, 'nu': NU, 'rho': 7850, 'k': K_COND, 'alpha': ALPHA, 'T_ref': 20.0},
                'bcs': [{'node_set': 'fixed', 'temperature': 20 + dT}, {'node_set': 'tip', 'temperature': 20 + dT},
                        {'node_set': 'fixed', 'dofs': [0, 1, 2], 'values': [0, 0, 0]},
                        {'node_set': 'tip', 'dofs': [0], 'values': [0]}], 'loads': []})
            got = head['summary']['max_von_mises_mpa']
            want = ref['summary']['max_von_mises_mpa']
            check(abs(got - want) / want < 1e-9, f'von Mises máx. {got:.6g} MPa = núcleo directo {want:.6g} MPa')
            ex = E * ALPHA * dT / 1e6
            check(abs(vm - ex) / ex < 0.03,
                  f'tramo central {vm:.5g} MPa vs E α ΔT = {ex:.5g} MPa ({100 * (vm - ex) / ex:+.1f} %: el '
                  'empotramiento impide la dilatación lateral en el extremo; caso exacto en A7)')
            check(set(head['fields']) == {'u', 'vm', 'T', 'q'}, f"pack con campos {head['fields']}")
    finally:
        for gid in ([] if keep else created):
            requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--timeout', type=float, default=300)
    args = ap.parse_args()
    t0 = time.perf_counter()
    kernel_cases()
    if args.server:
        server_cases(args.server.rstrip('/'), args.keep, args.timeout)
    print(f"\nHito multifísica: {'CUMPLIDO' if ok else 'NO CUMPLIDO'} ({time.perf_counter() - t0:.1f} s)")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
