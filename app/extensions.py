"""Flask extensions — shared singletons for the entire app."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
compress = Compress()
# explicit async_mode='threading' avoids deprecated eventlet
# allow_other_threads=True for GMSH signal() calls from worker threads
socketio = SocketIO(
    async_mode='threading',
    allow_other_threads=True,
    cors_allowed_origins='*'
)
