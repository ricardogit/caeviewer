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

    def __init__(self, nodes, elements, element_type: str = 'T4',
                 node_sets: dict = None, element_sets: dict = None):
        self.nodes = np.asarray(nodes, dtype=np.float64)         # (n, 3)
        self.elements = np.asarray(elements, dtype=np.int32)     # (m, n_nodes_per_el)
        self.element_type = element_type
        self.n_nodes = len(self.nodes)
        self.n_elements = len(self.elements)
        self.node_sets = node_sets or {}
        self.element_sets = element_sets or {}

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
            'bounding_box': self.bounding_box,
        }

    # ── Surface extraction ────────────────────────────────────────────────────

    def extract_surface_triangles(self) -> list:
        """Return surface triangles (faces shared by exactly 1 element).

        For T4 each element has 4 faces.  Interior faces are shared by 2
        elements and cancel; boundary faces appear once.
        """
        if self.element_type not in ('T4',):
            return []

        TET_LOCAL_FACES = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]

        face_count: dict = defaultdict(int)
        face_ori: dict = {}

        for el in self.elements:
            for lf in TET_LOCAL_FACES:
                global_nodes = [int(el[i]) for i in lf]
                key = tuple(sorted(global_nodes))
                face_count[key] += 1
                face_ori[key] = global_nodes  # one orientation (consistent winding handled in renderer)

        return [face_ori[k] for k, cnt in face_count.items() if cnt == 1]

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_inline(cls, nodes, elements, element_type='T4',
                    node_sets=None, element_sets=None) -> FEMMesh:
        return cls(nodes, elements, element_type, node_sets, element_sets)

    @classmethod
    def generate_cantilever(cls,
                            length: float = 0.050,
                            width:  float = 0.010,
                            height: float = 0.010,
                            n_along_length: int = 12) -> FEMMesh:
        """Generate a T4 tetrahedral mesh of a box using GMSH.

        Args:
            length: dimension along X [m]
            width:  dimension along Y [m]
            height: dimension along Z [m]
            n_along_length: number of elements along the beam axis (controls density)

        Node sets:
            'fixed': nodes at x ≈ 0 (clamped face)
            'tip':   nodes at x ≈ length (free tip, for tip load)
        """
        try:
            import gmsh
        except ImportError:
            raise RuntimeError("GMSH not installed. Run: pip install gmsh")

        lc = length / n_along_length

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

                # ── Nodes ──────────────────────────────────────────────────
                node_tags, coord_flat, _ = gmsh.model.mesh.getNodes()
                node_arr = coord_flat.reshape(-1, 3)
                tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

                # ── T4 elements (GMSH type id = 4) ─────────────────────────
                etypes, _, enodes_list = gmsh.model.mesh.getElements(dim=3)
                elements = []
                for etype, enodes_flat in zip(etypes, enodes_list):
                    if etype == 4:
                        en_mat = enodes_flat.reshape(-1, 4)
                        for el in en_mat:
                            elements.append([tag_to_idx[int(n)] for n in el])

                if not elements:
                    raise RuntimeError("GMSH produced no T4 elements.")

                # ── Node sets ───────────────────────────────────────────────
                tol = lc * 0.6
                fixed_nodes = [tag_to_idx[int(t)] for t in node_tags
                               if node_arr[tag_to_idx[int(t)], 0] < tol]
                tip_nodes = [tag_to_idx[int(t)] for t in node_tags
                             if node_arr[tag_to_idx[int(t)], 0] > length - tol]

                logger.info(f"Cantilever mesh: {len(node_arr)} nodes, "
                            f"{len(elements)} T4 elements, "
                            f"fixed={len(fixed_nodes)}, tip={len(tip_nodes)}")

                return cls(node_arr, elements, 'T4',
                           node_sets={'fixed': fixed_nodes, 'tip': tip_nodes})
            finally:
                gmsh.finalize()

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
            if cb.type in ('tetra', 'tetra4'):
                elements = cb.data.tolist()
                break

        if not elements:
            avail = [cb.type for cb in raw.cells]
            raise ValueError(f"No tetra/tetra4 cells in mesh {mesh_id}. "
                             f"Available: {avail}. Use a tet mesh.")

        node_sets = {}
        if hasattr(raw, 'point_sets') and raw.point_sets:
            for name, ids in raw.point_sets.items():
                node_sets[name] = ids.tolist()

        return cls(nodes, elements, 'T4', node_sets=node_sets)
