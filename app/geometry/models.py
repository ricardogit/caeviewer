"""Versioned CAD geometry with persistent entity IDs.

A *lineage* groups the versions of one part (same ``lineage_id``, increasing
``version``). Each version stores the source file content-addressed by sha256
and, once the ``geometry.import`` job has run, one ``GeometryEntity`` per face
and solid with its geometric signature.

Entity identity:
  * within a version: ``(geometry_id, entity_type, entity_index)`` where the
    index is the TopExp::MapShapes order (1-based) — deterministic on re-import.
  * across versions: the index is NOT stable (Fase 1a: only 10/196 identical
    faces kept their index between two pedestal versions). ``parent_entity_id``
    links a face to its match in the previous version (signature matching), so
    boundary conditions can be carried forward; unmatched faces are new geometry.
"""
from sqlalchemy import (Column, String, Integer, Float, Boolean, Text, BigInteger,
                        ForeignKey, UniqueConstraint, Index)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.extensions import db
from app.models.base import BaseModel

GEOMETRY_STATUSES = ('pending', 'processing', 'ready', 'failed')


class Geometry(BaseModel):
    __tablename__ = 'geometries'

    project_id   = Column(UUID(as_uuid=True), ForeignKey('projects.id', ondelete='SET NULL'), index=True)
    lineage_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    version      = Column(Integer, nullable=False, default=1)
    parent_id    = Column(UUID(as_uuid=True), ForeignKey('geometries.id', ondelete='SET NULL'))

    name              = Column(String(255), nullable=False)
    original_filename = Column(String(500))
    file_uri          = Column(String(1000), nullable=False)   # relative to DATA_DIR
    sha256            = Column(String(64), nullable=False, index=True)
    size_bytes        = Column(BigInteger)
    units             = Column(String(8), nullable=False, default='mm')

    status       = Column(String(16), nullable=False, default='pending')
    error        = Column(Text)
    import_job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='SET NULL'))

    # filled by geometry.import
    brep_uri     = Column(String(1000))                       # relative to DATA_DIR
    glb_uri      = Column(String(1000))                       # viewer mesh with _FACE_ID, relative to DATA_DIR
    bbox         = Column(JSONB)                              # [xmin, ymin, zmin, xmax, ymax, zmax] mm
    scale        = Column(Float)                              # bbox diagonal, mm
    n_faces      = Column(Integer)
    n_solids     = Column(Integer)
    is_assembly  = Column(Boolean)
    digest       = Column(String(64))                         # sha256 over ordered face signature hashes
    meta         = Column(JSONB, default=dict)                # surface_types, timings, remap summary

    entities = db.relationship('GeometryEntity', backref='geometry', lazy='dynamic',
                               cascade='all, delete-orphan', passive_deletes=True)

    __table_args__ = (UniqueConstraint('lineage_id', 'version', name='uq_geometries_lineage_version'),)


class GeometryEntity(BaseModel):
    __tablename__ = 'geometry_entities'

    geometry_id  = Column(UUID(as_uuid=True), ForeignKey('geometries.id', ondelete='CASCADE'), nullable=False)
    entity_type  = Column(String(8), nullable=False)          # face | solid
    entity_index = Column(Integer, nullable=False)            # TopExp map order, 1-based
    solid_index  = Column(Integer)                            # owning solid (faces), 0 = free face

    surface_type = Column(String(32))                         # normalised: plane, cylinder, bspline, ...
    measure      = Column(Float)                              # area (faces, mm²) / volume (solids, mm³)
    centroid     = Column(JSONB)
    normal       = Column(JSONB)
    radius       = Column(Float)
    bbox         = Column(JSONB)
    sig_hash     = Column(String(64), index=True)
    name         = Column(String(255))                        # XDE name, if the STEP carries one

    parent_entity_id = Column(UUID(as_uuid=True), ForeignKey('geometry_entities.id', ondelete='SET NULL'))
    match_kind       = Column(String(8))                      # exact | tight | loose | NULL (new / v1)

    __table_args__ = (
        UniqueConstraint('geometry_id', 'entity_type', 'entity_index', name='uq_geometry_entities_index'),
        Index('ix_geometry_entities_geometry_type', 'geometry_id', 'entity_type'),
    )

    def as_signature(self) -> dict:
        """Signature dict in the format expected by app.geometry.signature.match_signatures."""
        return {'index': self.entity_index, 'surface_type': self.surface_type, 'area': self.measure,
                'centroid': self.centroid, 'bbox': self.bbox, 'normal': self.normal,
                'radius': self.radius, 'solid': self.solid_index, 'hash': self.sig_hash}
