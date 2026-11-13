"""Simulation hasher — SHA-256 fingerprint for reproducibility (FASE 7).

The run hash covers exactly what determines the numerical result:

* the *physical inputs* of the solver spec, canonicalized (labels, graph/node ids, tier and other
  bookkeeping removed; numbers normalized; CAD geometry replaced by the content hash of its file),
* the *numerical environment*: FEM kernel version, CAD mesher version and the numeric libraries.

So two runs with the same parameters produce the same hash, even from different graphs, and
any change to a load, material, mesh option or library version changes it. Provenance that does
not affect the numbers (host, git commit, Python patch release) is recorded but not hashed.

Besides the input hash, each finished run stores ``mesh_hash`` (exact bytes of nodes + elements)
and ``result_hash`` (exact bytes of the displacement vector): equal result hashes mean a bitwise
identical result.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import platform
import socket
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Bump when a change in the FEM code changes numerical results for the same inputs
# (element formulation, quadrature, load integration, solver strategy...).
FEM_KERNEL_VERSION = 3

# Top-level spec keys that do not change the numerical result.
NON_PHYSICAL_KEYS = {
    'graph_id', 'tier', 'name', 'description', 'run_id',
    'max_cycles', 'target_error', 'refinement_fraction',   # adaptive loop: hashed separately below
}
# Keys dropped at any depth (presentation only).
# Nested 'geometry_id' in bcs/loads is the GEOMETRY *node* id of the graph, not the CAD file.
LABEL_KEYS = {'label', 'node_id', 'entity_ids', 'unit_label', 'source_node', 'geometry_id',
              'rom_id', 'material_id'}     # references: their content is hashed (rom_hash) or copied in
# Defaults applied by the kernel, made explicit so "omitted" and "explicit default" hash alike.
SPEC_DEFAULTS = {
    'tolerance': 1e-8,
    'material': {'type': 'linear_elastic_isotropic', 'E': 210e9, 'nu': 0.3, 'rho': 7800.0},
    'physics': ['structural'],
}

REPO_ROOT = Path(__file__).resolve().parents[4]


# ── Canonical inputs ──────────────────────────────────────────────────────────

def _normalize(x):
    """Numbers → float (int 210000000000 and 210e9 hash alike), dict keys sorted by json."""
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, (int, float)):
        return float(x)
    if hasattr(x, 'tolist'):                          # numpy arrays / scalars
        return _normalize(x.tolist())
    if isinstance(x, dict):
        return {str(k): _normalize(v) for k, v in x.items() if k not in LABEL_KEYS}
    if isinstance(x, (list, tuple)):
        return [_normalize(v) for v in x]
    return str(x)


def _geometry_identity(geometry_id) -> dict:
    """Content identity of a CAD geometry: the STEP file hash (face indices are stable for it)."""
    try:
        from app.extensions import db
        from app.geometry.models import Geometry
        geo = db.session.get(Geometry, geometry_id)
        if geo is not None:
            return {'step_sha256': geo.sha256, 'units': geo.units}
    except Exception as e:                            # no app context / DB
        logger.debug('geometry identity unavailable for %s: %s', geometry_id, e)
    return {'geometry_id': str(geometry_id)}


def _cae_mesh_identity(mesh_id) -> dict:
    try:
        from app.cae.models.mesh import CAEMesh
        m = CAEMesh.query.filter_by(id=mesh_id).first()
        path = getattr(m, 'file_path', None) if m else None
        if path and Path(path).exists():
            return {'mesh_file_sha256': file_sha256(path)}
    except Exception as e:
        logger.debug('cae mesh identity unavailable for %s: %s', mesh_id, e)
    return {'mesh_id': str(mesh_id)}


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_inputs(spec: dict) -> dict:
    """Physical inputs of a solver spec, in a form whose JSON is stable across equivalent specs."""
    s = copy.deepcopy({k: v for k, v in (spec or {}).items() if k not in NON_PHYSICAL_KEYS})
    for k, v in SPEC_DEFAULTS.items():
        if s.get(k) in (None, [], {}):
            s[k] = copy.deepcopy(v)
    if s.get('max_iterations') is None:
        s.pop('max_iterations', None)
    s.setdefault('mesh_source', 'cantilever' if 'nodes' not in s else 'inline')
    # mesh identity by content, not by database id
    if s.get('mesh_source') == 'geometry' and s.get('geometry_id'):
        s['geometry'] = _geometry_identity(s.pop('geometry_id'))
    if s.get('mesh_source') == 'cae_mesh' and s.get('mesh_id'):
        s['cae_mesh'] = _cae_mesh_identity(s.pop('mesh_id'))
    if 'nodes' in s or 'elements' in s:              # inline mesh: hash the arrays, not their JSON
        import numpy as np
        s['inline_mesh_sha256'] = mesh_hash(np.asarray(s.pop('nodes', []), float),
                                            np.asarray(s.pop('elements', []), np.int64))
    s['physics'] = sorted(s.get('physics') or [])
    out = _normalize(s)
    for k in ('bcs', 'loads'):            # graph edges have no intrinsic order
        if isinstance(out.get(k), list):
            out[k] = sorted(out[k], key=lambda e: json.dumps(e, sort_keys=True))
    return out


def adaptive_inputs(params: dict) -> dict:
    return _normalize({k: params[k] for k in ('max_cycles', 'target_error', 'refinement_fraction')
                       if k in params})


# ── Environment ───────────────────────────────────────────────────────────────

def _version(mod_name: str, attr: str = '__version__') -> str:
    try:
        mod = __import__(mod_name)
        return str(getattr(mod, attr, 'unknown'))
    except ImportError:
        return 'not_installed'


def numerical_environment() -> dict:
    """Everything outside the spec that changes the numbers. Part of the hash."""
    try:
        from app.design.services.fem.cad_mesh import MESHER_VERSION
    except Exception:
        MESHER_VERSION = None
    return {
        'fem_kernel': FEM_KERNEL_VERSION,
        'cad_mesher': MESHER_VERSION,
        'numpy': _version('numpy'),
        'scipy': _version('scipy'),
        'pyamg': _version('pyamg'),
        'gmsh': _version('gmsh', 'GMSH_API_VERSION'),
        'python': '.'.join(platform.python_version_tuple()[:2]),
    }


@lru_cache(maxsize=1)
def _git_commit() -> str | None:
    try:
        out = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=5)
        if out.returncode == 0:
            dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                                   cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
            return out.stdout.strip() + ('-dirty' if dirty.stdout.strip() else '')
    except Exception:
        pass
    return None


def provenance() -> dict:
    """Recorded with the run, not hashed."""
    return {
        'host': socket.gethostname(),
        'platform': platform.platform(),
        'python_full': platform.python_version(),
        'git_commit': _git_commit(),
        'h5py': _version('h5py'),
        'recorded_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }


def environment_diff(recorded: dict, current: dict | None = None) -> dict:
    """{key: [recorded, current]} for numerical-environment entries that differ."""
    current = current or numerical_environment()
    keys = set(recorded or {}) | set(current)
    return {k: [(recorded or {}).get(k), current.get(k)] for k in sorted(keys)
            if (recorded or {}).get(k) != current.get(k)}


# ── Hashes ────────────────────────────────────────────────────────────────────

def _sha(obj) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def compute_run_hash(inputs: dict, env: dict, adaptive: dict | None = None) -> str:
    payload = {'inputs': inputs, 'env': env}
    if adaptive:
        payload['adaptive'] = adaptive
    return _sha(payload)


def mesh_hash(nodes, elements) -> str:
    """Exact bytes of node coordinates (float64) and connectivity (int64)."""
    import numpy as np
    h = hashlib.sha256()
    n = np.ascontiguousarray(nodes, dtype='<f8')
    e = np.ascontiguousarray(elements, dtype='<i8')
    h.update(str(n.shape).encode()); h.update(n.tobytes())
    h.update(str(e.shape).encode()); h.update(e.tobytes())
    return h.hexdigest()


def array_hash(a) -> str:
    import numpy as np
    a = np.ascontiguousarray(a, dtype='<f8')
    return hashlib.sha256(str(a.shape).encode() + a.tobytes()).hexdigest()


def parameter_delta(old: dict | None, new: dict) -> dict:
    """{'material.E': [old, new], ...} between two canonical input dicts."""
    def flat(d, prefix=''):
        out = {}
        if isinstance(d, dict):
            for k, v in d.items():
                out.update(flat(v, f'{prefix}{k}.'))
        elif isinstance(d, list) and d and any(isinstance(v, (dict, list)) for v in d):
            for i, v in enumerate(d):
                out.update(flat(v, f'{prefix}{i}.'))
        else:
            out[prefix[:-1]] = d
        return out
    a, b = flat(old or {}), flat(new or {})
    return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def fingerprint(spec: dict, adaptive: dict | None = None) -> dict:
    """Everything a SimulationRun stores for traceability, computed in the current process."""
    inputs = canonical_inputs(spec)
    env = numerical_environment()
    return {'inputs': inputs, 'environment': env,
            'hash': compute_run_hash(inputs, env, adaptive_inputs(adaptive) if adaptive else None)}


class SimulationHasher:
    """Backward-compatible facade."""

    def fingerprint(self, spec: dict, adaptive: dict | None = None) -> dict:
        return fingerprint(spec, adaptive)

    def compute_mesh_hash(self, nodes, elements) -> str:
        return mesh_hash(nodes, elements)

    def check_reproducible(self, hash_a: str, hash_b: str) -> bool:
        return hashlib.compare_digest(hash_a or '', hash_b or '')
