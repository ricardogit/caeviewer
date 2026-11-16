"""FASE 10.5 geographic data: CRS, readers (every format agrees with the synthetic truth), tides, 2D mesh, API.

The API test needs a local PostgreSQL (scratch DB fixture of test_step_files_api); skipped otherwise. The mesh is
built in-process (the API test only checks the enqueue / cache contract, the worker is not running)."""
import io

import numpy as np
import pytest

pytest.importorskip('pyproj')
pytest.importorskip('shapely')

from app.geodata import crs as C  # noqa: E402
from app.geodata import readers as rd  # noqa: E402
from app.geodata import synthetic as S  # noqa: E402
from app.geodata.forcing import CONSTITUENTS, period_s, tide  # noqa: E402
from test_step_files_api import app  # noqa: F401,E402


def test_utm_zone_and_roundtrip():
    assert C.utm_epsg(-8.7, 42.2) == 32629 and C.utm_epsg(-58.4, -34.6) == 32721
    assert C.utm_epsg(5.0, 60.0) == 32632                     # Norway exception (32V)
    assert C.utm_epsg(15.0, 78.0) == 32633                    # Svalbard
    fr = C.LocalFrame.for_lonlat([-8.8, -8.6], [42.2, 42.3])
    assert fr.epsg == 32629 and fr.origin[0] % 1000 == 0
    lon, lat = np.array([-8.71, -8.62]), np.array([42.21, 42.29])
    x, y = fr.from_lonlat(lon, lat)
    lo, la = fr.to_lonlat(x, y)
    assert np.abs(lo - lon).max() < 1e-10 and np.abs(la - lat).max() < 1e-10
    assert C.parse_crs('urn:ogc:def:crs:OGC:1.3:CRS84') == C.WGS84 and C.parse_crs(25830) == 'EPSG:25830'
    with pytest.raises(ValueError):
        C.parse_crs('no-such-crs')


def test_utm_scale_factor_on_central_meridian():
    """Grid distance / geodesic distance = k0 = 0.9996 on the central meridian (−9° for zone 29)."""
    from pyproj import Geod
    fr = C.LocalFrame(32629)
    x, y = fr.from_lonlat([-9.0, -9.0], [42.0, 42.01])
    grid = np.hypot(x[1] - x[0], y[1] - y[0])
    geo = Geod(ellps='WGS84').inv(-9.0, 42.0, -9.0, 42.01)[2]
    assert grid / geo == pytest.approx(0.9996, abs=1e-7)


def test_vector_readers_agree():
    from shapely.ops import unary_union
    ref = unary_union(S.land_polygons())
    for data, fn in ((S.geojson_land(), 'c.geojson'), (S.geojson_land('EPSG:25829'), 'c.geojson'),
                     (S.kml_land(), 'c.kml'), (S.shapefile_zip_land(), 'c.zip')):
        d = rd.read_vector(data, fn)
        u = unary_union([f['geometry'] for f in d['features']])
        assert u.symmetric_difference(ref).area < 1e-9 * ref.area, fn
        assert {f['props']['name'] for f in d['features']} == {'costa', 'isla'}
    assert rd.read_vector(S.shapefile_zip_land(), 'c.zip')['source_crs'] == 'EPSG:25829'
    with pytest.raises(rd.GeoReadError):
        rd.read_vector(b'{"type": "FeatureCollection", "features": []}', 'x.geojson')


def test_bathymetry_readers_reproduce_linear_depth():
    rng = np.random.default_rng(0)
    lon = rng.uniform(S.LON0, S.LON0 + 0.3, 300)
    lat = rng.uniform(S.LAT0, S.LAT0 + 0.15, 300)
    for data, fn, conv in ((S.geotiff_bathy(), 'b.tif', 'elevation'), (S.netcdf_classic_bathy(), 'b.nc', 'elevation'),
                           (S.netcdf4_bathy(), 'b.nc', 'elevation'), (S.xyz_soundings(), 'b.xyz', 'depth')):
        d = rd.read_bathymetry(data, fn)
        assert d['convention'] == conv and d['crs'] == C.WGS84
        z = rd.DepthSampler([d])(lon, lat)
        assert np.abs(z - S.depth(lon, lat)).max() < 1e-7, fn
    with pytest.raises(rd.GeoReadError):
        rd.read_bathymetry(b'1 2\n3 4\n', 'b.xyz')


