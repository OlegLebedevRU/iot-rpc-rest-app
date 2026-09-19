"""add remote session lock and mutual exclusion index

Revision ID: 0006_remote_session_lock
Revises: 0005_device_provisioning
Create Date: 2026-09-19 14:00:00.000000

"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_remote_session_lock"
down_revision: str | None = "0005_device_provisioning"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_index(
        "uq_active_remote_session_per_sn",
        "tb_remote_sessions",
        ["sn"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'starting', 'active', 'stopping')"),
        sqlite_where=sa.text("status IN ('requested', 'starting', 'active', 'stopping')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_active_remote_session_per_sn",
        table_name="tb_remote_sessions",
    )
