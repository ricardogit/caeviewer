"""Hito: steady incompressible Navier–Stokes (laminar), Taylor-Hood P2-P1 on T10, Picard + Newton.

  1. Kovasznay flow (exact 2-D solution, Re = 40) on a thin slab: velocity / pressure error and convergence order
     with refinement (P2/P1: ~3 / ~2), Newton converges quadratically
  2. plane Poiseuille with inertia on: (v·∇)v = 0 for fully developed flow → exact like Stokes (1e-8)
  3. Stokes limit: ρ → 0 gives the Stokes solution
  4. lid-driven cavity, Re = 100: centreline extrema vs the 1024² reference of Marchi, Suero & Araki (2009, Table 6:
     u_min −0.2140417, v_max 0.1795728, v_min −0.253804); Ghia et al. (1982, 129² grid) shown for information
     (it differs ~1.5–3.5 % from the converged values)

Usage: python validate_navier_stokes.py [--server http://127.0.0.1:8080]   (~1.5 min local)
"""
import argparse
import sys
import time
from math import pi, sqrt, log

import numpy as np

# Marchi, Suero & Araki, J. Braz. Soc. Mech. Sci. & Eng. 31(3) 2009, doi:10.1590/S1678-58782009000300004,
# Table 6, Re = 100 (1024² grid; estimated discretisation error of the extrema ~1e-6, positions ±4.9e-4)
MARCHI = {'umin': (-0.2140417, 0.45850), 'vmax': (0.179572814, 0.23682), 'vmin': (-0.253804, 0.81006)}
GHIA = {'umin': (-0.21090, 0.4531), 'vmax': (0.17527, 0.2344), 'vmin': (-0.24533, 0.8047)}


def slab(L, W, n, H=None):
    from app.design.services.fem.mesh import FEMMesh
    return FEMMesh.generate_cantilever(L, W, H or L / n, n, order=2)


def kernel(m, bcs, loads, mu, rho, inertia=True):
    from app.design.services.fem.kernel import FEMKernel
    mat = {'type': 'newtonian_fluid', 'mu': mu, 'rho': rho, **({'inertia': True} if inertia else {})}
    return FEMKernel()._solve(None, {'tier': 1, 'material': mat, 'bcs': bcs, 'loads': loads}, None, mesh=m)


def kovasznay(n, Re=40.0):
    from app.design.services.fem import stokes as st
    from app.design.services.fem.assembler import _face_tris
    lam = Re / 2 - sqrt(Re ** 2 / 4 + 4 * pi ** 2)
    m = slab(1.5, 2.0, n)
    m.nodes = m.nodes + np.array([-0.5, -0.5, 0.0])
    x, y = m.nodes[:, 0], m.nodes[:, 1]
    V = np.stack([1 - np.exp(lam * x) * np.cos(2 * pi * y), lam / (2 * pi) * np.exp(lam * x) * np.sin(2 * pi * y),
                  0 * x], 1)
    P = 0.5 * (1 - np.exp(2 * lam * x))
    presc = {}
    for fs in ('fixed', 'tip', 'y0', 'y1'):                  # exact velocity on the 2-D boundary
        for nd in np.unique(_face_tris(m, fs)):
            for c in range(3):
                presc[3 * nd + c] = V[nd, c]
    for fs in ('z0', 'z1'):                                  # slab faces: w = 0 (∂u/∂z = 0 is natural)
        for nd in np.unique(_face_tris(m, fs)):
            presc.setdefault(3 * nd + 2, 0.0)
    dofs = np.array(sorted(presc))
    vals = np.array([presc[d] for d in dofs])
    v, p, info = st.solve_ns(m, st.FluidMaterial({'mu': 1 / Re, 'rho': 1.0, 'inertia': True}),
                             np.zeros(3 * m.n_nodes), dofs, vals)
    ev = float(np.abs(v - V).max())
    ep = float(np.abs((p - p.mean()) - (P - P.mean())).max())
    return ev, ep, info['navier_stokes'], info['n_dof']


