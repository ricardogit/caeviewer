"""
Mesh parser for CAE formats.

LS-DYNA (.k/.key) and Abaqus (.inp) are handled by native Python parsers
with correct per-part node-ID offsetting.  All other formats (VTK, GMSH,
Nastran, MED, Exodus, XDMF …) are delegated to meshio.
"""
import logging
import os

logger = logging.getLogger(__name__)

try:
    import meshio
    import numpy as np
    MESHIO_AVAILABLE = True
except ImportError:
    MESHIO_AVAILABLE = False
    np = None  # type: ignore
    logger.warning("meshio not installed — non-LSDYNA/INP formats disabled. Run: pip install meshio numpy")

# numpy is needed even without meshio (LS-DYNA / Abaqus parsers use it)
if np is None:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        pass


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


def _read_lsdyna_file_native(fpath: str) -> dict:
    """
    Native Python reader for a single LS-DYNA keyword file.
    Returns {'nodes': {nid: [x,y,z]}, 'solids': [[n1..n8], ...],
             'shells': [...], 'tshells': [...], 'beams': [...]}

    Handles:
    - Fixed-width (I10/F16) and free-format (space/comma separated) data lines
    - Comment lines starting with $ anywhere in a section
    - *ELEMENT_SOLID two-line format: (eid,pid) then (n1..n10)
    - *ELEMENT_SHELL / *ELEMENT_TSHELL / *ELEMENT_BEAM single-line format
    """
    nodes:   dict = {}    # nid (int) → [x, y, z]
    solids:  list = []    # [[n1..n8], ...]   hex8 / tet4 / wedge / pyramid
    shells:  list = []    # [[n1..n4], ...]
    tshells: list = []    # [[n1..n8], ...]
    beams:   list = []    # [[n1, n2], ...]

    MODE_NONE    = 0
    MODE_NODE    = 1
    MODE_SOLID   = 2   # 2-line per element: (eid,pid) then nodes
    MODE_SHELL   = 3   # 1-line per element
    MODE_TSHELL  = 4   # 2-line per element (same as SOLID)
    MODE_BEAM    = 5   # 1-line per element

    mode        = MODE_NONE
    solid_phase = 0   # 0 = expecting eid_line, 1 = expecting node_line

    def _vals(line: str) -> list:
        """Parse data line → list of strings (handles comma and space delimiters)."""
        if ',' in line:
            return [t.strip() for t in line.split(',') if t.strip()]
        return line.split()

    try:
        with open(fpath, 'r', errors='ignore') as fh:
            for raw in fh:
                s = raw.rstrip('\n').rstrip('\r')
                stripped = s.strip()

                # Skip blank and comment lines (but keep mode for SOLID phase)
                if not stripped or stripped.startswith('$'):
                    continue

                # Keyword line
                if stripped.startswith('*'):
                    upper = stripped.upper()
                    # Reset solid phase on every new keyword
                    solid_phase = 0
                    if upper.startswith('*NODE') and not upper.startswith('*NODE_'):
                        mode = MODE_NODE
                    elif upper.startswith('*ELEMENT_SOLID'):
                        mode = MODE_SOLID
                        solid_phase = 0
                    elif upper.startswith('*ELEMENT_TSHELL'):
                        mode = MODE_TSHELL
                        solid_phase = 0
                    elif upper.startswith('*ELEMENT_SHELL') or upper.startswith('*ELEMENT_SH'):
                        mode = MODE_SHELL
                    elif upper.startswith('*ELEMENT_BEAM'):
                        mode = MODE_BEAM
                    else:
                        mode = MODE_NONE
                    continue

                # ── Data line ─────────────────────────────────────────────────
                vals = _vals(stripped)
                if not vals:
                    continue

                if mode == MODE_NODE:
                    if len(vals) >= 4:
                        try:
                            nid = int(vals[0])
                            x, y, z = float(vals[1]), float(vals[2]), float(vals[3])
                            nodes[nid] = [x, y, z]
                        except (ValueError, IndexError):
                            pass

                elif mode == MODE_SOLID or mode == MODE_TSHELL:
                    if solid_phase == 0:
                        # eid, pid line — skip, just advance phase
                        solid_phase = 1
                    else:
                        # n1..n10 line
                        solid_phase = 0
                        try:
                            row = [int(v) for v in vals]
                        except ValueError:
                            continue
                        if mode == MODE_SOLID:
                            solids.append(row)
                        else:
                            tshells.append(row)

                elif mode == MODE_SHELL:
                    # eid, pid, n1, n2, n3[, n4, ...]
                    if len(vals) >= 5:
                        try:
                            row = [int(v) for v in vals[2:6]]  # n1..n4 (may be 3)
                            shells.append(row)
                        except ValueError:
                            pass

                elif mode == MODE_BEAM:
                    # eid, pid, n1, n2[, ...]
                    if len(vals) >= 4:
                        try:
                            row = [int(vals[2]), int(vals[3])]
                            beams.append(row)
                        except ValueError:
                            pass

    except OSError as e:
        logger.warning(f"LS-DYNA: cannot read {fpath}: {e}")

    return {'nodes': nodes, 'solids': solids, 'shells': shells,
            'tshells': tshells, 'beams': beams}


