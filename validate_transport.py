"""Hito FASE 10.1 + 10.2: advection–diffusion–reaction transport (SUPG, θ-method / BDF2) on T10.

  1. Ogata–Banks: continuous inlet c = 1 into a semi-infinite channel, element Péclet > 10 (SUPG): max error
     < 1 % and discrete mass balance < 1e-6 (the budget is exact by construction: 1e-15)
  2. Gaussian pulse advected with decay λ: error < 1 % of the initial peak, mass m(t) = m0 e^(−λt)
  3. 3-D plume of a continuous point source in uniform flow vs Q/(4πDr)·exp(−v(r − x)/2D): < 2 % at ≥ 3σ_mesh
     downstream (SUPG) and < 1 % (Galerkin); source rate = outflow (steady balance)
  4. Streeter–Phelps: batch reactor (BOD → oxygen deficit, reaeration) vs the exact ODE solution, time order
     BE 1 / CN 2 / BDF2 2; plug-flow river (steady) vs L0e^(−kd x/v) and the oxygen-sag curve, critical deficit
  5. imposed flux + exchange k(c_ext − c) on another face (no flow): linear profile, exact
Server (worker running): a slip-wall Stokes run gives a uniform velocity; a transport study takes it with
``velocity_source: run`` → Ogata–Banks at control points through the job queue, time steps in /surface.

Usage: python validate_transport.py [--server http://127.0.0.1:8080]
"""
import argparse
import sys
import time

import numpy as np
from scipy.special import erfc, erfcx

from app.design.services.fem import transport as tr
from app.design.services.fem.mesh import FEMMesh


def ogata_banks(x, t, v, D):
    """c/c0 for c(0, t) = c0, c(x, 0) = 0 (second term with erfcx: exp(vx/D)·erfc(b) overflows otherwise)."""
    a = (x - v * t) / (2 * np.sqrt(D * t))
    b = (x + v * t) / (2 * np.sqrt(D * t))
    return 0.5 * (erfc(a) + np.exp(v * x / D - b * b) * erfcx(b))


def channel(n, h_rel=2.0, L=1.0, order=2):
    h = L / n
    return FEMMesh.generate_cantilever(L, h_rel * h, h_rel * h, n, order=order), h


def case_ogata_banks(check):
    print('\n1. Ogata–Banks (entrada continua), T10, Péclet de malla > 10')
    v, T = 1.0, 0.75
    mesh, h = channel(40)
    D = v * h / 24
    out = {}
    for stab in ('supg', 'none'):
        m = tr.TransportModel({'species': [{'D': D}], 'velocity': [v, 0, 0], 'stabilization': stab})
        snaps, info = tr.solve(mesh, m, [{'concentration': 1.0, 'face_set': 'fixed'}], [],
                               time={'t_end': T, 'n_steps': 600, 'scheme': 'bdf2', 'n_output': 1})
        err = np.abs(snaps[-1][1] - ogata_banks(mesh.nodes[:, 0], T, v, D)).max()
        out[stab] = (err, info, tr.peclet_max(info['problem']))
    err, info, Pe = out['supg']
    check(Pe > 10 and err < 0.01, f'SUPG: Pe_h {Pe:.1f}, error máx {err * 100:.3f} % del valor de entrada '
                                  f'(Galerkin {out["none"][0] * 100:.3f} %)')
    mex = 0.0
    xs = np.linspace(0, 1, 20001)
    mex = np.trapz(ogata_banks(xs, T, v, D), xs) * (2 * h) ** 2
    check(info['mass_balance_error'] < 1e-6 and abs(info['mass_final'][0] / mex - 1) < 1e-6,
          f"balance de masa {info['mass_balance_error']:.1e}; masa {info['mass_final'][0]:.6e} vs exacta {mex:.6e}")


