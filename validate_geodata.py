"""Hito FASE 10.5: geographic data, reprojection and the 2D mesh of a water domain (synthetic bay with known truth).

  1. CRS: lon/lat → UTM → lon/lat round trip (< 1e-9°), automatic UTM zone (incl. Norway / Svalbard), grid / geodesic
     distance = k0 = 0.9996 on the central meridian
  2. Readers: land as GeoJSON (WGS84 and projected), KML, zipped shapefile with .prj → same polygons (area of the
     symmetric difference < 1e-9); bathymetry as GeoTIFF, NetCDF classic, NetCDF-4 (GEBCO elevation, descending lat)
     and XYZ soundings → the linear depth exactly at random points
  3. Mesh: water area = domain − land (1e-9), island = hole, edge fully on land disappears, coast length exact,
     depth exact at the nodes, min angle > 25°, element size / target: median ≈ 1, ≥ 90 % within [0.5, 1.6],
     refinement around the discharge point, grading |∇h| ≤ growth of the background field, deterministic
  4. Tide: harmonic synthesis recovered by least squares (1e-10), spring–neap period of M2 + S2 = 14.77 d
  5. Wave criterion: elements per M2 wavelength = the requested N (median within 20 %)
Server (worker running): upload the datasets → POST /api/geodata/mesh → job geo.mesh2d → mesh JSON = local mesh;
a study with GEOMETRY domain_2d gives the "FASE 10.3" preflight message.

Usage: python validate_geodata.py [--server http://127.0.0.1:8080]
"""
import argparse
import io
import sys
import time

import numpy as np

from app.geodata import crs as C
from app.geodata import readers as rd
from app.geodata import synthetic as S
from app.geodata.forcing import CONSTITUENTS, period_s, tide
from app.geodata.mesh2d import G, build_mesh, limit_gradation, params_of, target_size_at, water_domain

SPEC = {'domain': S.DOMAIN, 'segments': ['open', 'coast', 'coast', 'open'],
        'segment_labels': ['Mar abierto oeste', None, 'Costa norte', 'Mar abierto sur'],
        'mesh': {'h_min': 100, 'h_max': 1500, 'wavelength_points': 300, 'growth': 0.2},
        'points': [{**S.POINT, 'size': 80}]}


