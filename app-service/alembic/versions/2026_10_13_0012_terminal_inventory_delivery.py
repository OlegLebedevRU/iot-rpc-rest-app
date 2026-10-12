"""Private event75 outbox, additive and compatible with the previous image."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_terminal_inventory_delivery"
down_revision = "0011_event_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "tb_terminal_inventory_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("sn", sa.String(128), nullable=False),
        sa.Column("event", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(64)),
    )
    op.create_index(
        "ix_inventory_delivery_due",
        "tb_terminal_inventory_deliveries",
        ["finished_at", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("tb_terminal_inventory_deliveries")
