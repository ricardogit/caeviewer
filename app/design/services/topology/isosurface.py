"""Smooth boundary of a topology-optimization result (FASE 4).

The element densities are averaged to the nodes (volume weighted) and the iso-surface
ρ = threshold is extracted with marching tetrahedra. Where the material reaches the
boundary of the design domain the surface is closed with the domain's boundary triangles,
clipped against the same threshold, so the result is a closed (watertight) triangle mesh
that can be exported as STL/GLB or reused as geometry.

Vertices on mesh edges are shared through an edge key, so neighbouring tets produce a
connected surface. Triangles are oriented with the normal pointing out of the material.
"""
from __future__ import annotations

import numpy as np

from app.design.services.fem import tet_batch as tb

_EDGES = np.array([[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]])


def nodal_density(nodes: np.ndarray, elements: np.ndarray, rho: np.ndarray) -> np.ndarray:
    el = elements[:, :4]
    v = tb.volumes(nodes, el)
    num = np.zeros(len(nodes))
    den = np.zeros(len(nodes))
    np.add.at(num, el, (v * rho)[:, None])
    np.add.at(den, el, v[:, None])
    return np.divide(num, den, out=np.zeros_like(num), where=den > 0)


class _Verts:
    """Vertex pool: original nodes (inside points of caps) and edge crossings."""

    def __init__(self, nodes, phi):
        self.nodes, self.phi = nodes, phi
        self.keys: dict = {}
        self.coords: list = []

    def node(self, i):
        k = ('n', int(i))
        if k not in self.keys:
            self.keys[k] = len(self.coords)
            self.coords.append(self.nodes[i])
        return self.keys[k]

    def edge(self, a, b):
        a, b = int(a), int(b)
        k = ('e', min(a, b), max(a, b))
        if k not in self.keys:
            fa, fb = self.phi[a], self.phi[b]
            t = fa / (fa - fb)
            self.keys[k] = len(self.coords)
            self.coords.append(self.nodes[a] + t * (self.nodes[b] - self.nodes[a]))
        return self.keys[k]


def _marching_tets(nodes, el, phi, pool: _Verts):
    """Iso-surface triangles of φ = 0 (φ > 0 inside material)."""
    tris = []
    ph = phi[el]
    inside = ph > 0
    n_in = inside.sum(axis=1)
    cut = np.flatnonzero((n_in > 0) & (n_in < 4))
    for e in cut:
        ids = el[e]
        ins = inside[e]
        crossing = [pool.edge(ids[a], ids[b]) for a, b in _EDGES if ins[a] != ins[b]]
        # gradient of φ in this tet (points into the material); outward normal = −∇φ
        X = nodes[ids]
        M = np.column_stack([X[1] - X[0], X[2] - X[0], X[3] - X[0]]).T
        try:
            g = np.linalg.solve(M, ph[e, 1:] - ph[e, 0])
        except np.linalg.LinAlgError:
            continue
        if len(crossing) == 3:
            polys = [crossing]
        else:                               # 2 in / 2 out: quad, edges in cyclic order
            a_in = [i for i in range(4) if ins[i]]
            a_out = [i for i in range(4) if not ins[i]]
            i0, i1 = a_in
            o0, o1 = a_out
            q = [pool.edge(ids[i0], ids[o0]), pool.edge(ids[i0], ids[o1]),
                 pool.edge(ids[i1], ids[o1]), pool.edge(ids[i1], ids[o0])]
            polys = [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
        for t in polys:
            tris.append((t, -g))
    return tris


def _clip_caps(nodes, bfaces, phi, pool: _Verts):
    """Domain-boundary triangles clipped to φ ≥ 0, keeping their outward winding."""
    tris = []
    ph = phi[bfaces]
    inside = ph > 0
    n_in = inside.sum(axis=1)
    for f in np.flatnonzero(n_in == 3):
        tris.append([pool.node(i) for i in bfaces[f]])
    for f in np.flatnonzero((n_in == 1) | (n_in == 2)):
        ids = bfaces[f]
        poly = []
        for k in range(3):
            a, b = ids[k], ids[(k + 1) % 3]
            if phi[a] > 0:
                poly.append(pool.node(a))
            if (phi[a] > 0) != (phi[b] > 0):
                poly.append(pool.edge(a, b))
        for k in range(1, len(poly) - 1):
            tris.append([poly[0], poly[k], poly[k + 1]])
    return tris


def extract_isosurface(nodes: np.ndarray, elements: np.ndarray, rho: np.ndarray,
                       threshold: float = 0.5) -> dict:
    """Closed iso-surface of the density field.

    Returns {'vertices' (n,3), 'faces' (m,3), 'nodal_density' at vertices, 'volume', 'area',
    'n_iso', 'n_cap'}. Coordinates are in the mesh units.
    """
    el = np.asarray(elements)[:, :4]
    rn = nodal_density(nodes, el, rho)
    # nudge exact hits so no vertex lies on the surface (degenerate triangles)
    phi = rn - threshold
    phi[np.abs(phi) < 1e-9] = -1e-9
    pool = _Verts(nodes, phi)
    iso = _marching_tets(nodes, el, phi, pool)
    caps = _clip_caps(nodes, tb.boundary_faces(el), phi, pool)
    V = np.array(pool.coords).reshape(-1, 3)
    faces = []
    for t, nrm in iso:
        a, b, c = V[t]
        if np.dot(np.cross(b - a, c - a), nrm) < 0:
            t = [t[0], t[2], t[1]]
        faces.append(t)
    faces += caps
    F = np.array(faces, dtype=np.int64).reshape(-1, 3)
    # drop degenerate triangles
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area2 = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    keep = area2 > 1e-14 * max(1.0, float(np.ptp(nodes, axis=0).max()) ** 2)
    F = F[keep]
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    volume = float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)
    # density at vertices (for colouring): edge points are at the threshold by construction
    dens = np.full(len(V), threshold)
    for k, idx in pool.keys.items():
        if k[0] == 'n':
            dens[idx] = rn[k[1]]
    return {'vertices': V, 'faces': F, 'nodal_density': dens, 'volume': volume,
            'area': float(0.5 * area2[keep].sum()), 'n_iso': len(iso), 'n_cap': len(caps)}


def to_trimesh(surf: dict, scale: float = 1.0):
    import trimesh
    return trimesh.Trimesh(vertices=surf['vertices'] * scale, faces=surf['faces'], process=True)
