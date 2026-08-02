"""Initial schema."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_role = sa.Enum("ADMIN", "USER", name="user_role")
    server_role = sa.Enum("OWNER", "OPERATOR", name="server_role")
    server_type = sa.Enum("PAPER", "VANILLA", name="server_type")
    desired_state = sa.Enum("RUNNING", "STOPPED", name="desired_state")
    timestamps = [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        *timestamps,
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "minecraft_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("server_type", server_type, nullable=False),
        sa.Column("game_version", sa.String(32), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("host_port", sa.Integer(), nullable=False, unique=True),
        sa.Column("desired_state", desired_state, nullable=False),
        sa.Column("container_id", sa.String(128), nullable=True),
        *timestamps,
    )
    op.create_table(
        "server_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("minecraft_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", server_role, nullable=False),
        *timestamps,
        sa.UniqueConstraint("server_id", "user_id"),
    )
    op.create_table(
        "backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("minecraft_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        *timestamps,
    )
    op.create_index("ix_backups_server_id", "backups", ["server_id"])


def downgrade() -> None:
    op.drop_table("backups")
    op.drop_table("server_members")
    op.drop_table("minecraft_servers")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    for name in ("desired_state", "server_type", "server_role", "user_role"):
        sa.Enum(name=name).drop(op.get_bind())
