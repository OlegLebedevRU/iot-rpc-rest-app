"""Durable camera authority; additive, no runtime enablement."""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_camera_authority"
down_revision = "0012_terminal_inventory_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "tb_camera_authorities",
        sa.Column(
            "sn",
            sa.String(),
            primary_key=True,
        ),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("owner", sa.String(128)),
        sa.Column("owner_until", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_tb_camera_authorities_owner_until", "tb_camera_authorities", ["owner_until"]
    )
    # Seed only here or on a genuine new Device INSERT, never when a runtime row
    # disappears. Initial state is pinned in this migration, not imported code.
    state = json.dumps(
        {
            "version": 1,
            "generation": 0,
            "counter": 0,
            "boot": None,
            "retired": [],
            "configured": None,
            "enrolled": False,
            "pending": None,
            "ready": None,
            "active": None,
            "outbox": [],
            "commands": {},
            "command_order": [],
            "jobs": [],
            "results": {},
            "result_order": [],
            "hellos": {},
            "hello_order": [],
        }
    )
    op.execute(
        sa.text(
            "INSERT INTO tb_camera_authorities (sn,state) SELECT sn, CAST(:state AS jsonb) FROM tb_devices"
        ).bindparams(state=state)
    )
    op.execute(
        "CREATE FUNCTION camera_authority_on_device_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN INSERT INTO tb_camera_authorities(sn,state) VALUES(NEW.sn, '"
        + state
        + "'::jsonb) ON CONFLICT (sn) DO NOTHING; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER camera_authority_device_insert AFTER INSERT ON tb_devices FOR EACH ROW EXECUTE FUNCTION camera_authority_on_device_insert()"
    )


def downgrade() -> None:
    # Rollback must not silently erase boot retirement or sequence fences.
    raise RuntimeError(
        "Camera authority state is durable; export/retire identities before a reviewed destructive downgrade"
    )