def _parse_lsdyna(file_path: str) -> dict:
    """
    Parse a LS-DYNA keyword file (.k/.key) using native Python.

    *INCLUDE / *INCLUDE_TRANSFORM directives are resolved by
    _parse_include_transforms() which preserves duplicate part instances and
    embeds the per-instance TRANSL/ROTATE transform matrix.  Each file is
    read with _read_lsdyna_file_native(); node IDs are per-file-local and are
    mapped to global indices with a per-file offset so different instances of
    the same part file never collide.
    """
    import numpy as np

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

    # Returns [(abs_filepath, 4x4_matrix_or_None), ...]
    file_entries = _parse_include_transforms(file_path)

    # ZIP fallback: add any .k/.key inside assy_* dir not already listed
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if os.path.basename(parent_dir).startswith('assy_'):
        import glob as _glob
        known = set(p for p, _ in file_entries if p)
        for pat in ('**/*.k', '**/*.key'):
            for f in _glob.glob(os.path.join(parent_dir, pat), recursive=True):
                ap = os.path.abspath(f)
                if ap not in known:
                    file_entries.append((ap, None))
                    known.add(ap)
                    logger.info(f"LS-DYNA assy fallback: +{os.path.basename(ap)}")

    logger.info(
        f"LS-DYNA: {len(file_entries)} entries "
        f"({len(set(p for p,_ in file_entries if p))} unique files)"
    )

    global_coords: list = []
    elements:      dict = {}
    element_types: dict = {}
    total_elements: int = 0
    part_node_ranges: list = []  # [(label, first_gidx, last_gidx)]

    def _add(etype: str, batch: list) -> None:
        nonlocal total_elements
        if not batch:
            return
        elements.setdefault(etype, []).extend(batch)
        element_types[etype] = element_types.get(etype, 0) + len(batch)
        total_elements += len(batch)

    for fpath, transform_M in file_entries:
        if fpath is None or not os.path.exists(fpath):
            logger.warning(f"LS-DYNA: skipping missing file: {fpath}")
            continue

        data = _read_lsdyna_file_native(fpath)
        part_nodes = data['nodes']   # {local_nid: [x,y,z]}

        if not part_nodes and not data['solids'] and not data['shells']:
            continue

        first_gidx = len(global_coords)

        # Build per-file local_nid → global_idx map
        local_map: dict = {}
        if part_nodes:
            for nid in sorted(part_nodes.keys()):
                gidx = len(global_coords)
                local_map[nid] = gidx
                xyz = part_nodes[nid]
                if transform_M is not None:
                    c4 = transform_M @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
                    global_coords.append([float(c4[0]), float(c4[1]), float(c4[2])])
                else:
                    global_coords.append(xyz)

        # Record this part's node range for per-part surface grouping
        last_gidx = len(global_coords)
        if last_gidx > first_gidx:
            t_vec = transform_M[:3, 3] if transform_M is not None else np.zeros(3)
            fname_base = os.path.basename(fpath)
            plabel = (f"{fname_base} T=({t_vec[0]:.0f},{t_vec[1]:.0f},{t_vec[2]:.0f})"
                      if transform_M is not None else fname_base)
            part_node_ranges.append((plabel, first_gidx, last_gidx))

        def _safe(nid: int, _m=local_map) -> int:
            return _m.get(nid, -1)

        n_nodes = len(local_map)
        logger.info(f"  {os.path.basename(fpath)}: {n_nodes} nodes, "
                    f"{len(data['solids'])} solids, {len(data['shells'])} shells")

        # ── Solids (hex8 / tet4 / wedge / pyramid) ────────────────────────────
        # *ELEMENT_SOLID nodes line: [n1..n8, n9, n10] where n9/n10=0 for hex8
        # or [n1..n4, n4, n4, n4, n4, 0, 0] for tet4 (degenerate).
        hex_b, tet_b, wedge_b, pyr_b = [], [], [], []
        for row in data['solids']:
            nonzero = [v for v in row if v != 0]
            unique  = list(dict.fromkeys(nonzero))   # dedup, preserve order
            n = len(unique)
            if n == 4:
                idxs = [_safe(u) for u in unique]
                if -1 not in idxs:
                    tet_b.append(idxs)
            elif n == 5:
                idxs = [_safe(u) for u in unique]
                if -1 not in idxs:
                    pyr_b.append(idxs)
            elif n == 6:
                idxs = [_safe(u) for u in unique]
                if -1 not in idxs:
                    wedge_b.append(idxs)
            elif n >= 7:
                idxs = [_safe(u) for u in unique[:8]]
                if len(idxs) == 8 and -1 not in idxs:
                    hex_b.append(idxs)
        _add('hexahedron', hex_b)
        _add('tetra',      tet_b)
        _add('wedge',      wedge_b)
        _add('pyramid',    pyr_b)

        # ── Thick shells → hex ────────────────────────────────────────────────
        ts_b = []
        for row in data['tshells']:
            nz = [v for v in row if v != 0]
            idxs = [_safe(u) for u in nz[:8]]
            if len(idxs) == 8 and -1 not in idxs:
                ts_b.append(idxs)
        _add('hexahedron', ts_b)

        # ── Shells ────────────────────────────────────────────────────────────
        quads, tris = [], []
        for row in data['shells']:
            if len(row) >= 4:
                n1, n2, n3, n4 = row[:4]
                if n4 == 0 or n4 == n3:
                    idxs = [_safe(n) for n in (n1, n2, n3)]
                    if -1 not in idxs:
                        tris.append(idxs)
                else:
                    idxs = [_safe(n) for n in (n1, n2, n3, n4)]
                    if -1 not in idxs:
                        quads.append(idxs)
            elif len(row) == 3:
                idxs = [_safe(n) for n in row]
                if -1 not in idxs:
                    tris.append(idxs)
        _add('triangle', tris)
        _add('quad',     quads)

        # ── Beams ─────────────────────────────────────────────────────────────
        beam_b = []
        for row in data['beams']:
            idxs = [_safe(row[0]), _safe(row[1])]
            if -1 not in idxs:
                beam_b.append(idxs)
        _add('line', beam_b)

    if not global_coords:
        raise ValueError(
            f"No se encontraron nodos en {len(file_entries)} archivo(s) LS-DYNA. "
            "Si es un ensamble multi-archivo, sube todos los .k en un ZIP."
        )

    coords = np.array(global_coords, dtype=np.float64)
    bbox = {
        'min_x': float(coords[:, 0].min()), 'max_x': float(coords[:, 0].max()),
        'min_y': float(coords[:, 1].min()), 'max_y': float(coords[:, 1].max()),
        'min_z': float(coords[:, 2].min()), 'max_z': float(coords[:, 2].max()),
    }

    surface_triangles = extract_surface_triangles(elements, coords)

    # Group surface triangles by part so the frontend can render per-part actors
    parts_info: list = []
    if part_node_ranges and surface_triangles:
        node_part = np.full(len(global_coords), -1, dtype=np.int32)
        for pidx, (plabel, lo, hi) in enumerate(part_node_ranges):
            node_part[lo:hi] = pidx
        from collections import defaultdict as _ddict
        tri_by_part: dict = _ddict(list)
        for tri in surface_triangles:
            p = int(node_part[tri[0]]) if tri and 0 <= tri[0] < len(node_part) else -1
            tri_by_part[p].append(tri)
        sorted_tris: list = []
        for pidx, (plabel, lo, hi) in enumerate(part_node_ranges):
            tri_start = len(sorted_tris)
            ptris = tri_by_part.get(pidx, [])
            sorted_tris.extend(ptris)
            if ptris:
                parts_info.append({'name': plabel, 'tri_start': tri_start, 'tri_count': len(ptris)})
        sorted_tris.extend(tri_by_part.get(-1, []))  # unassigned triangles (if any)
        surface_triangles = sorted_tris

    return {
        'nodes':                  global_coords,
        'elements':               elements,
        'surface_triangles':      surface_triangles,
        'node_sets':              {},
        'element_sets':           {},
        'node_fields':            {},
        'element_fields':         {},
        'time_steps':             [0],
        'bounding_box':           bbox,
        'node_count':             len(global_coords),
        'element_count':          total_elements,
        'element_types':          element_types,
        'surface_triangle_count': len(surface_triangles),
        'format':                 'k',
        'field_names':            [],
        'recommended_solvers':    recommend_solvers(element_types),
        'quality':                compute_mesh_quality(elements, coords),
        'parts':                  parts_info,
    }


