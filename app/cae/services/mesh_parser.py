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

try:
    import lsdyna_mesh_reader as _lmr_probe  # noqa: F401
    LSDYNA_AVAILABLE = True
except ImportError:
    LSDYNA_AVAILABLE = False
    logger.warning("lsdyna-mesh-reader not installed — LS-DYNA import disabled. Run: pip install lsdyna-mesh-reader")


# ---------------------------------------------------------------------------
# Outward-normal consistency
# ---------------------------------------------------------------------------

def _ensure_outward_normals(triangles: list, nodes_np) -> list:
    """Flip surface triangles whose normals point inward (centroid-based check)."""
    if not triangles or nodes_np is None:
        return triangles
    try:
        import numpy as np
        tri_arr = np.array(triangles, dtype=np.int32)
        n_pts = len(nodes_np)
        valid = np.all((tri_arr >= 0) & (tri_arr < n_pts), axis=1)
        tri_arr = tri_arr[valid]
        if len(tri_arr) == 0:
            return triangles
        p0 = nodes_np[tri_arr[:, 0]]
        p1 = nodes_np[tri_arr[:, 1]]
        p2 = nodes_np[tri_arr[:, 2]]
        centroid = nodes_np.mean(axis=0)
        normals = np.cross(p1 - p0, p2 - p0)
        face_centers = (p0 + p1 + p2) / 3.0
        dot = np.einsum('ij,ij->i', normals, face_centers - centroid)
        result = tri_arr.copy()
        flip = dot < 0
        result[flip, 1] = tri_arr[flip, 2]
        result[flip, 2] = tri_arr[flip, 1]
        return result.tolist()
    except Exception as exc:
        logger.warning(f"_ensure_outward_normals failed: {exc}")
        return triangles


# ---------------------------------------------------------------------------
# Solver recommendations
# ---------------------------------------------------------------------------

_SOLVER_RULES: dict = {
    'OpenFOAM':   {'description': 'CFD / FEA estructural, hex/poliédrico óptimo',
                   'excellent': {'hexahedron', 'hexahedron20', 'wedge', 'pyramid'},
                   'good':      {'tetra', 'tetra10'}},
    'CalculiX':   {'description': 'FEA estructural open-source, elementos C3D',
                   'excellent': {'tetra', 'tetra10', 'hexahedron', 'hexahedron20'},
                   'good':      {'wedge', 'pyramid', 'triangle', 'quad'}},
    'Abaqus':     {'description': 'FEA comercial, soporte completo de elementos',
                   'excellent': {'tetra', 'tetra10', 'hexahedron', 'hexahedron20',
                                 'wedge', 'pyramid', 'triangle', 'quad'},
                   'good':      {'line'}},
    'Code_Aster': {'description': 'FEA open-source (EDF), tet/hex robusto',
                   'excellent': {'tetra', 'tetra10', 'hexahedron'},
                   'good':      {'wedge', 'triangle', 'quad'}},
    'FEniCS':     {'description': 'FEM Python, nativo en mallas tet/tri',
                   'excellent': {'tetra', 'tetra10', 'triangle'},
                   'good':      {'hexahedron', 'quad'},
                   'poor':      {'wedge', 'pyramid'}},
    'Elmer':      {'description': 'FEM multifísica open-source',
                   'excellent': {'tetra', 'tetra10', 'hexahedron'},
                   'good':      {'wedge', 'triangle', 'quad'}},
    'Star-CCM+':  {'description': 'CFD/FEA comercial, hex/poliédrico',
                   'excellent': {'hexahedron', 'hexahedron20', 'wedge', 'pyramid'},
                   'good':      {'tetra', 'tetra10'}},
    'Fluent':     {'description': 'CFD comercial (ANSYS), hex/tet/mixto',
                   'excellent': {'hexahedron', 'hexahedron20', 'wedge'},
                   'good':      {'tetra', 'tetra10', 'pyramid'}},
    'LS-DYNA':    {'description': 'Dinámica explícita, shell/sólido',
                   'excellent': {'hexahedron', 'hexahedron20', 'tetra', 'tetra10',
                                 'triangle', 'quad'},
                   'good':      {'wedge', 'pyramid'}},
    'Kratos':     {'description': 'Framework multifísica open-source (CIMNE)',
                   'excellent': {'tetra', 'tetra10', 'hexahedron', 'triangle', 'quad'},
                   'good':      {'wedge', 'pyramid'}},
}


