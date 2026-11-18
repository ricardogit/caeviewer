"""PostgreSQL-backed job queue (Fase 0).

Web process: enqueue() + /api/jobs + listener (NOTIFY → socket.io).
Worker process: ``python -m app.jobs.worker --queues default,solve``.
"""
from app.jobs.queue import enqueue, request_cancel  # noqa: F401
