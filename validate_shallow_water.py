"""Hito FASE 10.3 — 2-D shallow water (finite volumes on the Mapa-mode triangle mesh).

Local (analytic / exact references):
  1. lake at rest around an emerging island (well-balanced, positive), orders 1 and 2
  2. Stoker dam break: L1 error and convergence order (order 2)
  3. standing tidal wave in a closed channel forced by a tide: amplitude and phase vs cos k(L−x)/cos kL
  4. Thacker planar oscillation in a parabolic bowl (moving wet/dry front): L1 error and convergence
  5. Manning uniform flow: river discharge into a sloping channel → normal depth (n q/√S)^(3/5)
  6. wind set-up in a closed basin: g d(H²/2)/dx = τ/ρ (Wu 1982 drag)
  7. Coriolis inertial oscillation (exact rotation)
  8. tide + river over a tidal flat: water budget to round-off, intertidal flooding, positivity
Server (``--server``, worker running): synthetic bay (shapefile land, GeoTIFF bathymetry, tidal harmonics CSV)
→ GEOMETRY domain_2d + MATERIAL water + tide BC (forcing dataset) + wind LOAD → run on the job queue → level in the
bay = tide (bay ≪ tidal wavelength), budget, Results surface pack with the η series.

    python validate_shallow_water.py [--server http://127.0.0.1:8080]
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np                                                    # noqa: E402
from scipy.optimize import brentq                                    # noqa: E402

from app.design.services.fem import shallow_water as sw              # noqa: E402
from app.geodata.forcing import period_s                             # noqa: E402

G = sw.G


def grid(xs, ys, bed):
    return sw.SWGrid(*sw.rect_grid(xs, ys, bed))


def stoker(x, t, hl=1.0, hr=0.1, x0=500.0):
    cl = math.sqrt(G * hl)

    def jump(cm):
        hm, um = cm * cm / G, 2 * (cl - cm)
        return (hm * um * um + 0.5 * G * (hm * hm - hr * hr)) * (hm - hr) - (hm * um) ** 2
    cm = brentq(jump, math.sqrt(G * hr) * 1.0001, cl * 0.9999)
    hm, um = cm * cm / G, 2 * (cl - cm)
    s = hm * um / (hm - hr)
    xi = (x - x0) / t
    return np.where(xi < -cl, hl, np.where(xi < um - cm, (2 * cl - xi) ** 2 / (9 * G), np.where(xi < s, hm, hr)))


def local(check):
    t0 = time.time()
    print('1. Lago en reposo con isla emergida')
    bed = lambda x, y: 2.0 - 3.0 * np.exp(-((x - 50) ** 2 + (y - 25) ** 2) / 100) + 0.3 * np.sin(x / 7)  # noqa: E731
    g = grid(np.linspace(0, 100, 41), np.linspace(0, 50, 21), bed)
    for order in (1, 2):
        r = sw.solve(g, {'order': order}, {}, t_end=50.0, eta0=0.0, n_output=1)
        U = r['snaps'][-1][1]
        wet = U[0] > 0
        q, de = np.abs(U[1:]).max(), np.abs((U[0] + g.zb)[wet]).max()
        check(q < 1e-12 and de < 1e-12 and (~wet).sum() > 10,
              f'orden {order}: |q| máx {q:.1e} m²/s, |η| máx {de:.1e} m, {(~wet).sum()} celdas secas (isla)')

    print('2. Rotura de presa de Stoker (orden 2)')
    errs = []
    for nx in (100, 200, 400):
        g = grid(np.linspace(0, 1000, nx + 1), np.linspace(0, 20, 3), None)
        r = sw.solve(g, {'order': 2}, {}, t_end=40.0, eta0=np.where(g.cen[:, 0] < 500, 1.0, 0.1), n_output=1)
        he = stoker(g.cen[:, 0], 40.0)
        errs.append(np.sum(np.abs(r['snaps'][-1][1][0] - he) * g.area) / np.sum(g.area * he))
        print(f'      nx {nx}: L1 {errs[-1] * 100:.3f} %, balance {r["balance_error"]:.1e}')
    rate = math.log2(errs[1] / errs[2])
    check(errs[-1] < 0.004 and rate > 0.6, f'L1 {errs[-1] * 100:.3f} % a nx 400, orden {rate:.2f} '
                                          '(≈ 1 con choque y abanico: esperado)')

    print('3. Onda de marea estacionaria (canal cerrado, M2 en x = 0)')
    L, d, A = 50e3, 5.0, 0.05
    T = period_s('M2')
    w = 2 * math.pi / T
    k = w / math.sqrt(G * d)
    for nx in (25, 50):
        g = grid(np.linspace(0, L, nx + 1), np.linspace(0, 2 * L / nx, 3), lambda x, y: d + 0 * x)
        U0 = np.zeros((3, g.nc))
        U0[0] = d + A * np.cos(k * (L - g.cen[:, 0])) / math.cos(k * L)
        sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': A, 'phase': 0}]})
        pr = [{'xy': [L * 0.999, L / nx]}, {'xy': [L / 2, L / nx]}]
        r = sw.solve(g, {'order': 2}, {'x0': {'kind': 'tide', 'signal': sig}}, t_end=3 * T, U0=U0, n_output=1,
                     probes=pr)
        P = np.asarray(r['probe_rows'])
        m = P[:, 0] > T
        X = np.column_stack([np.ones(m.sum()), np.cos(w * P[m, 0]), np.sin(w * P[m, 0])])
        res = []
        for j in range(2):
            c = np.linalg.lstsq(X, P[m, 1 + 4 * j], rcond=None)[0]
            xp = g.cen[r['probe_cells'][j], 0]
            res.append((math.hypot(c[1], c[2]) / (A * abs(math.cos(k * (L - xp)) / math.cos(k * L))) - 1,
                        math.degrees(math.atan2(c[2], c[1]))))
        check(max(abs(a) for a, _ in res) < 0.005 and max(abs(p) for _, p in res) < 1,
              f'nx {nx}: amplitud extremo {res[0][0] * 100:+.3f} %, centro {res[1][0] * 100:+.3f} %, fase '
              f'{res[0][1]:+.2f}°, balance {r["balance_error"]:.1e}')

    print('4. Oscilación de Thacker en un cuenco parabólico (frente móvil mojado/seco)')
    a, h0, eta = 1.0, 0.1, 0.5
    om = math.sqrt(2 * G * h0) / a
    Tp = 2 * math.pi / om
    zb = lambda x, y: -h0 * (1 - ((x - 2) ** 2 + (y - 2) ** 2) / a ** 2)     # noqa: E731
    errs = []
    for n in (40, 80):
        xs = np.linspace(0, 4, n + 1)
        g = grid(xs, xs, lambda x, y: -zb(x, y))
        x, y = g.cen.T
        H0 = np.maximum(eta * h0 / a ** 2 * (2 * (x - 2) - eta) - g.zb, 0)
        U0 = np.zeros((3, g.nc))
        U0[0], U0[2] = H0, H0 * eta * om
        r = sw.solve(g, {'order': 2, 'h_dry': 1e-6}, {}, t_end=Tp, U0=U0, n_output=1)
        t = r['snaps'][-1][0]
        he = np.maximum(eta * h0 / a ** 2 * (2 * (x - 2) * math.cos(om * t) + 2 * (y - 2) * math.sin(om * t) - eta)
                        - g.zb, 0)
        U = r['snaps'][-1][1]
        errs.append(np.sum(np.abs(U[0] - he) * g.area) / np.sum(he * g.area))
        print(f'      n {n}: L1 tras un periodo {errs[-1] * 100:.2f} %, balance {r["balance_error"]:.1e}, '
              f'calado mín {U[0].min():.1e}')
    rate = math.log2(errs[0] / errs[1])
    check(rate > 1.0 and errs[-1] < 0.02,
          f'L1 {errs[-1] * 100:.2f} % a n 80 tras un periodo, orden {rate:.2f}')

    print('5. Flujo uniforme de Manning (caudal de río en un canal con pendiente)')
    S, n, B, Q, Lc = 1e-3, 0.03, 40.0, 40.0, 2000.0
    hn = (n * Q / B / math.sqrt(S)) ** 0.6
    g = grid(np.linspace(0, Lc, 41), np.linspace(0, B, 3), lambda x, y: 5.0 + S * x)
    U0 = np.zeros((3, g.nc))
    U0[0], U0[1] = hn, Q / B
    r = sw.solve(g, {'order': 2, 'manning': n}, {'x0': {'kind': 'river', 'signal': lambda t: Q},
                                                 'x1': {'kind': 'free', 'signal': None}},
                 t_end=3000.0, U0=U0, n_output=1)
    U = r['snaps'][-1][1]
    mid = (g.cen[:, 0] > 0.2 * Lc) & (g.cen[:, 0] < 0.9 * Lc)
    eh, eq = U[0][mid].mean() / hn - 1, U[1][mid].mean() * B / Q - 1
    check(abs(eh) < 0.005 and abs(eq) < 0.005, f'calado {eh * 100:+.3f} % y caudal {eq * 100:+.3f} % vs normal '
                                               f'(h_n {hn:.4f} m), balance {r["balance_error"]:.1e}')

    print('6. Sobreelevación por viento en una cuenca cerrada')
    Lw, dw, W = 2000.0, 2.0, 15.0
    g = grid(np.linspace(0, Lw, 41), np.linspace(0, 100, 3), lambda x, y: dw + 0 * x)
    kw = sw.RHO_AIR / 1025.0 * sw.wind_drag(W) * W * W
    xs_ = np.linspace(0, Lw, 4001)
    C = brentq(lambda c: np.mean(np.sqrt(c + 2 * kw * xs_ / G)) - dw, 0.5 * dw * dw, 2 * dw * dw)
    x = g.cen[:, 0]
    He = np.sqrt(C + 2 * kw * x / G)
    U0 = np.zeros((3, g.nc))
    U0[0] = He
    r = sw.solve(g, {'order': 2, 'manning': 0.05}, {}, t_end=3600.0, U0=U0,
                 wind=sw.wind_vector({'speed': W, 'direction': 270.0}), n_output=1)
    U = r['snaps'][-1][1]
    su = U[0][x > Lw - 60].mean() - U[0][x < 60].mean()
    se = He[x > Lw - 60].mean() - He[x < 60].mean()
    check(abs(su / se - 1) < 0.01, f'sobreelevación {su * 100:.3f} cm vs {se * 100:.3f} cm '
                                   f'({(su / se - 1) * 100:+.2f} %), |u| máx {np.abs(U[1] / U[0]).max():.1e} m/s')

    print('7. Oscilación inercial (Coriolis)')
    g = grid(np.linspace(0, 1e4, 6), np.linspace(0, 1e4, 6), lambda x, y: 10.0 + 0 * x)
    f = 2 * sw.OMEGA * math.sin(math.radians(43.0))
    U0 = np.zeros((3, g.nc))
    U0[0], U0[1] = 10.0, 2.0
    free = {kk: {'kind': 'free', 'signal': None} for kk in ('x0', 'x1', 'y0', 'y1')}
    r = sw.solve(g, {'order': 2, 'coriolis_f': f}, free, t_end=0.37 * 2 * math.pi / f, U0=U0, n_output=1)
    t, U = r['snaps'][-1]
    e = max(np.abs(U[1] / U[0] - 0.2 * math.cos(f * t)).max(), np.abs(U[2] / U[0] + 0.2 * math.sin(f * t)).max())
    check(e < 1e-12, f'velocidad rotada vs exacta: {e:.1e} m/s (periodo inercial {2 * math.pi / f / 3600:.2f} h, '
                     'lat 43°)')

    print('8. Marea + río sobre una llanura intermareal')
    g = grid(np.linspace(0, 2000, 21), np.linspace(0, 400, 5), lambda x, y: 3.0 - 4.0 * x / 2000.0)
    sig = sw.make_signal({'constituents': [{'name': 'M2', 'amplitude': 1.0, 'phase': 0}], 'ramp': 3600.0})
    r = sw.solve(g, {'order': 2, 'manning': 0.025, 'h_dry': 0.01},
                 {'x0': {'kind': 'tide', 'signal': sig}, 'x1': {'kind': 'river', 'signal': lambda t: 5.0}},
                 t_end=T, eta0=0.0, n_output=12)
    flooded = int((r['wet_ever'] & ~r['wet0']).sum())
    qin = r['boundary_volume_in']['x1'] / (5.0 * r['snaps'][-1][0]) - 1
    check(r['balance_error'] < 1e-12 and flooded > 0 and abs(qin) < 1e-12 and
          all(np.all(U[0] >= 0) for _, U in r['snaps']),
          f'balance {r["balance_error"]:.1e}, {flooded} celdas intermareales inundadas, volumen del río '
          f'{qin:+.1e}, calado ≥ 0, recortado {r["clipped_mass"]:.1e} m³')
    print(f'   ({time.time() - t0:.0f} s)')


# ── server ──────────────────────────────────────────────────────────────────

def server(check, base):
    import requests
    from app.geodata import synthetic as S
    from app.geodata.forcing import tide
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
               'land_datasets': [land['id']], 'bathymetry_datasets': [bat['id']]}
        gid = requests.post(f'{Gr}/', json={'name': 'HITO aguas someras · bahía', 'tier': 1,
                                             'description': 'validate_shallow_water.py'}).json()['id']

        def add(t, label, props):
            return requests.post(f'{Gr}/{gid}/nodes', json={'node_type': t, 'label': label, 'properties': props,
                                                            'pos_x': 0, 'pos_y': 0}).json()['node_id']
        geo = add('GEOMETRY', 'Bahía', dom)
        plon, plat = S.LON0 + 0.10, S.LAT0 + 0.10
        mat = add('MATERIAL', 'Agua de mar', {'model_type': 'shallow_water', 'manning_n': 0.025, 't_end': 6,
                                              'time_unit': 'h', 'n_output': 12,
                                              'probes': [{'label': 'Centro', 'lon': plon, 'lat': plat}]})
        bc = add('BC', 'Marea (armónicos)', {'bc_type': 'tide', 'forcing_dataset': tid['id'], 'ramp_h': 2})
        ld = add('LOAD', 'Viento NE 8 m/s', {'load_type': 'wind', 'speed': 8, 'direction': 45})
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
        summ = requests.get(f'{Vs}/{rid}/results').json().get('summary') or {}
        d = summ.get('shallow_water') or {}
        check(d.get('balance_error', 1) < 1e-12, f"balance de agua {d.get('balance_error')} "
                                                 f"({d.get('n_cells')} celdas, {d.get('n_steps')} pasos)")
        cons = [{'name': n_, 'amplitude': a_, 'phase': p_} for n_, a_, p_ in
                (('M2', 1.20, 75), ('S2', 0.42, 105), ('K1', 0.07, 60), ('O1', 0.06, 320))]
        cur = np.asarray((d.get('probes') or [{}])[0].get('curve') or [[0, 0, 0, 0]])
        tt = cur[:, 0]
        ramp = np.where(tt >= 7200, 1.0, 0.5 * (1 - np.cos(np.pi * tt / 7200)))
        ref = 2.1 + ramp * tide(tt, cons, 0.0)
        late = tt > 7200
        err = np.abs(cur[late, 1] - ref[late]).max() if late.any() else 1
        rng = ref[late].max() - ref[late].min() if late.any() else 1
        check(err < 0.03 * rng, f'nivel en el centro de la bahía = marea (bahía ≪ longitud de onda): error máx '
                                f'{err * 100:.2f} cm de {rng:.2f} m de carrera ({err / rng * 100:.2f} %)')
        bt = {b['kind'] for b in d.get('boundaries') or []}
        check(bt == {'tide', 'wall'} and d.get('wind') and d.get('coriolis') and 41 < d.get('latitude_mean', 0) < 43,
              f"contornos {sorted(bt)}, viento {d.get('wind')}, Coriolis a lat {d.get('latitude_mean', 0):.2f}°")
        sp = requests.get(f'{Vs}/{rid}/surface', params={'step': 6})
        import json
        import struct
        hdr = {}
        if sp.status_code == 200:
            hl = struct.unpack('<I', sp.content[:4])[0]
            hdr = json.loads(sp.content[4:4 + hl].decode())
        keys = [e['key'] for e in hdr.get('extra_fields') or []]
        check(sp.status_code == 200 and hdr.get('step') == 6 and len(hdr.get('times') or []) == 13 and
              {'eta', 'speed', 'H', 'depth'} <= set(keys),
              f"superficie de Resultados: paso {hdr.get('step')}, {len(hdr.get('times') or [])} tiempos, "
              f"campos {keys}")
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
    print('\nHITO FASE 10.3:', 'CUMPLIDO' if not fails else f'NO CUMPLIDO ({len(fails)} fallos)')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
