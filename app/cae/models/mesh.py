"""CAE mesh and field data models."""
from app.extensions import db
from app.models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid


class CAEMesh(BaseModel):
    __tablename__ = 'cae_meshes'

    filename = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(500))
    file_path = db.Column(db.String(1000))
    file_format = db.Column(db.String(50))  # vtu, inp, bdf, msh, exo, med...

    node_count = db.Column(db.Integer)
    element_count = db.Column(db.Integer)
    element_types = db.Column(JSONB)  # {"tet4": 1200, "hex8": 300, ...}

    node_sets = db.Column(JSONB)     # {"name": [node_ids...]}
    element_sets = db.Column(JSONB)  # {"name": [elem_ids...]}

    field_names = db.Column(JSONB)   # list of available field names
    time_steps = db.Column(JSONB)    # list of time values

    bounding_box = db.Column(JSONB)  # {min_x, max_x, ...}
    description = db.Column(db.Text)

    def __repr__(self):
        return f'<CAEMesh {self.original_filename} {self.node_count}n/{self.element_count}e>'


class CAEField(BaseModel):
    __tablename__ = 'cae_fields'

    mesh_id = db.Column(UUID(as_uuid=True), db.ForeignKey('cae_meshes.id', ondelete='CASCADE'), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    field_type = db.Column(db.String(20))   # 'nodal' or 'elemental'
    components = db.Column(db.Integer, default=1)  # 1=scalar, 3=vector, 6=tensor
    component_names = db.Column(JSONB)       # ["Ux","Uy","Uz"] or ["S11","S22","S33","S12","S13","S23"]
    time_step = db.Column(db.Float)          # None = static

    data_min = db.Column(db.Float)
    data_max = db.Column(db.Float)

    mesh = db.relationship('CAEMesh', backref=db.backref('fields', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.Index('idx_cae_fields_mesh', 'mesh_id'),
    )

    def __repr__(self):
        return f'<CAEField {self.name} ({self.field_type})>'
