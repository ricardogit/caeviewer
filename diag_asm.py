"""Standalone diagnostic — imports mesh_parser directly, no Flask."""
import sys, os, importlib.util, logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

# Load mesh_parser without triggering app/__init__.py
spec = importlib.util.spec_from_file_location(
    'mesh_parser', r'app\cae\services\mesh_parser.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

import numpy as np

master = r'examples\asm1\00_main.k'
entries = mp._parse_include_transforms(master)

print(f"\n=== *INCLUDE_TRANSFORM entries: {len(entries)} total ===")
from collections import Counter
fname_count = Counter(os.path.basename(p) for p, _ in entries if p)
for f, c in sorted(fname_count.items()):
    print(f"  {f}: {c}x")

non_id = [(os.path.basename(p), M) for p, M in entries
          if p and M is not None and not np.allclose(M, np.eye(4))]
print(f"\nNon-identity transforms: {len(non_id)}")
for fname, M in non_id:
    t = M[:3, 3]
    print(f"  {fname}: T=({t[0]:.2f},{t[1]:.2f},{t[2]:.2f})")

print("\n=== Per-file node/element counts ===")
node_totals = {}
for fpath, transform_M in entries:
    if fpath is None or not os.path.exists(fpath):
        continue
    data = mp._read_lsdyna_file_native(fpath)
    bname = os.path.basename(fpath)
    node_totals.setdefault(bname, []).append((len(data['nodes']), len(data['solids']), len(data['shells'])))

for bname, instances in sorted(node_totals.items()):
    n, s, sh = instances[0]
    print(f"  {bname}: {n} nodes, {s} solids, {sh} shells  x{len(instances)} instances")

print("\n=== Full parse ===")
data = mp._parse_lsdyna(master)
print(f"Nodes: {data['node_count']}")
print(f"Elements: {data['element_count']}")
print(f"Element types: {data['element_types']}")
print(f"Surface tris: {data.get('surface_triangle_count', 0)}")
bb = data['bounding_box']
print(f"BBox: X[{bb['min_x']:.1f},{bb['max_x']:.1f}] "
      f"Y[{bb['min_y']:.1f},{bb['max_y']:.1f}] "
      f"Z[{bb['min_z']:.1f},{bb['max_z']:.1f}]")
