"""Standalone Part model for CAE Viewer (no CAPP manufacturing dependencies)."""
from app.extensions import db
from app.models.base import BaseModel
from sqlalchemy.dialects.postgresql import JSONB


class Part(BaseModel):
    __tablename__ = 'parts'

    name = db.Column(db.String(255), nullable=False)
    part_number = db.Column(db.String(100))
    description = db.Column(db.Text)

    material = db.Column(db.String(100), nullable=False, default='unknown')

    file_path = db.Column(db.String(500))
    file_hash = db.Column(db.String(64))

    bounding_box = db.Column(JSONB)
    complexity_score = db.Column(db.Float)
    estimated_weight = db.Column(db.Float)
    estimated_volume = db.Column(db.Float)

    def __repr__(self):
        return f'<Part {self.name}>'
