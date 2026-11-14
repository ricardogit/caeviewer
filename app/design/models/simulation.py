"""SimulationRun — versioned, hashed, fully traceable simulation record."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, Index
from app.extensions import db
from app.models.base import BaseModel


class SimulationRun(BaseModel):
    __tablename__ = 'simulation_runs'
    __table_args__ = (Index('ix_simulation_runs_graph_created', 'graph_id', 'created_at'),   # b3d5f7a9c2e4
                      Index('ix_simulation_runs_parent', 'parent_run_id'))

    graph_id        = Column(UUID(as_uuid=True), ForeignKey('design_graphs.id'), nullable=False)
    graph_version   = Column(Integer, nullable=False)
    # SHA-256 of (canonical physical inputs + numerical environment), see traceability/hasher.py.
    # Not unique: repeated runs of the same configuration share it (FASE 7 hito).
    hash            = Column(String(64), nullable=False, index=True)
    # run | reproduce | adaptive
    purpose         = Column(String(16), nullable=False, default='run', server_default='run')
    # What the hash covers: canonical inputs + numerical environment (FASE 7)
    inputs          = Column(JSONB)
    environment     = Column(JSONB)
    # Recorded, not hashed: host, platform, git commit, timestamps
    provenance      = Column(JSONB)
    # Key scalar results (copy of the HDF5 summary) for history/reports
    summary         = Column(JSONB)
    # Exact-bytes fingerprints: equal result_hash = bitwise identical displacement field
    mesh_hash       = Column(String(64))
    result_hash     = Column(String(64))
    # queued | running | done | failed | cancelled
    status          = Column(String(50), default='queued', nullable=False)
    tier            = Column(Integer, nullable=False)
    # Active physics: ['structural'], ['structural', 'thermal'], etc.
    physics         = Column(JSONB, default=list)
    # Solver parameters snapshot (tolerance, max_iter, method, etc.)
    solver_config   = Column(JSONB, default=dict)
    # Mesh statistics at time of run (n_nodes, n_elements, element_types, mesh_hash)
    mesh_stats      = Column(JSONB, default=dict)
    # Path to HDF5 file containing all field results
    result_ref      = Column(String(1000))
    # Performance metrics
    wall_time       = Column(Float)           # total seconds
    n_iterations    = Column(Integer)
    final_residual  = Column(Float)
    converged       = Column(Boolean)
    # List of (iter, residual, wall_time) tuples
    convergence_log = Column(JSONB, default=list)
    # Adaptive meshing cycles log
    adaptive_log    = Column(JSONB, default=list)
    # Lineage: which run triggered this one (parameter study, adaptive cycle, etc.)
    parent_run_id   = Column(UUID(as_uuid=True), ForeignKey('simulation_runs.id'), nullable=True)
    # What changed versus parent_run (for parameter studies)
    parameter_delta = Column(JSONB, default=dict)

    graph  = db.relationship('DesignGraph', backref=db.backref('runs', lazy='dynamic'))
    parent = db.relationship('SimulationRun', remote_side='SimulationRun.id',
                             backref='children')

    def to_history_dict(self) -> dict:
        s = self.summary or {}
        return {
            'run_id': str(self.id),
            'graph_id': str(self.graph_id),
            'hash': self.hash,
            'purpose': self.purpose,
            'status': self.status,
            'tier': self.tier,
            'physics': self.physics or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'wall_time_s': self.wall_time,
            'converged': self.converged,
            'element_type': s.get('element_type') or (self.mesh_stats or {}).get('element_type'),
            'n_nodes': s.get('n_nodes') or (self.mesh_stats or {}).get('n_nodes'),
            'max_displacement_mm': s.get('max_displacement_mm'),
            'max_von_mises_mpa': s.get('max_von_mises_mpa'),
            'mesh_hash': self.mesh_hash,
            'result_hash': self.result_hash,
            'parent_run_id': str(self.parent_run_id) if self.parent_run_id else None,
            'parameter_delta': self.parameter_delta or {},
            'environment': self.environment or {},
            'git_commit': (self.provenance or {}).get('git_commit'),
            'error': (self.mesh_stats or {}).get('error'),
        }

    def __repr__(self):
        return f'<SimulationRun {self.hash[:12]} status={self.status} tier={self.tier}>'
