"""CAE Viewer — Flask application factory."""
import os
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config.config import config as config_dict
from app.extensions import db, migrate, compress, socketio


def create_app(config_name=None):
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_dict[config_name])
    config_dict[config_name].init_app(app)

    # Ensure upload size is always current
    _max_mb = int(os.getenv('MAX_UPLOAD_SIZE_MB', 500))
    app.config['MAX_CONTENT_LENGTH'] = _max_mb * 1024 * 1024
    print(f"[INFO] MAX_CONTENT_LENGTH = {_max_mb} MB ({app.config['MAX_CONTENT_LENGTH']:,} bytes)")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    compress.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*')

    CORS(app, resources={
        r"/api/*": {
            "origins": app.config['CORS_ORIGINS'],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
            "max_age": 3600,
        }
    })

    _setup_logging(app)
    _register_models(app)
    _register_blueprints(app)
    _register_frontend(app)
    _register_error_handlers(app)
    _register_socketio_events()
    _warn_if_schema_behind(app)

    return app


def _setup_logging(app):
    log_file = app.config['LOG_FILE']
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, app.config['LOG_LEVEL']),
        format=app.config['LOG_FORMAT'],
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


def _register_models(app):
    """Import all models so Alembic / create_all can detect them."""
    with app.app_context():
        from app.models import Part, STEPFileHeader, STEPEntity, STEPEntityEdge  # noqa
        try:
            from app.step_view_pro.models import (  # noqa
                STEPFile, FileComparison, FileVersion, CacheEntry, PerformanceMetric
            )
        except ImportError as e:
            print(f"[WARN] step_view_pro models: {e}")
        try:
            from app.cae.models import CAEMesh, CAEField  # noqa
        except ImportError as e:
            print(f"[WARN] CAE models: {e}")
        from app.jobs.models import Job  # noqa
        from app.auth.models import User, Project  # noqa
        from app.geometry.models import Geometry, GeometryEntity  # noqa
        from app.catalog.models import SolverCatalog  # noqa
        try:
            from app.design.models import (  # noqa
                DesignGraph, DesignNode, DesignEdge,
                PhysicsConfig, MaterialModel, SimulationRun,
                FieldResult, ExperimentalRecord, SimExperimentCorrelation,
            )
        except ImportError as e:
            print(f"[WARN] Design models: {e}")


def _register_blueprints(app):
    # STEP-View Pro: 12 core blueprints + files endpoint
    from app.step_view_pro import register_step_view_blueprints
    from app.step_view_pro.backend.api.files_routes import bp as files_bp
    register_step_view_blueprints(app)
    app.register_blueprint(files_bp, url_prefix='/api/step-view')

    # CAE
    from app.cae.api.cae_routes import bp as cae_bp
    app.register_blueprint(cae_bp, url_prefix='/api/cae')

    from app.cae.api.ai_routes import bp as cae_ai_bp
    app.register_blueprint(cae_ai_bp, url_prefix='/api/cae')

    from app.cae.api.mesh_from_step_routes import bp as cae_from_step_bp
    app.register_blueprint(cae_from_step_bp, url_prefix='/api/cae')

    # Job queue + auth (Engineering Hub, Fase 0)
    from app.jobs.api import bp as jobs_bp
    app.register_blueprint(jobs_bp, url_prefix='/api/jobs', strict_slashes=False)
    from app.auth import init_auth
    init_auth(app)
    from app.geometry.api import bp as geometry_bp
    app.register_blueprint(geometry_bp, url_prefix='/api/geometry', strict_slashes=False)
    from app.catalog import init_catalog
    init_catalog(app)

    # Design module — new-generation CAE (FASE 0+)
    try:
        from app.design import register_design_blueprints
        register_design_blueprints(app)
    except ImportError as e:
        print(f"[WARN] Design module: {e}")

    print("[OK] All blueprints registered")


def _register_frontend(app):
    """Serve the built React SPA from frontend/dist/."""
    import pathlib
    dist_dir = str(pathlib.Path(__file__).parent.parent / 'frontend' / 'dist')

    @app.route('/step-view/', defaults={'path': ''})
    @app.route('/step-view/<path:path>')
    def serve_spa(path):
        if path and os.path.exists(os.path.join(dist_dir, path)):
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, 'index.html')

    @app.route('/')
    def index():
        return jsonify({
            'name': 'CAE Viewer',
            'version': '3.0.0',
            'viewer': '/step-view/',
            'api': {
                'step':   '/api/step-view/',
                'cae':    '/api/cae/',
                'design': '/api/design/',
            },
        }), 200


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(413)
    def too_large(e):
        limit_mb = app.config.get('MAX_UPLOAD_SIZE_MB', 500)
        return jsonify({'error': f'File too large. Max {limit_mb} MB'}), 413

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f'Internal error: {e}')
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500


def _register_socketio_events():
    """Register WebSocket event handlers for the FEM solver rooms."""
    from flask_socketio import join_room, leave_room

    @socketio.on('join_run')
    def handle_join(data):
        room = data.get('run_id')
        if room:
            join_room(room)

    @socketio.on('leave_run')
    def handle_leave(data):
        room = data.get('run_id')
        if room:
            leave_room(room)

    @socketio.on('connect')
    def handle_connect():
        pass   # connection acknowledged automatically

    @socketio.on('disconnect')
    def handle_disconnect():
        pass


def _warn_if_schema_behind(app):
    """Alembic is the only schema mechanism (run `flask db upgrade`).
    The old create_all fallback was removed; we only warn if the DB is behind."""
    if app.config.get('TESTING'):
        return
    try:
        from alembic.script import ScriptDirectory
        from alembic.migration import MigrationContext
        import pathlib
        mig_dir = pathlib.Path(__file__).parent.parent / 'migrations'
        cfg = app.extensions['migrate'].migrate.get_config(str(mig_dir))
        heads = set(ScriptDirectory.from_config(cfg).get_heads())
        with app.app_context(), db.engine.connect() as conn:
            current = set(MigrationContext.configure(conn).get_current_heads())
        if current != heads:
            logging.getLogger(__name__).warning(
                "Database schema %s is not at migration head %s — run `flask db upgrade`",
                sorted(current) or '<empty>', sorted(heads))
    except Exception as e:
        logging.getLogger(__name__).debug("schema check skipped: %s", e)
