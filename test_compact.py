"""Quick test of _compact_surface logic."""
import sys, importlib.util
spec = importlib.util.spec_from_file_location('routes', r'app\cae\api\cae_routes.py')
# Can't import routes without Flask; inline the function directly.

def _compact_surface(nodes, surface_triangles):
    seen = {}
    node_map = []
    for tri in surface_triangles:
        for idx in tri:
            if idx not in seen:
                seen[idx] = len(node_map)
                node_map.append(idx)
    compact_nodes = [nodes[i] for i in node_map]
    remapped = [[seen[idx] for idx in tri] for tri in surface_triangles]
    return compact_nodes, remapped, node_map

# Simulate 6 nodes, surface only uses nodes 0,2,4
nodes = [[i, i, i] for i in range(6)]  # 6 nodes
surface_tris = [[0, 2, 4], [2, 4, 0]]  # only reference nodes 0, 2, 4

compact, remapped, nmap = _compact_surface(nodes, surface_tris)
assert len(compact) == 3, f"expected 3 compact nodes, got {len(compact)}"
assert nmap == [0, 2, 4], f"node_map wrong: {nmap}"
assert compact == [[0,0,0],[2,2,2],[4,4,4]], f"compact nodes wrong: {compact}"
assert remapped == [[0,1,2],[1,2,0]], f"remapped tris wrong: {remapped}"

print("All assertions passed.")
print(f"Compression ratio: {len(nodes)}/{len(compact)} = {len(nodes)/len(compact):.1f}x")

# Estimate for asm1
asm_nodes = 434339
asm_surf_unique = 108000  # estimated unique surface nodes
print(f"\nasm1 estimate: {asm_nodes} -> ~{asm_surf_unique} nodes = {asm_nodes/asm_surf_unique:.1f}x reduction")
approx_original_mb = (asm_nodes * 3 * 10 + 215856 * 3 * 6) / 1e6
approx_compact_mb  = (asm_surf_unique * 3 * 10 + 215856 * 3 * 6 + asm_surf_unique * 6) / 1e6
print(f"JSON size: {approx_original_mb:.1f} MB -> {approx_compact_mb:.1f} MB")
