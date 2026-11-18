"""DesignGraph — directed, labeled, multi-level engineering concept graph."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey
from app.extensions import db
from app.models.base import BaseModel


class DesignGraph(BaseModel):
    __tablename__ = 'design_graphs'

    name        = Column(String(255), nullable=False)
    description = Column(Text)
    version     = Column(Integer, default=1, nullable=False)
    # Self-referential FK for versioning (parent_id = previous version)
    parent_id   = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=True)
    # SHA-256 of full graph state — computed on every save
    hash        = Column(String(64))
    # 0=Nano 1=Interactive 2=Standard 3=HPC-local 4=HPC-remote
    tier        = Column(Integer, default=1, nullable=False)
    # draft | simulating | optimizing | validated
    status      = Column(String(50), default='draft', nullable=False)
    meta        = Column('metadata', JSONB, default=dict)
    # Engineering Hub: owning project (nullable until projects are enforced)
    project_id  = Column(UUID(as_uuid=True), ForeignKey('projects.id', ondelete='SET NULL'),
                         nullable=True, index=True)

    nodes = db.relationship('DesignNode', backref='graph',
                            lazy='dynamic', cascade='all, delete-orphan',
                            foreign_keys='DesignNode.graph_id')
    edges = db.relationship('DesignEdge', backref='graph',
                            lazy='dynamic', cascade='all, delete-orphan',
                            foreign_keys='DesignEdge.graph_id')

    def __repr__(self):
        return f'<DesignGraph {self.name} v{self.version} tier={self.tier}>'


class DesignNode(BaseModel):
    __tablename__ = 'design_nodes'

    graph_id    = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=False)
    # CONCEPT | GEOMETRY | MATERIAL | BC | LOAD | RESULT | OPTIMIZATION
    node_type   = Column(String(50), nullable=False)
    label       = Column(String(255), nullable=False)
    # 0=system, 1=subsystem, 2=component, 3=feature
    level       = Column(Integer, default=0, nullable=False)
    # Type-specific payload (material params, load magnitude, BC type, etc.)
    properties  = Column(JSONB, default=dict)
    # GEOMETRY nodes: signed distance function descriptor
    # {"sdf_func": "sphere"|"box"|"custom", "params": {...}, "bbox": [xmin,ymin,zmin,xmax,ymax,zmax]}
    level_set   = Column(JSONB)
    # RESULT nodes: path to HDF5 result file
    result_ref  = Column(String(1000))
    # Tier constraint for this particular geometry node
    tier        = Column(Integer)
    # Canvas position for the graph editor UI
    pos_x       = Column(Float, default=0.0)
    pos_y       = Column(Float, default=0.0)

    def __repr__(self):
        return f'<DesignNode {self.node_type}:{self.label}>'


class DesignEdge(BaseModel):
    __tablename__ = 'design_edges'

    graph_id    = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=False)
    source_id   = Column(UUID(as_uuid=True), ForeignKey('design_nodes.id'), nullable=False)
    target_id   = Column(UUID(as_uuid=True), ForeignKey('design_nodes.id'), nullable=False)
    # FUNCTIONAL | PHYSICAL | DEPENDS_ON | MANUFACTURED_BY | CONSTRAINS | PRODUCES
    edge_type   = Column(String(50), nullable=False)
    weight      = Column(Float, default=1.0)
    properties  = Column(JSONB, default=dict)

    source = db.relationship('DesignNode', foreign_keys=[source_id])
    target = db.relationship('DesignNode', foreign_keys=[target_id])

    def __repr__(self):
        return f'<DesignEdge {self.edge_type}: {self.source_id} → {self.target_id}>'
