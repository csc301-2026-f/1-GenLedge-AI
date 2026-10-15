"""Create the authentication tables."""
from alembic import op
import sqlalchemy as sa


revision = '0001_auth_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names()) & {
        'auth_organizations', 'auth_users', 'auth_sessions'
    }
    if existing:
        raise RuntimeError(
            'Existing auth tables need schema review before applying the initial migration: '
            + ', '.join(sorted(existing))
        )
    op.create_table(
        'auth_organizations',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False, unique=True),
    )
    op.create_table(
        'auth_users',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('email', sa.String(length=254), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(length=512), nullable=False),
        sa.Column('organization_id', sa.String(length=36), sa.ForeignKey('auth_organizations.id'), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('token_hash', sa.String(length=64), primary_key=True),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('auth_users.id'), nullable=False),
        sa.Column('expires_at', sa.Integer(), nullable=False),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])


def downgrade():
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_table('auth_users')
    op.drop_table('auth_organizations')
