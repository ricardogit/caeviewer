"""Job ``geo.mesh2d`` (queue default): 2D mesh of a water domain, cached by content key under
DATA_DIR/geodata/meshes/<key>.npz. Gmsh is imported inside the handler (never in the web process)."""
from app.jobs.handlers import handler


@handler('geo.mesh2d', queue='default')
def geo_mesh2d(ctx, payload):
    from app.geodata import service
    spec = payload['spec']
    ctx.progress(5, 'datos geográficos cargados', force=True)
    ctx.check_cancel()
    m, cached = service.get_or_build_mesh(spec, progress=lambda p, msg: ctx.progress(p, msg))
    ctx.progress(100, f'malla 2D: {m.n_nodes:,} nodos, {m.n_elements:,} triángulos', force=True)
    return {'key': m.key, 'stats': m.stats, 'boundary_info': m.boundary_info, 'cached': cached}
