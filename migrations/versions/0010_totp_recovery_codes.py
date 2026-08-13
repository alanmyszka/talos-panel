"""Add hashed TOTP recovery codes."""

import sqlalchemy as sa
from alembic import op

revision = "0010_totp_recovery_codes"
down_revision = "0009_audit_server_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_recovery_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_codes")
