"""Preserve server identity in audit events after deletion."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_audit_server_snapshot"
down_revision = "0008_itzg_server_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("server_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("audit_events", sa.Column("server_name", sa.String(80), nullable=True))
    op.execute(
        """
        UPDATE audit_events AS event
        SET server_reference_id = event.server_id,
            server_name = server.name
        FROM minecraft_servers AS server
        WHERE server.id = event.server_id
        """
    )
    op.execute(
        """
        UPDATE audit_events
        SET server_reference_id = split_part(details, ':', 1)::uuid,
            server_name = split_part(details, ':', 2)
        WHERE action = 'server.delete'
          AND details ~ '^[0-9a-fA-F-]{36}:[^:]+'
        """
    )
    op.create_index(
        "ix_audit_events_server_reference_id",
        "audit_events",
        ["server_reference_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_server_reference_id", table_name="audit_events")
    op.drop_column("audit_events", "server_name")
    op.drop_column("audit_events", "server_reference_id")
