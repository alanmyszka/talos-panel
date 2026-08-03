"""Store per-server JVM startup flags."""

import sqlalchemy as sa
from alembic import op

revision = "0006_jvm_flags"
down_revision = "0005_safe_auto_restart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "minecraft_servers",
        sa.Column("use_aikar_flags", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("custom_jvm_flags", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("minecraft_servers", "custom_jvm_flags")
    op.drop_column("minecraft_servers", "use_aikar_flags")
