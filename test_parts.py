import importlib.util, logging
logging.basicConfig(level=logging.WARNING)
spec = importlib.util.spec_from_file_location('mesh_parser', r'app\cae\services\mesh_parser.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
data = mp._parse_lsdyna(r'examples\asm1\00_main.k')
parts = data.get('parts', [])
print(f'Parts: {len(parts)}')
for p in parts:
    print(f"  {p['name']}: tri_start={p['tri_start']}, tri_count={p['tri_count']}")
print(f"Total tris in parts: {sum(p['tri_count'] for p in parts)}")
print(f"Surface tris total:  {data['surface_triangle_count']}")
