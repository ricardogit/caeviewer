"""Adaptive refinement loop — simulate → estimate → refine → repeat.

Full implementation: FASE 3.
"""
import logging

logger = logging.getLogger(__name__)


class AdaptiveRefinementLoop:
    """Drives the full adaptive FEM cycle.

    Each cycle:
      1. Solve FEM on current mesh
      2. ZZ error estimate
      3. Mark elements
      4. Refine marked elements via GMSH (h-refinement by default)
      5. Project previous solution as warm start
      6. Repeat until error < tolerance or max_cycles reached
    """

    max_cycles: int = 5
    error_tolerance: float = 0.05    # 5% global energy-norm error
    max_refinement_factor: float = 4.0   # mesh cannot grow > 4× initial size

    def run(self, graph_id, initial_mesh, physics_config, socketio):
        """Execute the adaptive loop and return the final SimulationRun. FASE 3.

        Emits WebSocket event 'adaptive_progress' per cycle:
          { cycle, nodes, elements, global_error, marked_elements, status }
        """
        raise NotImplementedError("Implemented in FASE 3")

    def _project_solution(self, result, new_mesh):
        """L2-projection of previous solution onto the refined mesh. FASE 3."""
        raise NotImplementedError("Implemented in FASE 3")

    def _refine_with_gmsh(self, mesh, marked_elements, strategy: str = 'h'):
        """Call GMSH to subdivide marked elements. FASE 3.

        Args:
            strategy: 'h' (subdivision) | 'p' (order elevation)
        Returns: new mesh object
        """
        raise NotImplementedError("Implemented in FASE 3")

    def _check_tier_growth(self, original_mesh, refined_mesh, declared_tier: int):
        """Raise TierLimitExceeded if the refined mesh exceeds declared tier. FASE 3."""
        raise NotImplementedError("Implemented in FASE 3")
