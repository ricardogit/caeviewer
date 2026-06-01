"""Model recalibrator — update constitutive parameters from new experimental data.

Full implementation: FASE 8.
"""
import logging

logger = logging.getLogger(__name__)


class ModelRecalibrator:
    """Recalibrate a material model after the user uploads experimental results.

    Workflow:
      1. Load current MaterialModel parameters
      2. Load ExperimentalRecord raw data
      3. Minimise prediction error via MaterialCalibrator
      4. Save updated parameters + delta
      5. Create or update SimExperimentCorrelation record
      6. Emit recalibration summary
    """

    def recalibrate(self, material_id: str, experiment_id: str) -> dict:
        """Full recalibration pipeline. FASE 8.

        Returns: {
            'new_parameters': { param: { 'value': float, 'std': float } },
            'parameter_delta': { param: float },   # relative change per param
            'old_r2': float,
            'new_r2': float,
            'converged': bool,
        }
        """
        raise NotImplementedError("Implemented in FASE 8")

    def _load_material(self, material_id: str):
        """Load MaterialModel from DB. FASE 8."""
        raise NotImplementedError("Implemented in FASE 8")

    def _load_experiment(self, experiment_id: str):
        """Load ExperimentalRecord from DB. FASE 8."""
        raise NotImplementedError("Implemented in FASE 8")

    def _compute_delta(self, old_params: dict, new_params: dict) -> dict:
        """Relative change per parameter: (new - old) / old. FASE 8."""
        raise NotImplementedError("Implemented in FASE 8")
