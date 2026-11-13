"""Engineering Hub Fase 1b: geometries + geometry_entities (persistent face IDs)

Revision ID: d2b7a1c3e9f4
Revises: c1a0f0e5h0b1
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd2b7a1c3e9f4'
down_revision = 'c1a0f0e5h0b1'
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _base_cols():
    return [
        sa.Column('id', UUID, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        'geometries', *_base_cols(),
        sa.Column('project_id', UUID, sa.ForeignKey('projects.id', ondelete='SET NULL')),
        sa.Column('lineage_id', UUID, nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_id', UUID, sa.ForeignKey('geometries.id', ondelete='SET NULL')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(500)),
        sa.Column('file_uri', sa.String(1000), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger()),
        sa.Column('units', sa.String(8), nullable=False, server_default='mm'),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text()),
        sa.Column('import_job_id', UUID, sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('brep_uri', sa.String(1000)),
        sa.Column('bbox', postgresql.JSONB()),
        sa.Column('scale', sa.Float()),
        sa.Column('n_faces', sa.Integer()),
        sa.Column('n_solids', sa.Integer()),
        sa.Column('is_assembly', sa.Boolean()),
        sa.Column('digest', sa.String(64)),
        sa.Column('meta', postgresql.JSONB()),
        sa.UniqueConstraint('lineage_id', 'version', name='uq_geometries_lineage_version'),
        sa.CheckConstraint("status IN ('pending','processing','ready','failed')", name='ck_geometries_status'),
    )
    op.create_index('ix_geometries_project_id', 'geometries', ['project_id'])
    op.create_index('ix_geometries_lineage_id', 'geometries', ['lineage_id'])
    op.create_index('ix_geometries_sha256', 'geometries', ['sha256'])

    op.create_table(
        'geometry_entities', *_base_cols(),
        sa.Column('geometry_id', UUID, sa.ForeignKey('geometries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_type', sa.String(8), nullable=False),
        sa.Column('entity_index', sa.Integer(), nullable=False),
        sa.Column('solid_index', sa.Integer()),
        sa.Column('surface_type', sa.String(32)),
        sa.Column('measure', sa.Float()),
        sa.Column('centroid', postgresql.JSONB()),
        sa.Column('normal', postgresql.JSONB()),
        sa.Column('radius', sa.Float()),
        sa.Column('bbox', postgresql.JSONB()),
        sa.Column('sig_hash', sa.String(64)),
        sa.Column('name', sa.String(255)),
        sa.Column('parent_entity_id', UUID, sa.ForeignKey('geometry_entities.id', ondelete='SET NULL')),
        sa.Column('match_kind', sa.String(8)),
        sa.UniqueConstraint('geometry_id', 'entity_type', 'entity_index', name='uq_geometry_entities_index'),
    )
    op.create_index('ix_geometry_entities_geometry_type', 'geometry_entities', ['geometry_id', 'entity_type'])
    op.create_index('ix_geometry_entities_sig_hash', 'geometry_entities', ['sig_hash'])

    for t in ('geometries', 'geometry_entities'):
        op.create_unique_constraint(f'{t}_id_key', t, ['id'])


def downgrade():
    op.drop_table('geometry_entities')
    op.drop_table('geometries')
