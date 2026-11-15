"""Hito: thermo-piezoelectricity (one-way thermal → piezo coupling), PZT-5H.

σ = Cᴱ(ε − αΔT) − eᵀE,  D = eε + κˢE + pΔT  (p = [0, 0, p3] along the poling axis).
Exact checks (any mesh):
  A. clamped (u = 0) and short-circuited (both electrodes 0 V), uniform ΔT: σ = −Cᴱ α ΔT everywhere, the top
     electrode collects Q = −p3 ΔT A (bottom the opposite)
  B. free (3-2-1 supports), bottom grounded, top open circuit, uniform ΔT: open-circuit voltage from the 7×7
     homogeneous system (ε, E3) with σ = 0, D3 = 0
  C. clamped everywhere, shorted, T linear through the thickness: φ = (p3 ΔT / κ33)(z²/(2h) − z/2) (quadratic),
     charges ±p3 ΔT A / 2
  D. ΔT = 0 → identical to the plain piezoelectric model (converse effect); plain piezo + temperature → error
Server: graph with MATERIAL thermopiezoelectric + temperature BCs + electrodes → preflight, run on the queue,
φ and T fields, open-circuit voltage of case B.

Usage: python validate_thermopiezo.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time

import numpy as np

L, W, H = 0.01, 0.01, 0.001          # 10 × 10 × 1 mm
P3, ALPHA, TREF, DT = -3e-4, 3e-6, 20.0, 50.0


def material():
    from app.design.services.fem.piezo import PZT5H
    return {'type': 'thermopiezoelectric', **PZT5H, 'alpha': ALPHA, 'p3': P3, 'T_ref': TREF, 'k': 1.5}


def open_circuit_voltage(h=H):
    """Case B exact: unknowns ε (6) and E3 with σ = 0 and D3 = 0. Returns V(top) − V(bottom) = −E3 h."""
    from app.design.services.fem.piezo import PiezoMaterial
    pm = PiezoMaterial(material())
    M, b = np.zeros((7, 7)), np.zeros(7)
    M[:6, :6], M[:6, 6] = pm.C, -pm.e[2]
    b[:6] = pm.C @ (ALPHA * DT * np.array([1, 1, 1, 0, 0, 0]))
    M[6, :6], M[6, 6], b[6] = pm.e[2], pm.kappa[2, 2], -P3 * DT
    return float(-np.linalg.solve(M, b)[6] * h)


def local(check):
    from app.design.services.fem import piezo as pz
    from app.design.services.fem.kernel import FEMKernel
    from app.design.services.fem.mesh import FEMMesh
    k = FEMKernel()
    mat = material()
    pm = pz.PiezoMaterial(mat)
    A = L * W
    m = FEMMesh.generate_cantilever(L, W, H, 6, order=2)
    m.node_sets['all'] = np.arange(m.n_nodes)
    z = m.nodes[:, 2]

    def run(bcs, material=mat, physics=('thermal', 'piezoelectric')):
        return k._solve(None, {'tier': 1, 'physics': list(physics), 'material': material, 'bcs': bcs,
                               'loads': []}, None, mesh=m)

    def charges(r):
        return [e['charge_C'] for e in r['summary']['piezo']['electrodes']]

    shorted = [{'face_set': 'z0', 'voltage': 0.0}, {'face_set': 'z1', 'voltage': 0.0}]
    print('── A. Empotrada y en cortocircuito, ΔT uniforme ─────────────────────────')
    r = run([{'face_set': '@all', 'temperature': TREF + DT}, {'node_set': 'all', 'dofs': [0, 1, 2]}] + shorted)
    s_ex = -(pm.C @ (ALPHA * DT * np.array([1, 1, 1, 0, 0, 0])))
    es = float(np.abs(np.array(r['sigma_elemental']) - s_ex).max() / np.abs(s_ex).max())
    q0, q1 = charges(r)
    eq = max(abs(q1 / (-P3 * DT * A) - 1), abs(q0 / (P3 * DT * A) - 1))
    print(f'   σxx = {s_ex[0] / 1e6:.4f} MPa, σzz = {s_ex[2] / 1e6:.4f} MPa; Q sup = {q1:.6e} C (−p3ΔTA = {-P3 * DT * A:.6e})')
    check(es < 1e-10, f'σ = −Cᴱ α ΔT (error {es:.1e})')
    check(eq < 1e-10, f'carga piroeléctrica de los electrodos (error {eq:.1e})')

    print('── B. Libre, circuito abierto, ΔT uniforme ──────────────────────────────')
    r = run([{'face_set': '@all', 'temperature': TREF + DT}, {'face_set': 'z0', 'voltage': 0.0},
             {'face_set': 'fixed', 'dofs': [0]}, {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'z0', 'dofs': [2]}])
    phi = np.asarray(r['extra_fields']['phi'])
    V, Vex = float(phi[np.isclose(z, H)].mean()), open_circuit_voltage()
    spread = float(np.ptp(phi[np.isclose(z, H)]))
    print(f'   V = {V:.10f} V  (exacta {Vex:.10f} V)')
    check(abs(V / Vex - 1) < 1e-10 and spread < 1e-8 * abs(Vex), f'tensión en circuito abierto (error {abs(V / Vex - 1):.1e})')

    print('── C. Empotrada, cortocircuito, T lineal en el espesor ──────────────────')
    r = run([{'face_set': 'z0', 'temperature': TREF}, {'face_set': 'z1', 'temperature': TREF + DT},
             {'node_set': 'all', 'dofs': [0, 1, 2]}] + shorted)
    phi = np.asarray(r['extra_fields']['phi'])
    phi_ex = (P3 * DT / pm.kappa[2, 2]) * (z ** 2 / (2 * H) - z / 2)
    ep = float(np.abs(phi - phi_ex).max() / np.abs(phi_ex).max())
    q0, q1 = charges(r)
    eq = max(abs(q0 / (P3 * DT * A / 2) - 1), abs(q1 / (-P3 * DT * A / 2) - 1))
    print(f'   φ(h/2) = {phi_ex[np.isclose(z, H / 2)][0]:.4f} V; Q inf = {q0:.6e} C (p3ΔTA/2 = {P3 * DT * A / 2:.6e})')
    check(ep < 1e-10, f'φ cuadrática exacta (error {ep:.1e})')
    check(eq < 1e-10, f'cargas ±p3ΔTA/2 (error {eq:.1e})')

    print('── D. ΔT = 0 equivale al piezoeléctrico; piezo + temperatura → error ─────')
    sup = [{'face_set': 'fixed', 'dofs': [0]}, {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'z0', 'dofs': [2]},
           {'face_set': 'z0', 'voltage': 0.0}, {'face_set': 'z1', 'voltage': 100.0}]
    r1 = run([{'face_set': '@all', 'temperature': TREF}] + sup)
    plain = {kk: v for kk, v in mat.items() if kk not in ('alpha', 'p3', 'T_ref', 'k')}
    plain['type'] = 'piezoelectric'
    r2 = run(sup, material=plain, physics=('piezoelectric',))
    du = float(np.abs(np.asarray(r1['displacement']) - np.asarray(r2['displacement'])).max()
               / np.abs(np.asarray(r2['displacement'])).max())
    check(du < 1e-10, f'desplazamientos iguales con ΔT = 0 (diferencia {du:.1e})')
    try:
        run([{'face_set': '@all', 'temperature': TREF + DT}] + sup, material=plain)
        check(False, 'piezoeléctrico sin α/p3 con temperatura debía fallar')
    except ValueError as e:
        check('termo' in str(e).lower(), f'error claro: {str(e)[:70]}…')


def server(check, S):
    import json
    import struct

    import requests
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO termo-piezo', 'tier': 1,
                                       'description': 'validate_thermopiezo.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    try:
        geo = add('GEOMETRY', 'Placa 10×10×1', {'shape': 'beam', 'length_mm': 10, 'width_mm': 10, 'height_mm': 1,
                                                 'n_div': 4, 'element_order': 2, 'tier': 1})
        mp = {('model_type' if k_ == 'type' else k_): v for k_, v in material().items()}
        mat = add('MATERIAL', 'PZT-5H termo', mp)
        bcs = [add('BC', 'Apoyo', {'bc_type': 'roller_z', 'face_set': 'z0'}),
               add('BC', 'Apoyo x', {'bc_type': 'roller_x', 'face_set': 'fixed'}),
               add('BC', 'Apoyo y', {'bc_type': 'roller_y', 'face_set': 'y0'}),
               add('BC', 'Tierra', {'bc_type': 'voltage', 'voltage': 0, 'face_set': 'z0'}),
               add('BC', 'T inferior', {'bc_type': 'temperature', 'temperature': TREF + DT, 'face_set': 'z0'}),
               add('BC', 'T superior', {'bc_type': 'temperature', 'temperature': TREF + DT, 'face_set': 'z1'})]
        for s, kind in [(mat, 'CONSTRAINS_MATERIAL')] + [(b, 'CONSTRAINS_BC') for b in bcs]:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': geo, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Termo-piezo' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 300:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run: {st.get('status')} {st.get('error') or ('' if rid else r.text[:200])}")
        if st.get('status') == 'done':
            surf = requests.get(f'{Vs}/{rid}/surface')
            hl = struct.unpack('<I', surf.content[:4])[0]
            hdr = json.loads(surf.content[4:4 + hl])
            ex = {x['key']: x for x in hdr.get('extra_fields', [])}
            Vex = open_circuit_voltage()
            phi = ex.get('phi', {})
            Vfe = phi.get('min') if Vex < 0 else phi.get('max')
            check('T' in ex and 'phi' in ex, f'campos extra {sorted(ex)}')
            check(Vfe is not None and abs(Vfe / Vex - 1) < 1e-6,
                  f'tensión en circuito abierto {Vfe} V (exacta {Vex:.6f} V)')
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
    print(f"\nHito termo-piezoeléctrico{' vía servidor' if args.server else ''}: {'CUMPLIDO' if ok else 'NO CUMPLIDO'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
