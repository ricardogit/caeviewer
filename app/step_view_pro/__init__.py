"""STEP-View Pro — standalone CAE Viewer integration."""

__version__ = '2.0.0'


def register_step_view_blueprints(app):
    """Register all STEP-View Pro blueprints.

    The entity-graph blueprints (graph, features, pmi, analysis) were removed on 2026-11-14: the Part 21 ->
    relational storage they read lives in CAPP and was never ported (not needed for simulation)."""
    from app.step_view_pro.backend.api import (
        viewer_routes, comparison_routes, geometry_routes,
        measurement_routes, export_routes, upload_routes,
        performance_routes, markup_routes,
    )

    app.register_blueprint(viewer_routes.bp,       url_prefix='/api/step-view')
    app.register_blueprint(upload_routes.bp,       url_prefix='/api/step-view/upload')
    app.register_blueprint(geometry_routes.bp,     url_prefix='/api/step-view/geometry')
    app.register_blueprint(measurement_routes.bp,  url_prefix='/api/step-view/measurement')
    app.register_blueprint(export_routes.bp,       url_prefix='/api/step-view/export')
    app.register_blueprint(comparison_routes.bp,   url_prefix='/api/step-view/comparison')
    app.register_blueprint(performance_routes.bp,  url_prefix='/api/step-view/performance')
    app.register_blueprint(markup_routes.bp,       url_prefix='/api/step-view/markup')

    print(f"[OK] STEP-View Pro v{__version__} — 8 API blueprints registered at /api/step-view/*")
    return app
