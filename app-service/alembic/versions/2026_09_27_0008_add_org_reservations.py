"""Reserve organization IDs across MenuBuilder and IoT.

Revision ID: 0008_org_reservations
Revises: 0007_fin_archive_batches
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_org_reservations"
down_revision: str | None = "0007_fin_archive_batches"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "tb_org_reservations",
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("source_project", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("operation_id", name="tb_org_reservations_pk"),
        sa.UniqueConstraint("org_id", name="tb_org_reservations_org_uq"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["tb_orgs.org_id"],
            name="tb_org_reservations_org_fk",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("tb_org_reservations")