def cavity(n, Re=100.0):
    from app.design.services.validation.sensors import MeshProbe
    m = slab(1.0, 1.0, n)
    bcs = ([{'face_set': 'y1', 'dofs': [0, 1, 2], 'values': [1.0, 0, 0]}]          # lid u = 1
           + [{'face_set': f, 'dofs': [0, 1, 2]} for f in ('fixed', 'tip', 'y0')]  # walls (corners at rest)
           + [{'face_set': f, 'dofs': [2]} for f in ('z0', 'z1')])
    r = kernel(m, bcs, [], 1.0 / Re, 1.0)
    v = r['velocity']
    probe = MeshProbe(m.nodes, m.elements)
    s = np.linspace(0, 1, 1601)
    zc = 0.5 / n

    def line(pts, c):
        el, nat, _ = probe.locate(pts)
        return probe.displacement(v, el, nat)[:, c]
    u = line(np.stack([0.5 + 0 * s, s, zc + 0 * s], 1), 0)
    w = line(np.stack([s, 0.5 + 0 * s, zc + 0 * s], 1), 1)
    got = {'umin': (u.min(), s[u.argmin()]), 'vmax': (w.max(), s[w.argmax()]), 'vmin': (w.min(), s[w.argmin()])}
    return got, r['summary']


def local(check):
    print('── 1. Kovasznay (Re = 40, solución exacta) ─────────────────────────────')
    res = {}
    for n in (4, 8, 16):
        t = time.perf_counter()
        res[n] = kovasznay(n)
        ev, ep, ns, ndof = res[n]
        print(f'   n = {n:2d}: {ndof:6d} incógnitas, {ns["picard_iterations"]} Picard + {ns["newton_iterations"]} '
              f'Newton, error |v| {ev:.3e}, error p {ep:.3e}  ({time.perf_counter() - t:.0f} s)')
    ov = log(res[8][0] / res[16][0]) / log(2)
    op = log(res[8][1] / res[16][1]) / log(2)
    check(res[16][0] < 2.5e-3 and ov > 2.5, f'velocidad: error {res[16][0]:.2e} (n = 16), orden {ov:.2f} (P2: ~3)')
    check(op > 1.7, f'presión: orden {op:.2f} (P1: ~2)')
    rr = res[16][2]['newton_residuals']
    quad = all(b <= 10 * a ** 1.6 for a, b in zip(rr, rr[1:]) if a < 1e-3 and b > 1e-14)
    check(rr[-1] < 1e-12 and quad, 'Newton cuadrático: residuos ' + ' → '.join(f'{x:.1e}' for x in rr))

    print('── 2. Poiseuille plano con inercia ─────────────────────────────────────')
    L, W, H, dp, mu, rho = 4e-3, 2e-3, 1e-3, 2.0, 1e-3, 1000.0      # water, Re ≈ 60
    m = slab(L, W, 8, H)
    walls = [{'face_set': 'z0', 'dofs': [0, 1, 2]}, {'face_set': 'z1', 'dofs': [0, 1, 2]},
             {'face_set': 'y0', 'dofs': [1]}, {'face_set': 'y1', 'dofs': [1]},
             {'face_set': 'fixed', 'dofs': [1, 2]}, {'face_set': 'tip', 'dofs': [1, 2]}]
    r = kernel(m, walls, [{'face_set': 'fixed', 'pressure': dp}], mu, rho)
    z = m.nodes[:, 2]
    u_th = dp / (2 * mu * L) * z * (H - z)
    f = r['summary']['fluid']
    e = max(np.abs(r['velocity'][:, 0] - u_th).max() / u_th.max(), np.abs(r['velocity'][:, 1:]).max() / u_th.max())
    print(f'   Re = {f["reynolds"]:.0f}, u máx {r["velocity"][:, 0].max():.4f} m/s, '
          f'{f["navier_stokes"]["iterations"]} iteraciones')
    check(e < 1e-8 and f['model'] == 'navier_stokes', f'perfil parabólico exacto con inercia (error {e:.1e})')

    print('── 3. Límite de Stokes (ρ → 0) ─────────────────────────────────────────')
    rs = kernel(m, walls, [{'face_set': 'fixed', 'pressure': dp}], 1.41, 1e-6, inertia=False)
    rn = kernel(m, walls, [{'face_set': 'fixed', 'pressure': dp}], 1.41, 1e-6)
    d = np.abs(rn['velocity'] - rs['velocity']).max() / np.abs(rs['velocity']).max()
    check(d < 1e-8, f'Navier-Stokes con ρ ≈ 0 = Stokes (diferencia {d:.1e})')

    print('── 4. Cavidad con tapa móvil, Re = 100 ─────────────────────────────────')
    t = time.perf_counter()
    got, s = cavity(16)
    ns = s['fluid']['navier_stokes']
    print(f'   {s["n_dof"]} incógnitas, {ns["picard_iterations"]} Picard + {ns["newton_iterations"]} Newton, '
          f'Re de elemento {ns["element_reynolds_max"]:.1f}  ({time.perf_counter() - t:.0f} s)')
    for k, lbl in (('umin', 'u mín. (x = 0.5)'), ('vmax', 'v máx. (y = 0.5)'), ('vmin', 'v mín. (y = 0.5)')):
        val, pos = got[k]
        ref, rpos = MARCHI[k]
        g = GHIA[k][0]
        err = abs(val / ref - 1)
        check(err < 5e-3 and abs(pos - rpos) < 0.02,
              f'{lbl} = {val:.5f} en {pos:.3f}: ref. 1024² {ref:.5f} en {rpos:.3f} ({100 * err:.2f} %); '
              f'Ghia {g:.5f} ({100 * abs(val / g - 1):.1f} %)')


