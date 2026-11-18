"""Hito FASE 10.6: groundwater flow (Darcy) and contaminant transport in an aquifer, on T10.

  1. Thiem: steady pumping well in a confined aquifer (quarter sector, log-graded radial mesh, fixed head at R):
     h(r) = h_R − Q/(2πKb) ln(R/r), error < 0.2 % of the well drawdown, second-order convergence
  2. Theis: transient pumping test (variable-step BDF2, growing Δt), drawdown vs Q/(4πT) W(u) at 1, 10 and 50 m
     before the cone reaches the far boundary: < 0.5 %; water budget (storage change = pumped − boundary inflow)
     exact (round-off)
  3. Recharge on top draining through a leaky bed (river / aquitard) and two K zones in series: exact (linear
     head), flow through the outlet = harmonic K
  4. Aquifer transport: Ogata–Banks with retardation R = 2 and longitudinal dispersion α_L (< 1 %), anisotropic
     Gaussian pulse (α_L ≠ α_T, R, decay on dissolved + sorbed mass) vs the exact solution (< 1 %), total mass
     m0 e^(−λt)
  5. Coupling: the Darcy flux of a head drop drives the transport (v = q/n_e) → Ogata–Banks front
Server (worker running): a Darcy study (beam aquifer, heads on both ends) → transport study with
``velocity_source: run`` (porosity taken from the Darcy run) → control points vs Ogata–Banks through the job queue.

Usage: python validate_darcy.py [--server http://127.0.0.1:8080]
(set OPENBLAS_NUM_THREADS=1 on a loaded Windows machine: OpenBLAS threading slows tiny batched solves ×60)
"""
import argparse
import sys
import time

import numpy as np
from scipy.special import exp1

from app.design.services.fem import darcy as dc
from app.design.services.fem import transport as tr
from app.design.services.fem.mesh import FEMMesh
from validate_transport import ogata_banks


def sector(P):
    r, t = P[:, 0], P[:, 1]
    return np.column_stack([r * np.cos(t), r * np.sin(t), P[:, 2]])


def well_mesh(rw, R, b, nr, nt=12):
    return FEMMesh.generate_grid(np.geomspace(rw, R, nr + 1), np.linspace(0, np.pi / 2, nt + 1), [0, b], transform=sector)


def case_thiem(check):
    print('1. Thiem (pozo en acuífero confinado, estacionario)')
    rw, R, b, K, Q = 0.1, 1000.0, 10.0, 1e-4, 0.01
    errs = []
    for nr in (20, 40):
        m = well_mesh(rw, R, b, nr)
        snaps, info = dc.solve(m, dc.PorousMedium({'K': K}), [{'hydraulic_head': 0.0, 'face_set': 'x1'}],
                               [{'well': {'rate': Q / 4}, 'face_set': 'x0'}])
        r = np.hypot(m.nodes[:, 0], m.nodes[:, 1])
        ex = -Q / (2 * np.pi * K * b) * np.log(R / r)
        errs.append(np.abs(snaps[0][1] - ex).max() / np.abs(ex).max())
    s_w = Q / (2 * np.pi * K * b) * np.log(R / rw)
    check(errs[-1] < 2e-3, f'n_r = 40: error máx {errs[-1] * 100:.3f} % del descenso en el pozo ({s_w:.3f} m)')
    order = np.log2(errs[0] / errs[1])
    check(order > 1.8, f'orden de convergencia {order:.2f} (n_r 20 → 40)')
    check(info['balance_error'] < 1e-10, f"balance: bombeo {info['rates']['well_out']:.6f} = entrada por el contorno "
                                         f"{info['rates']['boundary_in']:.6f} m³/s (error {info['balance_error']:.1e})")


