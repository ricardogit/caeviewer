"""FEMMesh — unified mesh container for the FEM solver.

Supports:
  - Inline specification (nodes + elements arrays)
  - GMSH-generated cantilever beam (validation / testing)
  - CAE mesh files via meshio (from existing CAEMesh records)
"""
from __future__ import annotations
import logging
import os
import threading
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

# Re-use the GMSH process-level lock from step_mesher
try:
    from app.cae.services.step_mesher import _gmsh_lock
except ImportError:
    _gmsh_lock = threading.Lock()


class FEMMesh:
    """Stores a volumetric FEM mesh with node sets for BCs and loads."""

    def __init__(self, nodes, elements, element_type: str = None,
                 node_sets: dict = None, element_sets: dict = None,
                 face_sets: dict = None, canonical: bool = False, mids_known: bool = False):
        from app.design.services.fem.tet_batch import canonicalize, etype_of
        self.nodes = np.asarray(nodes, dtype=np.float64)         # (n, 3)
        el = np.asarray(elements, dtype=np.int64)                # (m, n_nodes_per_el)
        if el.ndim == 2 and el.shape[1] in (4, 10):
            # internal node order + positive orientation (see tet_batch); idempotent
            el = el if canonical else canonicalize(self.nodes, el, reorder_mids=not mids_known)
            element_type = etype_of(el)
        self.elements = el
        self.element_type = element_type or 'T4'
        self.n_nodes = len(self.nodes)
        self.n_elements = len(self.elements)
        self.node_sets = {k: np.asarray(v, dtype=np.int64) for k, v in (node_sets or {}).items()}
        self.element_sets = element_sets or {}
        # name -> (k, 3|6) boundary triangles (global node ids); used for surface loads
        self.face_sets = {k: np.asarray(v, dtype=np.int64) for k, v in (face_sets or {}).items()}
        for name, tris in self.face_sets.items():
            self.node_sets.setdefault(name, np.unique(tris))

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def n_dof_structural(self) -> int:
        return 3 * self.n_nodes

    @property
    def bounding_box(self) -> dict:
        lo = self.nodes.min(axis=0)
        hi = self.nodes.max(axis=0)
        return dict(min_x=lo[0], max_x=hi[0], min_y=lo[1],
                    max_y=hi[1], min_z=lo[2], max_z=hi[2])

    def estimate_tier(self) -> int:
        from app.design.services.fem.solver import TIER_LIMITS
        n_dof = self.n_dof_structural
        for tier in range(4):
            lim = TIER_LIMITS[tier]
            if (self.n_nodes <= lim['max_nodes'] and
                    self.n_elements <= lim['max_elements'] and
                    n_dof <= lim['max_dof']):
                return tier
        return 3

    def stats(self) -> dict:
        return {
            'n_nodes': self.n_nodes,
            'n_elements': self.n_elements,
            'element_type': self.element_type,
            'tier': self.estimate_tier(),
            'n_dof': self.n_dof_structural,
            'node_sets': {k: len(v) for k, v in self.node_sets.items()},
            'face_sets': len(self.face_sets),
            'bounding_box': self.bounding_box,
        }

    # ── Surface extraction ────────────────────────────────────────────────────

    def extract_surface_triangles(self) -> list:
        """Return surface triangles (faces shared by exactly 1 element).

        For T4 each element has 4 faces.  Interior faces are shared by 2
        elements and cancel; boundary faces appear once.
        """
        if self.element_type not in ('T4', 'T10'):
            return []
        from app.design.services.fem.tet_batch import boundary_faces, split_t6
        # outward winding; T6 faces are split into 4 display triangles
        return split_t6(boundary_faces(self.elements)).tolist()

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_inline(cls, nodes, elements, element_type=None,
                    node_sets=None, element_sets=None, face_sets=None) -> FEMMesh:
        return cls(nodes, elements, element_type, node_sets, element_sets, face_sets)

    @classmethod
    def generate_cantilever(cls,
                            length: float = 0.050,
                            width:  float = 0.010,
                            height: float = 0.010,
                            n_along_length: int = 12,
                            order: int = 1) -> FEMMesh:
        """Generate a T4 (order=1) or T10 (order=2) tetrahedral mesh of a box using GMSH.

        Args:
            length: dimension along X [m]
            width:  dimension along Y [m]
            height: dimension along Z [m]
            n_along_length: number of elements along the beam axis (controls density)

        Node sets and face sets (boundary triangles, for consistent surface loads):
            'fixed': face x = 0 (clamped)
            'tip':   face x = length (free tip, for tip load)
        """
        try:
            import gmsh
        except ImportError:
            raise RuntimeError("GMSH not installed. Run: pip install gmsh")

        lc = length / n_along_length

        try:
            with _gmsh_lock:
                gmsh.initialize()
                try:
                    gmsh.option.setNumber("General.Terminal", 0)  # silent
                    gmsh.model.add("cantilever")
                    gmsh.model.occ.addBox(0, 0, 0, length, width, height)
                    gmsh.model.occ.synchronize()

                    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc)
                    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc)
                    gmsh.option.setNumber("Mesh.Algorithm3D", 1)   # Delaunay tet
                    gmsh.option.setNumber("Mesh.Algorithm", 5)     # Delaunay 2D
                    gmsh.option.setNumber("Mesh.Optimize", 1)      # Netgen smoothing
                    gmsh.model.mesh.generate(3)
                    if order == 2:
                        gmsh.model.mesh.setOrder(2)

                    surf = {}
                    eps = 1e-4 * length   # OCC bboxes are inflated by the shape tolerance
                    for _, tag in gmsh.model.getEntities(2):
                        xmin, _, _, xmax, _, _ = gmsh.model.getBoundingBox(2, tag)
                        if xmax < eps:
                            surf['fixed'] = tag
                        elif xmin > length - eps:
                            surf['tip'] = tag
                    nodes_, elements_, faces_ = gmsh_extract(gmsh, surf)

                    logger.info(f"Cantilever mesh: {len(nodes_)} nodes, "
                                f"{len(elements_)} {'T10' if order == 2 else 'T4'} elements, "
                                f"fixed={len(np.unique(faces_['fixed']))}, tip={len(np.unique(faces_['tip']))}")
                    return cls(nodes_, elements_, face_sets=faces_, mids_known=True)
                finally:
                    gmsh.finalize()
        except Exception as e:
            if "signal only works in main thread" in str(e):
                logger.warning(f"GMSH signal error in thread: {e}. Using fallback mesh generation.")
                if order != 1:
                    raise RuntimeError("GMSH unavailable in this thread; T10 cantilever needs GMSH") from e
                return cls._generate_fallback_cantilever(length, width, height, n_along_length)
            raise

    @classmethod
    def generate_plate(cls, length: float = 0.2, height: float = 0.1, thickness: float = 0.01,
                       mesh_size: float = 0.005, support_width: float = None,
                       hole_radius: float = 0.0, hole_center: tuple = None, order: int = 1) -> FEMMesh:
        """Thick plate in the XY plane (x: length, y: height, z: thickness), split in three
        blocks along x so the bottom support patches are separate faces (FASE 4 bridge hito).

        Face sets: 'top' (y = height), 'bottom' (y = 0), 'support_left' / 'support_right'
        (bottom patches of width ``support_width`` at both ends), 'left', 'right', 'hole',
        'back' (z = 0) and 'front' (z = thickness).
        """
        import gmsh
        sw = support_width or 0.05 * length
        with _gmsh_lock:
            gmsh.initialize()
            try:
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.option.setNumber("General.NumThreads", 1)
                gmsh.model.add("plate")
                occ = gmsh.model.occ
                b = [occ.addBox(0, 0, 0, sw, height, thickness),
                     occ.addBox(sw, 0, 0, length - 2 * sw, height, thickness),
                     occ.addBox(length - sw, 0, 0, sw, height, thickness)]
                vols = [(3, t) for t in b]
                if hole_radius and hole_radius > 0:
                    cx, cy = hole_center or (length / 2, height / 2)
                    cyl = occ.addCylinder(cx, cy, -thickness, 0, 0, 3 * thickness, hole_radius)
                    vols, _ = occ.cut([(3, b[1])], [(3, cyl)])
                    vols = [(3, b[0])] + vols + [(3, b[2])]
                occ.fragment(vols, [])
                occ.synchronize()
                gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size)
                gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)
                gmsh.option.setNumber("Mesh.Algorithm3D", 1)
                gmsh.option.setNumber("Mesh.Optimize", 1)
                gmsh.model.mesh.generate(3)
                if order == 2:
                    gmsh.model.mesh.setOrder(2)
                eps = 1e-4 * length
                groups: dict = {}
                for _, tag in gmsh.model.getEntities(2):
                    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, tag)
                    if y1 - y0 < eps and y0 > height - eps:
                        name = 'top'
                    elif y1 - y0 < eps and y1 < eps:
                        name = 'support_left' if x1 < sw + eps else 'support_right' if x0 > length - sw - eps                             else 'bottom'
                    elif x1 - x0 < eps and x1 < eps:
                        name = 'left'
                    elif x1 - x0 < eps and x0 > length - eps:
                        name = 'right'
                    elif z1 - z0 < eps:
                        name = 'back' if z1 < eps else 'front'
                    elif (x1 - x0 < eps) or (y1 - y0 < eps):
                        continue                       # internal block walls
                    else:
                        name = 'hole'
                    groups.setdefault(name, []).append(tag)
                surf = {f'{n}#{i}': t for n, tags in groups.items() for i, t in enumerate(tags)}
                nodes_, elements_, faces_ = gmsh_extract(gmsh, surf)
            finally:
                gmsh.finalize()
        merged: dict = {}
        for k, tris in faces_.items():
            merged.setdefault(k.split('#')[0], []).append(tris)
        faces = {k: np.concatenate(v) for k, v in merged.items()}
        faces['bottom'] = np.concatenate([faces[k] for k in ('bottom', 'support_left', 'support_right')
                                          if k in faces])
        return cls(nodes_, elements_, face_sets=faces, mids_known=True)

    @classmethod
    def _generate_fallback_cantilever(cls,
                                      length: float = 0.050,
                                      width: float = 0.010,
                                      height: float = 0.010,
                                      n_along_length: int = 12) -> FEMMesh:
        """Fallback mesh: simple hexahedral grid -> T4 via standard 5-tet subdivision."""
        n_x = max(2, n_along_length)
        n_y = max(2, int(n_x * width / length))
        n_z = max(2, int(n_x * height / length))

        nodes = []
        for i in range(n_x + 1):
            for j in range(n_y + 1):
                for k in range(n_z + 1):
                    x = i * length / n_x
                    y = j * width / n_y
                    z = k * height / n_z
                    nodes.append([x, y, z])
        nodes = np.array(nodes, dtype=np.float64)

        def idx(i, j, k):
            return i * (n_y+1) * (n_z+1) + j * (n_z+1) + k

        elements = []
        for i in range(n_x):
            for j in range(n_y):
                for k in range(n_z):
                    # Hex corners
                    n0 = idx(i, j, k)
                    n1 = idx(i+1, j, k)
                    n2 = idx(i+1, j+1, k)
                    n3 = idx(i, j+1, k)
                    n4 = idx(i, j, k+1)
                    n5 = idx(i+1, j, k+1)
                    n6 = idx(i+1, j+1, k+1)
                    n7 = idx(i, j+1, k+1)
                    # Standard 5-tet decomposition (pyramid + base tets)
                    elements.append([n0, n1, n3, n4])
                    elements.append([n1, n2, n3, n6])
                    elements.append([n1, n5, n6, n4])
                    elements.append([n3, n4, n6, n7])
                    elements.append([n1, n3, n4, n6])
        elements = np.array(elements, dtype=np.int32)

        fixed_nodes = [i for i in range(len(nodes)) if nodes[i, 0] < 1e-6]
        tip_nodes = [i for i in range(len(nodes)) if nodes[i, 0] > length - 1e-6]

        logger.info(f"Fallback cantilever mesh: {len(nodes)} nodes, {len(elements)} T4 elements "
                    f"(5-tet subdiv, no GMSH)")
        return cls(nodes, elements, 'T4', node_sets={'fixed': fixed_nodes, 'tip': tip_nodes})

    @classmethod
    def from_cae_mesh_id(cls, mesh_id: str) -> FEMMesh:
        """Load volumetric T4 mesh from an existing CAEMesh database record."""
        try:
            import meshio
        except ImportError:
            raise RuntimeError("meshio not installed. Run: pip install meshio")

        from app.cae.models import CAEMesh
        rec = CAEMesh.query.filter_by(id=mesh_id).first()
        if not rec:
            raise ValueError(f"CAEMesh {mesh_id} not found")

        raw = meshio.read(rec.file_path)
        nodes = raw.points

        elements = []
        for cb in raw.cells:
            if cb.type in ('tetra', 'tetra4', 'tetra10'):
                elements = cb.data
                break

        if len(elements) == 0:
            avail = [cb.type for cb in raw.cells]
            raise ValueError(f"No tetra/tetra4 cells in mesh {mesh_id}. "
                             f"Available: {avail}. Use a tet mesh.")

        node_sets = {}
        if hasattr(raw, 'point_sets') and raw.point_sets:
            for name, ids in raw.point_sets.items():
                node_sets[name] = ids.tolist()

        return cls(nodes, elements, node_sets=node_sets)


