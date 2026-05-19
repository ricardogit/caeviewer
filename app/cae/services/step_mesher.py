"""
STEP → FEA mesh pipeline using GMSH.

Takes a STEP file path, generates a 3-D mesh, and exports it as a .vtu file
ready for the CAEViewer.  Mesh size is derived automatically from the model's
bounding-box diagonal so the result looks reasonable regardless of model units
(mm, m, in …).

Mesh types
----------
"tetra"  — pure tetrahedral mesh (Delaunay / Frontal / HXT).  Robust on any
            STEP geometry.  Default.

"hexa"   — structured-dominant hex mesh via a three-stage strategy:
            1. Recombine surfaces (tri → quad) with the Blossom algorithm.
            2. Extrude / frontal-hex volume generation (Algorithm3D = 3).
            3. SubdivisionAlgorithm = 2 as fallback for regions that cannot
               be hexed directly (guarantees a pure-hex output with no mixed
               elements, at the cost of ~4× more elements than the tet mesh).
           For simple prismatic / cylindrical STEP geometries this produces
           well-aligned hex layers similar to ICEM blocking.  For highly
           complex free-form shapes the subdivision fallback kicks in and the
           result is valid but not as structured as a hand-blocked mesh.

"hybrid" — hex-dominant mesh: recombine surfaces + frontal-hex volume but
            WITHOUT the subdivision fallback.  Regions that cannot be hexed
            stay as tets/wedges/pyramids.  Smaller file, faster to generate,
            good quality on moderate geometry.
"""

import logging
import math
import os
import threading
import time

logger = logging.getLogger(__name__)

# GMSH is not thread-safe: serialise all calls with a process-level lock.
_gmsh_lock = threading.Lock()

ALGORITHMS_3D = {
    "delaunay": 1,   # robust, good general-purpose tet
    "frontal":  4,   # higher-quality tet, slower
    "hxt":     10,   # fastest (parallel Delaunay) tet
    "frontal_hex": 3,  # frontal-hex (structured regions become hex)
}

# Recombination algorithms for 2-D surfaces (Mesh.RecombineOptimizeTopology)
_RECOMBINE_BLOSSOM   = 1   # best quad quality (Blossom algorithm)

# Subdivision algorithm — splits every remaining tet → 4 hex (pure hex output)
_SUBDIV_ALL_HEX = 2


def _configure_hexa(gmsh, strategy: str) -> None:
    """
    Apply Gmsh options for hex-dominant or pure-hex meshing.

    strategy : "hexa"   → recombine + frontal-hex + subdivision fallback
               "hybrid" → recombine + frontal-hex, no subdivision (mixed ok)
    """
    # ── 2-D: recombine all surfaces (tri → quad) ──────────────────────────
    # RecombineAll   = 1  : apply to every surface automatically
    # RecombineOptimizeTopology iterations improve quad quality
    gmsh.option.setNumber("Mesh.RecombineAll", 1)
    gmsh.option.setNumber("Mesh.RecombineOptimizeTopology", 5)
    gmsh.option.setNumber("Mesh.RecombineMinimumQuality", 0.01)

    # Blossom gives the best quad layout for curved surfaces (cylinders etc.)
    # Algorithm = 8  → Packing of parallelograms  (good for structured-looking quads)
    # Algorithm = 9  → Quasi-structured quad
    # Keep 6 (Frontal-Delaunay) as 2-D base; Blossom post-processes it.
    gmsh.option.setNumber("Mesh.Algorithm",  6)   # 2-D: Frontal-Delaunay triangles first

    # ── 3-D: frontal-hex algorithm ────────────────────────────────────────
    # Algorithm3D = 3  : Frontal Hex — sweeps hex layers where topology allows
    gmsh.option.setNumber("Mesh.Algorithm3D", ALGORITHMS_3D["frontal_hex"])

    # ── Subdivision fallback (pure-hex mode only) ─────────────────────────
    if strategy == "hexa":
        # Every tet that survived the frontal-hex pass is split into 4 hex.
        # Guarantees zero tets in output at the cost of element count ×4.
        gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", _SUBDIV_ALL_HEX)
    else:
        # hybrid: leave residual tets/wedges/pyramids as-is
        gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 0)


