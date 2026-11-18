"""Queue operations on the ``jobs`` table.

Channels (Postgres LISTEN/NOTIFY):
  * ``job_enqueued`` — payload = queue name. Wakes idle workers.
  * ``job_events``   — payload = JSON event. The web process forwards these to
                       socket.io (see listener.py). NOTIFY payloads are capped at
                       ~8000 bytes, so events must stay small; full logs go to files.

All timestamps are naive UTC, matching ``BaseModel`` (datetime.utcnow).
"""
import json
import logging
from datetime import datetime

from sqlalchemy import text

from app.extensions import db
from app.jobs.models import Job, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

CH_ENQUEUED = 'job_enqueued'
CH_EVENTS = 'job_events'
_NOTIFY_MAX = 7900
_NOW = "timezone('utc', now())"


# ── Notifications ─────────────────────────────────────────────────────────────

def notify(channel: str, payload, conn=None):
    """pg_notify inside the current transaction (delivered on commit)."""
    if not isinstance(payload, str):
        payload = json.dumps(payload, default=str)
    if len(payload.encode('utf-8')) > _NOTIFY_MAX:
        logger.warning("NOTIFY payload on %s too large (%d bytes) — truncated event sent",
                       channel, len(payload))
        try:
            ev = json.loads(payload)
            payload = json.dumps({k: ev.get(k) for k in ('type', 'job_id', 'status', 'event', 'room')}
                                 | {'truncated': True})
        except Exception:
            payload = json.dumps({'truncated': True})
    stmt = text("SELECT pg_notify(:ch, :pl)")
    (conn or db.session).execute(stmt, {'ch': channel, 'pl': payload})


def job_event(job: Job, type_: str = 'status', **extra) -> dict:
    ev = {
        'type': type_,
        'job_id': str(job.id),
        'kind': job.kind,
        'queue': job.queue,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'simulation_run_id': str(job.simulation_run_id) if job.simulation_run_id else None,
    }
    ev.update(extra)
    return ev


# ── Producer side ─────────────────────────────────────────────────────────────

def enqueue(kind: str, payload: dict | None = None, *, queue: str | None = None,
            priority: int = 0, max_attempts: int = 1, simulation_run_id=None,
            parent_job_id=None, commit: bool = True) -> Job:
    from app.jobs.handlers import get_handler
    spec = get_handler(kind)           # raises KeyError for unknown kinds
    job = Job(kind=kind, queue=queue or spec.queue, payload=payload or {},
              priority=priority, max_attempts=max_attempts,
              simulation_run_id=simulation_run_id, parent_job_id=parent_job_id,
              status='queued', progress=0.0, message='En cola')
    db.session.add(job)
    db.session.flush()
    notify(CH_ENQUEUED, job.queue)
    notify(CH_EVENTS, job_event(job, 'status'))
    if commit:
        db.session.commit()
    return job


def request_cancel(job_id) -> Job | None:
    """Queued jobs are cancelled immediately; running ones get a flag the worker polls."""
    job = db.session.get(Job, job_id)
    if job is None:
        return None
    if job.status in TERMINAL_STATUSES:
        return job
    if job.status == 'queued':
        job.status = 'cancelled'
        job.finished_at = datetime.utcnow()
        job.message = 'Cancelado antes de iniciar'
    else:
        job.cancel_requested = True
        job.message = 'Cancelación solicitada'
    notify(CH_EVENTS, job_event(job, 'status'))
    db.session.commit()
    return job


# ── Worker side ───────────────────────────────────────────────────────────────

_CLAIM_SQL = text(f"""
    UPDATE jobs
       SET status = 'running', worker_id = :worker, attempts = attempts + 1,
           started_at = {_NOW}, heartbeat_at = {_NOW}, updated_at = {_NOW},
           message = 'Iniciando'
     WHERE id = (SELECT id FROM jobs
                  WHERE status = 'queued' AND queue = ANY(:queues)
                  ORDER BY priority DESC, created_at
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1)
 RETURNING id
""")


def claim(queues: list[str], worker_id: str) -> Job | None:
    row = db.session.execute(_CLAIM_SQL, {'queues': list(queues), 'worker': worker_id}).first()
    if row is None:
        db.session.commit()
        return None
    job = db.session.get(Job, row[0])
    notify(CH_EVENTS, job_event(job, 'status', worker_id=worker_id))
    db.session.commit()
    return job


def finish(job: Job, status: str, *, result=None, error: str | None = None, message: str | None = None):
    assert status in TERMINAL_STATUSES
    job.status = status
    job.finished_at = datetime.utcnow()
    job.heartbeat_at = job.finished_at
    if status == 'done':
        job.progress = 100.0
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error
    job.message = message or {'done': 'Completado', 'failed': 'Falló', 'cancelled': 'Cancelado'}[status]
    notify(CH_EVENTS, job_event(job, 'status', error=(error or '')[:1500] or None))
    db.session.commit()


def requeue(job: Job, reason: str):
    """Put a job back (e.g. worker shutting down mid-job)."""
    job.status = 'queued'
    job.worker_id = None
    job.message = reason
    notify(CH_ENQUEUED, job.queue)
    notify(CH_EVENTS, job_event(job, 'status'))
    db.session.commit()


_REAP_SQL = text(f"""
    UPDATE jobs
       SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
           finished_at = CASE WHEN attempts < max_attempts THEN NULL ELSE {_NOW} END,
           error = CASE WHEN attempts < max_attempts THEN error
                        ELSE 'Worker perdido: sin heartbeat durante ' || :secs || ' s' END,
           message = 'Worker perdido (heartbeat vencido)',
           worker_id = NULL, updated_at = {_NOW}
     WHERE status = 'running'
       AND heartbeat_at < {_NOW} - make_interval(secs => :secs)
 RETURNING id
""")


def reap_stale(timeout_s: int = 60) -> int:
    """Requeue (or fail) jobs whose worker stopped sending heartbeats."""
    ids = [r[0] for r in db.session.execute(_REAP_SQL, {'secs': timeout_s})]
    for jid in ids:
        job = db.session.get(Job, jid)
        if job.status == 'queued':
            notify(CH_ENQUEUED, job.queue)
        notify(CH_EVENTS, job_event(job, 'status'))
    db.session.commit()
    if ids:
        logger.warning("Reaped %d stale job(s): %s", len(ids), ids)
    return len(ids)