def recommend_solvers(element_types: dict) -> list:
    """Return [{solver, level, confidence, description}] sorted by confidence."""
    present = set(element_types.keys()) if element_types else set()
    if not present:
        return []
    results = []
    for solver, rules in _SOLVER_RULES.items():
        exc_n  = len(present & rules.get('excellent', set()))
        good_n = len(present & rules.get('good',      set()))
        poor_n = len(present & rules.get('poor',      set()))
        score  = (exc_n * 3 + good_n * 2 - poor_n * 2) / (len(present) * 3)
        score  = round(max(0.0, min(1.0, score)), 2)
        if score > 0.1:
            level = 'excellent' if score >= 0.8 else 'good' if score >= 0.5 else 'compatible'
            results.append({
                'solver':      solver,
                'level':       level,
                'confidence':  score,
                'description': rules['description'],
            })
    results.sort(key=lambda x: -x['confidence'])
    return results[:6]


# ---------------------------------------------------------------------------
# Mesh quality metrics (vectorised aspect-ratio)
# ---------------------------------------------------------------------------

_TET_EDGES   = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
_HEX_EDGES   = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
_WEDGE_EDGES = [(0,1),(1,2),(2,0),(3,4),(4,5),(5,3),(0,3),(1,4),(2,5)]
_MAX_SAMPLE  = 20_000


