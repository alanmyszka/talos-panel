"""Store server version metadata with backups."""

import sqlalchemy as sa
from alembic import op

revision = "0007_backup_metadata"
down_revision = "0006_jvm_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backups", sa.Column("installed_version", sa.String(32), nullable=True))
    op.add_column("backups", sa.Column("game_version", sa.String(32), nullable=True))
    op.add_column("backups", sa.Column("java_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("backups", "java_version")
    op.drop_column("backups", "game_version")
    op.drop_column("backups", "installed_version")