def test_sampler_priority_and_projected_soundings():
    """Detailed chart over a regional grid; soundings given in UTM."""
    fr = C.LocalFrame(32629)
    xs, ys = np.meshgrid(np.linspace(-20e3, 20e3, 15), np.linspace(-20e3, 20e3, 15))
    X, Y = xs.ravel() + 520000, ys.ravel() + 4675000
    chart = {'kind': 'scatter', 'x': X, 'y': Y, 'z': np.full(X.size, 7.0), 'crs': 'EPSG:32629'}
    grid = rd.read_bathymetry(S.geotiff_bathy(), 'b.tif')
    s = rd.DepthSampler([chart, grid])
    lon, lat = fr.to_lonlat(np.array([520000.0, 0.0]) - fr.origin[0], np.array([4675000.0, 4675000.0]) - fr.origin[1])
    z = s(np.r_[lon[0], S.LON0 + 0.3], np.r_[lat[0], S.LAT0 + 0.1])
    assert z[0] == pytest.approx(7.0) and z[1] == pytest.approx(S.depth(S.LON0 + 0.3, S.LAT0 + 0.1))


def test_tide_synthesis_and_forcing_csv():
    d = rd.read_forcing(S.tide_harmonics_csv(), 't.csv')
    assert [c['name'] for c in d['constituents']] == ['M2', 'S2', 'K1', 'O1'] and d['z0'] == 2.1
    t = np.arange(0, 30 * 86400, 600.0)
    eta = tide(t, d['constituents'], d['z0'])
    # harmonic least squares recovers the constants
    cols = [np.ones_like(t)]
    for c in d['constituents']:
        w = np.radians(CONSTITUENTS[c['name']]) / 3600
        cols += [np.cos(w * t), np.sin(w * t)]
    coef = np.linalg.lstsq(np.column_stack(cols), eta, rcond=None)[0]
    for i, c in enumerate(d['constituents']):
        a, b = coef[1 + 2 * i], coef[2 + 2 * i]
        assert np.hypot(a, b) == pytest.approx(c['amplitude'], abs=1e-10)
        assert np.degrees(np.arctan2(b, a)) % 360 == pytest.approx(c['phase'] % 360, abs=1e-8)
    assert period_s('M2') / 3600 == pytest.approx(12.4206, abs=1e-4)
    r = rd.read_forcing(S.river_series_csv(), 'q.csv')
    assert r['t0'] == '2026-03-01T00:00:00' and r['t'][1] == 10800 and r['columns']['caudal_m3s'][0] == 40.0
    with pytest.raises(rd.GeoReadError):
        rd.read_forcing(b'constituent,amplitude,phase\nXX9,1,0\n', 't.csv')


SPEC = {'domain': S.DOMAIN, 'segments': ['open', 'coast', 'coast', 'open'],
        'mesh': {'h_min': 100, 'h_max': 1500, 'wavelength_points': 300, 'growth': 0.2},
        'points': [{**S.POINT, 'size': 80}]}


@pytest.fixture(scope='module')
def bay():
    pytest.importorskip('gmsh')
    from app.geodata.mesh2d import build_mesh
    samp = rd.DepthSampler([rd.read_bathymetry(S.geotiff_bathy(), 'b.tif')])
    return build_mesh(SPEC, land=S.land_polygons(), depth_sampler=samp, key='k'), samp


