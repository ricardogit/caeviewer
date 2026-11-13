"""FASE 8: continuous validation — correlations without a run (material tests), scope and details.

sim_experiment_correlations:
  run_id nullable (a tensile test correlates against the material model, not a simulation)
  + kind ('material' | 'structural'), graph_id, material_id, details (per-sensor values, curves, metrics)
experimental_records: + index on (graph_id), (material_id)

Revision ID: c8e4a6b2d9f1
Revises: b3d5f7a9c2e4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c8e4a6b2d9f1'
down_revision = 'b3d5f7a9c2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sim_experiment_correlations') as b:
        b.alter_column('run_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
        b.add_column(sa.Column('kind', sa.String(length=50), nullable=False, server_default='structural'))
        b.add_column(sa.Column('graph_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('design_graphs.id'),
                               nullable=True))
        b.add_column(sa.Column('material_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('material_models.id'),
                               nullable=True))
        b.add_column(sa.Column('details', postgresql.JSONB(), nullable=True))
        b.create_index('idx_sim_exp_graph', ['graph_id'])
        b.create_index('idx_sim_exp_material', ['material_id'])
    with op.batch_alter_table('experimental_records') as b:
        b.create_index('idx_exp_graph', ['graph_id'])
        b.create_index('idx_exp_material', ['material_id'])


def downgrade():
    with op.batch_alter_table('experimental_records') as b:
        b.drop_index('idx_exp_material')
        b.drop_index('idx_exp_graph')
    with op.batch_alter_table('sim_experiment_correlations') as b:
        b.drop_index('idx_sim_exp_material')
        b.drop_index('idx_sim_exp_graph')
        b.drop_column('details')
        b.drop_column('material_id')
        b.drop_column('graph_id')
        b.drop_column('kind')
        b.alter_column('run_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)
