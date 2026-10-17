"""Transactional intake manifests and parsed JSON records."""
from alembic import op
import sqlalchemy as sa

revision = '0002_intake'
down_revision = '0001_auth_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('intake_sources',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('source_id', sa.String(68), primary_key=True),
        sa.Column('active_batch_id', sa.String(128)),
    )
    op.create_table('intake_batches',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('batch_id', sa.String(128), primary_key=True),
        sa.Column('source_id', sa.String(68)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('manifest', sa.Text()),
        sa.CheckConstraint("status IN ('staged', 'published', 'discarded')", name='ck_intake_batch_status'),
        sa.ForeignKeyConstraint(['scope_id', 'source_id'], ['intake_sources.scope_id', 'intake_sources.source_id']),
    )
    op.create_table('intake_collections',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('batch_id', sa.String(128), primary_key=True),
        sa.Column('collection_id', sa.String(68), primary_key=True),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('complete', sa.Boolean(), nullable=False),
        sa.CheckConstraint('row_count >= 0', name='ck_intake_row_count'),
        sa.ForeignKeyConstraint(['scope_id', 'batch_id'], ['intake_batches.scope_id', 'intake_batches.batch_id']),
    )
    op.create_table('intake_records',
        sa.Column('scope_id', sa.String(70), primary_key=True),
        sa.Column('batch_id', sa.String(128), primary_key=True),
        sa.Column('collection_id', sa.String(68), primary_key=True),
        sa.Column('ordinal', sa.Integer(), primary_key=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['scope_id', 'batch_id', 'collection_id'],
            ['intake_collections.scope_id', 'intake_collections.batch_id', 'intake_collections.collection_id'], ondelete='CASCADE'),
    )


def downgrade():
    for name in ('intake_records', 'intake_collections', 'intake_batches', 'intake_sources'):
        op.drop_table(name)
