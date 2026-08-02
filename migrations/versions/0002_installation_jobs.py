"""Add durable server installation jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_installation_jobs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    state_values = (
        "QUEUED", "RESOLVING", "DOWNLOADING", "VERIFYING", "INSTALLING",
        "COMPLETED", "FAILED"
    )
    postgresql.ENUM(*state_values, name="installation_state").create(
        op.get_bind(), checkfirst=True
    )
    state = postgresql.ENUM(*state_values, name="installation_state", create_type=False)
    op.add_column("minecraft_servers", sa.Column("installation_state", state, nullable=True))
    op.add_column("minecraft_servers", sa.Column("installed_version", sa.String(32), nullable=True))
    op.add_column("minecraft_servers", sa.Column("java_version", sa.Integer(), nullable=True))
    op.create_table(
        "installation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("minecraft_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("requested_version", sa.String(32), nullable=False),
        sa.Column("installed_version", sa.String(32), nullable=True),
        sa.Column("build_id", sa.String(64), nullable=True),
        sa.Column("java_version", sa.Integer(), nullable=True),
        sa.Column("checksum_algorithm", sa.String(16), nullable=True),
        sa.Column("expected_checksum", sa.String(128), nullable=True),
        sa.Column("actual_checksum", sa.String(128), nullable=True),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("eula_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_installation_jobs_server_id", "installation_jobs", ["server_id"])


def downgrade() -> None:
    op.drop_table("installation_jobs")
    op.drop_column("minecraft_servers", "java_version")
    op.drop_column("minecraft_servers", "installed_version")
    op.drop_column("minecraft_servers", "installation_state")
    sa.Enum(name="installation_state").drop(op.get_bind())
