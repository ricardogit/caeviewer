"""Simulation hasher — SHA-256 fingerprint for reproducibility.

Implemented: FASE 0 (usable immediately, needed by SimulationRun).
"""
import hashlib
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SimulationHasher:
    """Compute a deterministic SHA-256 hash of all simulation inputs.

    Same hash = same result (given identical software versions).
    The hash covers: graph state, solver config, mesh statistics,
    constitutive models, and Python library versions.
    """

    def compute_hash(self, graph_state: dict, solver_config: dict,
                     mesh_stats: dict, sw_versions: dict = None) -> str:
        """Return hex SHA-256 of all inputs. Available immediately (FASE 0).

        Args:
            graph_state:   serialised graph (nodes, edges, properties)
            solver_config: { type, tol, max_iter, nonlinear_method, physics }
            mesh_stats:    { n_nodes, n_elements, element_types, geometry_hash }
            sw_versions:   { numpy, scipy } versions (auto-detected if None)
        """
        if sw_versions is None:
            sw_versions = self._get_sw_versions()

        payload = {
            'graph': graph_state,
            'solver': solver_config,
            'mesh': mesh_stats,
            'sw': sw_versions,
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def compute_mesh_hash(self, nodes, elements) -> str:
        """SHA-256 of raw mesh geometry. Available immediately (FASE 0)."""
        payload = {
            'nodes': [list(map(float, n)) for n in nodes],
            'elements': [list(map(int, e)) for e in elements],
        }
        canonical = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]

    def check_reproducible(self, hash_a: str, hash_b: str) -> bool:
        """Return True if two hashes are identical (constant-time comparison)."""
        return hashlib.compare_digest(hash_a, hash_b)

    def _get_sw_versions(self) -> dict:
        """Auto-detect installed package versions."""
        versions = {}
        for pkg in ('numpy', 'scipy', 'meshio', 'gmsh'):
            try:
                mod = __import__(pkg)
                versions[pkg] = getattr(mod, '__version__', 'unknown')
            except ImportError:
                versions[pkg] = 'not_installed'
        return versions
