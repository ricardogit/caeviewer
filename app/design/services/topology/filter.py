"""Density filter and Heaviside projection for topology optimization (FASE 4).

Unstructured meshes: the filter is volume weighted,

    ρ̃_i = Σ_j H_ij v_j x_j / Σ_j H_ij v_j,      H_ij = max(0, r − |c_i − c_j|)

with c the element centroids. This is the density filter of Bruns & Tortorelli / Bourdin
(consistent sensitivities, unlike Sigmund's heuristic sensitivity filter). The projection is the
smooth Heaviside of Wang, Lazarov & Sigmund (2011).
"""
from __future__ import annotations

import logging

import numpy as np
import scipy.sparse as sp

logger = logging.getLogger(__name__)


class DensityFilter:
    """Linear, volume-weighted density filter (prevents checkerboards and mesh dependence)."""

    def __init__(self, filter_radius: float):
        if not filter_radius or filter_radius <= 0:
            raise ValueError('filter_radius must be > 0')
        self.filter_radius = float(filter_radius)
        self._H = None          # weights, (n, n) CSR
        self._v = None          # element volumes
        self._s = None          # row sums of H·diag(v)

    def build_weight_matrix(self, centroids: np.ndarray, volumes: np.ndarray):
        """Pre-compute the weight matrix once (KD-tree neighbour search)."""
        from scipy.spatial import cKDTree
        tree = cKDTree(centroids)
        D = tree.sparse_distance_matrix(tree, self.filter_radius, output_type='coo_matrix')
        # sparse_distance_matrix omits zero distances: add the diagonal explicitly
        n = len(centroids)
        rows = np.concatenate([D.row, np.arange(n)])
        cols = np.concatenate([D.col, np.arange(n)])
        w = np.concatenate([self.filter_radius - D.data, np.full(n, self.filter_radius)])
        H = sp.csr_matrix((w, (rows, cols)), shape=(n, n))
        H.sum_duplicates()
        self._H = H
        self._v = np.asarray(volumes, float)
        self._s = H @ self._v
        logger.info('Density filter r=%.4g: %d elements, %.1f neighbours/element',
                    self.filter_radius, n, H.nnz / max(n, 1))
        return self

    @property
    def mean_neighbours(self) -> float:
        return self._H.nnz / self._H.shape[0]

    def apply(self, x: np.ndarray) -> np.ndarray:
        return (self._H @ (self._v * x)) / self._s

    def backprop(self, dfdrho: np.ndarray) -> np.ndarray:
        """Chain rule: df/dx_j = v_j Σ_i H_ij (df/dρ̃_i) / s_i."""
        return self._v * (self._H.T @ (dfdrho / self._s))


class SensitivityFilter:
    """Kept for API compatibility; SIMPOptimizer uses the (consistent) density filter."""

    def __init__(self, filter_radius: float):
        self.filter_radius = filter_radius

    def apply(self, sensitivities, densities, mesh):
        raise NotImplementedError('Use DensityFilter (consistent sensitivities)')


class HeavisideProjection:
    """Smooth Heaviside projection ρ̄ = H_β(ρ̃) that drives densities towards 0/1."""

    def __init__(self, beta: float = 1.0, eta: float = 0.5):
        self.beta = float(beta)
        self.eta = float(eta)

    def project(self, rho: np.ndarray) -> np.ndarray:
        b, e = self.beta, self.eta
        return (np.tanh(b * e) + np.tanh(b * (rho - e))) / (np.tanh(b * e) + np.tanh(b * (1 - e)))

    def sensitivity_chain(self, rho: np.ndarray) -> np.ndarray:
        """dρ̄/dρ̃."""
        b, e = self.beta, self.eta
        return b * (1 - np.tanh(b * (rho - e)) ** 2) / (np.tanh(b * e) + np.tanh(b * (1 - e)))
