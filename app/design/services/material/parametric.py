"""Parametric material model fitting from experimental data.

Full implementation: FASE 6.
"""
import logging

logger = logging.getLogger(__name__)

CANDIDATE_MODELS = [
    'linear',           # σ = E ε
    'polynomial_3',     # σ = a₁ε + a₂ε² + a₃ε³
    'ramberg_osgood',   # ε = σ/E + (σ/K)^(1/n)
    'swift',            # σ = C (ε₀ + ε)^n
    'prony_series',     # viscoelastic relaxation
    'bilinear',         # elastoplastic bilinear
]


class ParametricMaterialModel:
    """Fit a constitutive model to experimental data via least-squares."""

    def fit(self, experimental_data: dict, model_candidates: list = None) -> dict:
        """Fit all candidate models and return the best by R². FASE 6.

        Args:
            experimental_data: { 'strain': [...], 'stress': [...], 'temperature': float }
            model_candidates: subset of CANDIDATE_MODELS (None = try all)

        Returns: {
            'best_model': str,
            'parameters': { param: { 'value': float, 'std': float } },
            'r_squared': float,
            'all_results': [ { 'model': str, 'r2': float, 'params': {...} } ]
        }
        """
        raise NotImplementedError("Implemented in FASE 6")

    def predict(self, strain, temperature: float = 293.0) -> dict:
        """Evaluate fitted model at given strain and temperature. FASE 6.

        Returns: { 'stress': float, 'tangent_modulus': float }
        """
        raise NotImplementedError("Implemented in FASE 6")

    def get_uncertainty_bounds(self, strain, confidence: float = 0.95):
        """Compute confidence interval for stress prediction. FASE 6.

        Returns: (lower_bound: float, upper_bound: float)
        """
        raise NotImplementedError("Implemented in FASE 6")
