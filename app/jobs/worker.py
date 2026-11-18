"""Job worker process.

    python -m app.jobs.worker --queues default,solve [--id my-worker]

Waits on ``LISTEN job_enqueued`` (with a periodic fallback poll), claims jobs
with SKIP LOCKED, runs the registered handler, and keeps a heartbeat thread
alive that also picks up cancellation requests. Never imported by the web app.
"""
import argparse
import logging
import os
import select
import signal
import socket
import threading
import time
import traceback
import uuid
from pathlib import Path

import psycopg2
from sqlalchemy.engine import make_url
from sqlalchemy import text

logger = logging.getLogger('app.jobs.worker')

HEARTBEAT_S = 3          # also bounds cancellation latency
STALE_AFTER_S = 60
REAP_EVERY_S = 30
IDLE_POLL_S = 5


def _dsn(sqlalchemy_url: str) -> str:
    url = make_url(sqlalchemy_url).set(drivername='postgresql')
    return url.render_as_string(hide_password=False)


class _Heartbeat(threading.Thread):
    """Updates heartbeat_at and mirrors cancel_requested into a threading.Event."""

    def __init__(self, engine, job_id, cancel_event):
        super().__init__(daemon=True, name=f'hb-{job_id}')
        self.engine, self.job_id, self.cancel_event = engine, job_id, cancel_event
        self._stop = threading.Event()

    def run(self):
        while not self._stop.wait(HEARTBEAT_S if not self.cancel_event.is_set() else 1):
            try:
                with self.engine.begin() as c:
                    row = c.execute(text(
                        "UPDATE jobs SET heartbeat_at = timezone('utc', now()) "
                        "WHERE id = :id AND status = 'running' RETURNING cancel_requested"),
                        {'id': self.job_id}).first()
                if row and row[0]:
                    self.cancel_event.set()
            except Exception as e:     # keep going; a missed beat is not fatal
                logger.warning("heartbeat failed for %s: %s", self.job_id, e)

    def poll_now(self):
        """Fast cancel check used at start (cheap, single query)."""
        try:
            with self.engine.begin() as c:
                row = c.execute(text("SELECT cancel_requested FROM jobs WHERE id = :id"),
                                {'id': self.job_id}).first()
            if row and row[0]:
                self.cancel_event.set()
        except Exception:
            pass

    def stop(self):
        self._stop.set()


class Worker:
    def __init__(self, app, queues, worker_id):
        self.app = app
        self.queues = queues
        self.worker_id = worker_id
        self.stopping = False
        self.jobs_dir = Path(app.config.get('JOBS_DATA_DIR') or Path(app.config['DATA_DIR']) / 'jobs')
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # -- lifecycle ----------------------------------------------------------
    def request_stop(self, *_):
        if not self.stopping:
            logger.info("Stop requested — finishing current job, then exiting")
        self.stopping = True

    def run_forever(self):
        from app.extensions import db
        from app.jobs import queue as q

        with self.app.app_context():
            listen = psycopg2.connect(_dsn(self.app.config['SQLALCHEMY_DATABASE_URI']))
            listen.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            listen.cursor().execute(f"LISTEN {q.CH_ENQUEUED};")
            logger.info("Worker %s listening on queues %s", self.worker_id, self.queues)
            last_reap = 0.0
            try:
                while not self.stopping:
                    if time.monotonic() - last_reap > REAP_EVERY_S:
                        last_reap = time.monotonic()
                        try:
                            q.reap_stale(STALE_AFTER_S)
                        except Exception as e:
                            db.session.rollback()
                            logger.warning("reap failed: %s", e)

                    job = q.claim(self.queues, self.worker_id)
                    if job is not None:
                        self._execute(job)
                        continue

                    # idle: wait for NOTIFY or poll timeout
                    if select.select([listen], [], [], IDLE_POLL_S) != ([], [], []):
                        listen.poll()
                        listen.notifies.clear()
            finally:
                listen.close()
                db.session.remove()

    # -- execution ----------------------------------------------------------
    def _execute(self, job):
        from app.extensions import db
        from app.jobs import queue as q
        from app.jobs.handlers import get_handler, JobContext, JobCancelled

        job_id = str(job.id)
        log_path = self.jobs_dir / f'{job_id}.log'
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        root = logging.getLogger()
        root.addHandler(fh)
        job.log_uri = str(log_path)
        db.session.commit()

        cancel_event = threading.Event()
        hb = _Heartbeat(db.engine, job_id, cancel_event)
        hb.poll_now()
        hb.start()
        ctx = JobContext(job, cancel_event, log_path)
        t0 = time.monotonic()
        logger.info("> job %s kind=%s attempt=%d", job_id, job.kind, job.attempts)
        try:
            spec = get_handler(job.kind)
            result = spec.fn(ctx, dict(job.payload or {}))
            q.finish(job, 'done', result=result if isinstance(result, dict) else {'value': result})
            logger.info("OK job %s done in %.2fs", job_id, time.monotonic() - t0)
        except JobCancelled:
            db.session.rollback()
            db.session.refresh(job)
            q.finish(job, 'cancelled')
            logger.info("CANCELLED job %s", job_id)
        except KeyboardInterrupt:
            db.session.rollback()
            db.session.refresh(job)
            q.requeue(job, 'Worker interrumpido; reencolado')
            self.stopping = True
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("FAILED job %s: %s\n%s", job_id, e, tb)
            db.session.rollback()
            db.session.refresh(job)
            if job.attempts < job.max_attempts:
                q.requeue(job, f'Reintento tras error: {e}'[:500])
            else:
                q.finish(job, 'failed', error=f'{type(e).__name__}: {e}\n\n{tb}')
        finally:
            hb.stop()
            root.removeHandler(fh)
            fh.close()
            db.session.remove()


def main(argv=None):
    p = argparse.ArgumentParser(description='CAE Viewer job worker')
    p.add_argument('--queues', default=os.getenv('WORKER_QUEUES', 'default'),
                   help='comma-separated queue names (default: %(default)s)')
    p.add_argument('--id', default=os.getenv('WORKER_ID'))
    args = p.parse_args(argv)

    os.environ['CAE_ROLE'] = 'worker'
    from app import create_app
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    with app.app_context():
        from app.extensions import db
        db.engine.echo = False      # DevelopmentConfig echoes SQL; too noisy for a worker

    worker_id = args.id or f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}'
    queues = [s.strip() for s in args.queues.split(',') if s.strip()]
    w = Worker(app, queues, worker_id)
    signal.signal(signal.SIGTERM, w.request_stop)
    try:
        w.run_forever()
    except KeyboardInterrupt:
        pass
    logger.info("Worker %s exited", worker_id)


if __name__ == '__main__':
    main()
