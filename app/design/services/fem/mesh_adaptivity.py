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

    # Refine elements - use regular 1-to-8 subdivision for simplicity
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
                # Create midpoints for all edges that will be split
                mid_01 = edge_midpoints.get((min(n0,n1), max(n0,n1)), None)
                mid_02 = edge_midpoints.get((min(n0,n2), max(n0,n2)), None)
                mid_03 = edge_midpoints.get((min(n0,n3), max(n0,n3)), None)
                mid_12 = edge_midpoints.get((min(n1,n2), max(n1,n2)), None)
                mid_13 = edge_midpoints.get((min(n1,n3), max(n1,n3)), None)
                mid_23 = edge_midpoints.get((min(n2,n3), max(n2,n3)), None)

                # 1-to-8 subdivision (refine all edges that touch split edges)
                # Create 8 new tetrahedra from corners + edge midpoints + center
                has_split = [e in edges_to_split for e in edges_on_el]

                # Simple strategy: if any edge splits, create 2 new elements by bisecting longest edge
                longest_edge = split_edges[np.argmax([np.linalg.norm(nodes[e[1]]-nodes[e[0]])
                                                        for e in split_edges])]
                mid_id = edge_midpoints[longest_edge]

                # Standard bisection: split by longest edge
                if longest_edge == (min(n0, n1), max(n0, n1)):
                    m = mid_id
                    elements_new.append([n0, m, n2, n3])
                    elements_new.append([m, n1, n2, n3])
                elif longest_edge == (min(n0, n2), max(n0, n2)):
                    m = mid_id
                    elements_new.append([n0, n1, m, n3])
                    elements_new.append([m, n1, n2, n3])
                elif longest_edge == (min(n0, n3), max(n0, n3)):
                    m = mid_id
                    elements_new.append([n0, n1, n2, m])
                    elements_new.append([m, n1, n2, n3])
                elif longest_edge == (min(n1, n2), max(n1, n2)):
                    m = mid_id
                    elements_new.append([n0, n1, m, n3])
                    elements_new.append([n0, m, n2, n3])
                elif longest_edge == (min(n1, n3), max(n1, n3)):
                    m = mid_id
                    elements_new.append([n0, n1, m, n3])
                    elements_new.append([n0, n2, n3, m])
                else:  # (n2, n3)
                    m = mid_id
                    elements_new.append([n0, n1, n2, m])
                    elements_new.append([n0, n1, m, n3])
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
