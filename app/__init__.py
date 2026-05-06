"""CAE Viewer — Flask application factory."""
import os
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config.config import config as config_dict
from app.extensions import db, migrate, compress


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
            'version': '2.0.0',
            'viewer': '/step-view/',
            'api': {
                'step': '/api/step-view/',
                'cae': '/api/cae/',
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


def _create_tables(app):
    with app.app_context():
        _log = logging.getLogger(__name__)
        for tbl in db.metadata.sorted_tables:
            try:
                tbl.create(db.engine, checkfirst=True)
            except Exception as e:
                _log.warning(f"Could not create table '{tbl.name}': {e}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
