"""Field identities, saved mapping work and safe snapshot retention."""
from alembic import op
import sqlalchemy as sa

revision = '0003_mapping_retention'
down_revision = '0002_intake'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('intake_batches', sa.Column('retired_at', sa.DateTime(timezone=True)))
    op.add_column('intake_batches', sa.Column('purged', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Pre-migration superseded batches get a full grace period starting now.
    op.execute("""UPDATE intake_batches SET retired_at = CURRENT_TIMESTAMP
        WHERE status = 'published' AND NOT EXISTS (
            SELECT 1 FROM intake_sources s WHERE s.scope_id = intake_batches.scope_id
            AND s.active_batch_id = intake_batches.batch_id)""")
    op.create_table('intake_fields',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('batch_id', sa.String(128), primary_key=True),
        sa.Column('collection_id', sa.String(68), primary_key=True),
        sa.Column('field_id', sa.String(68), primary_key=True),
        sa.Column('path', sa.JSON(), nullable=False),
        sa.Column('kinds', sa.JSON(), nullable=False),
        sa.Column('matchable', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['scope_id', 'batch_id', 'collection_id'],
            ['intake_collections.scope_id', 'intake_collections.batch_id', 'intake_collections.collection_id'], ondelete='CASCADE'))
    op.create_table('source_mappings',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('source_id', sa.String(68), primary_key=True),
        sa.Column('mapping_id', sa.String(128), primary_key=True),
        sa.Column('collection_id', sa.String(68), nullable=False),
        sa.Column('field_ids', sa.JSON(), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('valid_batch_id', sa.String(128), nullable=False),
        sa.Column('checked_batch_id', sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(['scope_id', 'source_id'], ['intake_sources.scope_id', 'intake_sources.source_id']),
        sa.ForeignKeyConstraint(['scope_id', 'valid_batch_id'], ['intake_batches.scope_id', 'intake_batches.batch_id']),
        sa.CheckConstraint("status IN ('valid', 'needs_review')", name='ck_mapping_status'))
    op.create_table('intake_pins',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('batch_id', sa.String(128), primary_key=True),
        sa.Column('pin_id', sa.String(128), primary_key=True),
        sa.ForeignKeyConstraint(['scope_id', 'batch_id'], ['intake_batches.scope_id', 'intake_batches.batch_id']))


def downgrade():
    for table in ('intake_pins', 'source_mappings', 'intake_fields'):
        op.drop_table(table)
    op.drop_column('intake_batches', 'purged')
    op.drop_column('intake_batches', 'retired_at')
