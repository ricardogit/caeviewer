"""Global FEM assembler — K, F matrices and BC application.

FASE 2: full implementation for T4 structural problems.
"""
from __future__ import annotations
import logging
import numpy as np
import scipy.sparse as sp

from app.design.services.fem.elements import t4_stiffness
from app.design.services.fem.mesh import FEMMesh

logger = logging.getLogger(__name__)

# DOF sets per physics type
PHYSICS_DOFS = {
    'structural':      3,
    'thermal':         1,
    'fluid':           4,
    'electromagnetic': 4,
}

PENALTY = 1.0e30   # penalty stiffness for Dirichlet BCs


def assemble_K(mesh: FEMMesh, D: np.ndarray) -> sp.csr_matrix:
    """Assemble global stiffness matrix K using COO format.

    Args:
        mesh: FEMMesh with T4 elements.
        D:    (6, 6) constitutive matrix.

    Returns:
        K: (n_dof, n_dof) sparse CSR matrix.
    """
    n_dof = mesh.n_dof_structural
    n_elem = mesh.n_elements
    nnz = n_elem * 144          # each T4 contributes 12×12 = 144 entries

    rows = np.empty(nnz, dtype=np.int32)
    cols = np.empty(nnz, dtype=np.int32)
    vals = np.zeros(nnz,  dtype=np.float64)

    ptr = 0
    for el in mesh.elements:
        coords = mesh.nodes[el]                          # (4, 3)
        Ke = t4_stiffness(coords, D)                     # (12, 12)

        dofs = np.array([3*n + d for n in el for d in range(3)], dtype=np.int32)  # (12,)

        I = np.repeat(dofs, 12)                          # (144,)
        J = np.tile(dofs, 12)                            # (144,)
        rows[ptr:ptr+144] = I
        cols[ptr:ptr+144] = J
        vals[ptr:ptr+144] = Ke.flatten()
        ptr += 144

    K = sp.coo_matrix((vals, (rows, cols)), shape=(n_dof, n_dof))
    return K.tocsr()


def assemble_F(mesh: FEMMesh, loads: list) -> np.ndarray:
    """Assemble global load vector F.

    Each load spec is a dict with ONE of:
      - 'node_set' + 'force_per_node': [fx, fy, fz]  (applied equally to each node)
      - 'node_set' + 'force':          [fx, fy, fz]  (total, distributed over set)
      - 'node'    + 'force':           [fx, fy, fz]  (single node)

    Returns:
        F: (n_dof,) load vector.
    """
    F = np.zeros(mesh.n_dof_structural, dtype=np.float64)

    for load in loads:
        f = np.array(load.get('force', load.get('force_per_node', [0.0, 0.0, 0.0])),
                     dtype=np.float64)

        if 'node' in load:
            n = int(load['node'])
            F[3*n : 3*n+3] += f

        elif 'node_set' in load:
            nodes = mesh.node_sets.get(load['node_set'], [])
            if not nodes:
                logger.warning(f"Node set '{load['node_set']}' is empty or missing.")
                continue
            if 'force' in load and 'force_per_node' not in load:
                f_per = f / len(nodes)
            else:
                f_per = f
            for n in nodes:
                F[3*n : 3*n+3] += f_per

    return F


def apply_bcs(K: sp.csr_matrix, F: np.ndarray,
              bcs: list, mesh: FEMMesh) -> tuple[sp.csr_matrix, np.ndarray]:
    """Apply Dirichlet boundary conditions via the penalty method.

    Args:
        K:    (n_dof, n_dof) stiffness matrix.
        F:    (n_dof,) load vector.
        bcs:  list of dicts with keys:
                'node_set': str name in mesh.node_sets
                'dofs':     list of DOF offsets [0,1,2] for ux,uy,uz (default all 3)
                'values':   prescribed values (default 0.0 for each dof)
        mesh: FEMMesh providing node_sets.

    Returns:
        (K_mod, F_mod): modified stiffness and load vector.
    """
    K_lil = K.tolil()
    F = F.copy()

    for bc in bcs:
        nodes = mesh.node_sets.get(bc.get('node_set', ''), [])
        dof_offsets = bc.get('dofs', [0, 1, 2])
        vals = bc.get('values', [0.0] * len(dof_offsets))

        for n in nodes:
            for d_off, v in zip(dof_offsets, vals):
                dof = 3 * n + d_off
                K_lil[dof, dof] = PENALTY
                F[dof] = float(v) * PENALTY

    return K_lil.tocsr(), F


def get_n_dof(mesh: FEMMesh, physics: list) -> int:
    """Total DOFs for a given physics combination."""
    return sum(PHYSICS_DOFS.get(p, 3) for p in physics) * mesh.n_nodes
