"""Persist task history ownership; no global history inference or backfill."""

from alembic import op
import sqlalchemy as sa

revision = "0014_task_tenant_history"
down_revision = "0013_camera_authority"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.add_column("tb_dev_tasks", sa.Column("org_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_dev_tasks_org_device_created",
        "tb_dev_tasks",
        ["org_id", "device_id", "created_at"],
    )


def downgrade():
    if not op.get_context().as_sql:
        changed = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT 1 FROM tb_dev_tasks t LEFT JOIN tb_device_org_binds b ON b.device_id=t.device_id WHERE t.org_id IS NOT NULL AND (b.org_id IS NULL OR b.org_id<>t.org_id) LIMIT 1"
                )
            )
            .first()
        )
        if changed:
            raise RuntimeError(
                "Task history has previous owners; retain0014 and roll forward"
            )
    op.drop_index("ix_dev_tasks_org_device_created", table_name="tb_dev_tasks")
    op.drop_column("tb_dev_tasks", "org_id")