def case_pulse(check):
    print('\n2. Pulso gaussiano con decaimiento de primer orden')
    v, D, lam, T, x0, s0 = 1.0, 5e-4, 0.5, 0.5, 0.2, 0.03
    mesh, h = channel(60)
    x = mesh.nodes[:, 0]
    c0 = np.exp(-(x - x0) ** 2 / (2 * s0 ** 2))
    m = tr.TransportModel({'species': [{'D': D, 'decay': lam}], 'velocity': [v, 0, 0]})
    snaps, info = tr.solve(mesh, m, [{'concentration': 0.0, 'face_set': 'fixed'}], [],
                           time={'t_end': T, 'n_steps': 500, 'scheme': 'bdf2', 'n_output': 5}, initial=[c0])
    s2 = s0 ** 2 + 2 * D * T
    ce = s0 / np.sqrt(s2) * np.exp(-(x - x0 - v * T) ** 2 / (2 * s2) - lam * T)
    err = np.abs(snaps[-1][1] - ce).max()
    Pe = tr.peclet_max(info['problem'])
    check(Pe > 10 and err < 0.01, f'Pe_h {Pe:.1f}, error máx {err * 100:.3f} % del pico inicial '
                                  f'(pico {snaps[-1][1].max():.5f} vs {ce.max():.5f})')
    ratio = info['mass_final'][0] / info['mass_initial'][0]
    check(abs(ratio / np.exp(-lam * T) - 1) < 1e-4 and info['mass_balance_error'] < 1e-6,
          f"m(T)/m0 {ratio:.7f} vs e^(−λT) {np.exp(-lam * T):.7f}; balance {info['mass_balance_error']:.1e}, "
          f"desintegrado {info['budget']['reaction_out'][0]:.4e}")


def case_plume(check):
    print('\n3. Pluma 3-D de una fuente puntual continua en flujo uniforme')
    D, v, Q = 0.004, 1.0, 1.0
    xs = np.array([0.2, 0.2, 0.2])
    mesh = FEMMesh.generate_cantilever(1.0, 0.4, 0.4, 30, order=2)
    probes = [{'point': (xs + [d, oy, oz]).tolist()} for d in (0.3, 0.5, 0.7)
              for oy, oz in ((0, 0), (0.05, 0), (0.03, 0.04))]

    def exact(p):
        d = np.asarray(p) - xs
        r = np.linalg.norm(d)
        return Q / (4 * np.pi * D * r) * np.exp(-v * (r - d[0]) / (2 * D))

    for stab, tol in (('supg', 0.02), ('none', 0.01)):
        m = tr.TransportModel({'species': [{'D': D}], 'velocity': [v, 0, 0], 'stabilization': stab})
        snaps, info = tr.solve(mesh, m, [{'concentration': 0.0, 'face_set': 'fixed'}],
                               [{'point_source': {'point': xs.tolist(), 'rate': Q}}], probes=probes)
        rel = [abs(val[0] / exact(p['point']) - 1) for p, val in zip(probes, info['curves'][0][1:])]
        r = info['rates']
        check(max(rel) < tol, f'{stab}: error relativo máx {max(rel) * 100:.2f} % en {len(rel)} puntos a 0.3–0.7 m '
                              f'(Pe_h {tr.peclet_max(info["problem"]):.1f})')
    check(info['mass_balance_error'] < 1e-10 and abs(r['source'][0] + r['boundary_in'][0] - r['advection_out'][0]) < 1e-9,
          f"vertido {r['source'][0]:.6f} = salida advectiva {r['advection_out'][0]:.6f} + salida por difusión aguas "
          f"arriba {-r['boundary_in'][0]:.2e}")


def sp_exact(t, kd, ka, L0, D0):
    return L0 * np.exp(-kd * t), kd * L0 / (ka - kd) * (np.exp(-kd * t) - np.exp(-ka * t)) + D0 * np.exp(-ka * t)


