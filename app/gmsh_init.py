"""Thread-safe Gmsh start-up.

``gmsh.initialize()`` installs a SIGINT handler by default (``interruptible=True``), and Python only allows that in the
main thread: inside a gunicorn / socket.io worker thread it raises ``ValueError: signal only works in main thread`` and
leaves Gmsh half initialised (the next call warns "Gmsh has already been initialized"). Every Gmsh session in the app
goes through :func:`initialize`.
"""
from __future__ import annotations

import threading


def initialize(argv=None, read_config_files: bool = True):
    """``gmsh.initialize`` that works off the main thread and recovers a session left open by a failed call."""
    import gmsh
    try:
        if gmsh.isInitialized():
            gmsh.finalize()
    except Exception:  # noqa: BLE001 — a broken half-initialised state must not block the new session
        pass
    gmsh.initialize(list(argv or []), readConfigFiles=read_config_files,
                    interruptible=threading.current_thread() is threading.main_thread())
    return gmsh