def server(check, S):
    import json
    import struct
    import requests
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    gid = requests.post(f'{G}/', json={'name': 'HITO Navier-Stokes', 'tier': 1,
                                       'description': 'validate_navier_stokes.py'}).json()['id']
    add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
        'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
    L, W, H, dp, mu = 4e-3, 2e-3, 1e-3, 2.0, 1.002e-3            # water, Re ≈ 60
    try:
        geo = add('GEOMETRY', 'Canal 4×2×1', {'shape': 'beam', 'length_mm': 4, 'width_mm': 2, 'height_mm': 1,
                                              'n_div': 8, 'element_order': 2, 'tier': 1})
        mat = add('MATERIAL', 'Agua', {'model_type': 'newtonian_fluid', 'mu': mu, 'rho': 998,
                                       'flow_model': 'navier_stokes'})
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
        check('Navier-Stokes' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        rid = r.json().get('run_id')
        t0, st = time.perf_counter(), {}
        while rid and time.perf_counter() - t0 < 300:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed', 'cancelled'):
                break
            time.sleep(1)
        check(st.get('status') == 'done',
              f"run: {st.get('status')} {st.get('error') or ''} {r.text[:200] if not rid else ''}")
        if st.get('status') == 'done':
            surf = requests.get(f'{Vs}/{rid}/surface')
            hl = struct.unpack('<I', surf.content[:4])[0]
            hdr = json.loads(surf.content[4:4 + hl])
            fl = hdr['summary']['fluid']
            q = next(f['flow_m3_s'] for f in fl['flow_rates'] if f['face_set'] == 'tip')
            Q_th = dp * W * H ** 3 / (12 * mu * L)
            check(fl.get('model') == 'navier_stokes' and abs(q / Q_th - 1) < 1e-8,
                  f'modelo {fl.get("model")}, caudal {q:.6e} m³/s (teoría {Q_th:.6e}), Re = {fl["reynolds"]:.0f}, '
                  f'{fl["navier_stokes"]["iterations"]} iteraciones')
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
        label = 'Hito Navier-Stokes vía servidor'
    else:
        local(check)
        label = 'Hito Navier-Stokes'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
