"""FASE 7: traceability columns on simulation_runs

inputs/environment are exactly what the run hash covers; provenance is recorded but
not hashed. mesh_hash/result_hash fingerprint the mesh and the displacement vector so
a reproduction can be checked bit for bit. summary keeps the key results queryable
without opening the HDF5 file. purpose: run | reproduce | adaptive.

Revision ID: b3d5f7a9c2e4
Revises: a7c9e2f4b6d1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b3d5f7a9c2e4'
down_revision = 'a7c9e2f4b6d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('simulation_runs') as b:
        b.add_column(sa.Column('purpose', sa.String(16), nullable=False, server_default='run'))
        b.add_column(sa.Column('inputs', postgresql.JSONB(), nullable=True))
        b.add_column(sa.Column('environment', postgresql.JSONB(), nullable=True))
        b.add_column(sa.Column('provenance', postgresql.JSONB(), nullable=True))
        b.add_column(sa.Column('summary', postgresql.JSONB(), nullable=True))
        b.add_column(sa.Column('mesh_hash', sa.String(64), nullable=True))
        b.add_column(sa.Column('result_hash', sa.String(64), nullable=True))
    op.create_index('ix_simulation_runs_graph_created', 'simulation_runs', ['graph_id', 'created_at'])
    op.create_index('ix_simulation_runs_parent', 'simulation_runs', ['parent_run_id'])


def downgrade():
    op.drop_index('ix_simulation_runs_parent', table_name='simulation_runs')
    op.drop_index('ix_simulation_runs_graph_created', table_name='simulation_runs')
    with op.batch_alter_table('simulation_runs') as b:
        for c in ('result_hash', 'mesh_hash', 'summary', 'provenance', 'environment', 'inputs', 'purpose'):
            b.drop_column(c)
