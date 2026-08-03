"""Add operational policies, updates, metrics and two-factor authentication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_operations"
down_revision = "0003_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column(
        "users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("backup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("backup_interval_hours", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("backup_retention", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "minecraft_servers", sa.Column("next_backup_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("auto_restart", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "minecraft_servers",
        sa.Column("restart_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("minecraft_servers", sa.Column("last_runtime_state", sa.String(32)))
    op.create_table(
        "server_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("minecraft_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backups.id", ondelete="SET NULL"),
        ),
        sa.Column("from_version", sa.String(32), nullable=False),
        sa.Column("to_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("error_message", sa.String(500)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_server_updates_server_id", "server_updates", ["server_id"])
    op.create_table(
        "metric_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("minecraft_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("runtime_state", sa.String(32), nullable=False),
        sa.Column("cpu_percent", sa.Integer()),
        sa.Column("memory_bytes", sa.BigInteger()),
        sa.Column("players_online", sa.Integer()),
    )
    op.create_index("ix_metric_samples_server_id", "metric_samples", ["server_id"])
    op.create_index("ix_metric_samples_recorded_at", "metric_samples", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("metric_samples")
    op.drop_table("server_updates")
    for column in (
        "last_runtime_state",
        "restart_failures",
        "auto_restart",
        "next_backup_at",
        "backup_retention",
        "backup_interval_hours",
        "backup_enabled",
    ):
        op.drop_column("minecraft_servers", column)
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
