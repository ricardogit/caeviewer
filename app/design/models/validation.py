"""Validation models — experimental records and simulation-experiment correlations."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Float, Boolean, Text, ForeignKey
from app.extensions import db
from app.models.base import BaseModel


class ExperimentalRecord(BaseModel):
    __tablename__ = 'experimental_records'

    graph_id        = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=True)
    material_id     = Column(UUID(as_uuid=True), ForeignKey('material_models.id'), nullable=True)
    # tensile | compressive | fatigue | thermal | vibration | impact | creep | ...
    test_type       = Column(String(100), nullable=False)
    # Test conditions: {"temperature_c": 25, "strain_rate": 0.001, "humidity": 0.5}
    conditions      = Column(JSONB, default=dict)
    # Raw data as list of [x, y] pairs or columnar dict {"strain": [...], "stress": [...]}
    raw_data        = Column(JSONB, default=dict)
    # Derived scalar summary: {"E": 69e9, "sigma_y": 276e6, "sigma_uts": 310e6, ...}
    scalar_summary  = Column(JSONB, default=dict)
    # Path to original uploaded CSV/Excel file
    file_ref        = Column(String(1000))
    # "user" | "literature" | "internal_database"
    source          = Column(String(100), default='user')
    description     = Column(Text)

    def __repr__(self):
        return f'<ExperimentalRecord {self.test_type} source={self.source}>'


class SimExperimentCorrelation(BaseModel):
    __tablename__ = 'sim_experiment_correlations'

    run_id              = Column(UUID(as_uuid=True), ForeignKey('simulation_runs.id'), nullable=False)
    experiment_id       = Column(UUID(as_uuid=True), ForeignKey('experimental_records.id'), nullable=False)
    # R² coefficient between interpolated simulation field and experimental measurements
    correlation_r2      = Column(Float)
    max_relative_error  = Column(Float)
    # Which field was compared: "displacement", "strain_x", "stress_von_mises", etc.
    field_compared      = Column(String(100))
    # Composite confidence score [0–1] used to weight future recommendations
    confidence_factor   = Column(Float)
    # JSON diff of material params before/after recalibration
    recalibration_delta = Column(JSONB)

    run        = db.relationship('SimulationRun',
                                 backref=db.backref('correlations', lazy='dynamic'))
    experiment = db.relationship('ExperimentalRecord',
                                 backref=db.backref('correlations', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_sim_exp_run', 'run_id'),
        db.Index('idx_sim_exp_exp', 'experiment_id'),
    )

    def __repr__(self):
        return f'<SimExperimentCorrelation R²={self.correlation_r2:.3f} conf={self.confidence_factor:.2f}>'
