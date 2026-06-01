"""PhysicsConfig — per-graph solver configuration."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey
from app.extensions import db
from app.models.base import BaseModel


class PhysicsConfig(BaseModel):
    __tablename__ = 'physics_configs'

    graph_id    = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=False)
    # Active physics as a list: ['structural', 'thermal', 'fluid', 'electromagnetic']
    physics_types       = Column(JSONB, default=list)
    # direct | iterative_cg | nonlinear | parallel  (None = auto-detect)
    solver_type         = Column(String(50))
    tolerance           = Column(Float, default=1e-8)
    max_iterations      = Column(Integer, default=100)
    # newton | arc_length | auto
    nonlinear_method    = Column(String(50), default='auto')
    adaptive_meshing    = Column(Boolean, default=True)
    error_tolerance     = Column(Float, default=0.05)
    max_refinement_cycles = Column(Integer, default=5)
    # h | p | hp
    refinement_strategy = Column(String(10), default='h')

    graph = db.relationship('DesignGraph', backref=db.backref('physics_config', uselist=False))

    def __repr__(self):
        return f'<PhysicsConfig graph={self.graph_id} physics={self.physics_types}>'
