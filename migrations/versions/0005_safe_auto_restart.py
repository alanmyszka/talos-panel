"""Disable automatic restarts by default and for existing servers."""

import sqlalchemy as sa
from alembic import op

revision = "0005_safe_auto_restart"
down_revision = "0004_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("minecraft_servers", "auto_restart", server_default=sa.false())
    op.execute(sa.text("UPDATE minecraft_servers SET auto_restart = false"))


def downgrade() -> None:
    op.alter_column("minecraft_servers", "auto_restart", server_default=sa.true())
