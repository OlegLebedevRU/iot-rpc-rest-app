"""add fin_archive_batches table for monthly archive lifecycle

Revision ID: 0007_fin_archive_batches
Revises: 0006_remote_session_lock
Create Date: 2026-09-21 02:00:00.000000

"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0007_fin_archive_batches"
down_revision: str | None = "0006_remote_session_lock"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "fin_archive_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_project", sa.String(length=64), nullable=False),
        sa.Column("source_month", sa.String(length=7), nullable=False),
        sa.Column("manifest_version", sa.String(length=16), server_default="1.0.0", nullable=False),
        sa.Column("schema_version", sa.String(length=16), server_default="1.0.0", nullable=False),
        sa.Column("state", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("total_records", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("data_size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("sha256_checksum", sa.String(length=64), nullable=False),
        sa.Column("min_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("through_cursor", sa.BigInteger(), nullable=True),
        sa.Column("consumers_passed_cursor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "manifest_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", "source_project", name="pk_fin_archive_batches"),
    )
    op.create_index(
        "ix_fin_archive_batches_source_month",
        "fin_archive_batches",
        ["source_month"],
        unique=False,
    )
    op.create_index(
        "ix_fin_archive_batches_state",
        "fin_archive_batches",
        ["state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fin_archive_batches_state", table_name="fin_archive_batches")
    op.drop_index("ix_fin_archive_batches_source_month", table_name="fin_archive_batches")
    op.drop_table("fin_archive_batches")
