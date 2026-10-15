"""US4 source inventory and proposal persistence baseline."""

from pathlib import Path

from alembic import op

revision = "001_us4_control_plane"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    body = (Path(__file__).resolve().parents[1] / "001_us4_control_plane.sql").read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(body)


def downgrade():
    raise RuntimeError("This audit baseline is forward-only; restore a backup to roll back data")