def compute_mesh_quality(elements: dict, nodes_np) -> dict:
    """Vectorised aspect-ratio quality metric for tet/hex/wedge elements."""
    if nodes_np is None:
        return {}
    try:
        import numpy as np

        def _ratios(conns_raw, edge_pairs, n_corner):
            c = np.array(conns_raw, dtype=np.int32)
            if len(c) > _MAX_SAMPLE:
                idx = np.random.default_rng(0).choice(len(c), _MAX_SAMPLE, replace=False)
                c = c[idx]
            pts = nodes_np[c[:, :n_corner]]              # (N, K, 3)
            edges = np.stack([
                np.linalg.norm(pts[:, b] - pts[:, a], axis=-1)
                for a, b in edge_pairs
            ])                                           # (E, N)
            return edges.max(axis=0) / (edges.min(axis=0) + 1e-30)

        all_ratios = []
        for etype in ('tetra', 'tetra10'):
            if elements.get(etype):
                all_ratios.append(_ratios(elements[etype], _TET_EDGES, 4))
        for etype in ('hexahedron', 'hexahedron20'):
            if elements.get(etype):
                all_ratios.append(_ratios(elements[etype], _HEX_EDGES, 8))
        for etype in ('wedge', 'wedge15'):
            if elements.get(etype):
                all_ratios.append(_ratios(elements[etype], _WEDGE_EDGES, 6))

        if not all_ratios:
            return {}
        arr = np.concatenate(all_ratios)
        return {
            'aspect_ratio_mean': round(float(arr.mean()), 3),
            'aspect_ratio_max':  round(float(arr.max()),  3),
            'aspect_ratio_p95':  round(float(np.percentile(arr, 95)), 3),
            'bad_elements_pct':  round(float(np.mean(arr > 10.0) * 100), 2),
            'sampled_count':     int(len(arr)),
        }
    except Exception as exc:
        logger.warning(f"compute_mesh_quality failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# LS-DYNA keyword reader
# ---------------------------------------------------------------------------

def _parse_lsdyna(file_path: str) -> dict:
    """
    Parse a LS-DYNA keyword file (.k/.key) using lsdyna-mesh-reader 0.1.x API.

    lsdyna-mesh-reader does NOT resolve *INCLUDE — for multi-file assemblies,
    the ZIP upload workflow extracts all files and points here to the master .k
    file; nodes/elements in other files won't be visible unless they are in
    this single file (limitation of the library at v0.1.x).
    """
    try:
        import lsdyna_mesh_reader
    except ImportError:
        raise RuntimeError(
            "lsdyna-mesh-reader no está instalado. Ejecuta: pip install lsdyna-mesh-reader"
        )
    import numpy as np

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

    logger.info(f"Parsing LS-DYNA keyword: {file_path}")
    deck = lsdyna_mesh_reader.Deck(file_path)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    # Merge all node sections; LS-DYNA uses arbitrary integer IDs — remap to
    # 0-based contiguous indices for the viewer.
    all_nids:   list = []
    all_coords: list = []
    for ns in (deck.node_sections or []):
        all_nids.append(np.asarray(ns.nid,         dtype=np.int64))
        all_coords.append(np.asarray(ns.coordinates, dtype=np.float64))

    if not all_nids:
        raise ValueError("No nodes found in LS-DYNA file")

    nid_arr = np.concatenate(all_nids)
    coords  = np.concatenate(all_coords, axis=0)
    nid_to_idx: dict = {int(nid): i for i, nid in enumerate(nid_arr)}
    nodes = coords.tolist()

    elements:       dict = {}
    element_types:  dict = {}
    total_elements: int  = 0

    def _safe(nid: int) -> int:
        return nid_to_idx.get(nid, -1)

    def _add(etype: str, batch: list) -> None:
        nonlocal total_elements
        if not batch:
            return
        if etype in elements:
            elements[etype].extend(batch)
            element_types[etype] += len(batch)
        else:
            elements[etype]      = batch
            element_types[etype] = len(batch)
        total_elements += len(batch)

    def _iter_sections(sections):
        """
        Yield per-element node-ID arrays from lsdyna-mesh-reader 0.1.x sections.
        Each section stores connectivity as a flat node_ids array with a
        node_id_offsets array (CSR-style: offsets[i]:offsets[i+1] = elem i nodes).
        """
        for sec in (sections or []):
            nids    = np.asarray(sec.node_ids,        dtype=np.int64)
            offsets = np.asarray(sec.node_id_offsets, dtype=np.intp)
            for i in range(len(offsets) - 1):
                yield nids[offsets[i]:offsets[i + 1]]

    # ── Solids (ELEMENT_SOLID) ────────────────────────────────────────────────
    # LS-DYNA stores 8 node columns even for degenerate types (repeated nodes).
    # Detect actual type by counting unique IDs in the row:
    #   4 unique → tet4, 5 → pyramid, 6 → wedge6, 7-8 → hex8
    hex_b, tet_b, wedge_b, pyr_b = [], [], [], []
    try:
        for row in _iter_sections(deck.element_solid_sections):
            unique = list(dict.fromkeys(int(x) for x in row))  # ordered dedup
            n      = len(unique)
            idxs   = [_safe(u) for u in unique]
            if -1 in idxs:
                continue
            if n == 4:
                tet_b.append(idxs)
            elif n == 5:
                pyr_b.append(idxs)
            elif n == 6:
                wedge_b.append(idxs)
            else:                                           # 7 or 8 → hex8
                idxs8 = [_safe(int(x)) for x in row[:8]]
                if -1 not in idxs8:
                    hex_b.append(idxs8)
    except Exception as exc:
        logger.warning(f"LS-DYNA solids: {exc}")
    _add('hexahedron', hex_b)
    _add('tetra',      tet_b)
    _add('wedge',      wedge_b)
    _add('pyramid',    pyr_b)

    # ── Thick shells (ELEMENT_TSHELL) → hexahedra ────────────────────────────
    try:
        batch = []
        for row in _iter_sections(getattr(deck, 'element_tshell_sections', None)):
            idxs = [_safe(int(x)) for x in row[:8]]
            if -1 not in idxs:
                batch.append(idxs)
        _add('hexahedron', batch)
    except Exception as exc:
        logger.warning(f"LS-DYNA tshells: {exc}")

    # ── Shells (ELEMENT_SHELL) ────────────────────────────────────────────────
    # 4-column card; tri3 detected when 4th node repeats 3rd (or is 0).
    try:
        quads, tris = [], []
        for row in _iter_sections(deck.element_shell_sections):
            row_list = [int(x) for x in row]
            if len(row_list) >= 4:
                n1, n2, n3, n4 = row_list[:4]
                if n4 == n3 or n4 == 0:
                    idxs = [_safe(n) for n in (n1, n2, n3)]
                    if -1 not in idxs:
                        tris.append(idxs)
                else:
                    idxs = [_safe(n) for n in (n1, n2, n3, n4)]
                    if -1 not in idxs:
                        quads.append(idxs)
            elif len(row_list) == 3:
                idxs = [_safe(n) for n in row_list]
                if -1 not in idxs:
                    tris.append(idxs)
        _add('triangle', tris)
        _add('quad',     quads)
    except Exception as exc:
        logger.warning(f"LS-DYNA shells: {exc}")

    # ── Beams (ELEMENT_BEAM) ──────────────────────────────────────────────────
    try:
        batch = []
        for row in _iter_sections(getattr(deck, 'element_beam_sections', None)):
            idxs = [_safe(int(x)) for x in row[:2]]
            if -1 not in idxs:
                batch.append(idxs)
        _add('line', batch)
    except Exception as exc:
        logger.warning(f"LS-DYNA beams: {exc}")

    # ── Node sets ─────────────────────────────────────────────────────────────
    node_sets: dict = {}
    try:
        for ns in (getattr(deck, 'node_set_sections', None) or []):
            sid  = str(getattr(ns, 'sid', id(ns)))
            idxs = [_safe(int(n)) for n in (getattr(ns, 'nid', None) or [])]
            good = [i for i in idxs if i >= 0]
            if good:
                node_sets[sid] = good
    except Exception as exc:
        logger.warning(f"LS-DYNA node sets: {exc}")

    # ── Parts → element set names ─────────────────────────────────────────────
    element_sets: dict = {}
    try:
        for part in (getattr(deck, 'part_sections', None) or []):
            pid  = str(getattr(part, 'pid', id(part)))
            name = (getattr(part, 'title', '') or '').strip() or f'Part_{pid}'
            element_sets[name] = []
    except Exception as exc:
        logger.warning(f"LS-DYNA parts: {exc}")

    # ── Bounding box ──────────────────────────────────────────────────────────
    bbox = {
        'min_x': float(coords[:, 0].min()), 'max_x': float(coords[:, 0].max()),
        'min_y': float(coords[:, 1].min()), 'max_y': float(coords[:, 1].max()),
        'min_z': float(coords[:, 2].min()), 'max_z': float(coords[:, 2].max()),
    }

    surface_triangles = extract_surface_triangles(elements)
    surface_triangles = _ensure_outward_normals(surface_triangles, coords)

    return {
        'nodes':                  nodes,
        'elements':               elements,
        'surface_triangles':      surface_triangles,
        'node_sets':              node_sets,
        'element_sets':           element_sets,
        'node_fields':            {},
        'element_fields':         {},
        'time_steps':             [0],
        'bounding_box':           bbox,
        'node_count':             len(nodes),
        'element_count':          total_elements,
        'element_types':          element_types,
        'surface_triangle_count': len(surface_triangles),
        'format':                 'k',
        'field_names':            [],
        'recommended_solvers':    recommend_solvers(element_types),
        'quality':                compute_mesh_quality(elements, coords),
    }


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
    # Route LS-DYNA keyword files to dedicated parser
    if os.path.splitext(file_path)[1].lower() in ('.k', '.key'):
        return _parse_lsdyna(file_path)

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
    surface_triangles = _ensure_outward_normals(surface_triangles, mesh.points)

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
        'recommended_solvers': recommend_solvers(element_types),
        'quality': compute_mesh_quality(elements, mesh.points),
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
