"""FieldResult — metadata for a simulation result stored in HDF5."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Float, Integer, Boolean, ForeignKey
from app.extensions import db
from app.models.base import BaseModel


class FieldResult(BaseModel):
    __tablename__ = 'field_results'

    run_id          = Column(UUID(as_uuid=True), ForeignKey('simulation_runs.id'), nullable=False)
    # displacement | stress | strain | temperature | pressure | von_mises | principal_stress | ...
    field_name      = Column(String(100), nullable=False)
    # nodal | elemental
    field_type      = Column(String(20), nullable=False)
    # 1=scalar, 3=vector, 6=symmetric tensor
    components      = Column(Integer, default=1)
    component_names = Column(JSONB)  # ['Ux','Uy','Uz'] or ['S11','S22','S33','S12','S13','S23']
    # Global range of field values across all time steps
    data_min        = Column(Float)
    data_max        = Column(Float)
    # HDF5 dataset path inside result_ref file, e.g. '/fields/displacement/step_0'
    hdf5_dataset    = Column(String(500))
    # For time-dependent results
    time_steps      = Column(JSONB, default=list)
    # Uncertainty: std field stored as separate HDF5 dataset
    has_uncertainty = Column(Boolean, default=False)
    uncertainty_ref = Column(String(500))

    run = db.relationship('SimulationRun', backref=db.backref('field_results', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_field_results_run', 'run_id'),
    )

    def __repr__(self):
        return f'<FieldResult {self.field_name} [{self.field_type}] run={self.run_id}>'
