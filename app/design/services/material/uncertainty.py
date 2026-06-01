"""Uncertainty propagation — Monte Carlo and Polynomial Chaos Expansion.

Full implementation: FASE 6.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Samples per tier
TIER_MC_SAMPLES = {0: 100, 1: 100, 2: 500, 3: 2000}


class UncertaintyPropagator:
    """Propagate material parameter uncertainty through FEM simulation.

    Strategy:
      - If ROM is available: evaluate ROM n_samples times (fast, parallelisable)
      - If no ROM: run n_samples full FEM simulations (slower, ThreadPool)
    """

    def propagate_monte_carlo(self, graph_id: str, n_samples: int,
                               rom_id: str = None, confidence: float = 0.95) -> dict:
        """Monte Carlo uncertainty propagation. FASE 6.

        Returns: {
            'mean_fields': { field_name: ndarray },
            'std_fields':  { field_name: ndarray },
            'confidence_bands': { field_name: { 'lower': ndarray, 'upper': ndarray } },
            'reliability_index': float,
            'n_samples': int,
            'wall_time': float,
        }
        """
        raise NotImplementedError("Implemented in FASE 6")

    def compute_reliability_index(self, result_distribution, failure_criterion: dict) -> float:
        """Compute first-order reliability index β. FASE 6.

        Args:
            failure_criterion: { 'field': 'von_mises', 'threshold': 276e6 }

        Returns: β = (μ - threshold) / σ  (positive = safe, negative = failed)
        """
        raise NotImplementedError("Implemented in FASE 6")

    def _sample_parameters(self, material_models: list, n_samples: int):
        """Draw parameter samples from normal distributions. FASE 6.

        Returns: list of dicts { material_id: { param: value } }
        """
        raise NotImplementedError("Implemented in FASE 6")
