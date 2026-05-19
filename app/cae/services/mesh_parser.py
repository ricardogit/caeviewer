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

    # Elements — accumulate blocks of the same type (GMSH emits multiple
    # CellBlocks per element type when physical groups exist; overwriting
    # drops all but the last block and breaks surface extraction).
    elements = {}
    element_types = {}
    total_elements = 0
    for cell_block in mesh.cells:
        etype = cell_block.type
        data = cell_block.data.tolist()
        if etype in elements:
            elements[etype].extend(data)
            element_types[etype] += len(data)
        else:
            elements[etype] = data
            element_types[etype] = len(data)
        total_elements += len(data)

    # Sets
    node_sets = {k: v.tolist() for k, v in (mesh.point_sets or {}).items()}
    element_sets = {k: v.tolist() for k, v in (mesh.cell_sets_dict or {}).items()}

    # Fields — handle single-step and multi-step (Exodus II, XDMF, etc.)
    node_fields = {}
    n_steps = 1

    for name, data in (mesh.point_data or {}).items():
        data_np = np.array(data) if not isinstance(data, np.ndarray) else data

        # 3-D array → (n_steps, n_nodes, n_components)  [some meshio Exodus readers]
        if data_np.ndim == 3:
            s = data_np.shape[0]
            node_fields[name] = {str(i): data_np[i].tolist() for i in range(s)}
            n_steps = max(n_steps, s)
        # List of arrays → one per time step  [some meshio readers return lists]
        elif isinstance(data, list) and len(data) > 0 and hasattr(data[0], 'tolist'):
            s = len(data)
            node_fields[name] = {str(i): a.tolist() for i, a in enumerate(data)}
            n_steps = max(n_steps, s)
        else:
            node_fields[name] = {'0': data_np.tolist()}

    element_fields = {}
    for name, cell_data_list in (mesh.cell_data_dict or {}).items():
        combined = []
        for cell_type, arr in cell_data_list.items():
            combined.extend(arr.tolist() if hasattr(arr, 'tolist') else arr)
        element_fields[name] = {'0': combined}

    time_steps = list(range(n_steps))

    # Use file-embedded time values when available (Exodus II stores them)
    if hasattr(mesh, 'point_tags') and hasattr(mesh, 'time_values'):
        try:
            time_steps = list(mesh.time_values)
        except Exception:
            pass

    ext = os.path.splitext(file_path)[1].lower()

    surface_triangles = extract_surface_triangles(elements)

    return {
        'nodes': nodes,
        'elements': elements,
        'surface_triangles': surface_triangles,
        'node_sets': node_sets,
        'element_sets': element_sets,
        'node_fields': node_fields,
        'element_fields': element_fields,
        'time_steps': time_steps,
        'bounding_box': bbox,
        'node_count': len(nodes),
        'element_count': total_elements,
        'element_types': element_types,
        'surface_triangle_count': len(surface_triangles),
        'format': ext.lstrip('.'),
        'field_names': list(node_fields.keys()) + list(element_fields.keys()),
    }


def extract_surface_triangles(elements: dict) -> list:
    """
    Extract triangles suitable for WebGL surface rendering.

    Priority:
    1. If explicit triangle/quad surface elements exist (e.g. GMSH boundary mesh), use them.
    2. Otherwise extract boundary faces from volumetric elements (tet, hex, wedge, pyramid).
    """
    triangles = []

    surf_tri_types = [e for e in ('triangle', 'tri', 'tri3', 'triangle6', 'tri6') if e in elements]
    surf_quad_types = [e for e in ('quad', 'quad4', 'quad8') if e in elements]

    if surf_tri_types or surf_quad_types:
        for etype in surf_tri_types:
            triangles.extend([conn[:3] for conn in elements[etype]])
        for etype in surf_quad_types:
            for conn in elements[etype]:
                q = conn[:4]
                triangles.append([q[0], q[1], q[2]])
                triangles.append([q[0], q[2], q[3]])
        return triangles

    # No surface elements — extract boundary faces from volumetric mesh
    from collections import defaultdict
    face_count: dict = defaultdict(int)
    face_nodes: dict = {}

    def _reg(fn):
        key = tuple(sorted(fn))
        face_count[key] += 1
        if key not in face_nodes:
            face_nodes[key] = fn

    tet_faces = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
    for etype in ('tetra', 'tet4', 'tetra10', 'tet10'):
        for conn in elements.get(etype, []):
            for f in tet_faces:
                _reg([conn[i] for i in f])

    hex_faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    for etype in ('hexahedron', 'hex8', 'hexahedron20', 'hex20'):
        for conn in elements.get(etype, []):
            for f in hex_faces:
                _reg([conn[i] for i in f])

    for etype in ('wedge', 'penta6', 'prism6'):
        for conn in elements.get(etype, []):
            for f in [(0, 1, 2), (3, 4, 5)]:
                _reg([conn[i] for i in f])
            for f in [(0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]:
                _reg([conn[i] for i in f])

    for etype in ('pyramid', 'pyra5'):
        for conn in elements.get(etype, []):
            _reg([conn[i] for i in (0, 3, 2, 1)])
            for f in [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]:
                _reg([conn[i] for i in f])

    for key, count in face_count.items():
        if count != 1:
            continue
        fn = face_nodes[key]
        if len(fn) == 3:
            triangles.append(fn)
        elif len(fn) == 4:
            triangles.append([fn[0], fn[1], fn[2]])
            triangles.append([fn[0], fn[2], fn[3]])

    return triangles


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
