"""Flask extensions — shared singletons for the entire app."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_compress import Compress
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
compress = Compress()
# allow_other_threads=True enables signal() calls in background worker threads (needed for GMSH)
socketio = SocketIO(allow_other_threads=True)
