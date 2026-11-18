"""Engineering Hub Fase 0: jobs queue, users, projects, design_graphs.project_id

Revision ID: c1a0f0e5h0b1
Revises: b4d784c2b9bd
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c1a0f0e5h0b1'
down_revision = 'b4d784c2b9bd'
branch_labels = None
depends_on = None


def _base_cols():
    return [
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        'users', *_base_cols(),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255)),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(32), nullable=False, server_default='engineer'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'projects', *_base_cols(),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL')),
    )
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'])

    op.add_column('design_graphs', sa.Column(
        'project_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_design_graphs_project_id', 'design_graphs', ['project_id'])

    op.create_table(
        'jobs', *_base_cols(),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('queue', sa.String(32), nullable=False, server_default='default'),
        sa.Column('status', sa.String(16), nullable=False, server_default='queued'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('result', postgresql.JSONB()),
        sa.Column('error', sa.Text()),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0'),
        sa.Column('message', sa.String(500)),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('worker_id', sa.String(128)),
        sa.Column('heartbeat_at', sa.DateTime()),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('finished_at', sa.DateTime()),
        sa.Column('log_uri', sa.String(1000)),
        sa.Column('simulation_run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('simulation_runs.id', ondelete='SET NULL')),
        sa.Column('parent_job_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.CheckConstraint("status IN ('queued','running','done','failed','cancelled')",
                           name='ck_jobs_status'),
    )
    op.create_index('ix_jobs_claim', 'jobs', ['queue', 'status', 'priority', 'created_at'])
    op.create_index('ix_jobs_simulation_run_id', 'jobs', ['simulation_run_id'])

    # BaseModel declares id unique=True on top of the PK (repo convention, keeps autogenerate quiet)
    for t in ('users', 'projects', 'jobs'):
        op.create_unique_constraint(f'{t}_id_key', t, ['id'])


def downgrade():
    op.drop_index('ix_jobs_simulation_run_id', table_name='jobs')
    op.drop_index('ix_jobs_claim', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_design_graphs_project_id', table_name='design_graphs')
    op.drop_column('design_graphs', 'project_id')
    op.drop_index('ix_projects_owner_id', table_name='projects')
    op.drop_table('projects')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
