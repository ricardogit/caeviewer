"""Additive-manufacturing (overhang) constraint for topology optimization — FASE 4.3.

Langelaar's AM filter (2016/2017) generalised to unstructured tetrahedral meshes. An element can
only hold material if material below it supports it: with ``b`` the build direction,

    ξ_i = smin(ρ̃_i, Σ_i),    Σ_i = smax{ ξ_j : j ∈ S_i }

where S_i (support region) = elements of *earlier layers* whose centroid lies in the cone of
half-angle ``max_overhang_angle`` (from the build direction) below element i, within one or two
element sizes. Elements of the first layer (on the build plate) are always supported. Layers are
slabs normal to ``b`` of thickness ~h/2, processed bottom-up, so every element is evaluated after
its supporters; the sensitivities are propagated top-down with the exact adjoint of the recursion.

smax is a p-norm (exact for one fully supporting element, a slight over-estimate otherwise, the
smin caps it at ρ̃), smin the smooth minimum of Langelaar. The filter sits between the density filter
and the Heaviside projection: x → ρ̃ → ξ → ρ̄.
"""
from __future__ import annotations

import logging

import numpy as np
import scipy.sparse as sp

logger = logging.getLogger(__name__)


class AMConstraints:
    """Overhang (self-supporting) filter for printable designs."""

    def __init__(self, centroids: np.ndarray, volumes: np.ndarray, h_mean: float,
                 build_direction=(0.0, 0.0, 1.0), max_overhang_angle: float = 45.0,
                 P: float = 40.0, eps: float = 1e-4, reach: float = 2.0, layer_factor: float = 0.5):
        b = np.asarray(build_direction, float)
        if np.linalg.norm(b) < 1e-12:
            raise ValueError('build_direction must be a non-zero vector')
        self.b = b / np.linalg.norm(b)
        self.max_overhang_angle = float(max_overhang_angle)
        if not 10.0 <= self.max_overhang_angle <= 80.0:
            raise ValueError('max_overhang_angle must be between 10 and 80 degrees')
        self.P, self.eps = float(P), float(eps)
        self.vol = np.asarray(volumes, float)
        c = np.asarray(centroids, float)
        n = len(c)
        z = c @ self.b
        t = layer_factor * h_mean
        self.layer = np.floor((z - z.min()) / t).astype(np.int64)
        self.base = self.layer == 0
        # support cone: earlier layer, height difference dz > 0, lateral offset ≤ dz·tan(angle)
        from scipy.spatial import cKDTree
        tree = cKDTree(c)
        D = tree.sparse_distance_matrix(tree, reach * h_mean, output_type='coo_matrix')
        i, j = D.row, D.col
        d = c[i] - c[j]
        dz = d @ self.b
        lat = np.linalg.norm(d - dz[:, None] * self.b, axis=1)
        keep = (self.layer[j] < self.layer[i]) & (dz > 0) & (lat <= dz * np.tan(np.radians(self.max_overhang_angle)) + 1e-12)
        i, j = i[keep], j[keep]
        S = sp.csr_matrix((np.ones(len(i)), (i, j)), shape=(n, n))
        S.sum_duplicates()
        S.data[:] = 1.0
        self.S = S
        n_sup = np.diff(S.indptr)
        self.orphans = (~self.base) & (n_sup == 0)       # no supporter found: treated as unsupported
        order = np.argsort(self.layer, kind='stable')
        bounds = np.flatnonzero(np.diff(self.layer[order])) + 1
        self.layers = [g for g in np.split(order, bounds) if len(g)]
        self.S_layers = [S[g] for g in self.layers]
        self._cache = None
        logger.info('AM filter: %d elements, %d layers, %.1f supporters/element, %d orphans, angle %.0f°',
                    n, len(self.layers), n_sup[~self.base].mean() if (~self.base).any() else 0.0,
                    int(self.orphans.sum()), self.max_overhang_angle)

    # smooth min / max
    def _smin(self, x, s):
        e = self.eps
        r = np.sqrt((x - s) ** 2 + e)
        return 0.5 * (x + s - r + np.sqrt(e)), 0.5 * (1 - (x - s) / r), 0.5 * (1 + (x - s) / r)

    def forward(self, rho: np.ndarray, keep: bool = True) -> np.ndarray:
        """Printed density ξ of the filtered density ρ̃."""
        P = self.P
        xi = np.array(rho, float)
        partials = []
        for g, Sg in zip(self.layers, self.S_layers):
            if self.base[g[0]]:
                partials.append(None)
                continue
            agg = Sg @ (np.maximum(xi, 0.0) ** P)
            sig = (agg + 1e-300) ** (1.0 / P)
            val, a, bb = self._smin(rho[g], sig)
            xi[g] = val
            if keep:
                partials.append((a, bb, sig))
        if keep:
            self._cache = (np.array(xi), partials)
        return xi

    def backprop(self, g_xi: np.ndarray) -> np.ndarray:
        """d f/d ρ̃ from d f/d ξ (adjoint of the layer recursion; call after ``forward``)."""
        xi, partials = self._cache
        P = self.P
        lam = np.array(g_xi, float)
        out = np.zeros_like(lam)
        xp = np.maximum(xi, 0.0) ** (P - 1)
        for g, Sg, part in zip(self.layers[::-1], self.S_layers[::-1], partials[::-1]):
            if part is None:
                out[g] += lam[g]
                continue
            a, bb, sig = part
            out[g] += lam[g] * a
            w = lam[g] * bb * sig ** (1 - P)              # ∂ξ_i/∂Σ_i · ∂Σ_i/∂(ξ_j^P)·P/P
            lam += (Sg.T @ w) * xp
        return out

    # ── evaluation (independent of the optimizer) ─────────────────────────────

    def unsupported_fraction(self, rho_bw: np.ndarray) -> float:
        """Volume fraction of a 0/1 design that the sharp printing recursion removes."""
        P0, e0 = self.P, self.eps
        self.P, self.eps = 200.0, 1e-10
        try:
            xi = self.forward(np.asarray(rho_bw, float), keep=False)
        finally:
            self.P, self.eps = P0, e0
        solid = self.vol @ rho_bw
        return float(self.vol @ np.maximum(rho_bw - (xi > 0.5), 0.0) / max(solid, 1e-300))


def overhang_area_fraction(vertices: np.ndarray, faces: np.ndarray, build_direction=(0, 0, 1),
                           max_overhang_angle: float = 45.0, plate_tol: float | None = None) -> dict:
    """Downward-facing surface steeper than allowed (needs support), from a closed iso-surface:
    facets whose outward normal n satisfies n·(−b) > cos(angle), excluding the build-plate facets."""
    b = np.asarray(build_direction, float)
    b = b / np.linalg.norm(b)
    V = np.asarray(vertices, float)
    F = np.asarray(faces, np.int64)
    X = V[F]
    nrm = np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0])
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        n = nrm / (2 * area[:, None])
    z = X.mean(axis=1) @ b
    zmin = float((V @ b).min())
    tol = plate_tol if plate_tol is not None else 1e-3 * float(np.ptp(V @ b) or 1.0)
    down = (-(n @ b)) > np.cos(np.radians(max_overhang_angle)) + 1e-9
    over = down & (z > zmin + tol) & (area > 0)
    tot = float(area.sum())
    return {'overhang_area': float(area[over].sum()), 'total_area': tot,
            'overhang_fraction': float(area[over].sum() / tot) if tot else 0.0}
