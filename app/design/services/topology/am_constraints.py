"""Additive Manufacturing constraints for topology optimization.

Full implementation: FASE 4.
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)


class AMConstraints:
    """AM-specific constraints for printable topology optimization results."""

    build_direction: np.ndarray = np.array([0.0, 0.0, 1.0])   # +Z default
    max_overhang_angle: float = 45.0    # degrees — 45° is typical FFF/SLA limit
    min_feature_size: float = None      # None = auto (bbox_diagonal / 20)

    def compute_overhang_violation(self, densities, mesh):
        """Per-element overhang angle vs build_direction. FASE 4.

        Returns: numpy.ndarray of violation magnitudes (0 = no violation).
        """
        raise NotImplementedError("Implemented in FASE 4")

    def apply_am_filter(self, sensitivities, densities, mesh):
        """Augment sensitivity with overhang penalty term. FASE 4.

        This biases the optimizer to avoid overhangs beyond max_overhang_angle
        without requiring physical supports.
        """
        raise NotImplementedError("Implemented in FASE 4")

    def check_minimum_feature_size(self, densities, mesh):
        """Flag elements forming features thinner than min_feature_size. FASE 4.

        Returns: numpy.ndarray bool mask — True where feature is too thin.
        """
        raise NotImplementedError("Implemented in FASE 4")
