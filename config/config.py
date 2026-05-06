"""Configuration for CAE Viewer."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
_local = Path(__file__).parent.parent / '.env.local'
if _local.exists():
    load_dotenv(_local, override=True)

BASE_DIR = Path(__file__).parent.parent


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'cae-viewer-dev-key')
    APPLICATION_ROOT = os.getenv('APPLICATION_ROOT', '/')

    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/caedb'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    API_HOST = os.getenv('API_HOST', '0.0.0.0')
    API_PORT = int(os.getenv('API_PORT', 8080))

    MAX_UPLOAD_SIZE_MB = int(os.getenv('MAX_UPLOAD_SIZE_MB', 500))
    MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE
    UPLOAD_FOLDER = BASE_DIR / 'data' / 'uploads'
    ALLOWED_EXTENSIONS = {'.stp', '.step', '.p21'}

    STEP_PARSER_TIMEOUT = int(os.getenv('STEP_PARSER_TIMEOUT', 300))

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', str(BASE_DIR / 'logs' / 'cae_viewer.log'))
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    CORS_ORIGINS = os.getenv(
        'CORS_ORIGINS',
        'http://localhost:8080,http://localhost:3000,http://127.0.0.1:8080'
    ).split(',')

    DATA_DIR = BASE_DIR / 'data'
    LOGS_DIR = BASE_DIR / 'logs'

    @classmethod
    def init_app(cls, app):
        for d in [cls.UPLOAD_FOLDER, cls.DATA_DIR, cls.LOGS_DIR]:
            d.mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = True
    LOG_LEVEL = 'DEBUG'


class ProductionConfig(Config):
    DEBUG = False

    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        import logging
        from logging.handlers import RotatingFileHandler
        log_path = Path(cls.LOG_FILE)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(str(log_path), maxBytes=10485760, backupCount=10)
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter(cls.LOG_FORMAT))
            app.logger.addHandler(fh)
        except OSError as e:
            app.logger.warning(f"Could not create log handler at {log_path}: {e}")


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'TEST_DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/caedb_test'
    )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
