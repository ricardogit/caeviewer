"""Job ``geo.mesh2d`` (queue default): 2D mesh of a water domain, cached by content key under
DATA_DIR/geodata/meshes/<key>.npz. Gmsh is imported inside the handler (never in the web process)."""
from app.jobs.handlers import handler


@handler('geo.mesh2d', queue='default')
def geo_mesh2d(ctx, payload):
    from app.geodata import service
    from app.geodata.mesh2d import build_mesh
    spec = payload['spec']
    inp = service.mesh_inputs(spec)
    path = service.mesh_path(inp['key'])
    if path.exists():
        from app.geodata.mesh2d import Mesh2D
        m = Mesh2D.from_bytes(path.read_bytes())
        return {'key': inp['key'], 'stats': m.stats, 'cached': True}
    ctx.progress(5, 'datos geográficos cargados', force=True)
    ctx.check_cancel()
    m = build_mesh(spec, land=inp['land'], depth_sampler=inp['depth_sampler'], zones=inp['zones'],
                   points=inp['points'], key=inp['key'], progress=lambda p, msg: ctx.progress(p, msg))
    ctx.check_cancel()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(m.to_bytes())
    tmp.replace(path)
    ctx.progress(100, f'malla 2D: {m.n_nodes:,} nodos, {m.n_elements:,} triángulos', force=True)
    return {'key': inp['key'], 'stats': m.stats, 'boundary_info': m.boundary_info, 'cached': False}
