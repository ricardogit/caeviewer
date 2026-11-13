"""Adaptive mesh refinement — h-refinement strategy.

FASE 3: Longest-edge bisection refinement + simple coarsening.
"""
from __future__ import annotations
import numpy as np
from typing import Set, Tuple
import logging

logger = logging.getLogger(__name__)

_TET_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _edge(a, b):
    return (a, b) if a < b else (b, a)


def refine_marked_elements_bisection(nodes, elements, mark_refine, return_midpoints: bool = False):
    """Conforming longest-edge bisection of marked T4 elements.

    1. Each marked element contributes its longest edge to the split set.
    2. Every element that contains any split edge (marked or not) is bisected
       recursively, always at its longest split edge (ties broken by node ids).
       Splitting neighbours too removes hanging nodes, and the deterministic
       order makes the two sides of every shared face triangulate identically,
       so the result is conforming.

    (FASE 2 fix: the previous version only split marked elements — leaving
    hanging nodes — and produced a zero-volume tet when bisecting edge (1,3).)

    Returns nodes_new, elements_new[, midpoints {edge (a,b): mid node}].
    """
    nodes = np.asarray(nodes, dtype=np.float64)
    elements = np.asarray(elements, dtype=np.int64)
    if not np.any(mark_refine):
        out = (nodes.copy(), elements.copy())
        return (*out, {}) if return_midpoints else out

    def length_key(e):
        return (float(np.linalg.norm(nodes_list[e[1]] - nodes_list[e[0]])), -e[0], -e[1])

    nodes_list = [p for p in nodes]
    split: set = set()
    for el in np.flatnonzero(mark_refine):
        conn = elements[el]
        edges = [_edge(conn[i], conn[j]) for i, j in _TET_EDGES]
        split.add(max(edges, key=length_key))

    midpoints: dict = {}
    for e in sorted(split):
        midpoints[e] = len(nodes_list)
        nodes_list.append((nodes[e[0]] + nodes[e[1]]) / 2.0)

    out_elements = []
    stack = [list(map(int, c)) for c in elements]
    while stack:
        conn = stack.pop()
        cand = [(conn[i], conn[j], i, j) for i, j in _TET_EDGES if _edge(conn[i], conn[j]) in midpoints]
        if not cand:
            out_elements.append(conn)
            continue
        a, b, i, j = max(cand, key=lambda c: length_key(_edge(c[0], c[1])))
        m = midpoints[_edge(a, b)]
        c1 = list(conn); c1[j] = m      # keeps node i, replaces j by the midpoint
        c2 = list(conn); c2[i] = m      # keeps node j
        stack.append(c1)
        stack.append(c2)

    out = (np.array(nodes_list, dtype=np.float64), np.array(out_elements, dtype=np.int64))
    return (*out, midpoints) if return_midpoints else out


def coarsen_mesh(nodes, elements, coarsen_ratio=0.7):
    """Simple coarsening via random node removal (stub for FASE 3+).
    
    Args:
        nodes, elements
        coarsen_ratio: fraction of nodes to keep
        
    Returns:
        nodes_coarse, elements_coarse
    """
    if len(nodes) < 10:
        return nodes.copy(), elements.copy()

    n_keep = max(4, int(len(nodes) * coarsen_ratio))
    keep_indices = np.random.choice(len(nodes), n_keep, replace=False)
    keep_set = set(keep_indices)

    old_to_new = {idx: i for i, idx in enumerate(sorted(keep_indices))}
    new_nodes = [nodes[idx] for idx in sorted(keep_indices)]

    elements_coarse = []
    for el in elements:
        if all(n in keep_set for n in el):
            new_el = [old_to_new[n] for n in el]
            elements_coarse.append(new_el)

    if not elements_coarse:
        return nodes.copy(), elements.copy()

    return np.array(new_nodes, dtype=np.float64), np.array(elements_coarse, dtype=np.int32)