def gmsh_extract(gmsh, surfaces: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """Read the current Gmsh mesh: compact nodes, tets (4 or 10 nodes) and the
    boundary triangles (3 or 6 nodes) of each named surface tag in ``surfaces``.
    T10 connectivity is returned in the internal mid-node order (tet_batch).

    Only nodes used by volume elements are kept (Gmsh also returns geometry-only
    nodes); indices are 0-based into the returned node array.
    """
    tags, coords, _ = gmsh.model.mesh.getNodes()
    coords = coords.reshape(-1, 3)
    lookup = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
    lookup[tags.astype(np.int64)] = np.arange(len(tags))

    from app.design.services.fem.tet_batch import GMSH_TET10_TO_INTERNAL
    tets = []
    for et, n in ((4, 4), (11, 10)):
        _, en = gmsh.model.mesh.getElementsByType(et)
        if len(en):
            t = lookup[en.astype(np.int64)].reshape(-1, n)
            tets.append(t[:, GMSH_TET10_TO_INTERNAL] if n == 10 else t)
    if not tets:
        raise RuntimeError("GMSH produced no tetrahedra.")
    if len(tets) > 1:
        raise RuntimeError("Mixed linear/quadratic tetrahedra in one mesh.")
    tets = tets[0]

    used = np.unique(tets)
    remap = np.full(len(coords), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    nodes = coords[used]
    tets = remap[tets]

    faces = {}
    for name, stag in surfaces.items():
        tris = []
        for et, n in ((2, 3), (9, 6)):
            _, en = gmsh.model.mesh.getElementsByType(et, stag)
            if len(en):
                tris.append(lookup[en.astype(np.int64)].reshape(-1, n))
        if not tris:
            raise RuntimeError(f"Surface {name} (tag {stag}) has no triangles.")
        t = remap[tris[0]]
        if (t < 0).any():
            raise RuntimeError(f"Surface {name} uses nodes outside the volume mesh.")
        faces[name] = t
    return nodes, tets, faces
