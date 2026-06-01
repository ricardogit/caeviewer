"""Error estimator — Zienkiewicz-Zhu smoothed stress recovery + energy norm.

FASE 3 full implementation: nodal error indicators for adaptive mesh refinement.
"""
from __future__ import annotations
import numpy as np
import logging

logger = logging.getLogger(__name__)

def zienkiewicz_zhu_recovery(nodes, elements, stress_elemental):
    """Recover smoothed nodal stresses from elemental stress via L2 projection."""
    n_nodes = len(nodes)
    stress_nodal = np.zeros((n_nodes, 6), dtype=np.float64)
    node_count = np.zeros(n_nodes, dtype=np.int32)

    for el, nodes_el in enumerate(elements):
        sigma_el = stress_elemental[el]
        for n in nodes_el:
            stress_nodal[n] += sigma_el
            node_count[n] += 1

    with np.errstate(divide='ignore', invalid='ignore'):
        stress_nodal = np.where(node_count[:, None] > 0, stress_nodal / node_count[:, None], 0.0)
    return stress_nodal

def compute_error_indicators(nodes, elements, stress_elemental, E, nu):
    """Compute energy-norm element error indicators."""
    stress_nodal = zienkiewicz_zhu_recovery(nodes, elements, stress_elemental)

    mu = E / (2.0 * (1.0 + nu))
    C_inv = np.zeros((6, 6), dtype=np.float64)
    C_inv[0, 0] = C_inv[1, 1] = C_inv[2, 2] = 1.0 / E
    C_inv[0, 1] = C_inv[0, 2] = C_inv[1, 0] = C_inv[1, 2] = C_inv[2, 0] = C_inv[2, 1] = -nu / E
    C_inv[3, 3] = C_inv[4, 4] = C_inv[5, 5] = 1.0 / mu

    error_indicators = np.zeros(len(elements), dtype=np.float64)

    for el, nodes_el in enumerate(elements):
        coords = nodes[nodes_el]
        sigma_h = stress_elemental[el]
        sigma_rec = np.mean(stress_nodal[nodes_el], axis=0)
        delta_sigma = sigma_h - sigma_rec
        energy_density = delta_sigma @ C_inv @ delta_sigma
        volume = t4_volume(coords)
        error_indicators[el] = energy_density * volume

    return error_indicators

def t4_volume(coords):
    """Tetrahedral element volume."""
    v1 = coords[1] - coords[0]
    v2 = coords[2] - coords[0]
    v3 = coords[3] - coords[0]
    return abs(np.dot(v1, np.cross(v2, v3))) / 6.0

def compute_global_error(error_indicators):
    """Global energy-norm error."""
    return float(np.sqrt(np.sum(error_indicators)))

def mark_elements_for_refinement(error_indicators, strategy='fraction', target_fraction=0.2, tolerance=None):
    """Mark elements for refinement."""
    mark_refine = np.zeros(len(error_indicators), dtype=bool)
    if strategy == 'fraction' and len(error_indicators) > 0:
        threshold = np.quantile(error_indicators, max(0.0, 1.0 - target_fraction))
        mark_refine = error_indicators >= threshold
    elif strategy == 'absolute' and tolerance is not None:
        mark_refine = error_indicators >= tolerance
    return mark_refine
