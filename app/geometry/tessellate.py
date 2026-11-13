"""Per-face tessellation of an imported shape (pythonOCC) for the browser viewer.

Every CAD face is meshed with BRepMesh_IncrementalMesh and emitted as its own
vertex block (no vertex sharing across faces), tagged with its 1-based TopExp
face index — the same index stored in ``geometry_entities.entity_index``.
"""
import time

import numpy as np
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopAbs import TopAbs_REVERSED
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods

from .occ_import import ImportedGeometry, _static

_triangulation = _static("BRep", "BRep_Tool", "Triangulation")


def deflection_for(scale_mm: float) -> tuple[float, float]:
    """(linear mm, angular rad). Linear ~0.1 % of the bbox diagonal, clamped."""
    lin = min(max(scale_mm * 1e-3, 0.005), 5.0)
    return lin, 0.35


def tessellate(geom: ImportedGeometry, scale_mm: float, linear: float | None = None,
               angular: float | None = None) -> dict:
    """Return positions/normals/face_ids/indices arrays plus per-face vertex/triangle ranges."""
    t0 = time.perf_counter()
    lin_d, ang_d = deflection_for(scale_mm)
    lin_d = linear or lin_d
    ang_d = angular or ang_d
    # parallel=False keeps the result deterministic
    BRepMesh_IncrementalMesh(geom.shape, lin_d, False, ang_d, False)   # meshes in the constructor

    pos_chunks, nrm_chunks, fid_chunks, idx_chunks = [], [], [], []
    v_ranges, t_ranges, missing = {}, {}, []
    v_off = t_off = 0
    for fi in range(1, geom.face_map.Size() + 1):
        face = topods.Face(geom.face_map.FindKey(fi))
        loc = TopLoc_Location()
        tri = _triangulation(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            missing.append(fi)
            continue
        trsf = loc.Transformation()
        nn, nt = tri.NbNodes(), tri.NbTriangles()
        pts = np.empty((nn, 3), dtype=np.float64)
        for i in range(1, nn + 1):
            p = tri.Node(i).Transformed(trsf)
            pts[i - 1] = (p.X(), p.Y(), p.Z())
        tris = np.empty((nt, 3), dtype=np.int64)
        for i in range(1, nt + 1):
            tris[i - 1] = tri.Triangle(i).Get()
        tris -= 1
        if face.Orientation() == TopAbs_REVERSED:
            tris = tris[:, [0, 2, 1]]

        # smooth normals within the face (area-weighted), consistent with winding
        fn = np.cross(pts[tris[:, 1]] - pts[tris[:, 0]], pts[tris[:, 2]] - pts[tris[:, 0]])
        vn = np.zeros_like(pts)
        for k in range(3):
            np.add.at(vn, tris[:, k], fn)
        norm = np.linalg.norm(vn, axis=1, keepdims=True)
        vn = np.divide(vn, norm, out=np.zeros_like(vn), where=norm > 0)

        pos_chunks.append(pts)
        nrm_chunks.append(vn)
        fid_chunks.append(np.full(nn, fi, dtype=np.float32))
        idx_chunks.append(tris + v_off)
        v_ranges[fi] = (v_off, nn)
        t_ranges[fi] = (t_off, nt)
        v_off += nn
        t_off += nt

    if not pos_chunks:
        raise RuntimeError('La teselación no produjo triángulos')
    return {
        'positions': np.vstack(pos_chunks),
        'normals': np.vstack(nrm_chunks),
        'face_ids': np.concatenate(fid_chunks),
        'indices': np.vstack(idx_chunks),
        'face_vertex_ranges': v_ranges,
        'face_triangle_ranges': t_ranges,
        'missing_faces': missing,
        'linear_deflection': lin_d,
        'angular_deflection': ang_d,
        'seconds': round(time.perf_counter() - t0, 3),
    }
