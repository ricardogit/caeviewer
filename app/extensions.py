"""Flask extensions — shared singletons for the entire app."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
compress = Compress()
# allow_other_threads=True allows GMSH signal() calls from worker threads
socketio = SocketIO(allow_other_threads=True, cors_allowed_origins='*')
