"""Gmsh sessions started off the main thread (gunicorn / socket.io workers): gmsh.initialize() installs a SIGINT
handler, which Python only allows in the main thread → «Malla desde STEP» failed on the server for every file."""
import threading

import pytest

gmsh = pytest.importorskip('gmsh')


def test_initialize_in_worker_thread_and_recover_open_session():
    from app.gmsh_init import initialize
    out = []

    def work():
        try:
            for _ in range(2):                       # twice: no leftover session
                g = initialize(['', '-nopopup'])
                g.model.add('t')
                g.model.occ.addBox(0, 0, 0, 1, 1, 1)
                g.model.occ.synchronize()
                g.model.mesh.generate(3)
                out.append(len(g.model.mesh.getNodes()[0]))
                g.finalize()
            initialize()                              # a session left open is closed by the next initialize
            initialize()
            gmsh.finalize()
        except Exception as e:                       # noqa: BLE001
            out.append(e)
    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert len(out) == 2 and all(isinstance(n, int) and n > 8 for n in out), out
