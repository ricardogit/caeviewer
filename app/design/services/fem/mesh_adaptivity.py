"""Adaptive mesh refinement — h-refinement strategy.

FASE 3: Longest-edge bisection refinement + simple coarsening.
"""
from __future__ import annotations
import numpy as np
from typing import Set, Tuple
import logging

logger = logging.getLogger(__name__)

def refine_marked_elements_bisection(nodes, elements, mark_refine):
    """Refine marked T4 elements via longest-edge bisection.
    
    Args:
        nodes: (n_nodes, 3)
        elements: (n_elem, 4) T4 connectivity
        mark_refine: (n_elem,) bool
        
    Returns:
        nodes_new, elements_new
    """
    if not np.any(mark_refine):
        return nodes.copy(), elements.copy()

    # Edge → elements map
    edge_to_el = {}
    for el, conn in enumerate(elements):
        edges = [
            (min(conn[i], conn[j]), max(conn[i], conn[j]))
            for i, j in [(0,1), (0,2), (0,3), (1,2), (1,3), (2,3)]
        ]
        for edge in edges:
            if edge not in edge_to_el:
                edge_to_el[edge] = []
            edge_to_el[edge].append(el)

    # Mark edges to split: longest edge of each refined element
    edges_to_split = set()
    for el in np.where(mark_refine)[0]:
        conn = elements[el]
        edges = [(min(conn[i], conn[j]), max(conn[i], conn[j])) 
                 for i, j in [(0,1), (0,2), (0,3), (1,2), (1,3), (2,3)]]
        lengths = [np.linalg.norm(nodes[e[1]] - nodes[e[0]]) for e in edges]
        longest_edge = edges[np.argmax(lengths)]
        edges_to_split.add(longest_edge)

    # Create midpoints
    new_nodes = nodes.tolist()
    edge_midpoints = {}
    next_id = len(nodes)

    for edge in edges_to_split:
        mid = (nodes[edge[0]] + nodes[edge[1]]) / 2.0
        edge_midpoints[edge] = next_id
        new_nodes.append(mid)
        next_id += 1

    # Refine elements
    elements_new = []
    for el, conn in enumerate(elements):
        if not mark_refine[el]:
            elements_new.append(conn.tolist())
        else:
            n0, n1, n2, n3 = conn
            edges_on_el = [(min(conn[i], conn[j]), max(conn[i], conn[j]))
                           for i, j in [(0,1), (0,2), (0,3), (1,2), (1,3), (2,3)]]
            split_edges = [e for e in edges_on_el if e in edges_to_split]
            
            if split_edges:
                lengths = [np.linalg.norm(nodes[e[1]] - nodes[e[0]]) for e in split_edges]
                edge_split = split_edges[np.argmax(lengths)]
                mid_id = edge_midpoints[edge_split]
                
                # Bisect along edge_split
                if edge_split == (min(n0, n1), max(n0, n1)):
                    elements_new.append([n0, mid_id, n2, n3])
                    elements_new.append([mid_id, n1, n2, n3])
                elif edge_split == (min(n0, n2), max(n0, n2)):
                    elements_new.append([n0, n1, mid_id, n3])
                    elements_new.append([mid_id, n1, n2, n3])
                elif edge_split == (min(n0, n3), max(n0, n3)):
                    elements_new.append([n0, n1, n2, mid_id])
                    elements_new.append([mid_id, n1, n2, n3])
                else:
                    elements_new.append([n0, n1, mid_id, n3])
                    elements_new.append([n0, n2, mid_id, n3])
            else:
                elements_new.append(conn.tolist())

    return np.array(new_nodes, dtype=np.float64), np.array(elements_new, dtype=np.int32)

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
