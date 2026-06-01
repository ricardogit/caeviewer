"""
Deep audit: parse asm1, compact surface, verify each part is renderable.
Simulates exactly what the API sends to the frontend.
"""
import sys, os, importlib.util, logging
logging.basicConfig(level=logging.WARNING)

spec = importlib.util.spec_from_file_location('mesh_parser', r'app\cae\services\mesh_parser.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
import numpy as np

master = r'examples\asm1\00_main.k'
print("=== 1. PARSE ===")
data = mp._parse_lsdyna(master)
nodes = data['nodes']
tris  = data['surface_triangles']
print(f"Nodes: {len(nodes)}, Surface tris: {len(tris)}")
print(f"BBox: X[{data['bounding_box']['min_x']:.1f},{data['bounding_box']['max_x']:.1f}] "
      f"Y[{data['bounding_box']['min_y']:.1f},{data['bounding_box']['max_y']:.1f}] "
      f"Z[{data['bounding_box']['min_z']:.1f},{data['bounding_box']['max_z']:.1f}]")

# -------------------------------------------------------------------
print("\n=== 2. COMPACT SURFACE (same as _compact_surface in routes.py) ===")
seen = {}
node_map = []
for tri in tris:
    for idx in tri:
        if idx not in seen:
            seen[idx] = len(node_map)
            node_map.append(idx)
compact_nodes = [nodes[i] for i in node_map]
remapped = [[seen[idx] for idx in tri] for tri in tris]
print(f"Compact nodes: {len(compact_nodes)} (was {len(nodes)})")
print(f"Remapped tris: {len(remapped)}")
print(f"node_map length: {len(node_map)}")

# Verify all remapped indices are valid
n_compact = len(compact_nodes)
bad = sum(1 for tri in remapped for idx in tri if idx < 0 or idx >= n_compact)
print(f"Bad indices in remapped tris: {bad}")

# -------------------------------------------------------------------
print("\n=== 3. COMPACT NODE BOUNDING BOX (what VTK.js renders) ===")
carr = np.array(compact_nodes)
print(f"Compact BBox: X[{carr[:,0].min():.1f},{carr[:,0].max():.1f}] "
      f"Y[{carr[:,1].min():.1f},{carr[:,1].max():.1f}] "
      f"Z[{carr[:,2].min():.1f},{carr[:,2].max():.1f}]")

# -------------------------------------------------------------------
print("\n=== 4. PER-PART COMPACT NODE RANGES ===")
# Re-parse to get per-part info
entries = mp._parse_include_transforms(master)
all_nodes_global = []
part_info = []  # (fname, transform_label, first_gidx, n_nodes)

for fpath, transform_M in entries:
    if fpath is None or not os.path.exists(fpath): continue
    data2 = mp._read_lsdyna_file_native(fpath)
    pn = data2['nodes']
    if not pn: continue
    first_gidx = len(all_nodes_global)
    local_map = {}
    for nid in sorted(pn.keys()):
        gidx = len(all_nodes_global)
        local_map[nid] = gidx
        xyz = pn[nid]
        if transform_M is not None:
            c4 = transform_M @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
            all_nodes_global.append([float(c4[0]), float(c4[1]), float(c4[2])])
        else:
            all_nodes_global.append(xyz)
    n = len(local_map)
    fname = os.path.basename(fpath)
    t = transform_M[:3,3] if transform_M is not None else np.zeros(3)
    part_info.append((fname, t, first_gidx, n))

# For each part, find its compact indices and check if any triangles reference them
for fname, t, first_gidx, n_nodes in part_info:
    last_gidx = first_gidx + n_nodes
    # Which compact indices correspond to this part's global range?
    part_compact = [seen[g] for g in range(first_gidx, last_gidx) if g in seen]
    if not part_compact:
        status = "NO COMPACT NODES (invisible!)"
    else:
        part_nodes_arr = np.array([compact_nodes[ci] for ci in part_compact])
        ymin, ymax = part_nodes_arr[:,1].min(), part_nodes_arr[:,1].max()
        xmin, xmax = part_nodes_arr[:,0].min(), part_nodes_arr[:,0].max()
        zmin, zmax = part_nodes_arr[:,2].min(), part_nodes_arr[:,2].max()
        status = f"{len(part_compact)} compact nodes | X[{xmin:.1f},{xmax:.1f}] Y[{ymin:.1f},{ymax:.1f}] Z[{zmin:.1f},{zmax:.1f}]"
    label = f"{fname} T=({t[0]:.0f},{t[1]:.0f},{t[2]:.0f})"
    print(f"  {label:<38} -> {status}")

# -------------------------------------------------------------------
print("\n=== 5. VISIBILITY FROM ISO VIEW (camera at +X+Y+Z direction) ===")
cx = (carr[:,0].min() + carr[:,0].max()) / 2
cy = (carr[:,1].min() + carr[:,1].max()) / 2
cz = (carr[:,2].min() + carr[:,2].max()) / 2
# ISO direction vector (normalized)
iso_dir = np.array([1.0, 1.0, 1.0]) / np.sqrt(3)
neg_y_dir = np.array([0.0, -1.0, 0.0])

print(f"Scene center: ({cx:.1f}, {cy:.1f}, {cz:.1f})")
print(f"ISO camera direction (from): +X+Y+Z")
print()
print(f"{'Part':<38} | ISO visible? | -Y visible?")
print("-" * 75)

for fname, t, first_gidx, n_nodes in part_info:
    last_gidx = first_gidx + n_nodes
    part_compact = [seen[g] for g in range(first_gidx, last_gidx) if g in seen]
    if not part_compact:
        print(f"  {fname:<38}  NO SURFACE TRIS")
        continue
    part_nodes_arr = np.array([compact_nodes[ci] for ci in part_compact])
    part_center = part_nodes_arr.mean(axis=0)

    # Is part center "in front" of the scene center from ISO direction?
    # (positive dot product means part is on the camera side)
    diff = part_center - np.array([cx, cy, cz])
    iso_dot  = np.dot(diff, iso_dir)
    negy_dot = np.dot(diff, neg_y_dir)

    ymin, ymax = part_nodes_arr[:,1].min(), part_nodes_arr[:,1].max()
    # From -Y view: camera is at -Y, looking +Y. Part visible if ymin is exposed
    # From +Y+X+Z ISO: camera is above. Part visible if ymax is exposed above base plate.

    label = f"{fname} T=({t[0]:.0f},{t[1]:.0f},{t[2]:.0f})"
    # Rough visibility: a part is "likely hidden from ISO" if its ymax < base plate bottom
    base_y_bottom = -20.0  # from earlier analysis
    iso_vis  = "HIDDEN (below plate)" if ymax < base_y_bottom else "visible"
    negy_vis = "HIDDEN (above plate)" if ymin > 0.0 else "visible"
    print(f"  {label:<38} | {iso_vis:<20} | {negy_vis}")

print()
print("=== SUMMARY ===")
print("Parts hidden from ISO (+Y): bolt heads (Y<-20) and bottom washers (Y<-20)")
print("Parts hidden from -Y:  shaft (Y=35-45) and top parts (Y>0)")
print("No single view shows ALL 18 parts simultaneously.")
print("Solution: use section cut, or implement per-part visibility toggle.")
