"""Material library provenance: category, source, source_ref, seed_key (seed catalog upsert key).

Revision ID: a1f3c5e7b9d2
Revises: c8e4a6b2d9f1
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1f3c5e7b9d2'
down_revision = 'c8e4a6b2d9f1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_models') as b:
        b.add_column(sa.Column('category', sa.String(length=50), nullable=True))
        b.add_column(sa.Column('source', sa.String(length=20), nullable=True))
        b.add_column(sa.Column('source_ref', sa.Text(), nullable=True))
        b.add_column(sa.Column('seed_key', sa.String(length=100), nullable=True))
    op.create_index('ix_material_models_seed_key', 'material_models', ['seed_key'], unique=True)


def downgrade():
    op.drop_index('ix_material_models_seed_key', table_name='material_models')
    with op.batch_alter_table('material_models') as b:
        b.drop_column('seed_key')
        b.drop_column('source_ref')
        b.drop_column('source')
        b.drop_column('category')
