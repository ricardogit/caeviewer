"""Coordinate reference systems (pyproj). Datasets are normalised to WGS84 lon/lat (EPSG:4326) on import, except
grids, which keep their own CRS (resampling a raster is lossy) and are sampled through a transform. Meshes live in a
local UTM frame (metres, ``utm_epsg`` of the domain centroid) shifted by an origin for numerical robustness."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

WGS84 = 'EPSG:4326'


def parse_crs(value) -> str:
    """Canonical CRS string ('EPSG:xxxx' when it has an EPSG code, else the WKT) from an EPSG code / string / WKT
    (.prj content) / URN ('urn:ogc:def:crs:EPSG::25830', 'urn:ogc:def:crs:OGC:1.3:CRS84')."""
    from pyproj import CRS
    if value in (None, ''):
        return WGS84
    if isinstance(value, (int, np.integer)):
        return f'EPSG:{int(value)}'
    s = str(value).strip()
    if s.upper().endswith('CRS84'):
        return WGS84
    try:
        crs = CRS.from_user_input(s)
    except Exception as e:      # pyproj.exceptions.CRSError
        raise ValueError(f'Sistema de coordenadas no reconocido: {s[:80]!r} ({e})')
    epsg = crs.to_epsg(min_confidence=70)
    return f'EPSG:{epsg}' if epsg else crs.to_wkt()


@lru_cache(maxsize=64)
def transformer(src: str, dst: str):
    from pyproj import Transformer
    return Transformer.from_crs(src, dst, always_xy=True)


def transform(x, y, src: str, dst: str):
    """Arrays x, y (lon, lat for geographic CRS: always x = east) from src to dst."""
    if src == dst:
        return np.asarray(x, float), np.asarray(y, float)
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size == 1:              # pyproj's single-point path converts arrays to scalars (NumPy deprecation)
        X, Y = transformer(src, dst).transform(float(x.ravel()[0]), float(y.ravel()[0]))
        return np.full(x.shape, X), np.full(y.shape, Y)
    X, Y = transformer(src, dst).transform(x, y)
    return np.asarray(X, float), np.asarray(Y, float)


def map_geometry(geom, fn):
    """Apply fn(x_array, y_array) → (X, Y) to every coordinate of a shapely geometry (2-D)."""
    import shapely
    return shapely.transform(geom, lambda c: np.column_stack(fn(c[:, 0], c[:, 1])))


def is_geographic(crs: str) -> bool:
    from pyproj import CRS
    return CRS.from_user_input(crs).is_geographic


def utm_epsg(lon: float, lat: float) -> int:
    """WGS84 / UTM zone of a point (326zz north, 327zz south; Norway / Svalbard exceptions)."""
    if not (-180 <= lon <= 180 and -80 <= lat <= 84):
        raise ValueError(f'Punto fuera del rango UTM: lon {lon}, lat {lat}.')
    zone = int((lon + 180) // 6) + 1
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat < 84:
        for z, (a, b) in ((31, (0, 9)), (33, (9, 21)), (35, (21, 33)), (37, (33, 42))):
            if a <= lon < b:
                zone = z
    zone = min(zone, 60)
    return (32600 if lat >= 0 else 32700) + zone


class LocalFrame:
    """UTM frame of a domain with an origin: local (x, y) = UTM − origin, metres."""

    def __init__(self, epsg: int, origin=(0.0, 0.0)):
        self.epsg = int(epsg)
        self.crs = f'EPSG:{self.epsg}'
        self.origin = (float(origin[0]), float(origin[1]))

    @classmethod
    def for_lonlat(cls, lon, lat, epsg: int | None = None) -> 'LocalFrame':
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        e = epsg or utm_epsg(float(lon.mean()), float(lat.mean()))
        X, Y = transform(lon, lat, WGS84, f'EPSG:{e}')
        # origin rounded to 1 km: same domain ± a vertex → same origin (stable mesh hash)
        return cls(e, (round(float(X.mean()) / 1000) * 1000.0, round(float(Y.mean()) / 1000) * 1000.0))

    def from_lonlat(self, lon, lat):
        X, Y = transform(lon, lat, WGS84, self.crs)
        return X - self.origin[0], Y - self.origin[1]

    def to_lonlat(self, x, y):
        return transform(np.asarray(x, float) + self.origin[0], np.asarray(y, float) + self.origin[1], self.crs, WGS84)

    def from_crs(self, x, y, src: str):
        X, Y = transform(x, y, src, self.crs)
        return X - self.origin[0], Y - self.origin[1]

    def to_crs(self, x, y, dst: str):
        return transform(np.asarray(x, float) + self.origin[0], np.asarray(y, float) + self.origin[1], self.crs, dst)

    def to_dict(self) -> dict:
        return {'epsg': self.epsg, 'origin': list(self.origin)}
