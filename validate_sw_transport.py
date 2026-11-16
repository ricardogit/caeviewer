"""Hito FASE 10.4 — depth-averaged transport on the 2-D shallow-water flow (pollutants, bacteria, salinity).

Tracers are extra unknowns H·c of the finite-volume shallow-water solver: advective flux = the HLL mass flux ×
upwind (MUSCL-limited) concentration, so a uniform concentration is kept exactly through tides and wetting/drying;
horizontal diffusion ∇·(H D ∇c) with a corrected face gradient (consistent on any triangulation); first-order decay
integrated exactly; outfalls = point sources of water and mass.

Local (analytic / exact references):
  1. uniform concentration through tide + river + wetting/drying: c = 1 to round-off, budgets per species
  2. Gaussian pulse in still water, diffusion + decay: L2 error and order, mass e^(−λT)
  3. Gaussian pulse advected by a uniform channel flow (river inflow → fixed level): L2, centre of mass
  4. steady plume of a continuous outfall in a uniform current vs c = ṁ/(2πHD) e^(ux/2D) K0(ur/2D)
  5. bacteria outfall with T90 decay in a tidal estuary: mass budget (sources, boundaries, decay) to round-off
Server (``--server``, worker running): synthetic bay + tide (harmonics CSV) carrying salinity 35 + outfall with
E. coli (T90) and fresh water → run on the job queue → budgets, salinity bounded by [0, 35], concentration series
in the Results surface pack. Salinity overshoot < 1e-6 relative on the Gmsh mesh (MUSCL
+ the non-orthogonal diffusion correction are not strictly monotone).

    python validate_sw_transport.py [--server http://127.0.0.1:8080] [--server-only]     (~20 min local)
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np                                                    # noqa: E402
from scipy.special import k0e                                        # noqa: E402

from app.design.services.fem import shallow_water as sw              # noqa: E402

H0, U0V = 10.0, 0.5


def grid(xs, ys, bed, boundary=None):
    nodes, tris, depth, bnd = sw.rect_grid(xs, ys, bed)
    g = sw.SWGrid(nodes, tris, depth, {k: bnd[v] for k, v in (boundary or {}).items()})
    return g


def channel(nx, Lx=20000.0, W=4000.0):
    """Flat frictionless channel: river inflow at x = 0 (u0·H0·W), level 0 at x = Lx → exactly uniform flow."""
    g = grid(np.linspace(0, Lx, nx + 1), np.linspace(-W / 2, W / 2, nx // 5 + 1), lambda x, y: H0 + 0 * x,
             {'in': 'x0', 'out': 'x1'})
    bc = {'in': {'kind': 'river', 'signal': lambda t: U0V * H0 * W, 'c_in': [0.0]},
          'out': {'kind': 'level', 'signal': lambda t: 0.0}}
    return g, bc


def l2(g, c, ex):
    return math.sqrt(np.sum(g.area * (c - ex) ** 2) / np.sum(g.area * ex ** 2))


def local(check):
    t0 = time.time()
    print('1. Concentración uniforme con marea, río y secado/mojado')
    g = grid(np.linspace(0, 2000, 21), np.linspace(0, 400, 5), lambda x, y: 3.0 - 4.0 * x / 2000.0,
             {'x0': 'x0', 'x1': 'x1'})
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'ramp': 3600.0})
    r = sw.solve(g, {'order': 2, 'manning': 0.025, 'h_dry': 0.01, 'tracers': [{'D': 0.0}, {'D': 2.0}]},
                 {'x0': {'kind': 'tide', 'signal': sig, 'c_in': [1.0, 1.0]},
                  'x1': {'kind': 'river', 'signal': lambda t: 5.0, 'c_in': [1.0, 1.0]}},
                 t_end=6 * 3600.0, eta0=0.0, n_output=6, c0=[1.0, 1.0])
    dev = max(np.abs(U[3:][:, U[0] > 0.05] / U[0][U[0] > 0.05] - 1).max() for _, U in r['snaps'])
    fl = int((r['wet_ever'] & ~r['wet0']).sum())
    bal = max(t['balance_error'] for t in r['tracers'])
    check(dev < 1e-12 and bal < 1e-12 and fl > 0,
          f'|c − 1| máx {dev:.1e} (advección y difusión), {fl} celdas que se mojan, balance por especie {bal:.1e}')

    print('2. Pulso gaussiano en agua quieta: difusión + decaimiento')
    s0, D, lam, T = 500.0, 20.0, 1e-4, 5000.0
    errs = []
    for n in (16, 32, 64):
        xs = np.linspace(-5000, 5000, n + 1)
        g = grid(xs, xs, lambda x, y: H0 + 0 * x)
        r2 = (g.cen ** 2).sum(1)
        c0 = np.exp(-r2 / (2 * s0 ** 2))
        r = sw.solve(g, {'order': 2, 'manning': 0.0, 'coriolis_f': 0.0, 'tracers': [{'D': D, 'decay': lam}]}, {},
                     t_end=T, eta0=0.0, n_output=1, c0=c0[None])
        U = r['snaps'][-1][1]
        s2 = s0 ** 2 + 2 * D * T
        errs.append(l2(g, U[3] / U[0], s0 ** 2 / s2 * np.exp(-r2 / (2 * s2)) * math.exp(-lam * T)))
        dm = np.sum(g.area * U[3]) / (np.sum(g.area * H0 * c0) * math.exp(-lam * T)) - 1
        print(f'   n {n}: L2 {errs[-1] * 100:.3f} %, masa / (m0 e^(−λT)) − 1 = {dm:+.1e}')
    order = math.log2(errs[-2] / errs[-1])
    check(errs[-1] < 0.004 and order > 1.6 and abs(dm) < 1e-11,
          f'L2 {errs[-1] * 100:.3f} % (64²), orden {order:.2f}, masa con decaimiento exacta')

    print('3. Pulso advectado por una corriente uniforme (canal, río → nivel fijo)')
    D, T, s0 = 10.0, 10000.0, 600.0
    errs = []
    for nx in (50, 100):
        g, bc = channel(nx)
        x, y = g.cen[:, 0], g.cen[:, 1]
        c0 = np.exp(-((x - 5000) ** 2 + y ** 2) / (2 * s0 ** 2))
        U0 = np.vstack([np.full(g.nc, H0), np.full(g.nc, H0 * U0V), np.zeros(g.nc), H0 * c0])
        r = sw.solve(g, {'order': 2, 'manning': 0.0, 'coriolis_f': 0.0, 'tracers': [{'D': D}]}, bc, t_end=T,
                     U0=U0, n_output=1)
        U = r['snaps'][-1][1]
        s2 = s0 ** 2 + 2 * D * T
        errs.append(l2(g, U[3] / U[0], s0 ** 2 / s2 * np.exp(-((x - 5000 - U0V * T) ** 2 + y ** 2) / (2 * s2))))
        xc = np.sum(g.area * U[3] * x) / np.sum(g.area * U[3]) - 5000 - U0V * T
        du = np.ptp(U[1] / U[0])
        print(f'   celda {20000 / nx:.0f} m: L2 {errs[-1] * 100:.2f} %, centro de masa {xc:+.1f} m, '
              f'u uniforme ±{du:.0e}')
    order = math.log2(errs[0] / errs[1])
    check(errs[1] < 0.06 and order > 1.4 and abs(xc) < 15 and du < 1e-10,
          f'L2 {errs[1] * 100:.2f} % (σ = 3 celdas), orden {order:.2f}, recorrido u·T = {U0V * T:.0f} m '
          f'({xc:+.1f} m), corriente intacta')

    print('4. Penacho estacionario de un emisario en corriente uniforme (solución K0)')
    D, mdot, xs = 5.0, 100.0, 4000.0
    res = {}
    for nx in (50, 100):
        g, bc = channel(nx)
        x, y = g.cen[:, 0], g.cen[:, 1]
        U0 = np.vstack([np.full(g.nc, H0), np.full(g.nc, H0 * U0V), np.zeros(g.nc), np.zeros(g.nc)])
        r = sw.solve(g, {'order': 2, 'manning': 0.0, 'coriolis_f': 0.0, 'tracers': [{'D': D}],
                         'sources': [{'xy': [xs, 0.0], 'Q': 0.0, 'mass': [mdot]}]},
                     bc, t_end=30000.0, U0=U0, n_output=1)
        c = r['snaps'][-1][1][3] / H0
        rr = np.hypot(x - xs, y)
        a = U0V / (2 * D)
        ex = mdot / (2 * math.pi * H0 * D) * np.exp(a * (x - xs) - a * rr) * k0e(a * rr)
        row = []
        for xq in (5000, 10000):
            jc = (np.abs(x - xs - xq) < 150) & (np.abs(y) < 300)
            sel = np.abs(x - xs - xq) < 150
            row.append((c[jc].mean() / ex[jc].mean() - 1, np.sum(c[sel] * g.area[sel]) /
                        np.sum(ex[sel] * g.area[sel]) - 1))
        res[nx] = row
        print(f'   celda {20000 / nx:.0f} m: eje a +5 km {row[0][0] * 100:+.2f} %, a +10 km {row[1][0] * 100:+.2f} %; '
              f'masa en la sección {row[0][1] * 100:+.2f} / {row[1][1] * 100:+.2f} %; balance '
              f'{r["tracers"][0]["balance_error"]:.0e}')
    e1, e2 = abs(res[50][1][0]), abs(res[100][1][0])
    check(e2 < 0.025 and abs(res[100][0][0]) < 0.04 and math.log2(e1 / e2) > 1.5 and abs(res[100][1][1]) < 0.005,
          f'eje a 10 km {res[100][1][0] * 100:+.2f} % (orden {math.log2(e1 / e2):.2f}), a 5 km '
          f'{res[100][0][0] * 100:+.2f} %, sección {res[100][1][1] * 100:+.2f} %')

    print('5. Emisario de bacterias (T90) en un estuario mareal: balance de masa')
    g = grid(np.linspace(0, 3000, 31), np.linspace(0, 600, 7), lambda x, y: 4.0 - 5.0 * x / 3000.0,
             {'x0': 'x0', 'x1': 'x1'})
    lam = math.log(10) / (6 * 3600.0)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.2, 'phase': 0}], 'ramp': 3600.0})
    r = sw.solve(g, {'order': 2, 'manning': 0.025, 'h_dry': 0.01,
                     'tracers': [{'D': 1.0, 'decay': lam}, {'D': 1.0}],
                     'sources': [{'xy': [800.0, 300.0], 'Q': 0.5, 'mass': [0.5 * 1e6, 0.0],
                                  'factor': lambda t: 1.0 if t < 4 * 3600 else 0.0}]},
                 {'x0': {'kind': 'tide', 'signal': sig, 'c_in': [0.0, 35.0]},
                  'x1': {'kind': 'river', 'signal': lambda t: 8.0, 'c_in': [0.0, 0.0]}},
                 t_end=12.42 * 3600, eta0=0.0, n_output=12, c0=[0.0, 35.0])
    tb, ts_ = r['tracers']
    smin = min(float((U[4][U[0] > 0.05] / U[0][U[0] > 0.05]).min()) for _, U in r['snaps'])
    smax = max(float((U[4][U[0] > 0.05] / U[0][U[0] > 0.05]).max()) for _, U in r['snaps'])
    out_ = sum(tb['boundary_out'].values())
    check(tb['balance_error'] < 1e-12 and ts_['balance_error'] < 1e-12 and r['balance_error'] < 1e-12 and
          tb['decayed'] > 0.3 * tb['source'] and smin > -1e-9 and smax < 35 + 1e-9,
          f'aportado {tb["source"]:.3e}, decaído {tb["decayed"] / tb["source"] * 100:.1f} %, sale al mar '
          f'{out_ / tb["source"] * 100:.1f} %, queda {tb["mass1"] / tb["source"] * 100:.1f} %; balances '
          f'{tb["balance_error"]:.0e} / {ts_["balance_error"]:.0e} / agua {r["balance_error"]:.0e}; '
          f'salinidad en [{smin:.3f}, {smax:.3f}]')
    print(f'   ({time.time() - t0:.0f} s)')


# ── server ──────────────────────────────────────────────────────────────────

def server(check, base):
    import requests
    from app.geodata import synthetic as S
    A, Gr, Vs = f'{base}/api/geodata', f'{base}/api/design/graph', f'{base}/api/design/solver'
    made, gid = [], None

    def up(data, fn, kind):
        r = requests.post(A, files={'file': (fn, io.BytesIO(data))}, data={'kind': kind})
        check(r.status_code in (200, 201), f'subida {fn} ({kind}): {r.status_code}')
        ds = r.json()['dataset']
        if r.status_code == 201:
            made.append(ds['id'])
        return ds
    try:
        land = up(S.shapefile_zip_land(), 'costa_hito.zip', 'coastline')
        bat = up(S.geotiff_bathy(), 'gebco_hito.tif', 'bathymetry')
        tid = up(S.tide_harmonics_csv(), 'marea_hito.csv', 'forcing')
        dom = {'shape': 'domain_2d', 'domain': S.DOMAIN, 'segments': ['open', 'coast', 'coast', 'open'],
               'segment_labels': ['Mar abierto oeste', None, 'Costa norte', 'Mar abierto sur'],
               'mesh': {'h_min': 300, 'h_max': 1500, 'wavelength_points': 300, 'growth': 0.25},
               'points': [{**S.POINT, 'size': 300}],
               'land_datasets': [land['id']], 'bathymetry_datasets': [bat['id']]}
        gid = requests.post(f'{Gr}/', json={'name': 'HITO transporte 2D · emisario', 'tier': 1,
                                             'description': 'validate_sw_transport.py'}).json()['id']

        def add(t, label, props):
            return requests.post(f'{Gr}/{gid}/nodes', json={'node_type': t, 'label': label, 'properties': props,
                                                            'pos_x': 0, 'pos_y': 0}).json()['node_id']
        geo = add('GEOMETRY', 'Bahía', dom)
        mat = add('MATERIAL', 'Agua de mar', {
            'model_type': 'shallow_water', 'manning_n': 0.025, 't_end': 6, 'time_unit': 'h', 'n_output': 12,
            'probes': [{'label': 'Emisario', 'lon': S.POINT['lon'], 'lat': S.POINT['lat']}],
            'species': [{'name': 'E. coli', 'unit': 'UFC/100 mL', 'decay': 24, 'decay_unit': 'T90_h',
                         'threshold': 500, 'D': 2},
                        {'name': 'Salinidad', 'unit': 'psu', 'D': 2, 'c0': 35}]})
        bc = add('BC', 'Marea', {'bc_type': 'tide', 'forcing_dataset': tid['id'], 'ramp_h': 2,
                                 'concentrations': {'Salinidad': 35}})
        ld = add('LOAD', 'Emisario', {'load_type': 'outfall', 'lon': S.POINT['lon'], 'lat': S.POINT['lat'],
                                      'discharge': 2, 'unit': 'm3/s', 't_off': 3,
                                      'concentrations': {'E. coli': 1e6}})
        for s_, kind in ((mat, 'CONSTRAINS_MATERIAL'), (bc, 'CONSTRAINS_BC'), (ld, 'APPLIED_TO')):
            requests.post(f'{Gr}/{gid}/edges', json={'source_id': s_, 'target_id': geo, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('Aguas someras' in (pf.get('physics_label') or '') and not pf.get('issues'),
              f"preflight: {pf.get('physics_label')} {[i['message'] for i in pf.get('issues', [])][:2]}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        check(r.status_code in (200, 202), f'lanzar run: {r.status_code} {r.text[:200]}')
        rid = r.json().get('run_id')
        t0, st = time.time(), {}
        while time.time() - t0 < 900:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed'):
                break
            time.sleep(1)
        check(st.get('status') == 'done', f"run en la cola: {st.get('status')} {st.get('error') or ''} "
                                          f"({time.time() - t0:.0f} s)")
        if st.get('status') != 'done':
            return
        d = ((requests.get(f'{Vs}/{rid}/results').json().get('summary') or {}).get('shallow_water')) or {}
        tr = d.get('tracers') or [{}, {}]
        ec, sal = tr[0], tr[1]
        src = ec.get('source', 0)
        check(d.get('tracer_balance_error', 1) < 1e-12 and d.get('balance_error', 1) < 1e-12,
              f"balances: especies {d.get('tracer_balance_error')}, agua {d.get('balance_error')} "
              f"({d.get('n_cells')} celdas)")
        check(abs(src / (2 * 1e6 * 3 * 3600) - 1) < 2e-3 and ec.get('decayed', 0) > 0 and
              ec.get('area_above_max_m2', 0) > 0,
              f"E. coli: aportado {src:.3e} (Q·c·3 h), decaído {ec.get('decayed', 0) / max(src, 1) * 100:.1f} %, "
              f"zona > 500: {ec.get('area_above_max_m2', 0) / 1e6:.2f} km² durante {ec.get('hours_above_max', 0):.1f} h")
        pr = (d.get('probes') or [{}])[0]
        over = sal.get('max', 99) / 35 - 1                 # MUSCL + non-orthogonal diffusion: not strictly monotone
        check(over < 1e-6 and (pr.get('c_max') or [0])[0] > 500,
              f"salinidad máx 35·(1 {over:+.1e}) (el vertido es agua dulce; sobrepaso < 1e-6); E. coli máx en el "
              f"emisario {(pr.get('c_max') or [0])[0]:.3g}")
        sp = requests.get(f'{Vs}/{rid}/surface', params={'step': 4})
        hdr = {}
        if sp.status_code == 200:
            hl = struct.unpack('<I', sp.content[:4])[0]
            hdr = json.loads(sp.content[4:4 + hl].decode())
        keys = [e['key'] for e in hdr.get('extra_fields') or []]
        check(sp.status_code == 200 and {'c0', 'cmax0', 'tabove0', 'c1'} <= set(keys) and hdr.get('step') == 4,
              f"superficie de Resultados: paso {hdr.get('step')}, campos {keys}")
    finally:
        if gid:
            requests.delete(f'{Gr}/{gid}', params={'cascade': 1})
        for i in made:
            requests.delete(f'{A}/{i}')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--server')
    ap.add_argument('--server-only', action='store_true')
    args = ap.parse_args()
    fails = []

    def check(cond, msg):
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)
        if not cond:
            fails.append(msg)
    if not args.server_only:
        local(check)
    if args.server:
        print('Servidor', args.server)
        server(check, args.server.rstrip('/'))
    print('\nHITO FASE 10.4:', 'CUMPLIDO' if not fails else f'NO CUMPLIDO ({len(fails)} fallos)')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