def case_theis(check):
    print('2. Theis (ensayo de bombeo transitorio)')
    rw, R, b, K, Ss, Q = 0.1, 10_000.0, 10.0, 1e-4, 1e-5, 0.01
    T, S = K * b, Ss * b
    m = well_mesh(rw, R, b, 50)
    rs = (1.0, 10.0, 50.0)
    snaps, info = dc.solve(m, dc.PorousMedium({'K': K, 'Ss': Ss}), [{'hydraulic_head': 0.0, 'face_set': 'x1'}],
                           [{'well': {'rate': Q / 4}, 'face_set': 'x0'}],
                           time={'t_end': 86_400.0, 'n_steps': 80, 'dt_growth': 1.08, 'n_output': 10},
                           probes=[{'point': [r / np.sqrt(2), r / np.sqrt(2), b / 2]} for r in rs])
    worst = 0.0
    for row in info['curves']:
        t = row[0]
        if t < 300:
            continue
        for j, r in enumerate(rs):
            s_ex = Q / (4 * np.pi * T) * exp1(r * r * S / (4 * T * t))
            worst = max(worst, abs(-row[1 + j] - s_ex) / s_ex)
    uR = R * R * S / (4 * T * 86_400.0)
    ts = info['time']
    check(worst < 5e-3, f'descenso a 1 / 10 / 50 m, t = 300 s … 1 d: error máx {worst * 100:.3f} % (u en R = {uR:.0f}, '
                        f'Δt {ts["dt_first"]:.1f} → {ts["dt_last"]:.0f} s, BDF2)')
    bud = info['budget']
    check(info['balance_error'] < 1e-10, f"balance de agua: almacenamiento {bud['storage_change']:.3f} m³ = "
                                         f"−bombeo {-bud['well_out']:.3f} + contorno {bud['boundary_in']:.2e} m³ "
                                         f"(error {info['balance_error']:.1e})")


def case_recharge_zones(check):
    print('3. Recarga + goteo, zonas de K en serie')
    K, Rr, C, he = 1e-4, 1e-7, 1e-6, 3.0
    m = FEMMesh.generate_grid([0, 1, 2], [0, 1, 2], np.linspace(0, 10, 6), order=2)
    snaps, info = dc.solve(m, dc.PorousMedium({'K': K}), [],
                           [{'recharge': Rr, 'face_set': 'z1'}, {'leakage': {'conductance': C, 'head': he}, 'face_set': 'z0'}])
    ex = he + Rr / C + Rr * m.nodes[:, 2] / K
    check(np.abs(snaps[0][1] - ex).max() < 1e-9, f'recarga → goteo por el lecho: error {np.abs(snaps[0][1] - ex).max():.1e} m '
                                                 f'(recarga {info["rates"]["recharge"]:.2e} = goteo '
                                                 f'{-info["rates"]["leakage_in"]:.2e} m³/s)')
    K1, K2 = 1e-4, 1e-5
    m = FEMMesh.generate_grid(np.linspace(0, 2, 9), [0, 0.5], [0, 0.5], order=2)
    med = dc.PorousMedium({'K': K1, 'K_zones': [{'box': [[1.0, -1, -1], [3, 1, 1]], 'K': K2}]})
    snaps, _ = dc.solve(m, med, [{'hydraulic_head': 1.0, 'face_set': 'x0'}, {'hydraulic_head': 0.0, 'face_set': 'x1'}], [])
    q = 1.0 / (1.0 / K1 + 1.0 / K2)
    x = m.nodes[:, 0]
    ex = np.where(x <= 1.0, 1.0 - q * x / K1, q * (2.0 - x) / K2)
    Ke, _ = med.element_K(m)
    Qo = dc.face_flow(m, Ke, snaps[0][1], 'x1')
    check(np.abs(snaps[0][1] - ex).max() < 1e-12 and abs(Qo / (q * 0.25) - 1) < 1e-10,
          f'dos zonas en serie: error {np.abs(snaps[0][1] - ex).max():.1e} m, caudal {Qo:.4e} = K armónica '
          f'{q * 0.25:.4e} m³/s')


