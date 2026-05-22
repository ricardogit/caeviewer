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

def _resolve_lsdyna_includes(master_path: str) -> list:
    """
    BFS traversal of *INCLUDE directives.  Returns [(abs_path, None), ...]
    where None means identity transform (no *INCLUDE_TRANSFORM offsets).
    Deduplicates: each unique file is visited once.
    Used as fallback when no *INCLUDE_TRANSFORM is present.
    """
    def _find_includes(path: str) -> list:
        found = []
        try:
            with open(path, 'r', errors='ignore') as fh:
                take_next = False
                for line in fh:
                    s = line.strip()
                    su = s.upper()
                    # Skip *INCLUDE_TRANSFORM (handled by _parse_include_transforms)
                    if su.startswith('*INCLUDE') and not su.startswith('*INCLUDE_TRANSFORM'):
                        take_next = True
                        continue
                    if take_next:
                        if s and not s.startswith('$') and not s.startswith('*'):
                            candidate = os.path.normpath(
                                os.path.join(os.path.dirname(path), s)
                            )
                            found.append(candidate)
                        take_next = False
        except OSError:
            pass
        return found

    ordered: list = []
    visited: set  = set()
    queue         = [os.path.abspath(master_path)]
    while queue:
        abs_p = queue.pop(0)
        if abs_p in visited:
            continue
        visited.add(abs_p)
        if not os.path.exists(abs_p):
            logger.warning(f"LS-DYNA *INCLUDE not found (skipped): {abs_p}")
            continue
        ordered.append(abs_p)
        for inc in _find_includes(abs_p):
            inc_abs = os.path.abspath(inc)
            if inc_abs not in visited:
                queue.append(inc_abs)
    return [(p, None) for p in ordered]


