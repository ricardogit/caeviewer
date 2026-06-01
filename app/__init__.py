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
    _create_tables(app)

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


def _create_tables(app):
    """Create any tables not yet managed by Alembic (fail-safe only).
    Alembic migrations are the authoritative schema source — this is a
    best-effort fallback for tables that weren't captured in a migration.
    Circular-FK tables (step_file_headers ↔ step_view_files) are skipped
    silently because Alembic handles them correctly.
    """
    import warnings
    with app.app_context():
        _log = logging.getLogger(__name__)
        circular = {'step_file_headers', 'step_view_files'}
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                tables = list(db.metadata.sorted_tables)
            except Exception:
                tables = list(db.metadata.tables.values())
        for tbl in tables:
            if tbl.name in circular:
                continue   # managed by Alembic migration
            try:
                tbl.create(db.engine, checkfirst=True)
            except Exception as e:
                _log.debug(f"Table '{tbl.name}' skipped: {e}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