def mesh_step_file(
    step_path: str,
    output_vtu: str,
    refinement: int = 3,
    algorithm: str = "hxt",
    optimize: bool = True,
    mesh_type: str = "tetra",
    gmsh_extra: dict | None = None,
    **kwargs,
) -> dict:
    """
    Mesh a STEP file and write the result as a .vtu.

    Parameters
    ----------
    step_path   : absolute path to the .step / .stp file
    output_vtu  : absolute path for the output .vtu
    refinement  : 1 (coarse) … 5 (fine)  — controls element count
    algorithm   : "delaunay" | "frontal" | "hxt"
                  (ignored when mesh_type is "hexa" or "hybrid" — those
                   use the frontal-hex algorithm internally)
    optimize    : run optimiser pass after meshing
    mesh_type   : "tetra"  — pure tetrahedral (default, most robust)
                  "hexa"   — pure hexahedral via recombine + frontal-hex
                             + subdivision fallback
                  "hybrid" — hex-dominant: recombine + frontal-hex,
                             residual tets/wedges/pyramids kept as-is
    gmsh_extra  : optional dict of extra Gmsh option overrides applied
                  after the type-specific defaults, e.g.
                  {"Mesh.ElementOrder": 2} for TET10 or
                  {"Mesh.BoundaryLayerFanPoints": 5} for PRISM.

    Returns
    -------
    dict with node_count, element_count, element_types, bbox, mesh_size_used
    """
    try:
        import gmsh
    except ImportError:
        raise RuntimeError("gmsh is not installed.  Run: pip install gmsh")

    try:
        import meshio
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "meshio / numpy not installed.  Run: pip install meshio numpy"
        )

    if not os.path.exists(step_path):
        raise FileNotFoundError(f"STEP file not found: {step_path}")

    mesh_type = mesh_type.lower()
    if mesh_type not in ("tetra", "hexa", "hybrid"):
        logger.warning(f"Unknown mesh_type '{mesh_type}', falling back to 'tetra'")
        mesh_type = "tetra"

    with _gmsh_lock:
        os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
        gmsh.initialize(["", "-nopopup"])
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
        gmsh.option.setNumber("General.NoPopup", 1)

        try:
            t0 = time.time()
            logger.info(f"GMSH: opening {step_path}")
            gmsh.open(step_path)

            # ── Bounding-box → auto mesh size ─────────────────────────────
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            diag = math.sqrt(
                (xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2
            )
            if diag == 0:
                raise ValueError(
                    "Model has zero bounding-box diagonal — geometry may be empty."
                )

            # refinement 1 → ~10 elements along diag, 5 → ~50
            mesh_size = diag / (refinement * 10)

            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size * 0.1)

            # ── Mesh-type-specific options ─────────────────────────────────
            if mesh_type == "tetra":
                algo_id = ALGORITHMS_3D.get(algorithm.lower(), ALGORITHMS_3D["hxt"])
                gmsh.option.setNumber("Mesh.Algorithm3D", algo_id)
                gmsh.option.setNumber("Mesh.RecombineAll", 0)
                gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 0)

            else:  # "hexa" or "hybrid"
                _configure_hexa(gmsh, mesh_type)

            gmsh.option.setNumber("Mesh.Optimize", 1 if optimize else 0)

            # ── Caller-supplied Gmsh overrides (e.g. ElementOrder=2 for TET10) ──
            for key, val in (gmsh_extra or {}).items():
                gmsh.option.setNumber(key, val)

            logger.info(
                f"GMSH: meshing  diag={diag:.3f}  size={mesh_size:.4f}  "
                f"type={mesh_type}  algo={algorithm}"
            )

            # ── Generate mesh ──────────────────────────────────────────────
            gmsh.model.mesh.generate(3)

            # ── Post-generation optimisation ───────────────────────────────
            if optimize:
                if mesh_type == "tetra":
                    # Netgen improves tet quality (dihedral angles)
                    gmsh.model.mesh.optimize("Netgen")
                elif mesh_type in ("hexa", "hybrid"):
                    # Untangle + HighOrder smoother work on hex/mixed meshes
                    gmsh.model.mesh.optimize("Relocate3D")
                    gmsh.model.mesh.optimize("UntangleMeshGeometry")

            # ── Write intermediate .msh ────────────────────────────────────
            msh_path = output_vtu.replace(".vtu", "_tmp.msh")
            gmsh.write(msh_path)
            elapsed = time.time() - t0
            logger.info(f"GMSH: done in {elapsed:.1f}s → {msh_path}")

        finally:
            gmsh.finalize()

    # ── Convert .msh → .vtu via meshio (outside the lock) ─────────────────
    mesh = meshio.read(msh_path)
    os.remove(msh_path)

    # Keep only solid (3-D) element types; drop points/lines/surface shells
    solid_types = {
        "tetra",        "tetra10",
        "hexahedron",   "hexahedron20",
        "wedge",        "wedge15",
        "pyramid",      "pyramid13",
    }
    cells_out = [c for c in mesh.cells if c.type in solid_types]
    if not cells_out:
        # last resort: anything with ≥4 nodes per element
        cells_out = [c for c in mesh.cells if c.data.shape[1] >= 4]

    mesh_out = meshio.Mesh(points=mesh.points, cells=cells_out)
    meshio.write(output_vtu, mesh_out)

    node_count  = len(mesh_out.points)
    elem_count  = sum(len(c.data) for c in mesh_out.cells)
    elem_types  = {c.type: len(c.data) for c in mesh_out.cells}

    bbox = {
        "min_x": float(xmin), "max_x": float(xmax),
        "min_y": float(ymin), "max_y": float(ymax),
        "min_z": float(zmin), "max_z": float(zmax),
    }

    logger.info(
        f"Mesh saved: {node_count} nodes, {elem_count} elements "
        f"({elem_types}) → {output_vtu}"
    )
    return {
        "node_count":     node_count,
        "element_count":  elem_count,
        "element_types":  elem_types,
        "bounding_box":   bbox,
        "mesh_size_used": mesh_size,
        "elapsed_s":      round(elapsed, 2),
    }
