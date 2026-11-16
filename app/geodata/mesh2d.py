"""2D unstructured triangle mesh of a water domain (FASE 10.5), Gmsh.

Water = domain polygon drawn on the map (lon/lat) − land polygons (coastline datasets; islands become holes), in
the local UTM frame of the domain. Boundary ids: ``edge<i>`` = the part of drawn edge i that stays in the water
(kind per edge: ``open`` sea, ``river`` inflow or ``coast``), ``coast`` = contact with land. They play the role of
CAD faces for the 2D boundary conditions (tide, river, coast) of FASE 10.3.

Element size (metres) = min of the active criteria, clamped to [h_min, h_max], then gradation-limited
(|∇h| ≤ growth) on a background grid handed to Gmsh as a post-processing view (no Python size callback):
  wave        √(g·d)·T / N         N = ``wavelength_points`` elements per tidal wavelength (T = ``period_s``, M2)
  slope       β · d / |∇d|         β = ``slope_factor`` (relative depth change per element ≲ 1/β)
  points      size_i + growth·r_i  refinement around discharges, beaches, gauges (``points``)
d = max(depth, ``d_min``) (dry / missing cells use d_min). Nodes get the depth of the bathymetry (priority list).
"""
from __future__ import annotations

import hashlib
import io
import json

import numpy as np

from app.geodata.crs import LocalFrame
from app.geodata.forcing import period_s

MESHER2D_VERSION = 1
G = 9.80665
SEGMENT_KINDS = ('open', 'river', 'coast')
DEFAULTS = {'h_min': 50.0, 'h_max': 2000.0, 'wavelength_points': 0.0, 'period_s': None, 'slope_factor': 0.0,
            'growth': 0.25, 'd_min': 1.0, 'grid_cells': 300, 'max_elements': 300_000}


def params_of(mesh: dict | None) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in (mesh or {}).items() if v is not None}}
    for k in ('h_min', 'h_max', 'growth', 'd_min'):
        p[k] = float(p[k])
        if not p[k] > 0:
            raise ValueError(f'Malla 2D: {k} debe ser > 0.')
    if p['h_min'] > p['h_max']:
        raise ValueError('Malla 2D: h_min ≤ h_max.')
    p['wavelength_points'] = float(p['wavelength_points'] or 0)
    p['slope_factor'] = float(p['slope_factor'] or 0)
    p['period_s'] = float(p['period_s'] or period_s('M2'))
    p['grid_cells'] = int(min(max(int(p['grid_cells']), 50), 1000))
    p['max_elements'] = int(min(max(int(p['max_elements']), 1000), 5_000_000))
    return p


# ── Domain ────────────────────────────────────────────────────────────────────

def _to_local(geom, frame: LocalFrame):
    from app.geodata.crs import map_geometry
    return map_geometry(geom, frame.from_lonlat)


