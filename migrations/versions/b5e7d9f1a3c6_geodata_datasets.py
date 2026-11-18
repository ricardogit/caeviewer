"""Geographic datasets (FASE 10.5): coastlines, bathymetry, zones, points, forcings.

Revision ID: b5e7d9f1a3c6
Revises: a1f3c5e7b9d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b5e7d9f1a3c6'
down_revision = 'a1f3c5e7b9d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'geo_datasets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('fmt', sa.String(length=16), nullable=True),
        sa.Column('original_filename', sa.String(length=500), nullable=True),
        sa.Column('file_uri', sa.String(length=1000), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_crs', sa.Text(), nullable=True),
        sa.Column('bbox', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('processed_uri', sa.String(length=1000), nullable=True),
        sa.Column('preview_uri', sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_unique_constraint('geo_datasets_id_key', 'geo_datasets', ['id'])   # BaseModel.id unique=True
    op.create_index('ix_geo_datasets_project_id', 'geo_datasets', ['project_id'])
    op.create_index('ix_geo_datasets_kind', 'geo_datasets', ['kind'])
    op.create_index('ix_geo_datasets_sha256', 'geo_datasets', ['sha256'])


def downgrade():
    op.drop_index('ix_geo_datasets_sha256', table_name='geo_datasets')
    op.drop_index('ix_geo_datasets_kind', table_name='geo_datasets')
    op.drop_index('ix_geo_datasets_project_id', table_name='geo_datasets')
    op.drop_table('geo_datasets')
