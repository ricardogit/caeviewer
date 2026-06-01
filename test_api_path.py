import sys
sys.path.insert(0, '/app')
from app import create_app
from app.cae.models import CAEMesh
from app.cae.services.mesh_parser import parse_mesh

app = create_app()
with app.app_context():
    m = CAEMesh.query.filter_by(id='86c36571-7bf9-4693-89d6-bb22b351c78b').first()
    print('file_path in DB:', m.file_path)
    import os
    print('file exists:', os.path.exists(m.file_path))

    data = parse_mesh(m.file_path)
    parts = data.get('parts', [])
    print(f'Parts from parse_mesh: {len(parts)}')
    for p in parts:
        print(f"  {p['name']}: tri_count={p['tri_count']}")
