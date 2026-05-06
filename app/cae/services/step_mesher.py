"""
STEP → FEA mesh pipeline using GMSH.

Takes a STEP file path, generates a 3-D tetrahedral mesh, and exports it
as a .vtu file ready for the CAEViewer.  Mesh size is derived automatically
from the model's bounding-box diagonal so the result looks reasonable
regardless of model units (mm, m, in …).
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
    "delaunay": 1,   # robust, good general purpose
    "frontal":  4,   # higher quality, slower
    "hxt":     10,   # fastest (parallel Delaunay)
}


def mesh_step_file(
    step_path: str,
    output_vtu: str,
    refinement: int = 3,
    algorithm: str = "hxt",
    optimize: bool = True,
) -> dict:
    """
    Mesh a STEP file and write the result as a .vtu.

    Parameters
    ----------
    step_path   : absolute path to the .step / .stp file
    output_vtu  : absolute path for the output .vtu
    refinement  : 1 (coarse) … 5 (fine)  — controls element count
    algorithm   : "delaunay" | "frontal" | "hxt"
    optimize    : run Netgen optimiser pass after meshing

    Returns
    -------
    dict with node_count, element_count, element_types, bbox, mesh_size_used
    """
    try:
        import gmsh
    except ImportError:
        raise RuntimeError(
            "gmsh is not installed. Run: pip install gmsh"
        )

    try:
        import meshio
        import numpy as np
    except ImportError:
        raise RuntimeError("meshio / numpy not installed. Run: pip install meshio numpy")

    if not os.path.exists(step_path):
        raise FileNotFoundError(f"STEP file not found: {step_path}")

    algo_id = ALGORITHMS_3D.get(algorithm.lower(), ALGORITHMS_3D["hxt"])

    with _gmsh_lock:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)          # suppress stdout
        gmsh.option.setNumber("General.Verbosity", 1)

        try:
            t0 = time.time()
            logger.info(f"GMSH: opening {step_path}")
            gmsh.open(step_path)

            # Bounding box → auto mesh size
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
            if diag == 0:
                raise ValueError("Model has zero bounding-box diagonal — geometry may be empty.")

            # refinement 1→10 elements along diag, 5→50 elements
            mesh_size = diag / (refinement * 10)

            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size * 0.1)
            gmsh.option.setNumber("Mesh.Algorithm3D", algo_id)
            gmsh.option.setNumber("Mesh.Optimize", 1 if optimize else 0)

            logger.info(f"GMSH: meshing (diag={diag:.3f}, size={mesh_size:.4f}, algo={algorithm})")
            gmsh.model.mesh.generate(3)

            if optimize:
                gmsh.model.mesh.optimize("Netgen")

            # Write to a temp .msh, then convert to .vtu via meshio
            msh_path = output_vtu.replace(".vtu", "_tmp.msh")
            gmsh.write(msh_path)
            elapsed = time.time() - t0
            logger.info(f"GMSH: done in {elapsed:.1f}s → {msh_path}")

        finally:
            gmsh.finalize()

    # Convert .msh → .vtu (outside the lock; meshio is thread-safe)
    mesh = meshio.read(msh_path)
    os.remove(msh_path)

    # Drop zero-node cells that GMSH sometimes adds (points, lines)
    solid_types = {
        "tetra", "tetra10",
        "hexahedron", "hexahedron20",
        "wedge", "wedge15",
        "pyramid", "pyramid13",
    }
    cells_out = [c for c in mesh.cells if c.type in solid_types]
    if not cells_out:
        # Fall back to keeping all 3-D cells
        cells_out = [c for c in mesh.cells if c.data.shape[1] >= 4]

    mesh_out = meshio.Mesh(points=mesh.points, cells=cells_out)
    meshio.write(output_vtu, mesh_out)

    node_count = len(mesh_out.points)
    elem_count = sum(len(c.data) for c in mesh_out.cells)
    elem_types = {c.type: len(c.data) for c in mesh_out.cells}

    bbox = {
        "min_x": float(xmin), "max_x": float(xmax),
        "min_y": float(ymin), "max_y": float(ymax),
        "min_z": float(zmin), "max_z": float(zmax),
    }

    logger.info(f"Mesh saved: {node_count} nodes, {elem_count} elements → {output_vtu}")
    return {
        "node_count":    node_count,
        "element_count": elem_count,
        "element_types": elem_types,
        "bounding_box":  bbox,
        "mesh_size_used": mesh_size,
        "elapsed_s":     round(elapsed, 2),
    }