def local(check):
    from pyproj import Geod
    from shapely.ops import unary_union
    print('1. Sistemas de coordenadas')
    lon = np.random.default_rng(3).uniform(-8.8, -8.5, 1000)
    lat = np.random.default_rng(4).uniform(42.2, 42.35, 1000)
    fr = C.LocalFrame.for_lonlat(lon, lat)
    lo, la = fr.to_lonlat(*fr.from_lonlat(lon, lat))
    err = max(np.abs(lo - lon).max(), np.abs(la - lat).max())
    check(fr.epsg == 32629 and err < 1e-9, f'UTM {fr.epsg}, ida y vuelta {err:.1e}°')
    zones = [C.utm_epsg(*p) for p in ((-3.7, 40.4), (-58.4, -34.6), (5.0, 60.0), (15.0, 78.0), (179.9, 0))]
    check(zones == [32630, 32721, 32632, 32633, 32660], f'zonas UTM {zones} (Madrid, Buenos Aires, Bergen 32V, '
                                                       f'Svalbard 33X, antimeridiano)')
    x, y = C.LocalFrame(32629).from_lonlat([-9.0, -9.0], [42.0, 42.01])
    k = np.hypot(x[1] - x[0], y[1] - y[0]) / Geod(ellps='WGS84').inv(-9.0, 42.0, -9.0, 42.01)[2]
    check(abs(k - 0.9996) < 1e-7, f'factor de escala en el meridiano central {k:.8f} (k0 = 0.9996)')

    print('2. Lectores')
    ref = unary_union(S.land_polygons())
    for data, fn, label in ((S.geojson_land(), 'c.geojson', 'GeoJSON WGS84'),
                            (S.geojson_land('EPSG:25829'), 'c.geojson', 'GeoJSON ETRS89/UTM29'),
                            (S.kml_land(), 'c.kml', 'KML'), (S.shapefile_zip_land(), 'c.zip', 'shapefile .zip + .prj')):
        d = rd.read_vector(data, fn)
        u = unary_union([f['geometry'] for f in d['features']])
        e = u.symmetric_difference(ref).area / ref.area
        check(e < 1e-9, f'tierra {label}: {len(d["features"])} polígonos, diferencia {e:.1e}')
    pl = np.random.default_rng(0).uniform([S.LON0, S.LAT0], [S.LON0 + 0.3, S.LAT0 + 0.15], (500, 2))
    exact = S.depth(pl[:, 0], pl[:, 1])
    bats = {}
    for data, fn, label in ((S.geotiff_bathy(), 'b.tif', 'GeoTIFF'), (S.netcdf_classic_bathy(), 'b.nc', 'NetCDF clásico'),
                            (S.netcdf4_bathy(), 'b.nc', 'NetCDF-4 (lat descendente)'), (S.xyz_soundings(), 'b.xyz', 'XYZ')):
        d = rd.read_bathymetry(data, fn)
        bats[label] = d
        e = np.abs(rd.DepthSampler([d])(pl[:, 0], pl[:, 1]) - exact).max()
        check(e < 1e-7, f'batimetría {label} ({d["convention"]}): error máx {e:.1e} m')

    print('3. Malla 2D de la bahía')
    samp = rd.DepthSampler([bats['GeoTIFF']])
    t0 = time.perf_counter()
    m = build_mesh(SPEC, land=S.land_polygons(), depth_sampler=samp, key='hito')
    dt = time.perf_counter() - t0
    water, dom = water_domain(S.DOMAIN, S.land_polygons(), m.frame)
    area = sum(p.area for p in water)
    check(abs(m.areas().sum() / area - 1) < 1e-9 and m.areas().min() > 0,
          f'{m.n_nodes:,} nodos, {m.n_elements:,} triángulos en {dt:.1f} s; área {m.areas().sum() / 1e6:.3f} km² '
          f'= agua (dominio − tierra)')
    ids = {b['id']: b for b in m.boundary_info}
    check(m.stats['n_holes'] == 1 and set(ids) == {'edge0', 'edge2', 'edge3', 'coast'},
          f'isla = 1 agujero; contornos {sorted(ids)} (el lado este queda entero en tierra)')
    shore = sum(p.boundary.length for p in water) - sum(ids[k]['length_m'] for k in ('edge0', 'edge2', 'edge3'))
    check(abs(ids['coast']['length_m'] / shore - 1) < 1e-9 and ids['edge0']['label'] == 'Mar abierto oeste',
          f"costa {ids['coast']['length_m'] / 1000:.3f} km; lado 1 «{ids['edge0']['label']}» "
          f"{ids['edge0']['length_m'] / 1000:.3f} km ({ids['edge0']['kind']})")
    ll = m.lonlat()
    e = np.abs(m.depth - S.depth(ll[:, 0], ll[:, 1])).max()
    check(e < 1e-7, f'profundidad en los nodos {m.stats["depth_min_m"]:.1f}–{m.stats["depth_max_m"]:.1f} m, '
                    f'error {e:.1e} m')
    check(m.stats['min_angle_deg'] > 25, f'ángulo mínimo {m.stats["min_angle_deg"]:.1f}°')
    r = m.edge_lengths().mean(1) / target_size_at(SPEC, m, samp)
    inband = np.mean((r > 0.5) & (r < 1.6))
    check(0.7 < np.median(r) < 1.3 and inband > 0.9,
          f'tamaño / objetivo: mediana {np.median(r):.2f}, {inband * 100:.0f} % en [0.5, 1.6]')
    px, py = m.frame.from_lonlat([S.POINT['lon']], [S.POINT['lat']])
    cen = m.nodes[m.tris].mean(1)
    dist = np.hypot(cen[:, 0] - px[0], cen[:, 1] - py[0])
    near, far = m.edge_lengths()[dist < 300].mean(), m.edge_lengths()[dist > 5000].mean()
    check(near < 250 and far > 4 * near, f'vertido: {near:.0f} m a < 300 m, {far:.0f} m a > 5 km')
    H = np.random.default_rng(5).uniform(100, 2000, (60, 60))
    Hg = limit_gradation(H, 50.0, 0.2)
    gr = max(np.abs(np.diff(Hg, axis=0)).max(), np.abs(np.diff(Hg, axis=1)).max()) / 50.0
    check(gr <= 0.2 + 1e-12 and np.all(Hg <= H), f'gradación del campo de fondo |∇h| ≤ {gr:.3f} (límite 0.2)')
    m2 = build_mesh(SPEC, land=S.land_polygons(), depth_sampler=samp, key='hito')
    check(np.array_equal(m.nodes, m2.nodes) and np.array_equal(m.tris, m2.tris), 'malla determinista (dos veces igual)')

    print('4. Marea')
    d = rd.read_forcing(S.tide_harmonics_csv(), 'marea.csv')
    t = np.arange(0, 30 * 86400, 600.0)
    eta = tide(t, d['constituents'], d['z0'])
    cols = [np.ones_like(t)]
    for c in d['constituents']:
        w = np.radians(CONSTITUENTS[c['name']]) / 3600
        cols += [np.cos(w * t), np.sin(w * t)]
    coef = np.linalg.lstsq(np.column_stack(cols), eta, rcond=None)[0]
    errs = [abs(np.hypot(coef[1 + 2 * i], coef[2 + 2 * i]) - c['amplitude']) for i, c in enumerate(d['constituents'])]
    check(max(errs) < 1e-10 and abs(coef[0] - d['z0']) < 1e-10, f'armónicos recuperados (error {max(errs):.1e} m)')
    sn = 1 / (1 / period_s('S2') - 1 / period_s('M2')) / 86400
    check(abs(sn - 14.765) < 1e-3, f'periodo vivas–muertas M2 + S2 = {sn:.3f} d')

    print('5. Criterio de longitud de onda (sin otros límites)')
    spec = {'domain': S.DOMAIN, 'segments': ['open'] * 4, 'mesh': {'h_min': 10, 'h_max': 1e5, 'wavelength_points': 2000,
                                                                     'growth': 1.0}}
    mw = build_mesh(spec, depth_sampler=samp, key='onda')
    p = params_of(spec['mesh'])
    cen = mw.nodes[mw.tris].mean(1)
    dc = samp(*mw.frame.to_lonlat(cen[:, 0], cen[:, 1]))
    npw = np.sqrt(G * dc) * p['period_s'] / mw.edge_lengths().mean(1)
    check(abs(np.median(npw) / 2000 - 1) < 0.2, f'elementos por longitud de onda M2: mediana {np.median(npw):.0f} '
                                                f'(pedidos 2000), {mw.n_elements:,} triángulos')
    return m


