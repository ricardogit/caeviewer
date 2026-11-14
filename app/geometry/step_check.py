"""Cheap STEP validity check (no pythonOCC): reject files that cannot produce any shape before they reach the DB.

A STEP file the viewer/mesher can use has B-rep topology in its DATA section: a solid (MANIFOLD_SOLID_BREP,
BREP_WITH_VOIDS, FACETED_BREP) or at least a shell (CLOSED_SHELL, OPEN_SHELL, SHELL_BASED_SURFACE_MODEL). A file
with only loose geometry (points, curves, bare CYLINDRICAL_SURFACE …) makes OpenCASCADE report "no transferable
shapes" — the viewer's "El archivo STEP no contiene geometría sólida válida". Scanned in chunks, so large files
cost one sequential read.
"""
from __future__ import annotations

import re

SOLID_ENTITIES = ('MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS', 'FACETED_BREP')
SHELL_ENTITIES = ('CLOSED_SHELL', 'OPEN_SHELL', 'SHELL_BASED_SURFACE_MODEL')
_TOPO = re.compile(rb'(?<![A-Z0-9_])(' + b'|'.join(e.encode() for e in SOLID_ENTITIES + SHELL_ENTITIES)
                   + rb')\s*\(')   # also inside complex instances #n=( … MANIFOLD_SOLID_BREP(…) … )
_CHUNK = 4 << 20
_OVERLAP = 64

INVALID_STEP_MESSAGE = ('El archivo STEP no contiene geometría sólida válida (sin sólidos ni cáscaras B-rep, solo '
                        'geometría suelta). Suba un STEP con cuerpos sólidos.')


def step_problem(path) -> str | None:
    """None if the file looks usable, else a user-facing reason (Spanish)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(_CHUNK)
            if not head.strip():
                return 'El archivo STEP está vacío.'
            if b'ISO-10303-21' not in head[:4096].upper():
                return 'No es un archivo STEP (falta la cabecera ISO-10303-21).'
            buf, seen_data = head, False
            while True:
                up = buf.upper()
                seen_data = seen_data or b'DATA;' in up
                if _TOPO.search(up):
                    return None
                nxt = f.read(_CHUNK)
                if not nxt:
                    break
                buf = buf[-_OVERLAP:] + nxt
    except OSError as e:
        return f'No se pudo leer el archivo STEP: {e}'
    if not seen_data:
        return 'Archivo STEP incompleto (sin sección DATA).'
    return INVALID_STEP_MESSAGE
