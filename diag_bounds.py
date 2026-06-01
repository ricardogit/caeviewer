"""Check per-part bounding boxes after transforms."""
import sys, os, importlib.util, logging
logging.basicConfig(level=logging.WARNING)

spec = importlib.util.spec_from_file_location('mesh_parser', r'app\cae\services\mesh_parser.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
import numpy as np

master = r'examples\asm1\00_main.k'
entries = mp._parse_include_transforms(master)

print("Part                               | X min    X max  | Y min    Y max  | Z min    Z max")
print("-" * 90)

for fpath, transform_M in entries:
    if fpath is None or not os.path.exists(fpath): continue
    data = mp._read_lsdyna_file_native(fpath)
    part_nodes = data['nodes']
    if not part_nodes: continue

    coords = []
    for nid, xyz in part_nodes.items():
        if transform_M is not None:
            c4 = transform_M @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
            coords.append([c4[0], c4[1], c4[2]])
        else:
            coords.append(xyz)

    arr = np.array(coords)
    fname = os.path.basename(fpath)
    t = transform_M[:3,3] if transform_M is not None else np.zeros(3)
    label = f"{fname} T=({t[0]:.0f},{t[1]:.0f},{t[2]:.0f})"
    print(f"{label:<35} | {arr[:,0].min():7.1f}  {arr[:,0].max():7.1f} | "
          f"{arr[:,1].min():7.1f}  {arr[:,1].max():7.1f} | "
          f"{arr[:,2].min():7.1f}  {arr[:,2].max():7.1f}")