def server(check, base):
    import requests
    A = f'{base}/api/geodata'
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
        spec = {**SPEC, 'land_datasets': [land['id']], 'bathymetry_datasets': [bat['id']]}
        r = requests.post(f'{A}/mesh', json=spec).json()
        key = r['key']
        if r.get('job_id'):
            t0 = time.time()
            while time.time() - t0 < 300:
                j = requests.get(f"{base}/api/jobs/{r['job_id']}").json()
                j = j.get('job', j)
                if j['status'] in ('done', 'failed', 'cancelled'):
                    break
                time.sleep(0.5)
            check(j['status'] == 'done', f"job geo.mesh2d: {j['status']} {j.get('error') or j.get('message') or ''}")
        mj = requests.get(f'{A}/mesh/{key}').json()
        # reference: same inputs as the server (land read back from the shapefile), built in-process
        from scipy.spatial import cKDTree
        land_shp = [f['geometry'] for f in rd.read_vector(S.shapefile_zip_land(), 'c.zip')['features']]
        m_local = build_mesh(SPEC, land=land_shp, key='ref',
                             depth_sampler=rd.DepthSampler([rd.read_bathymetry(S.geotiff_bathy(), 'b.tif')]))
        ns = np.asarray(mj.get('nodes', [[0, 0]]), float)
        dist, j = cKDTree(m_local.lonlat()).query(ns)
        dz = np.abs(np.asarray(mj.get('depth', [0]), float) - m_local.depth[j]).max()
        same = len(mj.get('tris', [])) == m_local.n_elements and len(ns) == m_local.n_nodes and dist.max() < 1e-6 and dz < 2e-3
        check(same, f"malla del servidor = local ({len(mj.get('tris', []))} triángulos, nodos a {dist.max():.1e}°, "
                    f"profundidad {dz:.1e} m)")
        G_ = f'{base}/api/design/graph'
        gid = requests.post(f'{G_}/', json={'name': 'HITO geodatos · bahía', 'tier': 1}).json()['id']
        requests.post(f'{G_}/{gid}/nodes', json={'node_type': 'GEOMETRY', 'label': 'Bahía', 'pos_x': 0, 'pos_y': 0,
                                                 'properties': {'shape': 'domain_2d', **spec}})
        pf = requests.get(f'{base}/api/design/solver/{gid}/preflight').json()
        msgs = [i['message'] for i in pf.get('issues', [])]
        check(msgs and not any('10.3' in m for m in msgs),
              f'preflight del estudio (dominio 2D aceptado, falta el resto): «{(msgs or [""])[0][:120]}»')
    finally:
        if gid:
            requests.delete(f'{base}/api/design/graph/{gid}', params={'cascade': 1})
        for i in made:
            requests.delete(f'{A}/{i}')


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

    local(check)
    label = 'Hito de datos geográficos y malla 2D (FASE 10.5)'
    if args.server:
        print('Servidor')
        server(check, args.server.rstrip('/'))
        label += ' + servidor'
    print(f"\n{label}: {'CUMPLIDO' if not fails else 'NO CUMPLIDO'}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
