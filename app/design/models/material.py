"""MaterialModel — active material model with uncertainty support."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, ForeignKey
from app.extensions import db
from app.models.base import BaseModel


class MaterialModel(BaseModel):
    __tablename__ = 'material_models'

    name        = Column(String(255), nullable=False)
    # From CONSTITUTIVE_REGISTRY keys, e.g. 'linear_elastic_isotropic'
    model_type  = Column(String(100), nullable=False)
    # Parameter values with optional uncertainty:
    # {"E": {"value": 70e9, "std": 2e9}, "nu": {"value": 0.33, "std": 0.01}, ...}
    parameters  = Column(JSONB, default=dict)
    # Calibration metadata: R², fit method, calibration date
    calibration = Column(JSONB, default=dict)
    # Optional link to a specific project/graph
    graph_id    = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=True)
    is_active   = Column(Boolean, default=True)
    description = Column(Text)

    def __repr__(self):
        return f'<MaterialModel {self.name} [{self.model_type}]>'
