"""
Hito FASE 9 — "Flujo completo conceptual → grafo → simulación → resultado en UI unificada".

Recorre por HTTP exactamente lo que hace la interfaz unificada (servidor + worker en marcha):
  1. concepto: nuevo estudio (DesignGraph) con un nodo CONCEPT
  2. grafo: GEOMETRY (viga paramétrica 500 × 25 × 25 mm, T10), MATERIAL (acero), BC empotrada
     y LOAD de 1 kN en el extremo, con sus aristas semánticas
  3. estado del estudio (franja §9.4 / TopBar): /preflight → listo, física, tier estimado ≤ declarado
  4. simulación: POST /run (cola de jobs → worker) y espera a 'done'
  5. resultado: /runs (lista del modo Resultados) y /surface (pack binario del visor 3D): la
     flecha en el extremo dentro del 2 % de Timoshenko, superficie cerrada, unidades mm/MPa
  6. la SPA unificada se sirve en /step-view/ con el modo "Resultados" en el bundle
El estudio de prueba se borra al final (--keep para conservarlo y abrirlo en la UI).

Uso:  python run.py  ·  python -m app.jobs.worker --queues default,solve
      python validate_workflow.py [--server http://127.0.0.1:8080] [--keep]
"""
import argparse
import json
import re
import struct
import sys
import time

import numpy as np
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

L, B, H, F, E, NU = 0.5, 0.025, 0.025, 1000.0, 210e9, 0.3


