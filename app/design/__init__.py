"""Design module — new-generation CAE with integrated design graph."""

__version__ = '1.0.0'


def register_design_blueprints(app):
    """Register all 7 Design-module blueprints."""
    from app.design.api import (
        graph_routes,
        solver_routes,
        material_routes,
        topology_routes,
        rom_routes,
        validation_routes,
        traceability_routes,
    )
    # strict_slashes=False allows both /api/design/graph and /api/design/graph/
    app.register_blueprint(graph_routes.bp,        url_prefix='/api/design/graph', strict_slashes=False)
    app.register_blueprint(solver_routes.bp,       url_prefix='/api/design/solver', strict_slashes=False)
    app.register_blueprint(material_routes.bp,     url_prefix='/api/design/material', strict_slashes=False)
    app.register_blueprint(topology_routes.bp,     url_prefix='/api/design/topology', strict_slashes=False)
    app.register_blueprint(rom_routes.bp,          url_prefix='/api/design/rom', strict_slashes=False)
    app.register_blueprint(validation_routes.bp,   url_prefix='/api/design/validation', strict_slashes=False)
    app.register_blueprint(traceability_routes.bp, url_prefix='/api/design/traceability', strict_slashes=False)
    print(f"[OK] Design module v{__version__} — 7 blueprints at /api/design/*")
    return app
