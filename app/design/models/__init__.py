"""Design module models — exported for Alembic discovery."""
from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
from app.design.models.physics import PhysicsConfig
from app.design.models.material import MaterialModel
from app.design.models.simulation import SimulationRun
from app.design.models.result import FieldResult
from app.design.models.validation import ExperimentalRecord, SimExperimentCorrelation

__all__ = [
    'DesignGraph', 'DesignNode', 'DesignEdge',
    'PhysicsConfig',
    'MaterialModel',
    'SimulationRun',
    'FieldResult',
    'ExperimentalRecord', 'SimExperimentCorrelation',
]