def water_domain(domain_lonlat, land_lonlat: list, frame: LocalFrame, simplify: float = 0.0):
    """(water polygon(s) in the local frame, drawn domain polygon in the local frame)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    ring = np.asarray(domain_lonlat, float)
    if ring.ndim != 2 or ring.shape[1] != 2 or len(ring) < 3:
        raise ValueError('Dominio: polígono de al menos 3 vértices [[lon, lat], …].')
    if np.allclose(ring[0], ring[-1]):
        ring = ring[:-1]
    x, y = frame.from_lonlat(ring[:, 0], ring[:, 1])
    dom = Polygon(np.column_stack([x, y]))
    if not dom.is_valid:
        raise ValueError('Dominio: el polígono dibujado se corta a sí mismo.')
    water = dom
    if land_lonlat:
        land = unary_union([make_valid(_to_local(g, frame)) for g in land_lonlat])
        land = land.intersection(dom.buffer(1e-6 * np.sqrt(dom.area)))
        if simplify > 0:
            land = land.simplify(simplify, preserve_topology=True)
        water = make_valid(dom.difference(land))
    polys = [g for g in getattr(water, 'geoms', [water]) if g.geom_type == 'Polygon' and g.area > 0]
    if not polys:
        raise ValueError('Dominio: no queda agua (el polígono está entero en tierra).')
    return polys, dom


def _edge_of(a, b, dom_xy, tol):
    """Index of the drawn edge containing segment ab (both ends on it), else None (coast)."""
    n = len(dom_xy)
    for i in range(n):
        p, q = dom_xy[i], dom_xy[(i + 1) % n]
        d = q - p
        L2 = float(d @ d)
        ok = True
        for c in (a, b, 0.5 * (a + b)):
            t = float(np.clip((c - p) @ d / L2, 0, 1))
            if np.linalg.norm(c - (p + t * d)) > tol:
                ok = False
                break
        if ok:
            return i
    return None


# ── Size field ────────────────────────────────────────────────────────────────

def size_grid(bounds, depth_fn, points_xy, p: dict):
    """Background size on a regular grid covering ``bounds`` (xmin, ymin, xmax, ymax): (xs, ys, H (ny, nx), D)."""
    xmin, ymin, xmax, ymax = bounds
    ext = max(xmax - xmin, ymax - ymin)
    pad = 0.02 * ext
    n = p['grid_cells']
    dx = ext / n
    xs = np.arange(xmin - pad, xmax + pad + dx, dx)
    ys = np.arange(ymin - pad, ymax + pad + dx, dx)
    X, Y = np.meshgrid(xs, ys)
    D = depth_fn(X.ravel(), Y.ravel()).reshape(X.shape) if depth_fn else np.full(X.shape, np.nan)
    d = np.where(np.isfinite(D), np.maximum(D, p['d_min']), p['d_min'])
    H = np.full(X.shape, p['h_max'])
    if p['wavelength_points'] > 0:
        H = np.minimum(H, np.sqrt(G * d) * p['period_s'] / p['wavelength_points'])
    if p['slope_factor'] > 0:
        gy, gx = np.gradient(d, dx)
        slope = np.hypot(gx, gy)
        with np.errstate(divide='ignore'):
            H = np.minimum(H, np.where(slope > 0, p['slope_factor'] * d / slope, np.inf))
    for (px, py, ps) in points_xy:
        H = np.minimum(H, ps + p['growth'] * np.hypot(X - px, Y - py))
    H = np.clip(H, p['h_min'], p['h_max'])
    H = limit_gradation(H, dx, p['growth'])
    return xs, ys, H, D


def estimate_elements(xs, ys, H, water) -> float:
    """Triangles of a mesh following H over ``water``: ∫ dA / (√3/4 h²) on the background grid cells inside it."""
    import shapely
    dx = xs[1] - xs[0]
    X, Y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(water, X.ravel(), Y.ravel()).reshape(X.shape)
    return float((dx * dx / (np.sqrt(3) / 4 * H[inside] ** 2)).sum())


def limit_gradation(H: np.ndarray, dx: float, growth: float, max_iter: int = 5000) -> np.ndarray:
    """H(x) ≤ H(y) + growth·|x − y| over the 8-neighbour graph (iterated until no change)."""
    H = H.copy()
    s1, s2 = growth * dx, growth * dx * np.sqrt(2.0)
    for _ in range(max_iter):
        old = H
        P = np.pad(H, 1, mode='edge')
        cand = [P[1:-1, :-2] + s1, P[1:-1, 2:] + s1, P[:-2, 1:-1] + s1, P[2:, 1:-1] + s1,
                P[:-2, :-2] + s2, P[:-2, 2:] + s2, P[2:, :-2] + s2, P[2:, 2:] + s2]
        H = np.minimum.reduce([H] + cand)
        if np.array_equal(H, old):
            break
    return H


# ── Mesh ──────────────────────────────────────────────────────────────────────

class Mesh2D:
    """P1 triangles in the local frame. ``boundary`` {id: (k, 2) node pairs}, ``boundary_info`` [{id, kind,
    label, length_m}], ``zone`` per triangle (−1 = none) with ``zones`` [{label, props}]."""

    def __init__(self, nodes, tris, depth, frame: LocalFrame, boundary: dict, boundary_info: list, zone=None,
                 zones=None, stats=None, key=None):
        self.nodes = np.asarray(nodes, float)
        self.tris = np.asarray(tris, np.int64)
        self.depth = np.asarray(depth, float)
        self.frame = frame
        self.boundary = {k: np.asarray(v, np.int64).reshape(-1, 2) for k, v in boundary.items()}
        self.boundary_info = boundary_info
        self.zone = np.full(len(self.tris), -1) if zone is None else np.asarray(zone, np.int64)
        self.zones = zones or []
        self.stats = stats or {}
        self.key = key

    @property
    def n_nodes(self):
        return len(self.nodes)

    @property
    def n_elements(self):
        return len(self.tris)

    def areas(self):
        P = self.nodes[self.tris]
        return 0.5 * ((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1])
                      - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))

    def min_angles_deg(self):
        P = self.nodes[self.tris]
        ang = []
        for i in range(3):
            a, b, c = P[:, i], P[:, (i + 1) % 3], P[:, (i + 2) % 3]
            u, v = b - a, c - a
            cosang = np.einsum('ij,ij->i', u, v) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
            ang.append(np.degrees(np.arccos(np.clip(cosang, -1, 1))))
        return np.min(ang, axis=0)

    def edge_lengths(self):
        P = self.nodes[self.tris]
        return np.stack([np.linalg.norm(P[:, (i + 1) % 3] - P[:, i], axis=1) for i in range(3)], 1)

    def lonlat(self):
        lon, lat = self.frame.to_lonlat(self.nodes[:, 0], self.nodes[:, 1])
        return np.column_stack([lon, lat])

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        arrs = {'nodes': self.nodes, 'tris': self.tris, 'depth': self.depth, 'zone': self.zone}
        for k, v in self.boundary.items():
            arrs[f'b__{k}'] = v
        meta = {'frame': self.frame.to_dict(), 'boundary_info': self.boundary_info, 'zones': self.zones,
                'stats': self.stats, 'key': self.key, 'version': MESHER2D_VERSION}
        np.savez_compressed(buf, meta=np.frombuffer(json.dumps(meta, default=float).encode(), np.uint8), **arrs)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Mesh2D':
        z = np.load(io.BytesIO(data))
        meta = json.loads(bytes(z['meta']).decode())
        fr = LocalFrame(meta['frame']['epsg'], meta['frame']['origin'])
        bnd = {k[3:]: z[k] for k in z.files if k.startswith('b__')}
        return cls(z['nodes'], z['tris'], z['depth'], fr, bnd, meta['boundary_info'], z['zone'], meta['zones'],
                   meta['stats'], meta['key'])


def mesh_key(spec: dict, dataset_hashes: list[str]) -> str:
    """Content key of a 2D mesh: geometry + parameters + dataset content + mesher / Gmsh version."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        gv = version('gmsh')            # no gmsh import in the web process
    except PackageNotFoundError:
        gv = None
    blob = json.dumps({'spec': {k: spec.get(k) for k in ('domain', 'segments', 'segment_labels', 'epsg', 'mesh',
                                                          'points')},
                       'data': dataset_hashes, 'v': MESHER2D_VERSION, 'gmsh': gv},
                      sort_keys=True, default=float)
    return hashlib.sha256(blob.encode()).hexdigest()


