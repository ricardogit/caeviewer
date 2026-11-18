"""Web-side bridge: Postgres ``LISTEN job_events`` → socket.io.

Started once per web process from run.py (never in workers or CLI commands).
Event forwarding:
  * type in (status, progress) → ``job_update`` broadcast + to room ``job:<id>``
  * type == socket            → the wrapped event (e.g. solver_progress) to its room
"""
import json
import logging
import select
import threading
import time

import psycopg2

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def start_job_listener(app, socketio):
    global _started
    with _lock:
        if _started or not app.config.get('JOBS_LISTENER_ENABLED', True):
            return
        _started = True
    from app.jobs.worker import _dsn
    dsn = _dsn(app.config['SQLALCHEMY_DATABASE_URI'])
    t = threading.Thread(target=_loop, args=(dsn, socketio), daemon=True, name='job-listener')
    t.start()
    logger.info("Job listener started (LISTEN job_events -> socket.io)")


def _loop(dsn, socketio):
    from app.jobs.queue import CH_EVENTS
    backoff = 1
    while True:
        conn = None
        try:
            conn = psycopg2.connect(dsn)
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            conn.cursor().execute(f"LISTEN {CH_EVENTS};")
            backoff = 1
            while True:
                if select.select([conn], [], [], 30) == ([], [], []):
                    conn.cursor().execute("SELECT 1")     # keepalive / detect dead conn
                    continue
                conn.poll()
                while conn.notifies:
                    n = conn.notifies.pop(0)
                    _dispatch(socketio, n.payload)
        except Exception as e:
            logger.warning("Job listener connection lost (%s); retrying in %ss", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def _dispatch(socketio, payload: str):
    try:
        ev = json.loads(payload)
    except ValueError:
        return
    try:
        if ev.get('type') == 'socket':
            socketio.emit(ev['event'], ev.get('data') or {}, room=ev.get('room'))
        else:
            socketio.emit('job_update', ev)          # broadcast (no auth scoping yet)
    except Exception as e:
        logger.warning("socket emit failed: %s", e)
