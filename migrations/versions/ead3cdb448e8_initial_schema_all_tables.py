"""initial schema all tables

Revision ID: ead3cdb448e8
Revises: 9f0e1d2c3b4a
Create Date: 2026-05-31 00:41:58.721210

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ead3cdb448e8'
down_revision = '9f0e1d2c3b4a'
branch_labels = None
depends_on = None


def upgrade():
    # Circular FK between step_view_files ↔ step_file_headers.
    # Strategy:
    #   1. Create step_view_files WITHOUT the graph_header_id FK.
    #   2. Create step_file_headers WITH its legacy_file_id FK to step_view_files.
    #   3. Add graph_header_id FK from step_view_files → step_file_headers afterwards.

    # 1. step_view_files (no FK to step_file_headers yet)
    op.create_table('step_view_files',
    sa.Column('filename', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=500), nullable=True),
    sa.Column('file_path', sa.String(length=1000), nullable=True),
    sa.Column('file_hash', sa.String(length=64), nullable=True),
    sa.Column('source_name', sa.String(length=255), nullable=True),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('file_size_mb', sa.Float(), nullable=True),
    sa.Column('entity_count', sa.Integer(), nullable=True),
    sa.Column('complexity_score', sa.Float(), nullable=True),
    sa.Column('upload_date', sa.DateTime(), nullable=True),
    sa.Column('bbox_min_x', sa.Float(), nullable=True),
    sa.Column('bbox_max_x', sa.Float(), nullable=True),
    sa.Column('bbox_min_y', sa.Float(), nullable=True),
    sa.Column('bbox_max_y', sa.Float(), nullable=True),
    sa.Column('bbox_min_z', sa.Float(), nullable=True),
    sa.Column('bbox_max_z', sa.Float(), nullable=True),
    sa.Column('graph_header_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_view_files', schema=None) as batch_op:
        batch_op.create_index('idx_step_view_files_hash', ['file_hash'], unique=False)
        batch_op.create_index('idx_step_view_files_header', ['graph_header_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_step_view_files_file_hash'), ['file_hash'], unique=True)

    # 2. step_file_headers (FK to step_view_files is now safe)
    op.create_table('step_file_headers',
    sa.Column('part_id', sa.UUID(), nullable=False),
    sa.Column('file_description', sa.Text(), nullable=True),
    sa.Column('file_name', sa.String(length=500), nullable=True),
    sa.Column('time_stamp', sa.DateTime(), nullable=True),
    sa.Column('author', sa.String(length=255), nullable=True),
    sa.Column('organization', sa.String(length=255), nullable=True),
    sa.Column('preprocessor_version', sa.String(length=100), nullable=True),
    sa.Column('originating_system', sa.String(length=255), nullable=True),
    sa.Column('authorization', sa.String(length=255), nullable=True),
    sa.Column('file_schema', sa.String(length=100), nullable=True),
    sa.Column('original_filename', sa.String(length=500), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('file_hash', sa.String(length=64), nullable=True),
    sa.Column('header_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('entity_tree_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('pmi_annotations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('measurements', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('markups', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('entity_count', sa.Integer(), nullable=True),
    sa.Column('total_entities', sa.Integer(), nullable=True),
    sa.Column('total_references', sa.Integer(), nullable=True),
    sa.Column('max_depth', sa.Integer(), nullable=True),
    sa.Column('root_entities', sa.Integer(), nullable=True),
    sa.Column('leaf_entities', sa.Integer(), nullable=True),
    sa.Column('depth_distribution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('legacy_file_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['legacy_file_id'], ['step_view_files.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['part_id'], ['parts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_hash'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_file_headers', schema=None) as batch_op:
        batch_op.create_index('idx_step_headers_hash', ['file_hash'], unique=False)
        batch_op.create_index('idx_step_headers_part', ['part_id'], unique=False)
        batch_op.create_index('idx_step_headers_schema', ['file_schema'], unique=False)

    # 3. Now add the deferred FK: step_view_files.graph_header_id → step_file_headers.id
    op.create_foreign_key(
        'fk_step_view_files_graph_header_id',
        'step_view_files', 'step_file_headers',
        ['graph_header_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_table('step_entities',
    sa.Column('header_id', sa.UUID(), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('entity_type', sa.String(length=100), nullable=False),
    sa.Column('entity_label', sa.String(length=255), nullable=True),
    sa.Column('entity_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('references_to', postgresql.ARRAY(sa.Integer()), nullable=True),
    sa.Column('referenced_by', postgresql.ARRAY(sa.Integer()), nullable=True),
    sa.Column('depth_level', sa.Integer(), nullable=True),
    sa.Column('is_leaf', sa.Boolean(), nullable=True),
    sa.Column('is_root', sa.Boolean(), nullable=True),
    sa.Column('manufacturing_feature', sa.String(length=100), nullable=True),
    sa.Column('feature_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('bounding_box', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('entity_category', sa.String(length=50), nullable=True),
    sa.Column('validation_status', sa.String(length=50), nullable=True),
    sa.Column('degree', sa.Integer(), nullable=True),
    sa.Column('raw_line', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['header_id'], ['step_file_headers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('header_id', 'entity_id', name='uq_header_entity'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_entities', schema=None) as batch_op:
        batch_op.create_index('idx_step_entities_depth', ['depth_level'], unique=False)
        batch_op.create_index('idx_step_entities_header', ['header_id'], unique=False)
        batch_op.create_index('idx_step_entities_refby', ['referenced_by'], unique=False, postgresql_using='gin')
        batch_op.create_index('idx_step_entities_refs', ['references_to'], unique=False, postgresql_using='gin')
        batch_op.create_index('idx_step_entities_type', ['entity_type'], unique=False)

    op.create_table('step_entity_edges',
    sa.Column('header_id', sa.UUID(), nullable=False),
    sa.Column('from_entity_id', sa.Integer(), nullable=False),
    sa.Column('to_entity_id', sa.Integer(), nullable=False),
    sa.Column('edge_type', sa.String(length=50), nullable=True),
    sa.Column('attribute_index', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['header_id'], ['step_file_headers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('header_id', 'from_entity_id', 'to_entity_id', 'attribute_index', name='uq_edge'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_entity_edges', schema=None) as batch_op:
        batch_op.create_index('idx_edges_from', ['from_entity_id'], unique=False)
        batch_op.create_index('idx_edges_header', ['header_id'], unique=False)
        batch_op.create_index('idx_edges_to', ['to_entity_id'], unique=False)

    op.create_table('step_file_comparisons',
    sa.Column('file1_id', sa.UUID(), nullable=False),
    sa.Column('file2_id', sa.UUID(), nullable=False),
    sa.Column('compared_at', sa.DateTime(), nullable=True),
    sa.Column('similarity_score', sa.Float(), nullable=True),
    sa.Column('change_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata_diff', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('structure_diff', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('geometry_diff', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file1_id'], ['step_file_headers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['file2_id'], ['step_file_headers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_file_comparisons', schema=None) as batch_op:
        batch_op.create_index('idx_comparisons_file1', ['file1_id'], unique=False)
        batch_op.create_index('idx_comparisons_file2', ['file2_id'], unique=False)

    op.create_table('step_file_versions',
    sa.Column('header_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('version_label', sa.String(length=100), nullable=True),
    sa.Column('file_hash', sa.String(length=64), nullable=True),
    sa.Column('metadata_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('change_description', sa.Text(), nullable=True),
    sa.Column('changed_by', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['header_id'], ['step_file_headers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('header_id', 'version_number', name='uq_file_version'),
    sa.UniqueConstraint('id')
    )
    with op.batch_alter_table('step_file_versions', schema=None) as batch_op:
        batch_op.create_index('idx_versions_header', ['header_id'], unique=False)

    with op.batch_alter_table('cae_fields', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('cae_meshes', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('design_edges', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('design_graphs', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('design_nodes', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('experimental_records', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('field_results', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('material_models', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('physics_configs', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('sim_experiment_correlations', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('simulation_runs', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('step_view_cache', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    with op.batch_alter_table('step_view_performance_metrics', schema=None) as batch_op:
        batch_op.create_unique_constraint(None, ['id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('step_view_performance_metrics_id_key', 'step_view_performance_metrics', type_='unique')

    op.drop_constraint('step_view_cache_id_key', 'step_view_cache', type_='unique')

    op.drop_constraint('simulation_runs_id_key', 'simulation_runs', type_='unique')

    op.drop_constraint('sim_experiment_correlations_id_key', 'sim_experiment_correlations', type_='unique')

    op.drop_constraint('physics_configs_id_key', 'physics_configs', type_='unique')

    op.drop_constraint('parts_id_key', 'parts', type_='unique')

    op.drop_constraint('material_models_id_key', 'material_models', type_='unique')

    op.drop_constraint('field_results_id_key', 'field_results', type_='unique')

    op.drop_constraint('experimental_records_id_key', 'experimental_records', type_='unique')

    op.drop_constraint('design_nodes_id_key', 'design_nodes', type_='unique')

    op.drop_constraint('design_graphs_id_key', 'design_graphs', type_='unique')

    op.drop_constraint('design_edges_id_key', 'design_edges', type_='unique')

    op.drop_constraint('cae_meshes_id_key', 'cae_meshes', type_='unique')

    op.drop_constraint('cae_fields_id_key', 'cae_fields', type_='unique')

    with op.batch_alter_table('step_file_versions', schema=None) as batch_op:
        batch_op.drop_index('idx_versions_header')

    op.drop_table('step_file_versions')
    with op.batch_alter_table('step_file_comparisons', schema=None) as batch_op:
        batch_op.drop_index('idx_comparisons_file2')
        batch_op.drop_index('idx_comparisons_file1')

    op.drop_table('step_file_comparisons')
    with op.batch_alter_table('step_entity_edges', schema=None) as batch_op:
        batch_op.drop_index('idx_edges_to')
        batch_op.drop_index('idx_edges_header')
        batch_op.drop_index('idx_edges_from')

    op.drop_table('step_entity_edges')
    with op.batch_alter_table('step_entities', schema=None) as batch_op:
        batch_op.drop_index('idx_step_entities_type')
        batch_op.drop_index('idx_step_entities_refs', postgresql_using='gin')
        batch_op.drop_index('idx_step_entities_refby', postgresql_using='gin')
        batch_op.drop_index('idx_step_entities_header')
        batch_op.drop_index('idx_step_entities_depth')

    op.drop_table('step_entities')
    op.drop_constraint('fk_step_view_files_graph_header_id', 'step_view_files', type_='foreignkey')
    with op.batch_alter_table('step_file_headers', schema=None) as batch_op:
        batch_op.drop_index('idx_step_headers_schema')
        batch_op.drop_index('idx_step_headers_part')
        batch_op.drop_index('idx_step_headers_hash')

    op.drop_table('step_file_headers')
    with op.batch_alter_table('step_view_files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_step_view_files_file_hash'))
        batch_op.drop_index('idx_step_view_files_header')
        batch_op.drop_index('idx_step_view_files_hash')

    op.drop_table('step_view_files')
    # ### end Alembic commands ###
