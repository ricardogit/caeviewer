"""Finite element library — shape functions, B matrices, element stiffness.

FASE 2 implementations: T4 (3D linear tet), T3 (2D linear triangle).
Other elements: stubs only.
"""
from __future__ import annotations
import numpy as np

# ── T4 — Linear tetrahedral element (3D, 4 nodes, 12 DOF) ────────────────────
#
# Natural coordinates: ξ, η, ζ  (ξ+η+ζ ≤ 1)
# Shape functions:
#   N1 = 1 - ξ - η - ζ
#   N2 = ξ
#   N3 = η
#   N4 = ζ
#
# Constant natural derivatives (3×4): rows = d/dξ, d/dη, d/dζ; cols = N1..N4
_T4_DN_DNAT = np.array([
    [-1.0,  1.0,  0.0,  0.0],
    [-1.0,  0.0,  1.0,  0.0],
    [-1.0,  0.0,  0.0,  1.0],
], dtype=np.float64)


def t4_jacobian_and_derivatives(coords: np.ndarray):
    """Jacobian (3×3), its determinant, and global shape derivatives (3×4).

    Args:
        coords: (4, 3) array of node (x, y, z) coordinates.

    Returns:
        J:     (3, 3) Jacobian
        detJ:  scalar determinant (volume * 6)
        dN:    (3, 4) global shape derivatives [dNi/dx, dNi/dy, dNi/dz]
    """
    J = _T4_DN_DNAT @ coords          # (3,4)@(4,3) = (3,3)
    detJ = float(np.linalg.det(J))
    if detJ <= 0.0:
        raise ValueError(f"Degenerate T4 element: det(J)={detJ:.4e}. "
                         "Check node ordering or mesh quality.")
    dN = np.linalg.solve(J, _T4_DN_DNAT)   # J_inv @ dN_dnat = (3,3)^-1 @ (3,4)
    return J, detJ, dN


def t4_B_matrix(dN: np.ndarray) -> np.ndarray:
    """Strain-displacement matrix B for a T4 element.

    Args:
        dN: (3, 4) global shape derivatives.

    Returns:
        B: (6, 12) matrix.  Voigt order: [εxx, εyy, εzz, γxy, γyz, γxz].
    """
    B = np.zeros((6, 12), dtype=np.float64)
    for i in range(4):
        c = 3 * i
        dx, dy, dz = dN[0, i], dN[1, i], dN[2, i]
        #           εxx       εyy       εzz
        B[0, c]   = dx
        B[1, c+1] = dy
        B[2, c+2] = dz
        #           γxy (= 2 εxy)
        B[3, c]   = dy;  B[3, c+1] = dx
        #           γyz
        B[4, c+1] = dz;  B[4, c+2] = dy
        #           γxz
        B[5, c]   = dz;  B[5, c+2] = dx
    return B


def t4_stiffness(coords: np.ndarray, D: np.ndarray) -> np.ndarray:
    """Element stiffness matrix Ke = V * B^T D B for a single T4 element.

    Args:
        coords: (4, 3) node coordinates.
        D:      (6, 6) constitutive matrix.

    Returns:
        Ke: (12, 12) symmetric positive-definite matrix.
    """
    _, detJ, dN = t4_jacobian_and_derivatives(coords)
    B = t4_B_matrix(dN)
    V = detJ / 6.0       # element volume
    return V * (B.T @ D @ B)


def t4_stress(coords: np.ndarray, D: np.ndarray, u_e: np.ndarray) -> np.ndarray:
    """Element stress vector σ = D B u_e for a T4 element.

    Args:
        coords: (4, 3) node coordinates.
        D:      (6, 6) constitutive matrix.
        u_e:    (12,) element displacement DOFs.

    Returns:
        sigma: (6,) stress vector [σxx, σyy, σzz, σxy, σyz, σxz].
    """
    _, _, dN = t4_jacobian_and_derivatives(coords)
    B = t4_B_matrix(dN)
    return D @ (B @ u_e)


def von_mises(sigma: np.ndarray) -> float:
    """Von Mises stress from Voigt stress vector [σxx,σyy,σzz,σxy,σyz,σxz]."""
    sxx, syy, szz = sigma[0], sigma[1], sigma[2]
    sxy, syz, sxz = sigma[3], sigma[4], sigma[5]
    return float(np.sqrt(0.5 * ((sxx - syy)**2 + (syy - szz)**2 + (szz - sxx)**2
                                + 6.0 * (sxy**2 + syz**2 + sxz**2))))


# ── T3 — Linear triangle 2D (plane stress/strain) ─────────────────────────────

_T3_DN_DNAT = np.array([
    [-1.0,  1.0,  0.0],
    [-1.0,  0.0,  1.0],
], dtype=np.float64)   # (2, 3)


def t3_stiffness(coords: np.ndarray, D: np.ndarray, thickness: float = 1.0) -> np.ndarray:
    """Element stiffness for a 2D linear triangle T3.

    Args:
        coords:    (3, 2) node (x, y) coordinates.
        D:         (3, 3) plane-stress constitutive matrix.
        thickness: element thickness [m].

    Returns:
        Ke: (6, 6).
    """
    J2 = _T3_DN_DNAT @ coords       # (2,3)@(3,2) = (2,2)
    detJ = float(np.linalg.det(J2))
    area = abs(detJ) / 2.0
    dN = np.linalg.solve(J2, _T3_DN_DNAT)  # (2, 3)

    B = np.zeros((3, 6), dtype=np.float64)  # [εxx, εyy, γxy]
    for i in range(3):
        c = 2 * i
        dx, dy = dN[0, i], dN[1, i]
        B[0, c] = dx
        B[1, c+1] = dy
        B[2, c] = dy;  B[2, c+1] = dx

    return thickness * area * (B.T @ D @ B)


# ── Stubs for FASE 2+ ─────────────────────────────────────────────────────────

class H8:
    """Trilinear hexahedron — implemented in FASE 2 (Tier 2)."""
    @staticmethod
    def stiffness(coords, D):
        raise NotImplementedError("H8 implemented in FASE 2")


class H20:
    """Serendipity hexahedron — implemented in FASE 2 (Tier 2)."""
    @staticmethod
    def stiffness(coords, D):
        raise NotImplementedError("H20 implemented in FASE 2")


class T10:
    """Quadratic tetrahedron — implemented in FASE 2 (accuracy upgrade)."""
    @staticmethod
    def stiffness(coords, D):
        raise NotImplementedError("T10 implemented in FASE 2")


ELEMENT_REGISTRY = {
    'T3': {'n_nodes': 3, 'dim': 2, 'n_dof': 6,  'stiffness': t3_stiffness},
    'T4': {'n_nodes': 4, 'dim': 3, 'n_dof': 12, 'stiffness': t4_stiffness},
    'H8': {'n_nodes': 8, 'dim': 3, 'n_dof': 24, 'stiffness': H8.stiffness},
}
