"""FASE 2: simulation_runs.hash is not unique

The hash identifies a *configuration* (graph state + solver config): running the
same study twice must create two runs with the same hash (that is what
reproducibility means), not fail with a UniqueViolation.

Revision ID: a7c9e2f4b6d1
Revises: f6a3b9d2c1e8
"""
from alembic import op

revision = 'a7c9e2f4b6d1'
down_revision = 'f6a3b9d2c1e8'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_simulation_runs_hash', table_name='simulation_runs')
    op.create_index('ix_simulation_runs_hash', 'simulation_runs', ['hash'], unique=False)


def downgrade():
    op.drop_index('ix_simulation_runs_hash', table_name='simulation_runs')
    op.create_index('ix_simulation_runs_hash', 'simulation_runs', ['hash'], unique=True)
