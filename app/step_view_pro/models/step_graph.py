"""
STEP-View Pro Models — extends CAPP core STEP models with viewer-specific tables.
"""

from app.extensions import db
from app.models.base import BaseModel
from app.models.step_storage import STEPFileHeader, STEPEntity, STEPEntityEdge
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

__all__ = [
    'STEPFileHeader', 'STEPEntity', 'STEPEntityEdge',
    'STEPFile', 'FileComparison', 'FileVersion', 'CacheEntry', 'PerformanceMetric'
]


class STEPFile(BaseModel):
    """
    Upload record for the STEP-View Pro viewer.
    Links uploaded STEP files to their processed graph headers.
    """

    __tablename__ = 'step_view_files'

    filename = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(500))
    file_path = db.Column(db.String(1000))
    file_hash = db.Column(db.String(64), unique=True, index=True)

    # Source metadata
    source_name = db.Column(db.String(255), default='user_upload')
    category = db.Column(db.String(100), default='uploaded')

    # File stats
    file_size_bytes = db.Column(db.BigInteger)
    file_size_mb = db.Column(db.Float)
    entity_count = db.Column(db.Integer)
    complexity_score = db.Column(db.Float)
    upload_date = db.Column(db.DateTime)

    # Bounding box (flat columns for fast queries)
    bbox_min_x = db.Column(db.Float)
    bbox_max_x = db.Column(db.Float)
    bbox_min_y = db.Column(db.Float)
    bbox_max_y = db.Column(db.Float)
    bbox_min_z = db.Column(db.Float)
    bbox_max_z = db.Column(db.Float)

    # Link to processed graph header
    graph_header_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey('step_file_headers.id', ondelete='SET NULL'),
        nullable=True
    )

    # Relationships
    header = db.relationship('STEPFileHeader', foreign_keys=[graph_header_id],
                             backref=db.backref('step_view_file', uselist=False))

    __table_args__ = (
        db.Index('idx_step_view_files_hash', 'file_hash'),
        db.Index('idx_step_view_files_header', 'graph_header_id'),
    )

    def __repr__(self):
        return f'<STEPFile {self.original_filename}>'


class FileComparison(BaseModel):
    """Result of comparing two STEP file versions."""

    __tablename__ = 'step_file_comparisons'

    file1_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_file_headers.id', ondelete='CASCADE'), nullable=False)
    file2_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_file_headers.id', ondelete='CASCADE'), nullable=False)

    compared_at = db.Column(db.DateTime, default=db.func.now())
    similarity_score = db.Column(db.Float)

    change_summary = db.Column(JSONB)
    metadata_diff = db.Column(JSONB)
    structure_diff = db.Column(JSONB)
    geometry_diff = db.Column(JSONB)

    __table_args__ = (
        db.Index('idx_comparisons_file1', 'file1_id'),
        db.Index('idx_comparisons_file2', 'file2_id'),
    )

    def to_dict(self):
        data = super().to_dict()
        data.update({
            'file1_id': str(self.file1_id),
            'file2_id': str(self.file2_id),
            'compared_at': self.compared_at.isoformat() if self.compared_at else None,
            'similarity_score': self.similarity_score,
            'change_summary': self.change_summary,
            'metadata_diff': self.metadata_diff,
            'structure_diff': self.structure_diff,
            'geometry_diff': self.geometry_diff,
        })
        return data

    def __repr__(self):
        return f'<FileComparison {self.file1_id} vs {self.file2_id}>'


class FileVersion(BaseModel):
    """Version snapshot of a STEP file header."""

    __tablename__ = 'step_file_versions'

    header_id = db.Column(UUID(as_uuid=True), db.ForeignKey('step_file_headers.id', ondelete='CASCADE'), nullable=False)

    version_number = db.Column(db.Integer, nullable=False)
    version_label = db.Column(db.String(100))
    file_hash = db.Column(db.String(64))

    metadata_snapshot = db.Column(JSONB)
    change_description = db.Column(db.Text)
    changed_by = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('header_id', 'version_number', name='uq_file_version'),
        db.Index('idx_versions_header', 'header_id'),
    )

    def __repr__(self):
        return f'<FileVersion {self.header_id} v{self.version_number}>'


class CacheEntry(BaseModel):
    """L2 PostgreSQL cache for geometry and analysis results."""

    __tablename__ = 'step_view_cache'

    namespace = db.Column(db.String(100), nullable=False)
    cache_key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.LargeBinary)  # JSON-serialized, not pickled

    expires_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('namespace', 'cache_key', name='uq_cache_entry'),
        db.Index('idx_cache_namespace_key', 'namespace', 'cache_key'),
        db.Index('idx_cache_expires', 'expires_at'),
    )

    def __repr__(self):
        return f'<CacheEntry {self.namespace}:{self.cache_key}>'


class PerformanceMetric(BaseModel):
    """Performance measurement records for API/processing operations."""

    __tablename__ = 'step_view_performance_metrics'

    metric_type = db.Column(db.String(50), nullable=False)   # 'api', 'query', 'processing'
    metric_name = db.Column(db.String(100), nullable=False)

    duration_ms = db.Column(db.Float)
    memory_mb = db.Column(db.Float)
    cpu_percent = db.Column(db.Float)

    metric_metadata = db.Column(JSONB)
    measured_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (
        db.Index('idx_perf_type_name', 'metric_type', 'metric_name'),
        db.Index('idx_perf_measured_at', 'measured_at'),
    )

    def __repr__(self):
        return f'<PerformanceMetric {self.metric_type}:{self.metric_name} {self.duration_ms:.1f}ms>'