def test_mesh_domain_boundaries_and_depth(bay):
    from app.geodata.mesh2d import water_domain
    m, _ = bay
    water, dom = water_domain(S.DOMAIN, S.land_polygons(), m.frame)
    area = sum(p.area for p in water)
    assert m.areas().min() > 0 and m.areas().sum() == pytest.approx(area, rel=1e-9)
    assert m.stats['n_holes'] == 1 and m.stats['n_parts'] == 1
    ids = {b['id']: b for b in m.boundary_info}
    assert set(ids) == {'edge0', 'edge2', 'edge3', 'coast'}       # edge1 (east) is entirely on land
    assert ids['edge0']['kind'] == 'open' and ids['edge2']['kind'] == 'coast'
    shore = sum(p.boundary.length for p in water) - sum(ids[k]['length_m'] for k in ('edge0', 'edge2', 'edge3'))
    assert ids['coast']['length_m'] == pytest.approx(shore, rel=1e-9)
    lonlat = m.lonlat()
    assert np.abs(m.depth - S.depth(lonlat[:, 0], lonlat[:, 1])).max() < 1e-7
    assert m.stats['min_angle_deg'] > 25
    assert 0.7 < m.n_elements / m.stats['estimated_elements'] < 1.3


def test_mesh_element_cap():
    pytest.importorskip('gmsh')
    from app.geodata.mesh2d import build_mesh
    with pytest.raises(ValueError, match='triángulos'):
        build_mesh({**SPEC, 'mesh': {'h_min': 100, 'h_max': 200, 'max_elements': 5000}}, land=S.land_polygons())


def test_mesh_size_grading(bay):
    from app.geodata.mesh2d import target_size_at
    m, samp = bay
    r = m.edge_lengths().mean(1) / target_size_at(SPEC, m, samp)
    assert 0.7 < np.median(r) < 1.3 and np.mean((r > 0.5) & (r < 1.6)) > 0.9
    px, py = m.frame.from_lonlat([S.POINT['lon']], [S.POINT['lat']])
    cen = m.nodes[m.tris].mean(1)
    near = np.hypot(cen[:, 0] - px[0], cen[:, 1] - py[0]) < 300
    assert near.sum() > 10 and m.edge_lengths()[near].mean() < 250


def test_mesh_bytes_and_key():
    from app.geodata.mesh2d import Mesh2D, mesh_key, params_of
    k1 = mesh_key(SPEC, ['bathy:abc:{}'])
    assert k1 == mesh_key(dict(SPEC), ['bathy:abc:{}'])
    assert k1 != mesh_key({**SPEC, 'mesh': {**SPEC['mesh'], 'h_min': 99}}, ['bathy:abc:{}'])
    assert k1 != mesh_key(SPEC, ['bathy:abd:{}'])
    with pytest.raises(ValueError):
        params_of({'h_min': 10, 'h_max': 5})
    m = Mesh2D(np.array([[0, 0], [1, 0], [0, 1.0]]), [[0, 1, 2]], [1, 2, 3], C.LocalFrame(32629, (5e5, 4e6)),
               {'coast': [[0, 1]]}, [{'id': 'coast'}])
    import json
    from app.geodata.service import mesh_json
    m.depth[1] = np.nan                        # node outside every bathymetry dataset
    assert json.loads(json.dumps(mesh_json(m), allow_nan=False))['depth'] == [1.0, None, 3.0]
    m2 = Mesh2D.from_bytes(m.to_bytes())
    assert np.array_equal(m2.nodes, m.nodes) and m2.frame.origin == (5e5, 4e6) and m2.boundary['coast'].shape == (1, 2)