def parse_pack(buf: bytes) -> tuple[dict, dict]:
    n = struct.unpack('<I', buf[:4])[0]
    head = json.loads(buf[4:4 + n])
    start = 4 + n + (-(4 + n)) % 4
    arrays = {}
    for a in head['arrays']:
        cnt = int(np.prod(a['shape']))
        arrays[a['name']] = np.frombuffer(buf, dtype=a['dtype'], count=cnt, offset=start + a['offset']).reshape(a['shape'])
    return head, arrays


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server', default='http://127.0.0.1:8080')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--timeout', type=float, default=300)
    args = ap.parse_args()
    S = args.server.rstrip('/')
    G = f'{S}/api/design/graph'
    V = f'{S}/api/design/solver'
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}")

    t0 = time.perf_counter()
    print('── 1. Concepto ─────────────────────────────────────────────────────────')
    g = requests.post(f'{G}/', json={'name': 'HITO F9 viga en voladizo', 'tier': 1,
                                     'description': 'validate_workflow.py'}).json()
    gid = g['id']
    add = lambda t, label, props, x, y: requests.post(f'{G}/{gid}/nodes', json={
        'node_type': t, 'label': label, 'properties': props, 'pos_x': x, 'pos_y': y}).json()['node_id']
    concept = add('CONCEPT', 'Soporte en voladizo', {'description': 'Ménsula que soporta 1 kN en su extremo'}, 0, 0)
    check(gid and concept, f'estudio {gid[:8]} con nodo CONCEPT')

    print('── 2. Grafo ────────────────────────────────────────────────────────────')
    geo = add('GEOMETRY', 'Viga 500×25×25', {'shape': 'beam', 'length_mm': L * 1000, 'width_mm': B * 1000,
                                             'height_mm': H * 1000, 'n_div': 20, 'element_order': 2, 'tier': 1}, 250, 0)
    mat = add('MATERIAL', 'Acero', {'model_type': 'linear_elastic_isotropic', 'E': E, 'nu': NU, 'rho': 7850}, 0, 150)
    bc = add('BC', 'Empotramiento', {'bc_type': 'fixed'}, 250, 150)
    ld = add('LOAD', 'Carga extremo', {'load_type': 'force', 'magnitude': F, 'unit': 'N',
                                        'dir_x': 0, 'dir_y': 0, 'dir_z': -1}, 500, 150)
    edges = [(concept, geo, 'FUNCTIONAL'), (mat, geo, 'CONSTRAINS_MATERIAL'), (bc, geo, 'CONSTRAINS_BC'),
             (ld, geo, 'APPLIED_TO')]
    codes = [requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': t, 'edge_type': k}).status_code
             for s, t, k in edges]
    check(all(c == 201 for c in codes), f'5 nodos y {len(edges)} aristas semánticas ({codes})')
    v = requests.get(f'{G}/{gid}/validate').json()
    check(v['ready_for_simulation'], f"validación del grafo: {v['error_count']} errores, {v['warning_count']} avisos")

    print('── 3. Estado del estudio (TopBar / franja §9.4) ───────────────────────')
    p = requests.get(f'{V}/{gid}/preflight').json()
    print(f"   física: {p['physics_label']} · tamaño ≈ {p['size']['n_dof']:,} DOF · tier necesario "
          f"{p['tier_needed']} / declarado {p['tier_declared']} · confianza {p['confidence']}")
    check(p['ready'] and p['tier_ok'] and p['mesh_source'] == 'cantilever', 'preflight: listo y dentro del tier')

    print('── 4. Simulación ───────────────────────────────────────────────────────')
    r = requests.post(f'{V}/{gid}/run', json={'physics': ['structural']})
    check(r.status_code in (200, 201, 202), f'POST /run → {r.status_code}')
    run_id = r.json()['run_id']
    t1 = time.perf_counter()
    status = 'queued'
    while time.perf_counter() - t1 < args.timeout:
        status = requests.get(f'{V}/{run_id}/status').json().get('status')
        if status in ('done', 'failed', 'cancelled'):
            break
        time.sleep(1)
    check(status == 'done', f'run {run_id[:8]}: {status} en {time.perf_counter() - t1:.1f} s (worker)')
    if status != 'done':
        print('   ¿está el worker en marcha?  python -m app.jobs.worker --queues default,solve')
        return finish(ok, S, gid, args.keep)

    print('── 5. Resultado (modo Resultados) ─────────────────────────────────────')
    runs = requests.get(f'{V}/runs', params={'graph_id': gid}).json()['runs']
    check(any(x['run_id'] == run_id and x['status'] == 'done' for x in runs), 'el run aparece en la lista del estudio')
    resp = requests.get(f'{V}/{run_id}/surface')
    head, a = parse_pack(resp.content)
    xyz, tris, u, vm = a['xyz'], a['tris'], a['u'], a['vm']
    tip = xyz[:, 0] > L * 1000 - 1e-3
    w_tip = float(-u[tip, 2].mean())
    I = B * H ** 3 / 12
    G_ = E / (2 * (1 + NU))
    w_timo = (F * L ** 3 / (3 * E * I) + F * L / (5 / 6 * G_ * B * H)) * 1000
    err = w_tip / w_timo - 1
    sigma_beam = F * L * (H / 2) / I / 1e6
    print(f"   pack {len(resp.content) / 1024:.0f} KB · {head['n_surface_nodes']:,} nodos · {head['n_triangles']:,} "
          f"triángulos · elemento {head['summary'].get('element_type')}")
    check(head['summary'].get('element_type') == 'T10', 'malla T10 desde el nodo GEOMETRY')
    check(abs(err) < 0.02, f'flecha en el extremo {w_tip:.4f} mm vs Timoshenko {w_timo:.4f} mm ({100 * err:+.2f} %)')
    edges_count = {}
    for t in tris:
        for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = (min(i, j), max(i, j))
            edges_count[k] = edges_count.get(k, 0) + 1
    check(all(c == 2 for c in edges_count.values()), 'superficie cerrada (cada arista en 2 triángulos)')
    vm_root = float(vm[xyz[:, 0] < 25].max())
    print(f"   σvM máx. {head['max_vm_mpa']:.1f} MPa (cerca del empotramiento {vm_root:.1f}; viga Mc/I = {sigma_beam:.1f} MPa,"
          f" con concentración en las esquinas empotradas)")
    check(head['units'] == {'xyz': 'mm', 'u': 'mm', 'vm': 'MPa'} and vm_root > 0.8 * sigma_beam, 'unidades y orden de σ')

    print('── 6. UI unificada ─────────────────────────────────────────────────────')
    html = requests.get(f'{S}/step-view/').text
    js = re.findall(r'assets/(index-[\w-]+\.js)', html)
    found = bool(js) and 'Ver resultados 3D' in requests.get(f'{S}/step-view/assets/{js[0]}').text
    check(found, f'SPA servida en /step-view/ ({js[0] if js else "sin bundle"}) con el modo Resultados')
    print(f'\nFlujo completo en {time.perf_counter() - t0:.1f} s')
    return finish(ok, S, gid, args.keep)


def finish(ok, S, gid, keep):
    if keep:
        print(f'Estudio conservado: {gid} (ábrelo en Design → Proyectos o en Resultados)')
    else:
        r = requests.delete(f'{S}/api/design/graph/{gid}', params={'cascade': 1})
        print(f'Estudio de prueba borrado ({r.status_code})' if r.ok else
              f'No se pudo borrar el estudio {gid} ({r.status_code}): {r.text[:200]}')
    print('\nHITO FASE 9:', 'CUMPLIDO' if ok else 'NO CUMPLIDO')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
