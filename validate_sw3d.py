"""Hito FASE 10.4 — 3-D hydrostatic stratified flow in σ layers (estuaries and bays with saline / thermal
stratification).

Multilayer shallow water with mass exchange through the σ surfaces (``fem/sw3d.py``): layer fluxes with wave speeds
common to the column (the layers of a block-moving column are the 2-D model exactly), layer momentum upwinded by its
own mass flux, ρ(T, S) baroclinic pressure with a reference profile ρ_ref(z), implicit vertical mixing (k-ε 1-D or
constant), log-law bed drag, wind stress.

Local:
  1. exact properties: block motion = 2-D model (1 and 5 layers), lake at rest with a dry island and uniform
     salinity, uniform S kept through tide + river + wetting, water / heat / salt budgets
  2. water columns: vertical diffusion of a cosine mode (constant κ), open-channel flow with k-ε vs the log law,
     Kato–Phillips wind-mixed layer D = 1.05 u* √(t/N₀) (Price 1979)
  3. internal seiche (linear stratification, closed basin): ω = N H/L (hydrostatic mode 1)
  4. lock exchange: front speed Fr = U/√(g'H) (Benjamin 0.5; experiments and hydrostatic models 0.43–0.48)
  5. pressure-gradient error: stratified water at rest over a seamount (σ coordinates)
Server (``--server``, worker running): synthetic bay (shapefile + GeoTIFF + tide harmonics) with 6 σ layers, k-ε,
tide carrying 12 °C / 35 psu, warm fresh-water outfall at the bed, wind → run on the job queue → budgets, salinity
bounds, stratification, probe profiles, series fields in the Results surface pack.

    python validate_sw3d.py [--server http://127.0.0.1:8080] [--server-only] [--quick]     (~35 min local)
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

from app.design.services.fem import shallow_water as sw              # noqa: E402
from app.design.services.fem import sw3d                              # noqa: E402

G = sw.G


def grid(xs, ys, bed):
    return sw.SWGrid(*sw.rect_grid(xs, ys, bed))


def column(H):
    return grid([0, 1000.0], [0, 1000.0], lambda x, y: H + 0 * x)


def local(check, quick=False):
    print('1. Propiedades exactas')
    g = grid(np.linspace(0, 1000, 31), np.linspace(0, 600, 19),
             lambda x, y: 10 + 3 * np.sin(x / 200) + 2 * np.cos(y / 150))
    eta0 = 0.3 * np.exp(-((g.cen[:, 0] - 400) ** 2 + (g.cen[:, 1] - 300) ** 2) / 150 ** 2)
    U2 = sw.solve(g, {'manning': 0.0}, {}, t_end=200, eta0=eta0, n_output=1)['snaps'][-1][1]
    errs = []
    for L in (1, 5):
        r = sw3d.solve(g, {'layers': L, 'closure': 'constant', 'nu_v': 0.0, 'kappa_v': 0.0, 'bottom_drag': False},
                       {}, t_end=200, eta0=eta0, n_output=1)
        errs.append(float(np.abs(r['snaps'][-1][1][0] - U2[0]).max()))
    check(max(errs) < 1e-12, f'columna en bloque = modelo 2D (onda sobre fondo irregular, 200 s): |ΔH| '
                             f'{errs[0]:.1e} (1 capa), {errs[1]:.1e} (5 capas)')
    g = grid(np.linspace(0, 1000, 21), np.linspace(0, 1000, 21),
             lambda x, y: 2.0 - 3.0 * np.exp(-((x - 500) ** 2 + (y - 500) ** 2) / 200 ** 2))
    r = sw3d.solve(g, {'layers': 6, 'closure': 'k_epsilon', 'salinity': 30.0}, {}, t_end=600, n_output=1)
    u, v, c, wet = r['solver'].primitive(r['snaps'][-1][1])
    check(np.abs(u).max() < 1e-11 and np.abs(c[0][:, wet] - 30).max() < 1e-10,
          f'lago en reposo con isla seca, 6 capas, k-ε: |u| {np.abs(u).max():.1e} m/s, |S − 30| '
          f'{np.abs(c[0][:, wet] - 30).max():.1e}')
    g = grid(np.linspace(0, 2000, 17), np.linspace(0, 400, 4), lambda x, y: 3.0 - 4.0 * x / 2000.0)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'ramp': 1800.0})
    bnd = {'x0': {'kind': 'tide', 'signal': sig, 'c_in': [12.0, 20.0]},
           'x1': {'kind': 'river', 'signal': lambda t: 5.0, 'c_in': [18.0, 20.0]}}
    r = sw3d.solve(g, {'layers': 4, 'closure': 'k_epsilon', 'temperature': 12.0, 'salinity': 20.0, 'manning': 0.025,
                       'h_dry': 0.01}, bnd, t_end=3 * 3600.0, n_output=3)
    u, v, c, wet = r['solver'].primitive(r['snaps'][-1][1])
    fl = int((r['wet_ever'] & ~r['wet0']).sum())
    check(r['balance_error'] < 1e-12 and max(t['balance_error'] for t in r['tracers']) < 1e-12
          and np.abs(c[1][:, wet] - 20).max() < 1e-9 and fl > 0,
          f'marea + río + secado/mojado (3 h): balances agua {r["balance_error"]:.1e}, calor '
          f'{r["tracers"][0]["balance_error"]:.1e}, sal {r["tracers"][1]["balance_error"]:.1e}; S uniforme '
          f'|ΔS| {np.abs(c[1][:, wet] - 20).max():.1e}; {fl} celdas inundadas')

    print('2. Columnas de agua (física vertical)')
    ka = 1e-3
    r = sw3d.solve(column(10.0), {'layers': 40, 'closure': 'constant', 'nu_v': 1e-3, 'kappa_v': ka,
                                  'bottom_drag': False, 'temperature': lambda d: 10 + np.cos(math.pi * (10 - d) / 10),
                                  'horizontal': False, 'dt': 10.0}, {}, t_end=20000, n_output=1)
    s3 = r['solver']
    cT = s3.primitive(r['snaps'][-1][1])[2][0][:, 0]
    amp = np.sum((cT - 10) * np.cos(math.pi * s3.sc * 10 / 10)) * 2 / 40
    ex = math.exp(-ka * (math.pi / 10) ** 2 * 20000)
    check(abs(amp / ex - 1) < 3e-3 and r['tracers'][0]['balance_error'] < 1e-12,
          f'difusión vertical de un modo coseno (κ = 1e-3, 40 capas): amplitud {amp:.5f} vs {ex:.5f} '
          f'({(amp / ex - 1) * 100:+.2f} %), calor {r["tracers"][0]["balance_error"]:.0e}')
    H, S, z0 = 10.0, 1e-5, 1e-3
    us = math.sqrt(G * S * H)
    for L in (10, 40):
        r = sw3d.solve(column(H), {'layers': L, 'closure': 'k_epsilon', 'bottom_roughness': z0,
                                   'body_force': (G * S, 0), 'horizontal': False, 'dt': 10.0}, {},
                       t_end=12 * 3600, n_output=1)
        s3 = r['solver']
        uu = s3.primitive(r['snaps'][-1][1])[0][:, 0]
        cd = s3._drag(np.array([H]), None)[0]
        um = float((s3.frac * uu).sum())
        ulog = us / 0.41 * (math.log(H / z0) - 1)
        ub = us / 0.41 * math.log((s3.sc[0] * H + z0) / z0)
        k3 = np.interp(0.3 * H, s3.s[1:-1] * H, s3.k[1:-1, 0]) * 0.3 / us ** 2 / 0.7
        check(abs(cd * uu[0] ** 2 / us ** 2 - 1) < 1e-4 and abs(uu[0] / ub - 1) < 2e-3 and abs(um / ulog - 1) < 0.05
              and abs(k3 - 1) < 0.05,
              f'canal abierto k-ε, {L} capas (u* = √(gHS), z₀ 1 mm): τ_fondo/ρu*² {cd * uu[0] ** 2 / us ** 2:.5f}, '
              f'capa de fondo vs ley log {(uu[0] / ub - 1) * 100:+.2f} %, media {um:.4f} vs integral log {ulog:.4f} '
              f'({(um / ulog - 1) * 100:+.1f} %: estela del k-ε), k(0.3H)√cμ/u*²(1 − z/H) {k3:.3f}')
    Hk, N0, usk, rho0, al = 50.0, 0.01, 0.01, 1025.0, 2e-4
    dTdz = N0 ** 2 / (G * al)
    r = sw3d.solve(column(Hk), {'layers': 100, 'closure': 'k_epsilon', 'rho': rho0, 'bottom_drag': False,
                                'eos': {'model': 'linear', 'alpha': al, 'beta': 0, 'rho_ref': rho0},
                                'temperature': lambda d: 20 - dTdz * d, 'surface_stress': (rho0 * usk ** 2, 0),
                                'horizontal': False, 'dt': 10.0}, {}, t_end=30 * 3600, n_output=6)
    s3 = r['solver']
    rows = []
    for tt, U in r['snaps'][1:]:
        T = s3.primitive(U)[2][0][:, 0]
        D = Hk - s3.s[1:-1][np.argmax(np.diff(T))] * Hk
        rows.append((tt / 3600, D, D / (1.05 * usk * math.sqrt(tt / N0))))
    worst = max(abs(q - 1) for _, _, q in rows)
    check(worst < 0.05, 'Kato–Phillips (u* 1 cm/s, N₀ 0.01 1/s, 100 capas): D/(1.05 u*√(t/N₀)) = '
          + ', '.join(f'{q:.3f} ({h:.0f} h, {D:.1f} m)' for h, D, q in rows))

    print('3. Seiche interno (estratificación lineal, cuenca cerrada)')
    Lx, Hs, N, rr = 1000.0, 20.0, 0.02, 1000.0
    nx, L = (12, 6) if quick else (25, 10)
    g = grid(np.linspace(0, Lx, nx + 1), np.linspace(0, 2 * Lx / nx, 3), lambda x, y: Hs + 0 * x)
    p = {'layers': L, 'closure': 'constant', 'nu_v': 0.0, 'kappa_v': 0.0, 'bottom_drag': False, 'rho': rr,
         'eos': {'model': 'linear', 'alpha': al, 'beta': 0, 'T_ref': 10, 'rho_ref': rr}, 'temperature': 10.0}
    s3 = sw3d.Stratified3D(g, p, {})
    U = s3.initial_state(0.0)
    zp = s3.sc[:, None] * Hs
    basis = np.cos(math.pi * g.cen[:, 0] / Lx)[None] * np.sin(math.pi * zp / Hs)
    dT = N ** 2 / (G * al)
    U[1 + 2 * L:] = s3.frac[:, None] * U[0][None] * (10 + dT * (zp - Hs / 2) + 0.2 * basis)
    w = N * Hs / Lx
    t0 = time.time()
    r = sw3d.solve(g, p, {}, t_end=1.5 * 2 * math.pi / w, n_output=150, U0=U)
    ts, amp = [], []
    for tt, Ux in r['snaps']:
        pert = s3.primitive(Ux)[2][0] - (10 + dT * (zp - Hs / 2))
        ts.append(tt)
        amp.append(np.sum(pert * basis * g.area) / np.sum(basis ** 2 * g.area) / 0.2)
    ts, amp = np.array(ts), np.array(amp)
    best = None
    for om in np.linspace(0.8 * w, 1.2 * w, 4001):
        M = np.column_stack([np.cos(om * ts), np.sin(om * ts)])
        co = np.linalg.lstsq(M, amp, rcond=None)[0]
        res = float(np.sum((M @ co - amp) ** 2))
        if best is None or res < best[0]:
            best = (res, om, float(np.hypot(*co)))
    check(abs(best[1] / w - 1) < 0.04 and best[2] > 0.9,
          f'modo 1 ({nx} celdas × {L} capas, 1.5 periodos, {time.time() - t0:.0f} s): ω/(NH/L) {best[1] / w:.4f}, '
          f'amplitud ajustada {best[2]:.3f} de la inicial, calor {r["tracers"][0]["balance_error"]:.0e}')

    print('4. Intercambio por compuerta (lock exchange)')
    Lx, Hl, be = 3000.0, 20.0, 7.6e-4
    nx, L = (50, 10) if quick else (100, 20)
    dS = 1.0 / (rr * be)
    g = grid(np.linspace(0, Lx, nx + 1), np.linspace(0, 2 * Lx / nx, 3), lambda x, y: Hl + 0 * x)
    p = {'layers': L, 'closure': 'constant', 'nu_v': 1e-4, 'kappa_v': 1e-5, 'bottom_drag': False, 'rho': rr,
         'eos': {'model': 'linear', 'alpha': 0, 'beta': be, 'S_ref': 0, 'rho_ref': rr}, 'salinity': 0.0}
    s3 = sw3d.Stratified3D(g, p, {})
    U = s3.initial_state(0.0)
    U[1 + 2 * L:] = s3.frac[:, None] * U[0][None] * np.where(g.cen[:, 0] < Lx / 2, dS, 0.0)[None]
    gp = G / rr
    t_end = 1100 / (0.5 * math.sqrt(gp * Hl))
    t0 = time.time()
    r = sw3d.solve(g, p, {}, t_end=t_end, n_output=40, U0=U)
    row = g.cen[:, 1] < Lx / nx
    o = np.argsort(g.cen[row, 0])
    xc = g.cen[row, 0][o]
    ts, fb, ft = [], [], []
    for tt, Ux in r['snaps'][1:]:
        cS = s3.primitive(Ux)[2][0]
        fb.append(xc[np.flatnonzero(cS[0][row][o] > dS / 2).max()])
        ft.append(xc[np.flatnonzero(cS[-1][row][o] < dS / 2).min()])
        ts.append(tt)
    ts, fb, ft = map(np.array, (ts, fb, ft))
    m = ts > 0.3 * t_end
    frb = np.polyfit(ts[m], fb[m], 1)[0] / math.sqrt(gp * Hl)
    frt = -np.polyfit(ts[m], ft[m], 1)[0] / math.sqrt(gp * Hl)
    check(0.40 < frb < 0.52 and 0.40 < frt < 0.52 and r['tracers'][0]['balance_error'] < 1e-12,
          f'Δρ 1 kg/m³, H 20 m, {nx} celdas × {L} capas ({time.time() - t0:.0f} s): Fr frente de fondo {frb:.3f}, '
          f'de superficie {frt:.3f} (Benjamin 0.5; experimentos 0.43–0.48), sal {r["tracers"][0]["balance_error"]:.0e}')

    print('5. Error de gradiente de presión (monte submarino, reposo estratificado)')
    W = 20000.0
    xs = np.linspace(0, W, 21)
    g = grid(xs, xs, lambda x, y: 100 - 50 * np.exp(-((x - W / 2) ** 2 + (y - W / 2) ** 2) / 4000.0 ** 2))
    hb = -g.zb
    rmax = float(np.max(np.abs(hb[g.L] - hb[g.R]) / (hb[g.L] + hb[g.R])))
    p = {'layers': 10, 'closure': 'constant', 'nu_v': 1e-4, 'kappa_v': 1e-5, 'bottom_drag': False,
         'eos': {'model': 'unesco'}, 'temperature': lambda d: 10 + 8 * np.exp(-d / 30.0), 'salinity': 35.0}
    t0 = time.time()
    r = sw3d.solve(g, p, {}, t_end=6 * 3600, n_output=2)
    vmax = float(np.hypot(*r['solver'].primitive(r['snaps'][-1][1])[:2]).max())
    rho = r['solver'].density(r['solver'].primitive(r['snaps'][0][1])[2])
    check(vmax < 1e-3, f'H 50–100 m (r = Δh/2h̄ máx {rmax:.2f}), ΔT 8 °C en 30 m, 10 capas, 6 h '
          f'({time.time() - t0:.0f} s): |u| espuria máx {vmax * 1000:.3f} mm/s (con ρ_ref(z); sin él 17 mm/s), '
          f'Δρ {rho.max() - rho.min():.2f} kg/m³')


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
               'mesh': {'h_min': 400, 'h_max': 2000, 'wavelength_points': 300, 'growth': 0.25},
               'points': [{**S.POINT, 'size': 400}],
               'land_datasets': [land['id']], 'bathymetry_datasets': [bat['id']]}
        gid = requests.post(f'{Gr}/', json={'name': 'HITO 3D estratificado · bahía', 'tier': 1,
                                            'description': 'validate_sw3d.py'}).json()['id']

        def add(t, label, props):
            return requests.post(f'{Gr}/{gid}/nodes', json={'node_type': t, 'label': label, 'properties': props,
                                                            'pos_x': 0, 'pos_y': 0}).json()['node_id']
        geo = add('GEOMETRY', 'Bahía', dom)
        mat = add('MATERIAL', 'Agua de mar', {
            'model_type': 'shallow_water', 'manning_n': 0.025, 't_end': 3, 'time_unit': 'h', 'n_output': 6,
            'vertical_layers': 6, 'closure': 'k_epsilon', 'T_surface': 17, 'T_bottom': 12, 'profile_depth': 40,
            'S_surface': 35,
            'probes': [{'label': 'Emisario', 'lon': S.POINT['lon'], 'lat': S.POINT['lat']}],
            'species': [{'name': 'E. coli', 'unit': 'UFC/100 mL', 'decay': 24, 'decay_unit': 'T90_h',
                         'threshold': 500, 'D': 2}]})
        bc = add('BC', 'Marea', {'bc_type': 'tide', 'forcing_dataset': tid['id'], 'ramp_h': 1,
                                 'temperature': 12, 'salinity': 35})
        ld = add('LOAD', 'Emisario', {'load_type': 'outfall', 'lon': S.POINT['lon'], 'lat': S.POINT['lat'],
                                      'discharge': 5, 'unit': 'm3/s', 'temperature': 20, 'salinity': 0,
                                      'release': 'bottom', 'concentrations': {'E. coli': 1e6}})
        wd = add('LOAD', 'Viento', {'load_type': 'wind', 'speed': 6, 'direction': 270})
        for s_, kind in ((mat, 'CONSTRAINS_MATERIAL'), (bc, 'CONSTRAINS_BC'), (ld, 'APPLIED_TO'),
                         (wd, 'APPLIED_TO')):
            requests.post(f'{Gr}/{gid}/edges', json={'source_id': s_, 'target_id': geo, 'edge_type': kind})
        pf = requests.get(f'{Vs}/{gid}/preflight').json()
        check('3D estratificado en 6 capas' in (pf.get('physics_label') or '') and not pf.get('issues'),
              f"preflight: {pf.get('physics_label')} {[i['message'] for i in pf.get('issues', [])][:2]}")
        r = requests.post(f'{Vs}/{gid}/run', json={})
        check(r.status_code in (200, 202), f'lanzar run: {r.status_code} {r.text[:200]}')
        rid = r.json().get('run_id')
        t0, st = time.time(), {}
        while time.time() - t0 < 1800:
            st = requests.get(f'{Vs}/{rid}/status').json()
            if st.get('status') in ('done', 'failed'):
                break
            time.sleep(2)
        check(st.get('status') == 'done', f"run en la cola: {st.get('status')} {st.get('error') or ''} "
                                          f"({time.time() - t0:.0f} s)")
        if st.get('status') != 'done':
            return
        summ = requests.get(f'{Vs}/{rid}/results').json().get('summary') or {}
        d = summ.get('shallow_water') or {}
        s3 = d.get('stratified') or {}
        b = {x['name']: x['balance_error'] for x in s3.get('budgets') or []}
        check(d.get('balance_error', 1) < 1e-12 and d.get('tracer_balance_error', 1) < 1e-12,
              f"balances: agua {d.get('balance_error')}, calor {b.get('T')}, sal {b.get('S')}, E. coli "
              f"{(d.get('tracers') or [{}])[0].get('balance_error')} ({d.get('n_cells')} celdas × {s3.get('layers')} "
              f"capas, {d.get('n_steps')} pasos, {summ.get('wall_time_s')} s)")
        rr = s3.get('density_range_kg_m3') or [0, 0]
        check(s3.get('stratification_max_kg_m3', 0) > 0.5 and s3.get('nut_max_m2_s', 0) > 0 and len(rr) == 2,
              f"estratificación Δρ fondo − superficie máx {s3.get('stratification_max_kg_m3', 0):.2f} kg/m³, ρ "
              f"{rr[0]:.2f} … {rr[1]:.2f} kg/m³, ν_t máx {s3.get('nut_max_m2_s', 0):.3g} m²/s")
        pr = (d.get('probes') or [{}])[0]
        prof = (pr.get('profiles') or [{}])[-1]
        Sp = prof.get('S') or []
        check(len(Sp) == 6 and min(Sp) < 35 and max(Sp) <= 35 * (1 + 1e-6),
              f"perfil en el emisario (t final): S {', '.join(f'{x:.2f}' for x in Sp)} psu (fondo → superficie), "
              f"T {', '.join(f'{x:.2f}' for x in prof.get('T') or [])} °C")
        sp = requests.get(f'{Vs}/{rid}/surface', params={'step': 3})
        hdr = {}
        if sp.status_code == 200:
            hl = struct.unpack('<I', sp.content[:4])[0]
            hdr = json.loads(sp.content[4:4 + hl].decode())
        keys = [e['key'] for e in hdr.get('extra_fields') or []]
        check(sp.status_code == 200 and {'S_s', 'S_b', 'T_s', 'strat', 'speed_s', 'c0_b'} <= set(keys)
              and hdr.get('step') == 3, f"superficie de Resultados: paso {hdr.get('step')}, campos {keys}")
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
    ap.add_argument('--quick', action='store_true', help='coarser seiche / lock exchange')
    args = ap.parse_args()
    fails = []

    def check(cond, msg):
        print(f"   {'OK   ' if cond else 'FALLA'} {msg}", flush=True)
        if not cond:
            fails.append(msg)
    if not args.server_only:
        local(check, args.quick)
    if args.server:
        print('Servidor', args.server)
        server(check, args.server.rstrip('/'))
    print('\nHITO FASE 10.4 (3D estratificado):', 'CUMPLIDO' if not fails else f'NO CUMPLIDO ({len(fails)} fallos)')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