def _parse_include_transforms(master_path: str) -> list:
    """
    Parse *DEFINE_TRANSFORMATION and *INCLUDE_TRANSFORM from a LS-DYNA master
    file.  Returns [(abs_filepath, transform), ...] preserving duplicate entries
    (e.g. the same bolt file included 6 times with different translations).

    transform is either None (identity) or a (R, t) tuple where:
      R: 3×3 numpy rotation matrix (or None for pure translation)
      t: (tx, ty, tz) float tuple

    Supports TRANSL and ROTATE operations.  Multiple operations per transform
    are composed left-to-right (last operation applied last).

    Falls back to _resolve_lsdyna_includes() if no *INCLUDE_TRANSFORM found.
    """
    import numpy as np

    master_abs = os.path.abspath(master_path)
    master_dir = os.path.dirname(master_abs)

    try:
        with open(master_abs, 'r', errors='ignore') as fh:
            lines = fh.readlines()
    except OSError:
        return _resolve_lsdyna_includes(master_path)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _advance(idx):
        """Skip comment/blank lines; return (stripped_line, next_idx) or (None, idx)."""
        while idx < len(lines):
            s = lines[idx].strip()
            if s and not s.startswith('$'):
                return s, idx + 1
            idx += 1
        return None, idx

    def _rot_matrix(rx, ry, rz, cx, cy, cz, angle_deg):
        """Build 4×4 homogeneous rotation around axis (rx,ry,rz) centered at (cx,cy,cz)."""
        L = (rx**2 + ry**2 + rz**2) ** 0.5
        if L < 1e-10:
            return np.eye(4)
        ux, uy, uz = rx / L, ry / L, rz / L
        a = angle_deg * 3.141592653589793 / 180.0
        c, s = np.cos(a), np.sin(a)
        R = np.array([
            [c + ux*ux*(1-c),    ux*uy*(1-c) - uz*s, ux*uz*(1-c) + uy*s, 0],
            [uy*ux*(1-c) + uz*s, c + uy*uy*(1-c),    uy*uz*(1-c) - ux*s, 0],
            [uz*ux*(1-c) - uy*s, uz*uy*(1-c) + ux*s, c + uz*uz*(1-c),    0],
            [0, 0, 0, 1],
        ], dtype=np.float64)
        # Rotate around (cx,cy,cz): translate to origin, rotate, translate back
        Tc  = np.eye(4); Tc[0,3]  = -cx; Tc[1,3]  = -cy; Tc[2,3]  = -cz
        Tci = np.eye(4); Tci[0,3] =  cx; Tci[1,3] =  cy; Tci[2,3] =  cz
        return Tci @ R @ Tc

    # ── Pass 1: parse *DEFINE_TRANSFORMATION ─────────────────────────────────
    transforms = {}   # tranid → 4×4 numpy matrix
    i = 0
    while i < len(lines):
        su = lines[i].strip().upper()
        if su.startswith('*DEFINE_TRANSFORMATION'):
            i += 1
            if 'TITLE' in su:
                _, i = _advance(i)   # title line — skip
            tranid_s, i = _advance(i)
            if tranid_s is None:
                continue
            try:
                tranid = int(tranid_s.split()[0])
            except (ValueError, IndexError):
                continue
            M = np.eye(4)
            while i < len(lines):
                s2 = lines[i].strip()
                if s2.startswith('*'):
                    break
                if s2 and not s2.startswith('$'):
                    parts = s2.split()
                    op = parts[0].upper()
                    try:
                        if op == 'TRANSL' and len(parts) >= 4:
                            T = np.eye(4)
                            T[0,3] = float(parts[1])
                            T[1,3] = float(parts[2])
                            T[2,3] = float(parts[3])
                            M = T @ M
                        elif op == 'ROTATE' and len(parts) >= 8:
                            R = _rot_matrix(
                                float(parts[1]), float(parts[2]), float(parts[3]),
                                float(parts[4]), float(parts[5]), float(parts[6]),
                                float(parts[7]),
                            )
                            M = R @ M
                    except (ValueError, IndexError):
                        pass
                i += 1
            transforms[tranid] = M
        else:
            i += 1

    # ── Pass 2: parse *INCLUDE_TRANSFORM ─────────────────────────────────────
    includes = []
    has_transform_kw = False
    i = 0
    while i < len(lines):
        su = lines[i].strip().upper()
        i += 1
        if su.startswith('*INCLUDE_TRANSFORM'):
            has_transform_kw = True
            fname_s, i = _advance(i)
            if fname_s is None or fname_s.startswith('*'):
                continue
            # 4 data cards (skip $ comments between them); card index 3 = tranid
            tranid = 0
            card = 0
            while i <= len(lines) and card < 4:
                ds, i = _advance(i)
                if ds is None or ds.startswith('*'):
                    break
                if card == 3:
                    try:
                        tranid = int(ds.split()[0])
                    except (ValueError, IndexError):
                        pass
                card += 1
            # Resolve file path (handles backslashes from Windows paths)
            fname_norm = fname_s.replace('\\', os.sep).replace('/', os.sep).strip()
            abs_path = os.path.normpath(os.path.join(master_dir, fname_norm))
            if not os.path.exists(abs_path):
                # Try basename only (for archives that flatten directory structure)
                abs_path2 = os.path.join(master_dir, os.path.basename(fname_norm))
                if os.path.exists(abs_path2):
                    abs_path = abs_path2
                else:
                    logger.warning(f"*INCLUDE_TRANSFORM: file not found: {fname_s!r}")
                    includes.append((None, transforms.get(tranid)))
                    continue
            includes.append((abs_path, transforms.get(tranid)))

        elif su.startswith('*INCLUDE') and not su.startswith('*INCLUDE_PATH'):
            fname_s, i = _advance(i)
            if fname_s is None or fname_s.startswith('*'):
                continue
            fname_norm = fname_s.replace('\\', os.sep).strip()
            abs_path = os.path.normpath(os.path.join(master_dir, fname_norm))
            if os.path.exists(abs_path):
                includes.append((abs_path, None))

    # ── Decide result ─────────────────────────────────────────────────────────
    if not has_transform_kw:
        # No *INCLUDE_TRANSFORM found — BFS resolver handles plain *INCLUDE chains
        return _resolve_lsdyna_includes(master_path)

    # Prepend master itself (may define nodes/elements at the root level)
    result = [(master_abs, None)] + [(p, M) for p, M in includes if p is not None]
    logger.info(
        f"*INCLUDE_TRANSFORM assembly: {len(result)} total entries "
        f"({len(set(p for p,_ in result))} unique files, "
        f"{sum(1 for _,M in result if M is not None and not (M == np.eye(4)).all())} "
        f"with non-identity transforms)"
    )
    return result


