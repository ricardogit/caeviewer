"""STEP File Graph Storage Models."""
from app.extensions import db
from app.models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import uuid


class STEPFileHeader(BaseModel):
    __tablename__ = 'step_file_headers'

    part_id = db.Column(UUID(as_uuid=True), db.ForeignKey('parts.id', ondelete='CASCADE'), nullable=False)

    file_description = db.Column(db.Text)
    file_name = db.Column(db.String(500))
    time_stamp = db.Column(db.DateTime)
    author = db.Column(db.String(255))
    organization = db.Column(db.String(255))
    preprocessor_version = db.Column(db.String(100))
    originating_system = db.Column(db.String(255))
    authorization = db.Column(db.String(255))
    file_schema = db.Column(db.String(100))

    original_filename = db.Column(db.String(500))
    file_size = db.Column(db.Integer)
    file_hash = db.Column(db.String(64), unique=True)

    header_json = db.Column(JSONB)
    entity_tree_json = db.Column(JSONB)
    pmi_annotations = db.Column(JSONB)
    measurements = db.Column(JSONB)
    markups = db.Column(JSONB)

    entity_count = db.Column(db.Integer)
    total_entities = db.Column(db.Integer)
    total_references = db.Column(db.Integer)
    max_depth = db.Column(db.Integer)
    root_entities = db.Column(db.Integer)
    leaf_entities = db.Column(db.Integer)
    depth_distribution = db.Column(JSONB)

    legacy_file_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_view_files.id', ondelete='SET NULL'), nullable=True)

    entities = db.relationship('STEPEntity', backref='header', lazy='dynamic', cascade='all, delete-orphan')
    part = db.relationship('Part', backref='step_header', uselist=False)

    __table_args__ = (
        db.Index('idx_step_headers_part', 'part_id'),
        db.Index('idx_step_headers_schema', 'file_schema'),
        db.Index('idx_step_headers_hash', 'file_hash'),
    )

    def to_dict(self):
        data = super().to_dict()
        data.update({
            'part_id': str(self.part_id),
            'entity_count': self.entities.count(),
            'time_stamp': self.time_stamp.isoformat() if self.time_stamp else None,
        })
        return data


class STEPEntity(BaseModel):
    __tablename__ = 'step_entities'

    header_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_file_headers.id', ondelete='CASCADE'), nullable=False)

    entity_id = db.Column(db.Integer, nullable=False)
    entity_type = db.Column(db.String(100), nullable=False)
    entity_label = db.Column(db.String(255))
    entity_attributes = db.Column(JSONB)

    references_to = db.Column(ARRAY(db.Integer), default=list)
    referenced_by = db.Column(ARRAY(db.Integer), default=list)

    depth_level = db.Column(db.Integer, default=0)
    is_leaf = db.Column(db.Boolean, default=False)
    is_root = db.Column(db.Boolean, default=False)

    manufacturing_feature = db.Column(db.String(100))
    feature_metadata = db.Column(JSONB)
    bounding_box = db.Column(JSONB)
    entity_category = db.Column(db.String(50))
    validation_status = db.Column(db.String(50))
    degree = db.Column(db.Integer)
    raw_line = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint('header_id', 'entity_id', name='uq_header_entity'),
        db.Index('idx_step_entities_header', 'header_id'),
        db.Index('idx_step_entities_type', 'entity_type'),
        db.Index('idx_step_entities_refs', 'references_to', postgresql_using='gin'),
        db.Index('idx_step_entities_refby', 'referenced_by', postgresql_using='gin'),
        db.Index('idx_step_entities_depth', 'depth_level'),
    )

    def to_dict(self):
        data = super().to_dict()
        data.update({
            'header_id': str(self.header_id),
            'references_to': self.references_to or [],
            'referenced_by': self.referenced_by or [],
        })
        return data


class STEPEntityEdge(BaseModel):
    __tablename__ = 'step_entity_edges'

    header_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_file_headers.id', ondelete='CASCADE'), nullable=False)
    from_entity_id = db.Column(db.Integer, nullable=False)
    to_entity_id = db.Column(db.Integer, nullable=False)
    edge_type = db.Column(db.String(50))
    attribute_index = db.Column(db.Integer)

    __table_args__ = (
        db.UniqueConstraint('header_id', 'from_entity_id', 'to_entity_id', 'attribute_index', name='uq_edge'),
        db.Index('idx_edges_header', 'header_id'),
        db.Index('idx_edges_from', 'from_entity_id'),
        db.Index('idx_edges_to', 'to_entity_id'),
    )
