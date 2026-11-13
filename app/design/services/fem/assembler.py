"""Global FEM assembler — K, F and Dirichlet boundary conditions.

FASE 2: vectorised T4/T10 assembly (tet_batch), consistent surface and body
loads, and Dirichlet BCs by elimination (exact, keeps K well conditioned for
CG). The penalty variant ``apply_bcs`` is kept for the Newton-Raphson path.

Load entries (one dict per load):
  * ``node`` + ``force``                      single node, [Fx,Fy,Fz] N
  * ``node_set`` + ``force``                  total force split equally over the set's nodes
  * ``node_set`` + ``force_per_node``         force applied to each node
  * ``face_set`` + ``force``                  total force as uniform traction F/A (consistent)
  * ``face_set`` + ``pressure``               Pa, positive pushes into the body
  * ``body_force``: [bx,by,bz] N/m³           over the whole mesh
  * ``gravity``: [gx,gy,gz] m/s² + ``density`` kg/m³
``face_set`` may be a name or a list of names (several CAD faces = one load).

BC entries: ``node_set`` or ``face_set`` (name or list), ``dofs`` [0,1,2], ``values``.
"""
from __future__ import annotations

import logging

import numpy as np
import scipy.sparse as sp

from app.design.services.fem import tet_batch as tb
from app.design.services.fem.mesh import FEMMesh

logger = logging.getLogger(__name__)

# DOF sets per physics type
PHYSICS_DOFS = {
    'structural':      3,
    'thermal':         1,
    'fluid':           4,
    'electromagnetic': 4,
}

PENALTY = 1.0e30   # penalty stiffness for Dirichlet BCs (Newton-Raphson path only)
CHUNK = 20_000     # elements per vectorised block (bounds memory: T10 Ke = 900 doubles each)


class BoundaryConditionError(ValueError):
    """A BC/load references a set that does not exist or is empty."""