_ABAQUS_ELEM_MAP = {
    # 3-D solids
    'C3D8':   'hexahedron',  'C3D8R':  'hexahedron',  'C3D8H':  'hexahedron',
    'C3D8I':  'hexahedron',  'C3D8RH': 'hexahedron',
    'C3D20':  'hexahedron20','C3D20R': 'hexahedron20','C3D20RH':'hexahedron20',
    'C3D4':   'tetra',       'C3D4H':  'tetra',
    'C3D10':  'tetra10',     'C3D10M': 'tetra10',     'C3D10MH':'tetra10',
    'C3D6':   'wedge',       'C3D6H':  'wedge',
    'C3D5':   'pyramid',
    # Shells
    'S4':     'quad',        'S4R':    'quad',        'S4RS': 'quad',
    'S4RT':   'quad',        'SC8R':   'quad',
    'S3':     'triangle',    'S3R':    'triangle',    'STRI3':'triangle',
    # Beams
    'B31':    'line',        'B31H':   'line',        'B32':  'line',
    'T2D2':   'line',
}


def _parse_abaqus_inp(file_path: str) -> dict:
    """
    Parse an Abaqus .inp file with correct per-part node-ID offsetting.

    meshio collapses all parts into a single node dict keyed by local part ID,
    so every part overwrites the previous one (last-part wins).  Element
    connectivity still uses the original local IDs → wrong coordinates +
    phantom shared faces → assembly appears as a single flat plate.

    This parser reads each *Part section separately, accumulates a per-part
    global_offset = len(global_nodes_so_far), builds a local_id→global_idx
    map, and translates element connectivity before appending.
    """
    import numpy as np

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Abaqus file not found: {file_path}")

    global_nodes: list  = []
    global_elements: dict = {}
    global_etypes:  dict  = {}
    total_elements: int   = 0

    # ── Line reader with continuation support ────────────────────────────────
    def _iter_data_lines(fh):
        """Yield (stripped, keyword_flag) handling Abaqus comma-continuation."""
        pending = ''
        for raw in fh:
            s = raw.strip()
            if not s or s.startswith('**'):
                if pending:
                    yield pending, False
                    pending = ''
                continue
            if s.startswith('*'):
                if pending:
                    yield pending, False
                    pending = ''
                yield s, True
                continue
            # data line — handle continuation
            if s.endswith(','):
                pending += s
            else:
                full = pending + s
                pending = ''
                yield full, False

        if pending:
            yield pending, False

    # ── State machine ─────────────────────────────────────────────────────────
    MODE_NONE = 0; MODE_NODE = 1; MODE_ELEM = 2

    part_nodes:     dict = {}  # local_id (int) → [x, y, z]
    part_local_map: dict = {}  # local_id (int) → global_idx (built on first *Element)
    nodes_committed: list = [False]  # mutable flag
    elem_etype:     str  = ''
    mode:           int  = MODE_NONE
    in_part:        bool = False

    def _commit_nodes():
        """Commit part_nodes to global_nodes and build part_local_map."""
        if nodes_committed[0] or not part_nodes:
            return
        for lid in sorted(part_nodes.keys()):
            part_local_map[lid] = len(global_nodes)
            global_nodes.append(part_nodes[lid])
        nodes_committed[0] = True

    try:
        with open(file_path, 'r', errors='ignore') as fh:
            for line, is_kw in _iter_data_lines(fh):
                if is_kw:
                    upper = line.upper()
                    mode = MODE_NONE

                    if upper.startswith('*PART'):
                        in_part = True
                        part_nodes.clear()
                        part_local_map.clear()
                        nodes_committed[0] = False
                    elif upper.startswith('*END PART'):
                        _commit_nodes()   # commit any nodes not yet committed
                        in_part = False
                    elif upper.startswith('*NODE') and not upper.startswith('*NODE OUTPUT') \
                            and not upper.startswith('*NSET'):
                        if in_part:
                            mode = MODE_NODE
                    elif upper.startswith('*ELEMENT') and not upper.startswith('*ELEMENT OUTPUT') \
                            and not upper.startswith('*ELSET'):
                        if in_part:
                            # Commit nodes on first *Element encounter
                            _commit_nodes()
                            etype_raw = ''
                            for tok in line.split(','):
                                tok = tok.strip()
                                if tok.upper().startswith('TYPE='):
                                    etype_raw = tok.split('=', 1)[1].strip().upper()
                                    break
                            elem_etype = _ABAQUS_ELEM_MAP.get(etype_raw, '')
                            if elem_etype:
                                mode = MODE_ELEM
                    continue  # done processing keyword line

                # ── Data line ─────────────────────────────────────────────────
                if mode == MODE_NODE and in_part:
                    toks = [p.strip() for p in line.split(',')]
                    if len(toks) >= 4:
                        try:
                            nid = int(toks[0])
                            x, y, z = float(toks[1]), float(toks[2]), float(toks[3])
                            part_nodes[nid] = [x, y, z]
                        except (ValueError, IndexError):
                            pass

                elif mode == MODE_ELEM and in_part and elem_etype:
                    toks = [p.strip() for p in line.split(',')]
                    # toks[0] = element_id, toks[1:] = local node IDs
                    try:
                        local_ids = [int(t) for t in toks[1:] if t]
                    except ValueError:
                        continue
                    global_idxs = [part_local_map.get(lid, -1) for lid in local_ids]
                    if -1 in global_idxs:
                        continue
                    if elem_etype not in global_elements:
                        global_elements[elem_etype] = []
                        global_etypes[elem_etype]   = 0
                    global_elements[elem_etype].append(global_idxs)
                    global_etypes[elem_etype] += 1
                    total_elements += 1

    except OSError as e:
        raise RuntimeError(f"Cannot read Abaqus file: {e}") from e

    # Safety: commit any un-flushed last part
    _commit_nodes()

    if not global_nodes:
        raise ValueError("No nodes found in Abaqus file.")

    coords = np.array(global_nodes, dtype=np.float64)
    bbox = {
        'min_x': float(coords[:, 0].min()), 'max_x': float(coords[:, 0].max()),
        'min_y': float(coords[:, 1].min()), 'max_y': float(coords[:, 1].max()),
        'min_z': float(coords[:, 2].min()), 'max_z': float(coords[:, 2].max()),
    }

    surface_triangles = extract_surface_triangles(global_elements, coords)

    logger.info(
        f"Abaqus assembly: {len(global_nodes):,} nodes, {total_elements:,} elements, "
        f"{len(surface_triangles):,} surface triangles"
    )

    return {
        'nodes':                  global_nodes,
        'elements':               global_elements,
        'surface_triangles':      surface_triangles,
        'node_sets':              {},
        'element_sets':           {},
        'node_fields':            {},
        'element_fields':         {},
        'time_steps':             [0],
        'bounding_box':           bbox,
        'node_count':             len(global_nodes),
        'element_count':          total_elements,
        'element_types':          global_etypes,
        'surface_triangle_count': len(surface_triangles),
        'format':                 'inp',
        'field_names':            [],
        'recommended_solvers':    recommend_solvers(global_etypes),
        'quality':                compute_mesh_quality(global_elements, coords),
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

    # Route Abaqus assembly files to dedicated parser that handles per-part
    # node-ID offsetting (meshio collapses all parts into a single node dict,
    # causing node collisions and face cancellation in multi-part assemblies).
    if os.path.splitext(file_path)[1].lower() == '.inp':
        return _parse_abaqus_inp(file_path)

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

    surface_triangles = extract_surface_triangles(elements, mesh.points)

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


def extract_surface_triangles(elements: dict, nodes_np=None) -> list:
    """
    Extract triangles suitable for WebGL surface rendering.

    Priority:
    1. If explicit triangle/quad surface elements exist (e.g. GMSH boundary mesh), use them.
    2. Otherwise extract boundary faces from volumetric elements (tet, hex, wedge, pyramid).

    When nodes_np (Nx3 numpy array) is provided, each boundary face's winding is
    verified against the centroid of the element that owns it — this corrects
    inverted/negative-Jacobian elements that analytical winding cannot handle.
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
    from collections import defaultdict
    import numpy as _np
    face_count: dict = defaultdict(int)
    face_nodes: dict = {}
    face_elem_conn: dict = {}   # key → element connectivity (for centroid correction)

    def _reg(fn, elem_conn=None):
        key = tuple(sorted(fn))
        face_count[key] += 1
        if key not in face_nodes:
            face_nodes[key] = fn
            if nodes_np is not None and elem_conn is not None:
                face_elem_conn[key] = elem_conn

    # Tet4: face opposite node 3 → (0,2,1) [NOT (0,1,2) which is inward]
    #        face opposite node 2 → (0,1,3)
    #        face opposite node 1 → (0,3,2) [NOT (0,2,3) which is inward]
    #        face opposite node 0 → (1,2,3)
    tet_faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    for etype in ('tetra', 'tet4', 'tetra10', 'tet10'):
        for conn in elements.get(etype, []):
            for f in tet_faces:
                _reg([conn[i] for i in f], conn)

    # Hex8: all faces verified outward by right-hand rule with VTK node layout
    hex_faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    for etype in ('hexahedron', 'hex8', 'hexahedron20', 'hex20'):
        for conn in elements.get(etype, []):
            for f in hex_faces:
                _reg([conn[i] for i in f], conn)

    # Wedge6: bottom triangle (0,2,1) outward [NOT (0,1,2)], top (3,4,5) outward
    for etype in ('wedge', 'penta6', 'prism6'):
        for conn in elements.get(etype, []):
            for f in [(0, 2, 1), (3, 4, 5)]:
                _reg([conn[i] for i in f], conn)
            for f in [(0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]:
                _reg([conn[i] for i in f], conn)

    # Pyramid5: base (0,3,2,1) outward; triangular side faces all outward
    for etype in ('pyramid', 'pyra5'):
        for conn in elements.get(etype, []):
            _reg([conn[i] for i in (0, 3, 2, 1)], conn)
            for f in [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]:
                _reg([conn[i] for i in f], conn)

    n_pts = len(nodes_np) if nodes_np is not None else 0

    for key, count in face_count.items():
        if count != 1:
            continue
        fn = list(face_nodes[key])

        # Per-element centroid winding correction: verify the face normal points
        # away from the element centroid.  Handles inverted/negative-Jacobian
        # elements where the analytical winding above would be wrong.
        if nodes_np is not None and key in face_elem_conn:
            try:
                ec = face_elem_conn[key]
                ec_arr = _np.array(ec, dtype=_np.int32)
                valid_ec = ec_arr[(ec_arr >= 0) & (ec_arr < n_pts)]
                if len(valid_ec) >= 4:
                    elem_c = nodes_np[valid_ec].mean(axis=0)
                    p0 = nodes_np[fn[0]]
                    p1 = nodes_np[fn[1]]
                    p2 = nodes_np[fn[2]]
                    face_c = (p0 + p1 + p2) / 3.0
                    normal = _np.cross(p1 - p0, p2 - p0)
                    if _np.dot(normal, face_c - elem_c) < 0:
                        fn = fn[::-1]
            except Exception:
                pass

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