def test_api_upload_mesh_contract_and_graph(app, tmp_path):  # noqa: F811
    from app.extensions import db
    from app.geodata import service
    from app.geodata.mesh2d import build_mesh
    app.config['DATA_DIR'] = str(tmp_path)
    c = app.test_client()

    def up(data, fn, kind, **extra):
        return c.post('/api/geodata', data={'file': (io.BytesIO(data), fn), 'kind': kind, **extra},
                      content_type='multipart/form-data')
    r = up(S.shapefile_zip_land(), 'costa.zip', 'coastline')
    assert r.status_code == 201, r.get_json()
    land = r.get_json()['dataset']
    assert land['source_crs'] == 'EPSG:25829' and land['summary']['n_features'] == 2
    assert up(S.shapefile_zip_land(), 'costa.zip', 'coastline').status_code == 200       # deduplicated
    bat = up(S.geotiff_bathy(), 'gebco.tif', 'bathymetry').get_json()['dataset']
    assert bat['has_preview'] and bat['summary']['convention'] == 'elevation'
    assert c.get(f"/api/geodata/{bat['id']}/preview.png").status_code == 200
    assert up(b'garbage', 'x.tif', 'bathymetry').status_code == 400
    tide_ds = up(S.tide_harmonics_csv(), 'marea.csv', 'forcing').get_json()['dataset']
    s = c.get(f"/api/geodata/{tide_ds['id']}/series?days=1&dt_min=60").get_json()
    assert len(s['t']) == 25 and s['columns']['eta_m'][0] == pytest.approx(
        tide([0.0], [{'name': 'M2', 'amplitude': 1.2, 'phase': 75}, {'name': 'S2', 'amplitude': 0.42, 'phase': 105},
                     {'name': 'K1', 'amplitude': 0.07, 'phase': 60}, {'name': 'O1', 'amplitude': 0.06, 'phase': 320}],
             2.1)[0], abs=1e-4)
    dep = c.post(f"/api/geodata/{bat['id']}/depth", json={'points': [[S.LON0 + 0.1, S.LAT0 + 0.1]]}).get_json()
    assert dep['depth'][0] == pytest.approx(S.depth(S.LON0 + 0.1, S.LAT0 + 0.1))
    assert len(c.get('/api/geodata?kind=bathymetry').get_json()['datasets']) == 1

    spec = {**SPEC, 'land_datasets': [land['id']], 'bathymetry_datasets': [bat['id']]}
    r = c.post('/api/geodata/mesh', json=spec)
    assert r.status_code == 202 and r.get_json()['job_id']
    key = r.get_json()['key']
    assert c.get(f'/api/geodata/mesh/{key}').status_code == 404
    with app.app_context():                     # what the worker does
        inp = service.mesh_inputs(spec)
        assert inp['key'] == key
        m = build_mesh(spec, land=inp['land'], depth_sampler=inp['depth_sampler'], key=key)
        service.mesh_path(key).parent.mkdir(parents=True, exist_ok=True)
        service.mesh_path(key).write_bytes(m.to_bytes())
    assert c.post('/api/geodata/mesh', json=spec).get_json() == {'key': key, 'cached': True}
    mj = c.get(f'/api/geodata/mesh/{key}').get_json()
    assert len(mj['tris']) == m.n_elements and {b['id'] for b in mj['boundary_info']} >= {'edge0', 'coast'}
    assert c.post('/api/geodata/mesh', json={'mesh': {}}).status_code == 400

    # study GEOMETRY domain_2d: spec error until the 2D solver exists; hash by dataset content
    from app.design.models.graph import DesignGraph, DesignNode
    from app.design.services.graph_to_solver_spec import GraphSpecError, graph_to_solver_spec
    from app.design.services.traceability.hasher import domain_2d_identity
    with app.app_context():
        g = DesignGraph(name='bahía', version=1, tier=1, status='draft')
        db.session.add(g)
        db.session.flush()
        db.session.add(DesignNode(graph_id=g.id, node_type='GEOMETRY', label='Dominio', level=0,
                                  properties={'shape': 'domain_2d', **spec}))
        db.session.commit()
        with pytest.raises(GraphSpecError, match='FASE 10.3'):
            graph_to_solver_spec(g.id)
        ident = domain_2d_identity(spec)
        assert ident['bathymetry_datasets'][0]['sha256'] == service.get_datasets([bat['id']])[0].sha256
        gid = g.id
    assert c.delete(f"/api/geodata/{bat['id']}").status_code == 409            # used by the study
    with app.app_context():
        DesignNode.query.filter_by(graph_id=gid).delete()
        db.session.delete(db.session.get(DesignGraph, gid))
        db.session.commit()
    assert c.delete(f"/api/geodata/{bat['id']}").status_code == 200
    assert c.get(f"/api/geodata/{bat['id']}").status_code == 404
