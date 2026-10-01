"""event tenants

Revision ID: 0011_event_tenants
Revises: 0010_rpc_result_webhooks
Create Date: 2026-10-01 18:19:45.386026

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0011_event_tenants"
down_revision: Union[str, Sequence[str], None] = "0010_rpc_result_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Expand only; existing history remains unknown, never infer its owner."""
    # Bound the table/index lock; transactional failure leaves the old schema intact.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.add_column("tb_dev_events", sa.Column("org_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_dev_events_org_device_id",
        "tb_dev_events",
        ["org_id", "device_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Development rollback only; production rolls back the image, retaining org_id."""
    op.drop_index("ix_dev_events_org_device_id", table_name="tb_dev_events")
    op.drop_column("tb_dev_events", "org_id")
