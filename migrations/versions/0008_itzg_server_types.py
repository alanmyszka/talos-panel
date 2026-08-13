"""Add server types supported by the ITZG Minecraft image."""

from alembic import op

revision = "0008_itzg_server_types"
down_revision = "0007_backup_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("PURPUR", "PUFFERFISH", "FABRIC", "QUILT", "FORGE", "NEOFORGE"):
        op.execute(f"ALTER TYPE server_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed while rows may use them.
    pass