def case_aquifer_transport(check):
    print('4. Transporte en acuífero (dispersión α_L/α_T, retardo R, decaimiento)')
    v, aL, Rt, ne = 1e-4, 0.01, 2.0, 0.3
    bar = FEMMesh.generate_cantilever(1.0, 0.05, 0.05, 40, order=2)
    T = 4000.0
    model = tr.TransportModel({'species': [{'D': 0.0, 'retardation': Rt}], 'velocity': [v, 0, 0],
                               'porous': {'porosity': ne, 'alpha_L': aL, 'alpha_T': aL / 10}})
    snaps, info = tr.solve(bar, model, [{'concentration': 1.0, 'face_set': 'fixed'}], [], time={'t_end': T, 'n_steps': 400})
    err = np.abs(snaps[-1][1] - ogata_banks(bar.nodes[:, 0], T, v / Rt, aL * v / Rt)).max()
    check(err < 0.01, f'Ogata–Banks con R = {Rt:g}, α_L = {aL} m (Pe de elemento '
                      f'{tr.peclet_max(info["problem"]):.2f}): error máx {err * 100:.3f} %, balance '
                      f'{info["mass_balance_error"]:.1e}')
    aT, lam, s0, x0 = 0.002, 2e-6, 0.08, 0.4
    v = 1e-5
    T = 0.8 * Rt / v
    h = 0.05
    m = FEMMesh.generate_grid(np.arange(0, 2.2 + 1e-9, h), np.arange(0, 0.45 + 1e-9, h), np.arange(0, 0.45 + 1e-9, h))
    model = tr.TransportModel({'species': [{'D': 1e-10, 'decay': lam, 'retardation': Rt}], 'velocity': [v, 0, 0],
                               'porous': {'porosity': ne, 'alpha_L': aL, 'alpha_T': aT}})
    snaps, info = tr.solve(m, model, [], [], time={'t_end': T, 'n_steps': 320},
                           initial=[{'gaussian': {'center': [x0, 0, 0], 'sigma': s0, 'peak': 1.0}}])
    c = snaps[-1][1]
    DL, DT = 1e-10 + aL * v, 1e-10 + aT * v
    sL2, sT2 = s0 ** 2 + 2 * DL * T / Rt, s0 ** 2 + 2 * DT * T / Rt
    X = m.nodes
    ex = s0 ** 3 / np.sqrt(sL2 * sT2 * sT2) * np.exp(-lam * T) * np.exp(
        -(X[:, 0] - x0 - v * T / Rt) ** 2 / (2 * sL2) - (X[:, 1] ** 2 + X[:, 2] ** 2) / (2 * sT2))
    err = np.abs(c - ex).max() / ex.max()
    check(err < 0.01, f'pulso 3-D anisótropo (σ_L {np.sqrt(sL2):.3f} m, σ_T {np.sqrt(sT2):.3f} m, cuarto de dominio): '
                      f'error máx {err * 100:.2f} % del pico')
    ratio = info['mass_final'][0] / info['mass_initial'][0]
    check(abs(ratio / np.exp(-lam * T) - 1) < 1e-4,
          f'masa total (disuelta + adsorbida) m/m0 = {ratio:.6f} vs e^(−λt) = {np.exp(-lam * T):.6f}')


def case_coupling(check):
    print('5. Darcy → transporte (v = q/n_e)')
    K, ne, aL = 1e-3, 0.25, 0.01
    bar = FEMMesh.generate_cantilever(1.0, 0.05, 0.05, 40, order=2)
    med = dc.PorousMedium({'K': K, 'porosity': ne})
    snaps, _ = dc.solve(bar, med, [{'hydraulic_head': 1.0, 'face_set': 'fixed'}, {'hydraulic_head': 0.0, 'face_set': 'tip'}], [])
    Ke, _ = med.element_K(bar)
    _, q = dc.darcy_flux(bar, Ke, snaps[0][1])
    v = q / ne
    check(np.abs(v - [K / ne, 0, 0]).max() < 1e-9 * K / ne, f'velocidad de poro uniforme {K / ne:.4g} m/s (exacta)')
    T = 0.6 / (K / ne)
    out, _ = tr.solve(bar, tr.TransportModel({'species': [{'D': 1e-9}], 'porous': {'porosity': ne, 'alpha_L': aL}}),
                      [{'concentration': 1.0, 'face_set': 'fixed'}], [], velocity=v, time={'t_end': T, 'n_steps': 400})
    err = np.abs(out[-1][1] - ogata_banks(bar.nodes[:, 0], T, K / ne, 1e-9 + aL * K / ne)).max()
    check(err < 0.01, f'frente de Ogata–Banks sobre la velocidad de Darcy: error máx {err * 100:.3f} %')


def local(check):
    for case in (case_thiem, case_theis, case_recharge_zones, case_aquifer_transport, case_coupling):
        t0 = time.perf_counter()
        case(check)
        print(f'   ({time.perf_counter() - t0:.1f} s)')


# ── Server ────────────────────────────────────────────────────────────────────

