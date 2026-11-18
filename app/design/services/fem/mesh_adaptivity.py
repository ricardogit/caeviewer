"""Adaptive mesh refinement — conforming longest-edge bisection (FASE 3), T4 and T10.

``refine_mesh`` is what the adaptive loop uses: T10 meshes are refined on their corner tets and the
mid-edge nodes are rebuilt (curved mid nodes of unsplit edges are kept; a split edge's new corner takes
the old mid-node position, so refinement follows curved CAD boundaries to second order). Node sets
follow (a new node joins a set when both ends of its edge belong to it); face sets are rebuilt from the
boundary faces whose nodes all belong to the set.
"""
from __future__ import annotations

import logging

import numpy as np

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


def _edge_keys(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return lo * np.int64(n) + hi


def refine_mesh(nodes, elements, marked, node_sets=None):
    """Refine the marked elements of a T4 or T10 mesh (conforming).

    Returns (nodes, elements, node_sets, face_sets). Face sets are only rebuilt for the names in
    ``node_sets``; the caller keeps the names it needs.
    """
    from app.design.services.fem.tet_batch import T10_EDGES, boundary_faces
    nodes = np.asarray(nodes, dtype=np.float64)
    elements = np.asarray(elements, dtype=np.int64)
    node_sets = {k: np.asarray(v, dtype=np.int64) for k, v in (node_sets or {}).items()}
    quadratic = elements.shape[1] == 10
    corners = elements[:, :4]

    nodes_b, tets, mids = refine_marked_elements_bisection(nodes, corners, marked, return_midpoints=True)
    n0 = len(nodes)

    old_mid = {}
    if quadratic:
        # edge (sorted corner ids) -> old mid node; a split edge's new corner sits at the old mid node
        k = _edge_keys(corners[:, T10_EDGES[:, 0]].ravel(), corners[:, T10_EDGES[:, 1]].ravel(), n0)
        uk, idx = np.unique(k, return_index=True)
        old_mid = dict(zip(uk.tolist(), elements[:, 4:].ravel()[idx].tolist()))
        for (a, b), m in mids.items():
            nodes_b[m] = nodes[old_mid[int(a) * n0 + int(b)]]

    member = {}
    for name, ids in node_sets.items():
        mask = np.zeros(len(nodes_b), dtype=bool)
        mask[ids] = True
        for (a, b), m in mids.items():
            if mask[a] and mask[b]:
                mask[m] = True
        member[name] = mask

    if quadratic:
        nb = len(nodes_b)
        ea, eb = tets[:, T10_EDGES[:, 0]].ravel(), tets[:, T10_EDGES[:, 1]].ravel()
        keys = _edge_keys(ea, eb, nb)
        uk, first, inv = np.unique(keys, return_index=True, return_inverse=True)
        lo, hi = np.minimum(ea, eb)[first], np.maximum(ea, eb)[first]
        # unsplit original edge (both ends old corners) -> its old mid node, else a new straight mid
        reuse = np.array([old_mid.get(int(a) * n0 + int(b), -1) if b < n0 else -1
                          for a, b in zip(lo.tolist(), hi.tolist())], dtype=np.int64)
        new = reuse < 0
        new_ids = nb + np.arange(int(new.sum()))
        mid_of_edge = reuse.copy()
        mid_of_edge[new] = new_ids
        nodes_b = np.vstack([nodes_b, (nodes_b[lo[new]] + nodes_b[hi[new]]) / 2])
        for name, mask in member.items():
            ext = np.zeros(len(nodes_b), dtype=bool)
            ext[:len(mask)] = mask
            ext[new_ids] = mask[lo[new]] & mask[hi[new]]
            member[name] = ext
        out = np.hstack([tets, mid_of_edge[inv.ravel()].reshape(-1, 6)])
    else:
        out = tets

    used = np.zeros(len(nodes_b), dtype=bool)          # old mids of split edges are dropped
    used[out.ravel()] = True
    remap = -np.ones(len(nodes_b), dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))
    out = remap[out]
    nodes_out = nodes_b[used]
    sets_out = {name: np.flatnonzero(mask[used]) for name, mask in member.items()}
    bf = boundary_faces(out)
    faces_out = {}
    for name, mask in member.items():
        m = mask[used]
        faces_out[name] = bf[m[bf].all(axis=1)]
    return nodes_out, out, sets_out, faces_out
