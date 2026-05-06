"""
Mesh parser — wraps meshio to read 40+ FEA formats into a canonical dict.

Supported formats (sample): VTK .vtu, Abaqus .inp, Nastran .bdf/.nas,
GMSH .msh, MED .med, Exodus .exo, ANSYS .cdb, OpenFOAM dirs.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import meshio
    import numpy as np
    MESHIO_AVAILABLE = True
except ImportError:
    MESHIO_AVAILABLE = False
    logger.warning("meshio not installed — CAE mesh import disabled. Run: pip install meshio numpy")


def parse_mesh(file_path: str) -> dict:
    """
    Read a mesh file and return a canonical dict:
    {
      nodes: [[x,y,z], ...],          # float32 Nx3
      elements: {                      # keyed by element type string
        "tetra": [[n0,n1,n2,n3], ...],
        "hexahedron": [...],
        ...
      },
      node_sets:    {"name": [node_idx, ...]},
      element_sets: {"name": [elem_idx, ...]},
      node_fields:  {"name": {"step": value_array}},
      element_fields: {"name": {"step": value_array}},
      time_steps: [0.0, 0.1, ...],
      bounding_box: {min_x, max_x, min_y, max_y, min_z, max_z},
      node_count: int,
      element_count: int,
      element_types: {"tet4": count, ...},
      format: str,
    }
    """
    if not MESHIO_AVAILABLE:
        raise RuntimeError("meshio is not installed. Run: pip install meshio numpy")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Mesh file not found: {file_path}")

    logger.info(f"Parsing mesh: {file_path}")
    mesh = meshio.read(file_path)

    # Nodes
    nodes = mesh.points.tolist()
    pts = mesh.points
    bbox = {
        'min_x': float(pts[:, 0].min()), 'max_x': float(pts[:, 0].max()),
        'min_y': float(pts[:, 1].min()), 'max_y': float(pts[:, 1].max()),
        'min_z': float(pts[:, 2].min()), 'max_z': float(pts[:, 2].max()),
    }

    # Elements
    elements = {}
    element_types = {}
    total_elements = 0
    for cell_block in mesh.cells:
        etype = cell_block.type
        data = cell_block.data.tolist()
        elements[etype] = data
        element_types[etype] = len(data)
        total_elements += len(data)

    # Sets
    node_sets = {k: v.tolist() for k, v in (mesh.point_sets or {}).items()}
    element_sets = {k: v.tolist() for k, v in (mesh.cell_sets_dict or {}).items()}

    # Fields
    node_fields = {}
    for name, data in (mesh.point_data or {}).items():
        arr = data if isinstance(data, list) else data.tolist()
        node_fields[name] = {'0': arr}

    element_fields = {}
    for name, cell_data_list in (mesh.cell_data_dict or {}).items():
        # meshio cell_data_dict: {field_name: {cell_type: array}}
        # Flatten to first cell block for simplicity
        combined = []
        for cell_type, arr in cell_data_list.items():
            combined.extend(arr.tolist() if hasattr(arr, 'tolist') else arr)
        element_fields[name] = {'0': combined}

    ext = os.path.splitext(file_path)[1].lower()

    return {
        'nodes': nodes,
        'elements': elements,
        'node_sets': node_sets,
        'element_sets': element_sets,
        'node_fields': node_fields,
        'element_fields': element_fields,
        'time_steps': [0.0],
        'bounding_box': bbox,
        'node_count': len(nodes),
        'element_count': total_elements,
        'element_types': element_types,
        'format': ext.lstrip('.'),
        'field_names': list(node_fields.keys()) + list(element_fields.keys()),
    }


def get_field_range(field_data: list) -> tuple:
    """Return (min, max) for a flat or nested list of field values."""
    try:
        import numpy as np
        arr = np.array(field_data, dtype=float)
        if arr.ndim > 1:
            arr = np.linalg.norm(arr, axis=-1)  # vector magnitude
        return float(arr.min()), float(arr.max())
    except Exception:
        return 0.0, 1.0
