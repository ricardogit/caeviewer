"""Solver / tool catalog shown in the Hub (Engineering Hub, H1d).

Adding a tool is inserting a row (see seed_data.py + ``flask catalog seed``),
never editing UI code. ``capabilities`` is free-form JSONB with a small shared
vocabulary (see seed_data.VOCABULARY) used by the Hub filters.
"""
from sqlalchemy import Column, String, Integer, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import BaseModel

CATEGORIES = ('open_source', 'commercial', 'cloud', 'specialized')
INTEGRATION_LEVELS = ('integrated', 'connectable', 'reference')
AVAILABILITY = ('available', 'partial', 'planned')


class SolverCatalog(BaseModel):
    __tablename__ = 'solver_catalog'

    slug              = Column(String(64), unique=True, nullable=False, index=True)
    name              = Column(String(128), nullable=False)
    category          = Column(String(16), nullable=False)       # open_source | commercial | cloud | specialized
    description       = Column(Text)
    icon              = Column(String(64))                       # UI icon key (own icons; no vendor logos)
    license           = Column(String(128))
    url               = Column(String(500))
    integration_level = Column(String(16), nullable=False)       # integrated | connectable | reference
    availability      = Column(String(16), nullable=False, default='planned')  # available | partial | planned
    availability_note = Column(String(255))                      # e.g. "Sin fecha"
    capabilities      = Column(JSONB, nullable=False, default=dict)
    launch            = Column(JSONB)                            # integrated tools: {"mode": "geometry"} etc.
    connection        = Column(JSONB)                            # connectable tools: adapter requirements
    sort_order        = Column(Integer, nullable=False, default=100)
    enabled           = Column(Boolean, nullable=False, default=True)