def build_mesh(spec: dict, *, land: list | None = None, depth_sampler=None, zones: list | None = None,
               points: list | None = None, key: str | None = None, progress=None) -> Mesh2D:
    """``spec`` {domain [[lon, lat]…], segments [kind per edge], segment_labels, epsg (optional), mesh {params},
    points [{label, lon, lat, size}]}; ``land`` shapely lon/lat polygons; ``depth_sampler(lon, lat)``; ``zones``
    [{'geometry': lon/lat polygon, 'props': {...}}]; ``points`` extra [{label, lon, lat, size}] (points dataset)."""
    import gmsh
    from app.design.services.fem.mesh import _gmsh_lock
    p = params_of(spec.get('mesh'))
    dom_ll = np.asarray(spec['domain'], float)
    if len(dom_ll) > 3 and np.allclose(dom_ll[0], dom_ll[-1]):
        dom_ll = dom_ll[:-1]
    n_edges = len(dom_ll)
    kinds = list(spec.get('segments') or ['open'] * n_edges)
    if len(kinds) != n_edges or any(k not in SEGMENT_KINDS for k in kinds):
        raise ValueError(f'Dominio: un tipo de contorno por lado ({n_edges}) de {", ".join(SEGMENT_KINDS)}.')
    labels = list(spec.get('segment_labels') or [None] * n_edges)
    frame = LocalFrame.for_lonlat(dom_ll[:, 0], dom_ll[:, 1], spec.get('epsg'))
    polys, dom = water_domain(dom_ll, land or [], frame, simplify=0.05 * p['h_min'])
    dom_xy = np.asarray(dom.exterior.coords)[:-1]
    ext = float(np.sqrt(dom.area))
    tol = 1e-6 * max(ext, 1.0)

    def depth_local(x, y):
        if depth_sampler is None:
            return np.full(np.shape(x), np.nan)
        lon, lat = frame.to_lonlat(x, y)
        return depth_sampler(lon, lat)

    pts = []
    for q in list(spec.get('points') or []) + list(points or []):
        px, py = frame.from_lonlat([q['lon']], [q['lat']])
        pts.append((float(px[0]), float(py[0]), float(q.get('size') or p['h_min'])))
    from shapely.ops import unary_union
    water_union = unary_union(polys)
    xs, ys, H, _ = size_grid(water_union.bounds, depth_local if depth_sampler else None, pts, p)
    n_est = estimate_elements(xs, ys, H, water_union)
    if n_est > p['max_elements']:
        raise ValueError(f'Malla 2D: se estiman {n_est:,.0f} triángulos (límite {p["max_elements"]:,}). Aumente h_min / '
                         f'h_max, reduzca el dominio o suba max_elements.')
    if progress:
        progress(20, f'campo de tamaño {H.shape[1]}×{H.shape[0]}: {H.min():.0f}–{H.max():.0f} m, '
                     f'≈ {n_est:,.0f} triángulos')

    with _gmsh_lock:
        from app.gmsh_init import initialize as _gmsh_init
        _gmsh_init()
        try:
            gmsh.option.setNumber('General.Terminal', 0)
            gmsh.option.setNumber('General.NumThreads', 1)
            gmsh.model.add('domain2d')
            geo = gmsh.model.geo
            curve_ids: dict[str, list[int]] = {}
            surfaces = []
            for poly in polys:
                loops = []
                for ring in [poly.exterior] + list(poly.interiors):
                    c = np.asarray(ring.coords)[:-1]
                    ptags = [geo.addPoint(float(x), float(y), 0.0) for x, y in c]
                    ltags = []
                    for i in range(len(c)):
                        a, b = c[i], c[(i + 1) % len(c)]
                        lt = geo.addLine(ptags[i], ptags[(i + 1) % len(c)])
                        ltags.append(lt)
                        e = _edge_of(a, b, dom_xy, tol)
                        curve_ids.setdefault('coast' if e is None else f'edge{e}', []).append(lt)
                    loops.append(geo.addCurveLoop(ltags))
                surfaces.append(geo.addPlaneSurface(loops))
            geo.synchronize()
            bnd_groups = {}
            for bid, lines in curve_ids.items():
                bnd_groups[bid] = gmsh.model.addPhysicalGroup(1, lines)
            gmsh.model.addPhysicalGroup(2, surfaces)
            # background size: two triangles per grid cell ('ST' list data), PostView field
            view = gmsh.view.add('size')
            X, Y = np.meshgrid(xs, ys)
            i0 = (slice(None, -1), slice(None, -1))
            i1 = (slice(None, -1), slice(1, None))
            i2 = (slice(1, None), slice(1, None))
            i3 = (slice(1, None), slice(None, -1))
            data = []
            for a, b, c in ((i0, i1, i2), (i0, i2, i3)):
                blk = np.column_stack([X[a].ravel(), X[b].ravel(), X[c].ravel(),
                                       Y[a].ravel(), Y[b].ravel(), Y[c].ravel(),
                                       np.zeros((X[a].size, 3)),
                                       H[a].ravel(), H[b].ravel(), H[c].ravel()])
                data.append(blk)
            data = np.vstack(data)
            gmsh.view.addListData(view, 'ST', len(data), data.ravel().tolist())
            f = gmsh.model.mesh.field.add('PostView')
            gmsh.model.mesh.field.setNumber(f, 'ViewTag', view)
            gmsh.model.mesh.field.setAsBackgroundMesh(f)
            for k, v in (('Mesh.MeshSizeExtendFromBoundary', 0), ('Mesh.MeshSizeFromPoints', 0),
                         ('Mesh.MeshSizeFromCurvature', 0), ('Mesh.Algorithm', 6),
                         ('Mesh.MeshSizeMin', p['h_min']), ('Mesh.MeshSizeMax', p['h_max'])):
                gmsh.option.setNumber(k, v)
            gmsh.model.mesh.generate(2)
            if progress:
                progress(70, 'malla generada')
            tags, coords, _ = gmsh.model.mesh.getNodes()
            xyz = coords.reshape(-1, 3)
            tri_tags = []
            for s in surfaces:
                et, _, en = gmsh.model.mesh.getElements(2, s)
                for t, nn in zip(et, en):
                    if t == 2:
                        tri_tags.append(np.asarray(nn).reshape(-1, 3))
            tri_tags = np.vstack(tri_tags)
            bnd_tags = {}
            for bid, pg in bnd_groups.items():
                seg = []
                for c in gmsh.model.getEntitiesForPhysicalGroup(1, pg):
                    et, _, en = gmsh.model.mesh.getElements(1, int(c))
                    for t, nn in zip(et, en):
                        if t == 1:
                            seg.append(np.asarray(nn).reshape(-1, 2))
                bnd_tags[bid] = np.vstack(seg) if seg else np.zeros((0, 2), np.int64)
        finally:
            gmsh.finalize()

    used = np.unique(tri_tags)
    index = {int(t): i for i, t in enumerate(used)}
    lookup = np.vectorize(index.get, otypes=[np.int64])
    pos = {int(t): i for i, t in enumerate(tags)}
    nodes = xyz[[pos[int(t)] for t in used], :2]
    tris = lookup(tri_tags)
    P = nodes[tris]
    neg = ((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1])
           - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1])) < 0
    tris[neg] = tris[neg][:, [0, 2, 1]]
    boundary = {bid: lookup(v) if len(v) else v for bid, v in bnd_tags.items()}

    depth = depth_local(nodes[:, 0], nodes[:, 1])
    missing = int((~np.isfinite(depth)).sum())
    if missing and np.isfinite(depth).any():
        from scipy.spatial import cKDTree
        ok = np.isfinite(depth)
        _, j = cKDTree(nodes[ok]).query(nodes[~ok])
        depth[~ok] = depth[ok][j]

    info = []
    for bid, e in boundary.items():
        L = float(np.linalg.norm(nodes[e[:, 1]] - nodes[e[:, 0]], axis=1).sum()) if len(e) else 0.0
        if bid == 'coast':
            info.append({'id': 'coast', 'kind': 'coast', 'label': 'Costa', 'length_m': L})
        else:
            i = int(bid[4:])
            info.append({'id': bid, 'kind': kinds[i], 'label': labels[i] or f'Lado {i + 1}', 'edge': i,
                         'length_m': L})
    info.sort(key=lambda b: (b['id'] == 'coast', b.get('edge', 0)))

    zone = np.full(len(tris), -1)
    zlist = []
    if zones:
        import shapely
        cen = nodes[tris].mean(1)
        for zi, z in enumerate(zones):
            g = _to_local(z['geometry'], frame)
            inside = shapely.contains_xy(g, cen[:, 0], cen[:, 1])
            zone[inside & (zone < 0)] = zi
            zlist.append({'label': str(z['props'].get('name') or z['props'].get('label') or f'Zona {zi + 1}'),
                          'props': {k: v for k, v in z['props'].items() if isinstance(v, (int, float, str))}})

    m = Mesh2D(nodes, tris, depth, frame, boundary, info, zone, zlist, key=key)
    ang = m.min_angles_deg()
    area = m.areas()
    m.stats = {'n_nodes': m.n_nodes, 'n_elements': m.n_elements, 'area_m2': float(area.sum()),
               'water_area_m2': float(water_union.area), 'n_parts': len(polys),
               'n_holes': int(sum(len(q.interiors) for q in polys)),
               'min_angle_deg': float(ang.min()), 'angle_below_20_pct': float(100 * np.mean(ang < 20)),
               'h_min_m': float(m.edge_lengths().min()), 'h_max_m': float(m.edge_lengths().max()),
               'depth_min_m': float(np.nanmin(depth)) if np.isfinite(depth).any() else None,
               'depth_max_m': float(np.nanmax(depth)) if np.isfinite(depth).any() else None,
               'nodes_without_depth': missing if depth_sampler is not None else 0,
               'has_bathymetry': depth_sampler is not None, 'estimated_elements': round(n_est), 'params': p, 'frame': frame.to_dict(),
               'points_outside_water': int(sum(not water_union.buffer(tol).contains(
                   __import__('shapely').geometry.Point(px, py)) for px, py, _ in pts))}
    return m


def target_size_at(spec: dict, mesh: Mesh2D, depth_sampler=None, points=None) -> np.ndarray:
    """Target size of the criteria (before clamping to the background grid) at the element centroids — for the
    grading check of the hito."""
    p = params_of(spec.get('mesh'))
    cen = mesh.nodes[mesh.tris].mean(1)
    lon, lat = mesh.frame.to_lonlat(cen[:, 0], cen[:, 1])
    d = depth_sampler(lon, lat) if depth_sampler else np.full(len(cen), np.nan)
    d = np.where(np.isfinite(d), np.maximum(d, p['d_min']), p['d_min'])
    H = np.full(len(cen), p['h_max'])
    if p['wavelength_points'] > 0:
        H = np.minimum(H, np.sqrt(G * d) * p['period_s'] / p['wavelength_points'])
    for q in list(spec.get('points') or []) + list(points or []):
        px, py = mesh.frame.from_lonlat([q['lon']], [q['lat']])
        H = np.minimum(H, float(q.get('size') or p['h_min']) + p['growth'] * np.hypot(cen[:, 0] - px[0], cen[:, 1] - py[0]))
    return np.clip(H, p['h_min'], p['h_max'])