def case_streeter_phelps(check):
    print('\n4. Streeter–Phelps (DBO → déficit de oxígeno, reaireación)')
    kd, ka, L0, D0 = 0.3, 0.7, 20.0, 1.0
    spec = {'species': [{'name': 'DBO', 'D': 1e-3}, {'name': 'déficit', 'D': 1e-3}],
            'reaction': {'model': 'streeter_phelps', 'kd': kd, 'ka': ka, 'do_sat': 9.0}}
    mesh = FEMMesh.generate_cantilever(0.1, 0.05, 0.05, 2, order=2)
    n, T = mesh.n_nodes, 5.0
    Le, De = sp_exact(T, kd, ka, L0, D0)
    for scheme, order in (('be', 1), ('cn', 2), ('bdf2', 2)):
        errs = []
        for nst in (20, 40, 80):
            snaps, info = tr.solve(mesh, tr.TransportModel(spec), [], [],
                                   time={'t_end': T, 'n_steps': nst, 'scheme': scheme}, initial=[{'value': L0}, {'value': D0}])
            x = snaps[-1][1]
            errs.append(max(np.abs(x[:n] - Le).max(), np.abs(x[n:] - De).max()) / L0)
        rate = np.log2(errs[1] / errs[2])
        check(abs(rate - order) < 0.15 and info['mass_balance_error'] < 1e-10,
              f'reactor {scheme}: error {errs[-1]:.2e} con 80 pasos, orden {rate:.2f} (teórico {order})')
    v, Lc = 0.5, 10.0
    mesh = FEMMesh.generate_cantilever(Lc, 0.5, 0.5, 40, order=2)
    n = mesh.n_nodes
    m = tr.TransportModel({**spec, 'species': [{'name': 'DBO', 'D': 0.0}, {'name': 'déficit', 'D': 0.0}],
                           'velocity': [v, 0, 0]})
    snaps, info = tr.solve(mesh, m, [{'concentration': L0, 'face_set': 'fixed', 'species': 0},
                                     {'concentration': D0, 'face_set': 'fixed', 'species': 1}], [])
    x = snaps[0][1]
    Le, De = sp_exact(mesh.nodes[:, 0] / v, kd, ka, L0, D0)
    eL, eD = np.abs(x[:n] - Le).max() / L0, np.abs(x[n:] - De).max() / De.max()
    tc = np.log(ka / kd * (1 - D0 * (ka - kd) / (kd * L0))) / (ka - kd)
    Dc = kd / ka * L0 * np.exp(-kd * tc)
    i = int(np.argmax(x[n:]))
    check(eL < 2e-3 and eD < 5e-3 and abs(x[n + i] / Dc - 1) < 2e-3 and abs(mesh.nodes[i, 0] - v * tc) < Lc / 40,
          f'río (flujo pistón): error DBO {eL * 100:.3f} %, déficit {eD * 100:.3f} %; déficit crítico '
          f'{x[n + i]:.4f} vs {Dc:.4f} en x = {mesh.nodes[i, 0]:.3f} m (teoría {v * tc:.3f} m)')


def case_flux_exchange(check):
    print('\n5. Flujo impuesto + intercambio con el exterior (sin flujo)')
    D, q, k, L = 2e-3, 0.5, 0.1, 0.2
    for order in (1, 2):
        mesh = FEMMesh.generate_cantilever(L, 0.05, 0.05, 6, order=order)
        m = tr.TransportModel({'species': [{'D': D}]})
        snaps, info = tr.solve(mesh, m, [], [{'species_flux': q, 'face_set': 'tip'},
                                             {'exchange': {'k': k, 'c_ext': 0.0}, 'face_set': 'fixed'}])
        ce = q / k + q * mesh.nodes[:, 0] / D
        err = np.abs(snaps[0][1] - ce).max() / ce.max()
        r = info['rates']
        check(err < 1e-10 and abs(r['exchange_out'][0] / r['source'][0] - 1) < 1e-10,
              f'T{4 if order == 1 else 10}: perfil lineal c = q/k + qx/D, error {err:.1e}; intercambio '
              f'{r["exchange_out"][0]:.6e} = flujo {r["source"][0]:.6e}')


def local(check):
    for case in (case_ogata_banks, case_pulse, case_plume, case_streeter_phelps, case_flux_exchange):
        t0 = time.perf_counter()
        case(check)
        print(f'   ({time.perf_counter() - t0:.1f} s)')


# ── Server ────────────────────────────────────────────────────────────────────

def _run(S, gid, label, check, timeout=600):
    import requests
    Vs = f'{S}/api/design/solver'
    r = requests.post(f'{Vs}/{gid}/run', json={})
    rid = r.json().get('run_id')
    t0, st = time.perf_counter(), {}
    while rid and time.perf_counter() - t0 < timeout:
        st = requests.get(f'{Vs}/{rid}/status').json()
        if st.get('status') in ('done', 'failed', 'cancelled'):
            break
        time.sleep(1)
    check(st.get('status') == 'done', f"{label}: {st.get('status')} {st.get('error') or ''} "
                                      f"{r.text[:300] if not rid else ''}")
    return rid if st.get('status') == 'done' else None