def _parse_lsdyna(file_path: str) -> dict:
    """
    Parse a LS-DYNA keyword file (.k/.key) using lsdyna-mesh-reader 0.1.x API.

    *INCLUDE directives are resolved manually (the library does not do this).
    Each file in the inclusion chain is read with a separate Deck() call and
    the node/element sections are concatenated before processing.  Works for
    both single-file models and multi-file assemblies extracted from a ZIP.
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

    # ── Resolve includes (handles *INCLUDE and *INCLUDE_TRANSFORM) ────────────
    # Returns [(abs_filepath, matrix_or_None), ...]
    # - *INCLUDE_TRANSFORM: preserves duplicates, embeds TRANSL/ROTATE matrix
    # - *INCLUDE / standalone file: deduplicates, matrix=None (identity)
    file_entries = _parse_include_transforms(file_path)

    # Fallback for ZIP assemblies where *INCLUDE paths use absolute Windows
    # paths that can't resolve on Linux: scan directory for any .k/.key not
    # already in the list (added with identity transform, no duplicates).
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if os.path.basename(parent_dir).startswith('assy_'):
        import glob as _glob
        known_paths = set(p for p, _ in file_entries if p)
        all_k: set = set()
        for pat in ('**/*.k', '**/*.key'):
            for f in _glob.glob(os.path.join(parent_dir, pat), recursive=True):
                all_k.add(os.path.abspath(f))
        extra = sorted(all_k - known_paths)
        if extra:
            logger.info(
                f"LS-DYNA assy fallback: +{len(extra)} unlisted file(s): "
                + ", ".join(os.path.basename(f) for f in extra)
            )
            file_entries.extend((f, None) for f in extra)

    logger.info(
        f"LS-DYNA: {len(file_entries)} file entries "
        f"({len(set(p for p,_ in file_entries if p))} unique files)"
    )

    # ── Per-file processing ────────────────────────────────────────────────────
    # LS-DYNA assemblies using *INCLUDE_TRANSFORM give each part file
    # independent local node IDs (e.g. 1..N in every part file).
    # We build a per-file local_nid→global_idx map and shift element
    # connectivity on merge, so IDs from different files never collide.
    # For "master+parts" assemblies where master defines all nodes and parts
    # define only elements, we fall back to an accumulated global map.

    global_coords:  list = []          # flat list of [x,y,z] triples
    accumulated_global_map: dict = {}  # nid → global_idx (first-seen, for Pattern B)
    elements:       dict = {}
    element_types:  dict = {}
    total_elements: int  = 0
    all_decks:      list = []

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

    def _iter_sec(sections):
        """Yield per-element node-ID arrays from CSR-style section objects."""
        for sec in (sections or []):
            try:
                nids    = np.asarray(sec.node_ids,        dtype=np.int64)
                offsets = np.asarray(sec.node_id_offsets, dtype=np.intp)
                for i in range(len(offsets) - 1):
                    yield nids[offsets[i]:offsets[i + 1]]
            except Exception as exc:
                logger.warning(f"LS-DYNA section iter: {exc}")

    def _process_elements(safe_fn, solid_secs, shell_secs, tshell_secs, beam_secs):
        # ── Solids ────────────────────────────────────────────────────────────
        # LS-DYNA ELEMENT_SOLID stores 8 or 10 columns.  Zeros are padding
        # (n9/n10 = 0).  Exclude zeros before deduplication so that a tet4
        # stored as [n1,n2,n3,n4,n4,n4,n4,n4,0,0] counts as 4 unique nodes,
        # not 5 (which would wrongly classify it as a pyramid).
        hex_b, tet_b, wedge_b, pyr_b = [], [], [], []
        try:
            for row in _iter_sec(solid_secs):
                nonzero = [int(x) for x in row if int(x) != 0]
                unique  = list(dict.fromkeys(nonzero))
                n       = len(unique)
                if n == 4:
                    idxs = [safe_fn(u) for u in unique]
                    if -1 not in idxs:
                        tet_b.append(idxs)
                elif n == 5:
                    idxs = [safe_fn(u) for u in unique]
                    if -1 not in idxs:
                        pyr_b.append(idxs)
                elif n == 6:
                    idxs = [safe_fn(u) for u in unique]
                    if -1 not in idxs:
                        wedge_b.append(idxs)
                elif n >= 7:
                    idxs8 = [safe_fn(u) for u in unique[:8]]
                    if len(idxs8) == 8 and -1 not in idxs8:
                        hex_b.append(idxs8)
        except Exception as exc:
            logger.warning(f"LS-DYNA solids: {exc}")
        _add('hexahedron', hex_b)
        _add('tetra',      tet_b)
        _add('wedge',      wedge_b)
        _add('pyramid',    pyr_b)

        # ── Thick shells → hexahedra ──────────────────────────────────────────
        try:
            batch = []
            for row in _iter_sec(tshell_secs):
                nz = [int(x) for x in row if int(x) != 0]
                idxs = [safe_fn(u) for u in nz[:8]]
                if len(idxs) == 8 and -1 not in idxs:
                    batch.append(idxs)
            _add('hexahedron', batch)
        except Exception as exc:
            logger.warning(f"LS-DYNA tshells: {exc}")

        # ── Shells ────────────────────────────────────────────────────────────
        try:
            quads, tris = [], []
            for row in _iter_sec(shell_secs):
                rl = [int(x) for x in row]
                if len(rl) >= 4:
                    n1, n2, n3, n4 = rl[:4]
                    if n4 == 0 or n4 == n3:
                        idxs = [safe_fn(n) for n in (n1, n2, n3)]
                        if -1 not in idxs:
                            tris.append(idxs)
                    else:
                        idxs = [safe_fn(n) for n in (n1, n2, n3, n4)]
                        if -1 not in idxs:
                            quads.append(idxs)
                elif len(rl) == 3:
                    idxs = [safe_fn(n) for n in rl]
                    if -1 not in idxs:
                        tris.append(idxs)
            _add('triangle', tris)
            _add('quad',     quads)
        except Exception as exc:
            logger.warning(f"LS-DYNA shells: {exc}")

        # ── Beams ─────────────────────────────────────────────────────────────
        try:
            batch = []
            for row in _iter_sec(beam_secs):
                nz = [int(x) for x in row if int(x) != 0]
                idxs = [safe_fn(u) for u in nz[:2]]
                if len(idxs) == 2 and -1 not in idxs:
                    batch.append(idxs)
            _add('line', batch)
        except Exception as exc:
            logger.warning(f"LS-DYNA beams: {exc}")

    for fpath, transform_M in file_entries:
        if fpath is None:
            continue
        try:
            deck = lsdyna_mesh_reader.Deck(fpath)
        except Exception as exc:
            logger.warning(f"LS-DYNA: cannot read {fpath}: {exc}")
            continue
        all_decks.append(deck)

        # Build local map: local nid → global coord index for THIS file's nodes
        local_nid_map: dict = {}
        file_node_start = len(global_coords)

        for ns in (deck.node_sections or []):
            nids_arr   = np.asarray(ns.nid,          dtype=np.int64)
            coords_arr = np.asarray(ns.coordinates,  dtype=np.float64)
            for nid_raw, coord in zip(nids_arr, coords_arr):
                nid_int = int(nid_raw)
                if nid_int == 0:
                    continue
                if nid_int not in local_nid_map:
                    gidx = len(global_coords)
                    local_nid_map[nid_int] = gidx
                    # Apply *INCLUDE_TRANSFORM matrix (TRANSL + ROTATE)
                    if transform_M is not None:
                        c4 = transform_M @ np.array([coord[0], coord[1], coord[2], 1.0])
                        global_coords.append([float(c4[0]), float(c4[1]), float(c4[2])])
                    else:
                        global_coords.append(coord.tolist())
                    if nid_int not in accumulated_global_map:
                        accumulated_global_map[nid_int] = gidx

        n_file_nodes = len(global_coords) - file_node_start
        logger.info(f"  {os.path.basename(fpath)}: {n_file_nodes} nodes, "
                    f"solids={len(deck.element_solid_sections or [])}, "
                    f"shells={len(deck.element_shell_sections or [])}")

        # Use this file's local map if it has nodes; otherwise fall back to the
        # accumulated global map (supports "master-nodes + part-elements" pattern)
        active_map = local_nid_map if local_nid_map else accumulated_global_map

        def _safe(nid: int, _m=active_map) -> int:
            return _m.get(nid, -1)

        _process_elements(
            _safe,
            deck.element_solid_sections,
            deck.element_shell_sections,
            getattr(deck, 'element_tshell_sections', None),
            getattr(deck, 'element_beam_sections',   None),
        )

    if not global_coords:
        n_files = len(file_list)
        raise ValueError(
            f"No se encontraron nodos en {n_files} archivo(s) LS-DYNA. "
            "Si es un ensamble multi-archivo, sube todos los .k en un ZIP."
        )

    coords = np.array(global_coords, dtype=np.float64)
    nodes  = global_coords  # already list of [x,y,z]

    # ── Node sets / parts (best-effort) ──────────────────────────────────────
    node_sets:    dict = {}
    element_sets: dict = {}
    for d in all_decks:
        try:
            for ns in (getattr(d, 'node_set_sections', None) or []):
                sid  = str(getattr(ns, 'sid', id(ns)))
                idxs = [accumulated_global_map.get(int(n), -1)
                        for n in (getattr(ns, 'nid', None) or [])]
                good = [i for i in idxs if i >= 0]
                if good:
                    node_sets[sid] = good
            for part in (getattr(d, 'part_sections', None) or []):
                pid  = str(getattr(part, 'pid', id(part)))
                name = (getattr(part, 'title', '') or '').strip() or f'Part_{pid}'
                element_sets[name] = []
        except Exception as exc:
            logger.warning(f"LS-DYNA sets/parts: {exc}")

    # ── Bounding box ──────────────────────────────────────────────────────────
    bbox = {
        'min_x': float(coords[:, 0].min()), 'max_x': float(coords[:, 0].max()),
        'min_y': float(coords[:, 1].min()), 'max_y': float(coords[:, 1].max()),
        'min_z': float(coords[:, 2].min()), 'max_z': float(coords[:, 2].max()),
    }

    surface_triangles = extract_surface_triangles(elements)
    # Face winding is analytically correct from extract_surface_triangles;
    # do NOT apply centroid-based flip (breaks non-convex geometry).

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
    # cell_sets_dict values are {cell_type: array} dicts — flatten to a single list
    element_sets = {}
    for name, by_type in (mesh.cell_sets_dict or {}).items():
        if isinstance(by_type, dict):
            combined = []
            for arr in by_type.values():
                combined.extend(arr.tolist() if hasattr(arr, 'tolist') else list(arr))
            element_sets[name] = combined
        elif hasattr(by_type, 'tolist'):
            element_sets[name] = by_type.tolist()
        else:
            element_sets[name] = []

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
    # Do NOT apply centroid-based normal flip here: face winding is already
    # guaranteed outward by extract_surface_triangles for VTK-convention meshes
    # (all meshio formats normalise to VTK node ordering).

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

    # Volumetric element type names recognised by the extractor.
    _VOL_TYPES = {
        'tetra', 'tet4', 'tetra10', 'tet10',
        'hexahedron', 'hex8', 'hexahedron20', 'hex20',
        'wedge', 'penta6', 'prism6',
        'pyramid', 'pyra5',
    }
    has_volume = any(t in elements for t in _VOL_TYPES)

    surf_tri_types  = [e for e in ('triangle', 'tri', 'tri3', 'triangle6', 'tri6') if e in elements]
    surf_quad_types = [e for e in ('quad', 'quad4', 'quad8') if e in elements]

    # Use explicit surface elements ONLY when there are no volumetric elements.
    # GMSH mixed meshes include tagged boundary triangles alongside tetra/hex
    # volumes; those boundary groups cover only named surfaces, not the full
    # outer shell, producing holes.  For pure surface meshes (shells) the
    # surface elements ARE the mesh.
    if (surf_tri_types or surf_quad_types) and not has_volume:
        for etype in surf_tri_types:
            triangles.extend([conn[:3] for conn in elements[etype]])
        for etype in surf_quad_types:
            for conn in elements[etype]:
                q = conn[:4]
                triangles.append([q[0], q[1], q[2]])
                triangles.append([q[0], q[2], q[3]])
        return triangles

    # Extract boundary faces from volumetric mesh.
    # Face winding follows VTK outward-normal convention (CCW when viewed from
    # outside → right-hand normal points away from element interior).
    # Verified analytically for each element type.
    from collections import defaultdict
    face_count: dict = defaultdict(int)
    face_nodes: dict = {}

    def _reg(fn):
        key = tuple(sorted(fn))
        face_count[key] += 1
        if key not in face_nodes:
            face_nodes[key] = fn

    # Tet4: face opposite node 3 → (0,2,1) [NOT (0,1,2) which is inward]
    #        face opposite node 2 → (0,1,3)
    #        face opposite node 1 → (0,3,2) [NOT (0,2,3) which is inward]
    #        face opposite node 0 → (1,2,3)
    tet_faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    for etype in ('tetra', 'tet4', 'tetra10', 'tet10'):
        for conn in elements.get(etype, []):
            for f in tet_faces:
                _reg([conn[i] for i in f])

    # Hex8: all faces verified outward by right-hand rule with VTK node layout
    hex_faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    for etype in ('hexahedron', 'hex8', 'hexahedron20', 'hex20'):
        for conn in elements.get(etype, []):
            for f in hex_faces:
                _reg([conn[i] for i in f])

    # Wedge6: bottom triangle (0,2,1) outward [NOT (0,1,2)], top (3,4,5) outward
    for etype in ('wedge', 'penta6', 'prism6'):
        for conn in elements.get(etype, []):
            for f in [(0, 2, 1), (3, 4, 5)]:
                _reg([conn[i] for i in f])
            for f in [(0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]:
                _reg([conn[i] for i in f])

    # Pyramid5: base (0,3,2,1) outward; triangular side faces all outward
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
