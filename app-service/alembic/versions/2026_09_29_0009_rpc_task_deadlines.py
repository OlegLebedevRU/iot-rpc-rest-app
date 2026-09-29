"""Add durable RPC deadlines and result identities.

Revision ID: 0009_rpc_task_deadlines
Revises: 0008_org_reservations
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_rpc_task_deadlines"
down_revision: str | None = "0008_org_reservations"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "tb_dev_tasks_status", sa.Column("initial_ttl", sa.Integer(), nullable=True)
    )
    op.add_column(
        "tb_dev_tasks_status",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Positive TTL is already a remainder; zero-TTL retains its creation window.
    op.execute("""
        UPDATE tb_dev_tasks_status AS s
        SET initial_ttl = s.ttl,
            expires_at = CASE
                WHEN s.ttl = 0 THEN t.created_at + INTERVAL '1 minute'
                ELSE CURRENT_TIMESTAMP + make_interval(mins => s.ttl)
            END
        FROM tb_dev_tasks AS t
        WHERE s.task_id = t.id AND s.status < 3
        """)
    op.execute("""
        UPDATE tb_dev_tasks_status
        SET status = 4, ttl = 0
        WHERE status < 3 AND expires_at <= CURRENT_TIMESTAMP
        """)
    op.execute(
        "UPDATE tb_dev_tasks_status SET initial_ttl = ttl WHERE initial_ttl IS NULL"
    )
    op.alter_column("tb_dev_tasks_status", "initial_ttl", nullable=False)
    op.create_index(
        "ix_tb_dev_tasks_status_expires_at",
        "tb_dev_tasks_status",
        ["expires_at"],
    )
    op.add_column(
        "tb_dev_task_results", sa.Column("result_uid", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "tb_dev_task_results",
        sa.Column("result_fingerprint", sa.String(length=64), nullable=True),
    )
    # Historical duplicate rows remain untouched. New rows get an identity.
    op.create_index(
        "uq_rpc_result_uid",
        "tb_dev_task_results",
        ["task_id", "result_uid"],
        unique=True,
        postgresql_where=sa.text("result_uid IS NOT NULL"),
    )
    op.create_index(
        "uq_rpc_result_fingerprint",
        "tb_dev_task_results",
        ["task_id", "result_fingerprint"],
        unique=True,
        postgresql_where=sa.text("result_fingerprint IS NOT NULL"),
    )


def downgrade() -> None:
    # Restore the counter expected by the old application without extending TTL.
    op.execute("""
        UPDATE tb_dev_tasks_status
        SET ttl = CASE
                WHEN initial_ttl = 0 THEN 0
                WHEN expires_at IS NULL THEN ttl
                ELSE greatest(0, ceil(extract(epoch FROM
                    (expires_at - clock_timestamp())) / 60))::integer
            END,
            status = CASE WHEN expires_at <= clock_timestamp() THEN 4 ELSE status END
        WHERE status < 3
        """)
    op.drop_index("uq_rpc_result_fingerprint", table_name="tb_dev_task_results")
    op.drop_index("uq_rpc_result_uid", table_name="tb_dev_task_results")
    op.drop_column("tb_dev_task_results", "result_fingerprint")
    op.drop_column("tb_dev_task_results", "result_uid")
    op.drop_index("ix_tb_dev_tasks_status_expires_at", table_name="tb_dev_tasks_status")
    op.drop_column("tb_dev_tasks_status", "expires_at")
    op.drop_column("tb_dev_tasks_status", "initial_ttl")
