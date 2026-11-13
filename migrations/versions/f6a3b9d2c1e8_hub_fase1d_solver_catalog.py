"""Engineering Hub Fase 1d: solver_catalog (data-driven Hub cards)

Rows are seeded with `flask catalog seed` (app/catalog/seed_data.py), not here,
so the catalog can evolve without new migrations.

Revision ID: f6a3b9d2c1e8
Revises: e4c2d8f1a7b3
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f6a3b9d2c1e8'
down_revision = 'e4c2d8f1a7b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'solver_catalog',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('slug', sa.String(64), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('category', sa.String(16), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('icon', sa.String(64)),
        sa.Column('license', sa.String(128)),
        sa.Column('url', sa.String(500)),
        sa.Column('integration_level', sa.String(16), nullable=False),
        sa.Column('availability', sa.String(16), nullable=False, server_default='planned'),
        sa.Column('availability_note', sa.String(255)),
        sa.Column('capabilities', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('launch', postgresql.JSONB()),
        sa.Column('connection', postgresql.JSONB()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("category IN ('open_source','commercial','cloud','specialized')",
                           name='ck_solver_catalog_category'),
        sa.CheckConstraint("integration_level IN ('integrated','connectable','reference')",
                           name='ck_solver_catalog_level'),
        sa.CheckConstraint("availability IN ('available','partial','planned')",
                           name='ck_solver_catalog_availability'),
    )
    op.create_index('ix_solver_catalog_slug', 'solver_catalog', ['slug'], unique=True)
    op.create_unique_constraint('solver_catalog_id_key', 'solver_catalog', ['id'])


def downgrade():
    op.drop_table('solver_catalog')