def server(check, S):
    import json
    import struct
    import requests
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    U, Lmm, Wmm, n_div = 0.01, 1000, 50, 40
    beam = {'shape': 'beam', 'length_mm': Lmm, 'width_mm': Wmm, 'height_mm': Wmm, 'n_div': n_div,
            'element_order': 2, 'tier': 1}
    gids = []

    def study(name):
        gid = requests.post(f'{G}/', json={'name': name, 'tier': 1, 'description': 'validate_transport.py'}).json()['id']
        gids.append(gid)
        add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
            'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
        return gid, add

    def link(gid, geo, mat, bcs, loads=()):
        for s, kind in [(mat, 'CONSTRAINS_MATERIAL')] + [(b, 'CONSTRAINS_BC') for b in bcs] + \
                [(ld, 'APPLIED_TO') for ld in loads]:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': geo, 'edge_type': kind})

    try:
        # 1. slip-wall channel: Stokes gives v = (U, 0, 0) exactly
        gid, add = study('HITO transporte · canal (fluido)')
        geo = add('GEOMETRY', 'Canal 1000×50×50', beam)
        mat = add('MATERIAL', 'Agua', {'model_type': 'newtonian_fluid', 'mu': 1e-3, 'rho': 1000})
        bcs = [add('BC', 'Entrada', {'bc_type': 'velocity', 'vx': U, 'vy': 0, 'vz': 0, 'face_set': 'fixed'})]
        for f, t in (('y0', 'roller_y'), ('y1', 'roller_y'), ('z0', 'roller_z'), ('z1', 'roller_z')):
            bcs.append(add('BC', f'Pared {f} (deslizamiento)', {'bc_type': t, 'face_set': f}))
        link(gid, geo, mat, bcs)
        fluid_run = _run(S, gid, 'run de fluido (paredes deslizantes)', check)
        if not fluid_run:
            return
        # 2. transport study on that velocity: Ogata–Banks
        h = Lmm / 1000 / n_div
        D = U * h / 24
        T = 0.75 / U
        gid2, add = study('HITO transporte · Ogata–Banks')
        geo = add('GEOMETRY', 'Canal 1000×50×50', beam)
        probes = [{'label': f'x{x}', 'x': x, 'y': 25, 'z': 25} for x in (600, 700, 750, 800, 900)]
        mat = add('MATERIAL', 'Trazador', {'model_type': 'scalar_transport', 'velocity_source': 'run',
                                           'velocity_run_id': fluid_run,
                                           'species': [{'name': 'Trazador', 'D': D, 'unit': 'mg/L', 'threshold': 0.5}],
                                           'transient': True, 't_end': T, 'time_steps': 600, 'scheme': 'bdf2',
                                           'n_output': 15, 'probes': probes})
        bc = add('BC', 'Entrada c = 1', {'bc_type': 'concentration', 'concentration': 1.0, 'face_set': 'fixed'})
        link(gid2, geo, mat, [bc])
        pf = requests.get(f'{Vs}/{gid2}/preflight').json()
        check('Transporte' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        rid = _run(S, gid2, 'run de transporte (velocidad del run de fluido)', check)
        if not rid:
            return
        summ = requests.get(f'{Vs}/{rid}/results').json().get('summary') or {}
        tp = summ.get('transport') or {}
        check(tp.get('velocity', {}).get('source') == 'run' and tp.get('mass_balance_error', 1) < 1e-6,
              f"velocidad del run {str(tp.get('velocity', {}).get('run_id'))[:8]}…, balance de masa "
              f"{tp.get('mass_balance_error')}")
        errs = []
        for p in tp.get('probes') or []:
            t_last, c_last = p['curve'][-1][0], p['curve'][-1][1]
            errs.append(abs(c_last - ogata_banks(p['point'][0], t_last, U, D)))
        check(errs and max(errs) < 0.01, f'puntos de control: error máx {max(errs or [1]) * 100:.3f} % (Ogata–Banks)')
        surf = requests.get(f'{Vs}/{rid}/surface', params={'step': 3})
        hl = struct.unpack('<I', surf.content[:4])[0]
        hdr = json.loads(surf.content[4:4 + hl])
        ex = {x['key']: x for x in hdr.get('extra_fields', [])}
        check(len(hdr.get('times') or []) == 16 and hdr.get('step') == 3 and ex.get('c0', {}).get('series'),
              f"/surface: {len(hdr.get('times') or [])} instantes, paso {hdr.get('step')}, campos {sorted(ex)}")
    finally:
        for gid in reversed(gids):
            requests.delete(f'{G}/{gid}', params={'cascade': 1})


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
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
        label = 'Hito de transporte vía servidor'
    else:
        local(check)
        label = 'Hito de transporte (FASE 10.1 + 10.2)'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
