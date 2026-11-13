"""Job model — PostgreSQL-backed work queue (Fase 0).

Workers claim jobs with ``SELECT ... FOR UPDATE SKIP LOCKED`` (see queue.py),
so several worker processes can share one table without double-processing.
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import BaseModel

JOB_STATUSES = ('queued', 'running', 'done', 'failed', 'cancelled')
TERMINAL_STATUSES = ('done', 'failed', 'cancelled')


class Job(BaseModel):
    __tablename__ = 'jobs'

    kind          = Column(String(64), nullable=False)            # e.g. dummy, fem.solve, geometry.import
    queue         = Column(String(32), nullable=False, default='default')
    status        = Column(String(16), nullable=False, default='queued')
    priority      = Column(Integer, nullable=False, default=0)    # higher first

    payload       = Column(JSONB, nullable=False, default=dict)
    result        = Column(JSONB)
    error         = Column(Text)

    progress      = Column(Float, nullable=False, default=0.0)    # 0..100
    message       = Column(String(500))

    attempts      = Column(Integer, nullable=False, default=0)
    max_attempts  = Column(Integer, nullable=False, default=1)
    cancel_requested = Column(Boolean, nullable=False, default=False)

    worker_id     = Column(String(128))
    heartbeat_at  = Column(DateTime)
    started_at    = Column(DateTime)
    finished_at   = Column(DateTime)
    log_uri       = Column(String(1000))

    simulation_run_id = Column(UUID(as_uuid=True), ForeignKey('simulation_runs.id', ondelete='SET NULL'))
    parent_job_id     = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='SET NULL'))

    __table_args__ = (
        Index('ix_jobs_claim', 'queue', 'status', 'priority', 'created_at'),
        Index('ix_jobs_simulation_run_id', 'simulation_run_id'),
    )

    def to_dict(self):
        d = super().to_dict()
        d.pop('payload', None)          # can be large (inline meshes); fetch via /api/jobs/<id>?payload=1
        return d