def _names(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def assemble_K(mesh: FEMMesh, D: np.ndarray) -> sp.csr_matrix:
    """Global stiffness (n_dof × n_dof, CSR) for T4 or T10 meshes."""
    n_dof = mesh.n_dof_structural
    K = sp.csr_matrix((n_dof, n_dof))
    for a in range(0, mesh.n_elements, CHUNK):
        el = mesh.elements[a:a + CHUNK]
        Ke = tb.stiffness_batch(mesh.nodes, el, D)                  # (m, nd, nd)
        dofs = tb.element_dofs(el)                                  # (m, nd)
        nd = dofs.shape[1]
        rows = np.repeat(dofs, nd, axis=1).ravel()
        cols = np.tile(dofs, (1, nd)).ravel()
        K = K + sp.csr_matrix((Ke.ravel(), (rows, cols)), shape=(n_dof, n_dof))
    return K


def _face_tris(mesh: FEMMesh, names) -> np.ndarray:
    parts = []
    for n in _names(names):
        t = mesh.face_sets.get(n)
        if t is None or not len(t):
            raise BoundaryConditionError(f"Conjunto de caras '{n}' inexistente o vacío en la malla.")
        parts.append(t)
    return np.concatenate(parts)


def _node_set(mesh: FEMMesh, names) -> np.ndarray:
    parts = []
    for n in _names(names):
        v = mesh.node_sets.get(n)
        if v is None or not len(v):
            raise BoundaryConditionError(f"Conjunto de nodos '{n}' inexistente o vacío en la malla.")
        parts.append(np.asarray(v, dtype=np.int64))
    return np.unique(np.concatenate(parts))


def assemble_F(mesh: FEMMesh, loads: list, info: list | None = None) -> np.ndarray:
    """Global load vector. ``info`` (optional list) receives one summary per load."""
    n_dof = mesh.n_dof_structural
    F = np.zeros(n_dof, dtype=np.float64)

    for i, load in enumerate(loads):
        Fi = np.zeros(n_dof)
        meta = {'index': i, 'label': load.get('label')}
        if 'face_set' in load:
            tris = _face_tris(mesh, load['face_set'])
            Fi, area = tb.surface_load(mesh.nodes, mesh.elements, tris, n_dof,
                                       total_force=load.get('force'), pressure=load.get('pressure'))
            meta['area_m2'] = area
        elif 'body_force' in load or 'gravity' in load:
            if 'body_force' in load:
                b = np.asarray(load['body_force'], float)
            else:
                b = float(load.get('density', 0.0)) * np.asarray(load['gravity'], float)
            Fi = tb.body_load(mesh.nodes, mesh.elements, b, n_dof)
        elif 'node' in load:
            n = int(load['node'])
            Fi[3 * n:3 * n + 3] = np.asarray(load.get('force', [0, 0, 0]), float)
        elif 'node_set' in load:
            nodes = _node_set(mesh, load['node_set'])
            f = np.asarray(load.get('force', load.get('force_per_node', [0.0, 0.0, 0.0])), float)
            f_per = f / len(nodes) if ('force' in load and 'force_per_node' not in load) else f
            for c in range(3):
                Fi[3 * nodes + c] += f_per[c]
        else:
            raise BoundaryConditionError(f'Carga {i} sin destino (face_set, node_set, node o body_force).')
        meta['resultant_N'] = [float(Fi[c::3].sum()) for c in range(3)]
        F += Fi
        if info is not None:
            info.append(meta)
    return F


def dirichlet(mesh: FEMMesh, bcs: list) -> tuple[np.ndarray, np.ndarray]:
    """Prescribed (dofs, values) from BC entries; later entries win on overlap."""
    presc: dict[int, float] = {}
    for bc in bcs:
        if 'face_set' in bc:
            nodes = np.unique(_face_tris(mesh, bc['face_set']))
        else:
            nodes = _node_set(mesh, bc.get('node_set', ''))
        offs = [int(d) for d in bc.get('dofs', [0, 1, 2]) if int(d) in (0, 1, 2)]
        vals = bc.get('values', [0.0] * len(offs))
        if len(vals) < len(offs):
            vals = list(vals) + [0.0] * (len(offs) - len(vals))
        for d, v in zip(offs, vals):
            for n in nodes:
                presc[3 * int(n) + d] = float(v)
    dofs = np.fromiter(presc.keys(), dtype=np.int64, count=len(presc))
    vals = np.fromiter(presc.values(), dtype=np.float64, count=len(presc))
    order = np.argsort(dofs)
    return dofs[order], vals[order]


def reduce_system(K: sp.csr_matrix, F: np.ndarray, dofs: np.ndarray, vals: np.ndarray):
    """Eliminate prescribed DOFs: K_ff u_f = F_f - K_fc u_c. Returns (K_ff, rhs, free)."""
    n = K.shape[0]
    mask = np.ones(n, dtype=bool)
    mask[dofs] = False
    free = np.flatnonzero(mask)
    Kf = K[free][:, free].tocsr()
    rhs = F[free]
    if len(dofs) and np.any(vals != 0):
        rhs = rhs - K[free][:, dofs] @ vals
    return Kf, rhs, free


def apply_bcs(K: sp.csr_matrix, F: np.ndarray,
              bcs: list, mesh: FEMMesh) -> tuple[sp.csr_matrix, np.ndarray]:
    """Dirichlet BCs via the penalty method (K_ii += P, F_i = v·P). Newton-Raphson path."""
    dofs, vals = dirichlet(mesh, bcs)
    diag = np.zeros(K.shape[0])
    diag[dofs] = PENALTY
    F = F.copy()
    F[dofs] = vals * PENALTY
    return (K + sp.diags(diag)).tocsr(), F


def get_n_dof(mesh: FEMMesh, physics: list) -> int:
    """Total DOFs for a given physics combination."""
    return sum(PHYSICS_DOFS.get(p, 3) for p in physics) * mesh.n_nodes
