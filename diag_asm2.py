"""Check surface triangles per part instance."""
import sys, os, importlib.util, logging
logging.basicConfig(level=logging.WARNING, format='%(message)s')

spec = importlib.util.spec_from_file_location(
    'mesh_parser', r'app\cae\services\mesh_parser.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

import numpy as np
from collections import defaultdict

master = r'examples\asm1\00_main.k'
entries = mp._parse_include_transforms(master)

# Re-implement the per-part surface count
all_nodes = []
per_part_elem_ranges = []   # (start_elem_gidx, n_elems, fname, transform_summary)
all_elements_hex = []       # list of [n0..n7]
part_labels = []            # one label per element

for fpath, transform_M in entries:
    if fpath is None or not os.path.exists(fpath):
        continue
    data = mp._read_lsdyna_file_native(fpath)
    part_nodes = data['nodes']
    if not part_nodes and not data['solids'] and not data['shells']:
        continue

    local_map = {}
    for nid in sorted(part_nodes.keys()):
        gidx = len(all_nodes)
        local_map[nid] = gidx
        xyz = part_nodes[nid]
        if transform_M is not None:
            c4 = transform_M @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
            all_nodes.append([float(c4[0]), float(c4[1]), float(c4[2])])
        else:
            all_nodes.append(xyz)

    fname = os.path.basename(fpath)
    t = transform_M[:3,3] if transform_M is not None else np.zeros(3)
    label = f"{fname} T=({t[0]:.0f},{t[1]:.0f},{t[2]:.0f})"

    def _safe(nid, _m=local_map):
        return _m.get(nid, -1)

    n_hex_before = len(all_elements_hex)
    for row in data['solids']:
        nonzero = [v for v in row if v != 0]
        unique = list(dict.fromkeys(nonzero))
        if len(unique) == 8:
            idxs = [_safe(u) for u in unique]
            if -1 not in idxs:
                all_elements_hex.append(idxs)
                part_labels.append(label)
    n_hex_added = len(all_elements_hex) - n_hex_before
    print(f"  {label}: {len(local_map)} nodes, {n_hex_added} hexes")

coords = np.array(all_nodes, dtype=np.float64)
n_pts = len(coords)

# Extract surface faces (count=1) and track which part they belong to
from collections import defaultdict
face_count = defaultdict(int)
face_part  = {}
hex_faces  = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]

for elem_idx, conn in enumerate(all_elements_hex):
    lbl = part_labels[elem_idx]
    for f in hex_faces:
        key = tuple(sorted(conn[i] for i in f))
        face_count[key] += 1
        if key not in face_part:
            face_part[key] = lbl

# Count surface triangles per part
surface_per_part = defaultdict(int)
total_surf = 0
for key, count in face_count.items():
    if count == 1:
        lbl = face_part[key]
        surface_per_part[lbl] += 2   # each quad → 2 triangles
        total_surf += 2

print(f"\n=== Surface triangles per part ===")
for lbl, ntri in sorted(surface_per_part.items()):
    print(f"  {lbl}: {ntri} tris")
print(f"\nTotal: {total_surf}")