def server(check, S):
    import requests
    from validate_transport import _run
    G, Vs = f'{S}/api/design/graph', f'{S}/api/design/solver'
    Lmm, Wmm, n_div = 1000, 50, 40
    K, ne, Rt, aL = 1e-3, 0.25, 2.0, 0.005
    beam = {'shape': 'beam', 'length_mm': Lmm, 'width_mm': Wmm, 'height_mm': Wmm, 'n_div': n_div,
            'element_order': 2, 'tier': 1}
    gids = []

    def study(name):
        gid = requests.post(f'{G}/', json={'name': name, 'tier': 1, 'description': 'validate_darcy.py'}).json()['id']
        gids.append(gid)
        add = lambda t, label, props: requests.post(f'{G}/{gid}/nodes', json={   # noqa: E731
            'node_type': t, 'label': label, 'properties': props, 'pos_x': 0, 'pos_y': 0}).json()['node_id']
        return gid, add

    def link(gid, geo, mat, bcs, loads=()):
        for s, kind in [(mat, 'CONSTRAINS_MATERIAL')] + [(b, 'CONSTRAINS_BC') for b in bcs] + \
                [(ld, 'APPLIED_TO') for ld in loads]:
            requests.post(f'{G}/{gid}/edges', json={'source_id': s, 'target_id': geo, 'edge_type': kind})

    try:
        gid, add = study('HITO Darcy · acuífero (flujo)')
        geo = add('GEOMETRY', 'Acuífero 1000×50×50', beam)
        mat = add('MATERIAL', 'Arena', {'model_type': 'porous_medium', 'K': K, 'K_unit': 'm/s', 'porosity': ne})
        bcs = [add('BC', 'Río aguas arriba h = 1 m', {'bc_type': 'hydraulic_head', 'head': 1.0, 'face_set': 'fixed'}),
               add('BC', 'Lago h = 0', {'bc_type': 'hydraulic_head', 'head': 0.0, 'face_set': 'tip'})]
        link(gid, geo, mat, bcs)
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Darcy' in (pf.get('physics_label') or ''), f"preflight: {pf.get('physics_label')}")
        darcy_run = _run(S, gid, 'run de Darcy', check)
        if not darcy_run:
            return
        d = (requests.get(f'{Vs}/{darcy_run}/results').json().get('summary') or {}).get('darcy') or {}
        v = K / ne
        check(abs(d.get('max_pore_velocity_m_d', 0) / (v * 86400) - 1) < 1e-6 and d.get('balance_error', 1) < 1e-10,
              f"velocidad de poro {d.get('max_pore_velocity_m_d')} m/d (exacta {v * 86400:g}), balance "
              f"{d.get('balance_error')}")
        DL = aL * v
        T = 0.6 * Rt / v
        gid2, add = study('HITO Darcy · pluma en el acuífero')
        geo = add('GEOMETRY', 'Acuífero 1000×50×50', beam)
        probes = [{'label': f'x{x}', 'x': x, 'y': 25, 'z': 25} for x in (400, 500, 600, 700)]
        mat = add('MATERIAL', 'Nitrato', {'model_type': 'scalar_transport', 'velocity_source': 'run',
                                          'velocity_run_id': darcy_run, 'porous': True, 'alpha_L': aL, 'alpha_T': aL / 10,
                                          'species': [{'name': 'Nitrato', 'D': 0, 'retardation': Rt, 'unit': 'mg/L'}],
                                          'transient': True, 't_end': T, 'time_steps': 400, 'n_output': 10,
                                          'probes': probes})
        bc = add('BC', 'Entrada c = 1', {'bc_type': 'concentration', 'concentration': 1.0, 'face_set': 'fixed'})
        link(gid2, geo, mat, [bc])
        rid = _run(S, gid2, 'run de transporte (velocidad del run de Darcy)', check)
        if not rid:
            return
        tp = (requests.get(f'{Vs}/{rid}/results').json().get('summary') or {}).get('transport') or {}
        check(tp.get('porous', {}).get('porosity') == ne and tp.get('velocity', {}).get('source') == 'run',
              f"porosidad tomada del run de Darcy: {tp.get('porous')}")
        errs = [abs(p['curve'][-1][1] - ogata_banks(p['point'][0], p['curve'][-1][0], v / Rt, DL / Rt))
                for p in tp.get('probes') or []]
        check(errs and max(errs) < 0.01, f'puntos de control: error máx {max(errs or [1]) * 100:.3f} % '
                                         f'(Ogata–Banks con R = {Rt:g})')
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
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)
        if not cond:
            fails.append(msg)

    if args.server:
        server(check, args.server.rstrip('/'))
        label = 'Hito de Darcy vía servidor'
    else:
        local(check)
        label = 'Hito de flujo subterráneo y transporte en acuífero (FASE 10.6)'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
