"""DEIM — Discrete Empirical Interpolation Method for non-linear ROM.

Full implementation: FASE 5 (non-linear extension of POD).

For linear problems POD is sufficient.
For non-linear problems (e.g. elastoplastic), the full non-linear residual
must be evaluated at all n_dof points every Newton iteration, which defeats
the ROM speed-up.  DEIM selects m << n_dof interpolation points where the
non-linear function is evaluated, reducing cost from O(n_dof) to O(m).
"""
import logging

logger = logging.getLogger(__name__)


class DEIMHyperReducer:
    """Discrete Empirical Interpolation for non-linear ROM hyper-reduction."""

    def build_interpolation_index(self, nonlinear_snapshots):
        """Greedy DEIM algorithm to select interpolation points. FASE 5.

        Args:
            nonlinear_snapshots: snapshot matrix of non-linear residuals

        Returns: (U_nl: ndarray, interp_indices: list[int])
        """
        raise NotImplementedError("Implemented in FASE 5")

    def compute_deim_operator(self, U_nl, interp_indices):
        """P^T U_nl (U_nl^T P^T P U_nl)^-1 — DEIM operator. FASE 5."""
        raise NotImplementedError("Implemented in FASE 5")

    def evaluate_nonlinear_term(self, u_r, Phi, deim_operator, nonlinear_func):
        """Evaluate F_nl(u) cheaply using DEIM interpolation. FASE 5."""
        raise NotImplementedError("Implemented in FASE 5")
