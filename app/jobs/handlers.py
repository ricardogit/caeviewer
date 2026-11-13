"""Job handler registry + execution context.

A handler is ``fn(ctx: JobContext, payload: dict) -> dict | None``. It runs in a
worker process (never in the web process). Register with::

    @handler('my.kind', queue='solve')
    def my_job(ctx, payload): ...

Handlers report progress with ``ctx.progress(pct, msg)`` and must call
``ctx.check_cancel()`` between stages so user cancellation is honoured.
"""
import logging
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


@dataclass(frozen=True)
class HandlerSpec:
    kind: str
    fn: Callable
    queue: str
    api_enqueueable: bool      # may be created directly via POST /api/jobs


_REGISTRY: dict[str, HandlerSpec] = {}


def handler(kind: str, *, queue: str = 'default', api_enqueueable: bool = False):
    def deco(fn):
        _REGISTRY[kind] = HandlerSpec(kind, fn, queue, api_enqueueable)
        return fn
    return deco


def get_handler(kind: str) -> HandlerSpec:
    _load_builtin_handlers()
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise KeyError(f"Unknown job kind '{kind}'. Known: {sorted(_REGISTRY)}") from None


def registered_kinds() -> dict[str, HandlerSpec]:
    _load_builtin_handlers()
    return dict(_REGISTRY)


_loaded = False


def _load_builtin_handlers():
    global _loaded
    if not _loaded:
        _loaded = True
        from app.jobs import builtin_handlers  # noqa: F401  (registers on import)


class JobContext:
    """Passed to handlers. Progress → DB row + NOTIFY job_events → socket.io."""

    _MIN_INTERVAL = 0.25   # s between progress writes (forced ones bypass)

    def __init__(self, job, cancel_event, log_path=None):
        self.job = job
        self.job_id = str(job.id)
        self._cancel_event = cancel_event
        self._last = 0.0
        self.log_path = log_path
        self.log = logging.getLogger(f'job.{job.kind}')

    # -- progress -----------------------------------------------------------
    def progress(self, pct: float | None = None, message: str | None = None, *, force=False, **extra):
        now = time.monotonic()
        if not force and now - self._last < self._MIN_INTERVAL:
            return
        self._last = now
        from app.extensions import db
        from app.jobs.queue import notify, job_event, CH_EVENTS
        if pct is not None:
            self.job.progress = float(max(0.0, min(100.0, pct)))
        if message is not None:
            self.job.message = message[:500]
        notify(CH_EVENTS, job_event(self.job, 'progress', **extra))
        db.session.commit()
        if message:
            self.log.info("[%5.1f%%] %s", self.job.progress, message)

    def emit_socket(self, event: str, data: dict, room: str | None = None):
        """Forward an arbitrary socket.io event through the web process (e.g. solver_progress)."""
        from app.extensions import db
        from app.jobs.queue import notify, CH_EVENTS
        notify(CH_EVENTS, {'type': 'socket', 'job_id': self.job_id, 'event': event,
                           'data': data, 'room': room})
        db.session.commit()

    # -- cancellation -------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancel(self):
        if self._cancel_event.is_set():
            raise JobCancelled()


class SocketIOProxy:
    """Duck-types ``flask_socketio.SocketIO.emit`` so existing code that takes a
    ``socketio`` argument (FEMKernel.solve_async) runs unchanged inside a worker."""

    _MIN_INTERVAL = 0.2    # throttle per-iteration solver_progress floods

    def __init__(self, ctx: JobContext):
        self.ctx = ctx
        self._last = 0.0
        self.last_error = None

    def emit(self, event, data=None, room=None, **_kw):
        data = data or {}
        if event == 'solver_error':
            self.last_error = data.get('message')
        if event == 'solver_progress':
            if self.ctx.cancelled:
                raise JobCancelled()
            now = time.monotonic()
            if now - self._last < self._MIN_INTERVAL and data.get('iter') not in (0, None):
                return
            self._last = now
            msg = data.get('status')
            if data.get('iter') is not None and data.get('residual') is not None:
                try:
                    msg = f"iter {data['iter']} · residual {float(data['residual']):.2e}"
                except (TypeError, ValueError):
                    pass
            self.ctx.progress(data.get('percent'), msg, force=True)
        self.ctx.emit_socket(event, data, room)
