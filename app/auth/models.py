"""Users and projects (Engineering Hub, Fase 0)."""
from flask_login import UserMixin
from sqlalchemy import Column, String, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from werkzeug.security import generate_password_hash, check_password_hash

from app.models.base import BaseModel


class User(UserMixin, BaseModel):
    __tablename__ = 'users'

    email         = Column(String(255), unique=True, nullable=False, index=True)
    name          = Column(String(255))
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(32), nullable=False, default='engineer')   # admin | engineer | viewer
    active        = Column(Boolean, nullable=False, default=True)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)

    def to_dict(self):
        d = super().to_dict()
        d.pop('password_hash', None)
        return d


class Project(BaseModel):
    __tablename__ = 'projects'

    name        = Column(String(255), nullable=False)
    description = Column(Text)
    owner_id    = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), index=True)
