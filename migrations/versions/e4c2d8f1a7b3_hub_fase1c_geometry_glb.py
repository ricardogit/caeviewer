"""Engineering Hub Fase 1c: geometries.glb_uri (viewer mesh with _FACE_ID)

Revision ID: e4c2d8f1a7b3
Revises: d2b7a1c3e9f4
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4c2d8f1a7b3'
down_revision = 'd2b7a1c3e9f4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('geometries', sa.Column('glb_uri', sa.String(1000)))


def downgrade():
    op.drop_column('geometries', 'glb_uri')
