"""Base model with common fields."""
import uuid
from datetime import datetime
from app.extensions import db
from sqlalchemy.dialects.postgresql import UUID


class BaseModel(db.Model):
    __abstract__ = True

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        data = {}
        for column in self.__mapper__.columns:
            value = getattr(self, column.key)
            if isinstance(value, datetime):
                data[column.key] = value.isoformat()
            elif isinstance(value, uuid.UUID):
                data[column.key] = str(value)
            else:
                data[column.key] = value
        return data

    def save(self):
        db.session.add(self)
        db.session.commit()
        return self

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.utcnow()
        db.session.commit()
        return self
