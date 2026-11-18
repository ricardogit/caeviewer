"""Synthetic geographic files with a known truth (tests and ``validate_geodata.py``): one bay written in every
supported format. Linear bathymetry in lon/lat (bilinear / linear interpolation reproduce it exactly), land = an
eastern coast with a cove + one island."""
from __future__ import annotations

import io
import json
import zipfile

import numpy as np

LON0, LAT0 = -8.80, 42.20                  # Ría-like site, UTM 29N
DOMAIN = [[LON0, LAT0], [LON0 + 0.25, LAT0], [LON0 + 0.25, LAT0 + 0.14], [LON0, LAT0 + 0.14]]
COAST = [(LON0 + 0.18, LAT0 - 0.01), (LON0 + 0.30, LAT0 - 0.01), (LON0 + 0.30, LAT0 + 0.15), (LON0 + 0.18, LAT0 + 0.15),
         (LON0 + 0.18, LAT0 + 0.09), (LON0 + 0.12, LAT0 + 0.08), (LON0 + 0.12, LAT0 + 0.06), (LON0 + 0.18, LAT0 + 0.05)]
ISLAND = [(LON0 + 0.05, LAT0 + 0.05), (LON0 + 0.07, LAT0 + 0.05), (LON0 + 0.07, LAT0 + 0.07), (LON0 + 0.05, LAT0 + 0.07)]
GX = np.linspace(LON0 - 0.05, LON0 + 0.35, 81)
GY = np.linspace(LAT0 - 0.05, LAT0 + 0.20, 51)
POINT = {'label': 'emisario', 'lon': LON0 + 0.10, 'lat': LAT0 + 0.07}


def depth(lon, lat):
    """Exact bathymetry [m, positive down]: deeper to the west (offshore)."""
    return 60.0 - 200.0 * (np.asarray(lon) - LON0) + 30.0 * (np.asarray(lat) - LAT0)


def land_polygons():
    from shapely.geometry import Polygon
    return [Polygon(COAST), Polygon(ISLAND)]


def geojson_land(crs: str | None = None) -> bytes:
    """Land polygons; with ``crs`` (e.g. 'EPSG:25829') the coordinates are projected and the legacy crs member set."""
    from app.geodata.crs import WGS84, transform

    def ring(pts):
        a = np.asarray(pts + [pts[0]], float)
        if crs:
            x, y = transform(a[:, 0], a[:, 1], WGS84, crs)
            a = np.column_stack([x, y])
        return a.tolist()
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'name': n}, 'geometry': {'type': 'Polygon', 'coordinates': [ring(p)]}}
        for n, p in (('costa', COAST), ('isla', ISLAND))]}
    if crs:
        fc['crs'] = {'type': 'name', 'properties': {'name': crs}}
    return json.dumps(fc).encode()


def kml_land() -> bytes:
    def coords(pts):
        return ' '.join(f'{x},{y},0' for x, y in pts + [pts[0]])
    pms = ''.join(f'<Placemark><name>{n}</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{coords(p)}'
                  f'</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>'
                  for n, p in (('costa', COAST), ('isla', ISLAND)))
    return (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{pms}'
            f'</Document></kml>').encode()


def shapefile_zip_land(crs: str = 'EPSG:25829') -> bytes:
    """Zipped shapefile in a projected CRS with its .prj (ESRI WKT)."""
    import shapefile
    from pyproj import CRS
    from pyproj.enums import WktVersion
    from app.geodata.crs import WGS84, transform
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    w.field('name', 'C', 20)
    for n, p in (('costa', COAST), ('isla', ISLAND)):
        a = np.asarray(p[::-1] + [p[-1]], float)             # shapefile outer rings are clockwise
        x, y = transform(a[:, 0], a[:, 1], WGS84, crs)
        w.poly([np.column_stack([x, y]).tolist()])
        w.record(n)
    w.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('costa.shp', shp.getvalue())
        z.writestr('costa.shx', shx.getvalue())
        z.writestr('costa.dbf', dbf.getvalue())
        z.writestr('costa.prj', CRS.from_user_input(crs).to_wkt(WktVersion.WKT1_ESRI))
    return buf.getvalue()


def _grid_elevation():
    X, Y = np.meshgrid(GX, GY)
    return -depth(X, Y)                                      # GEBCO style: elevation, negative below the datum


def geotiff_bathy() -> bytes:
    """GeoTIFF, EPSG:4326, PixelIsPoint (tie point = first pixel centre), north-up rows, elevation."""
    import tifffile
    z = _grid_elevation()[::-1]                               # row 0 = north (float64: exact)
    dx, dy = GX[1] - GX[0], GY[1] - GY[0]
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 2, 2048, 0, 1, 4326]
    buf = io.BytesIO()
    tifffile.imwrite(buf, z, extratags=[(33550, 'd', 3, (dx, dy, 0.0), True),
                                        (33922, 'd', 6, (0.0, 0.0, 0.0, GX[0], GY[-1], 0.0), True),
                                        (34735, 'H', len(geokeys), geokeys, True)])
    return buf.getvalue()


def netcdf_classic_bathy() -> bytes:
    import os
    import tempfile
    from scipy.io import netcdf_file
    fd, path = tempfile.mkstemp(suffix='.nc')
    os.close(fd)
    try:
        f = netcdf_file(path, 'w')
        f.createDimension('lat', len(GY))
        f.createDimension('lon', len(GX))
        f.createVariable('lat', 'd', ('lat',))[:] = GY
        f.createVariable('lon', 'd', ('lon',))[:] = GX
        f.createVariable("elevation", "d", ("lat", "lon"))[:] = _grid_elevation()
        f.close()
        with open(path, 'rb') as fh:
            return fh.read()
    finally:
        os.unlink(path)


def netcdf4_bathy() -> bytes:
    """NetCDF-4 (HDF5) like GEBCO: lat descending to exercise the axis flip."""
    import h5py
    buf = io.BytesIO()
    with h5py.File(buf, 'w') as f:
        f['lat'] = GY[::-1]
        f['lon'] = GX
        f["elevation"] = _grid_elevation()[::-1]
    return buf.getvalue()


def xyz_soundings(n: int = 1500, seed: int = 1) -> bytes:
    """Scattered soundings in lon/lat, depth positive down."""
    rng = np.random.default_rng(seed)
    lon = rng.uniform(GX[0], GX[-1], n)
    lat = rng.uniform(GY[0], GY[-1], n)
    corners = np.array([[GX[0], GY[0]], [GX[-1], GY[0]], [GX[-1], GY[-1]], [GX[0], GY[-1]]])
    lon, lat = np.r_[corners[:, 0], lon], np.r_[corners[:, 1], lat]
    return ('lon lat depth\n' + '\n'.join(f'{a:.10f} {b:.10f} {depth(a, b):.10f}' for a, b in zip(lon, lat))).encode()


def tide_harmonics_csv() -> bytes:
    return b'constituent,amplitude,phase\nM2,1.20,75\nS2,0.42,105\nK1,0.07,60\nO1,0.06,320\nZ0,2.1,0\n'


def river_series_csv() -> bytes:
    rows = ['fecha;caudal_m3s'] + [f'2026-03-0{1 + d} {h:02d}:00;{40 + 10 * np.sin(np.pi * (24 * d + h) / 36):.3f}'
                                   .replace('.', ',') for d in range(3) for h in range(0, 24, 3)]
    return '\n'.join(rows).encode()


def points_csv() -> bytes:
    return f'nombre,lon,lat\n{POINT["label"]},{POINT["lon"]},{POINT["lat"]}\n'.encode()
