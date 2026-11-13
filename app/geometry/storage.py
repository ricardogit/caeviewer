"""Content-addressed file storage under DATA_DIR.

URIs stored in the DB are *relative* to DATA_DIR so that the web process
(Windows host or container) and the workers (containers with the shared
volume mounted at /app/data) resolve the same file.
"""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from flask import current_app

STEP_EXTENSIONS = {'.stp', '.step', '.p21'}


def data_dir() -> Path:
    return Path(current_app.config['DATA_DIR'])


def abs_path(rel_uri: str) -> Path:
    p = (data_dir() / rel_uri).resolve()
    if data_dir().resolve() not in p.parents:
        raise ValueError(f'URI escapes DATA_DIR: {rel_uri}')
    return p


def store_step_upload(file_storage) -> tuple[str, str, int]:
    """Stream an uploaded STEP to geometry/files/<sha[:2]>/<sha>.step.

    Returns (relative_uri, sha256, size_bytes). Identical content is stored once.
    """
    ext = Path(file_storage.filename or '').suffix.lower()
    if ext not in STEP_EXTENSIONS:
        raise ValueError(f"Extensión no soportada '{ext}'. Use: {sorted(STEP_EXTENSIONS)}")
    tmp_dir = data_dir() / 'geometry' / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    h, size = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(dir=tmp_dir, suffix=ext)
    try:
        with os.fdopen(fd, 'wb') as out:
            while chunk := file_storage.stream.read(1 << 20):
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        if size == 0:
            raise ValueError('Archivo vacío')
        sha = h.hexdigest()
        rel = f'geometry/files/{sha[:2]}/{sha}.step'
        dest = data_dir() / rel
        if dest.exists():
            os.unlink(tmp)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(tmp, dest)
        return rel, sha, size
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
