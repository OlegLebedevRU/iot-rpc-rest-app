"""add org api keys table and seed

Revision ID: 0002_org_api_keys
Revises: 0001_lwt_flags
Create Date: 2026-08-27 23:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_org_api_keys'
down_revision: str | None = '0001_lwt_flags'
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        'tb_org_api_keys',
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('api_key', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['tb_orgs.org_id'], name='fk_tb_org_api_keys_org_id_tb_orgs', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('org_id', name='pk_tb_org_api_keys'),
    )
    op.create_index(
        'ix_tb_org_api_keys_api_key',
        'tb_org_api_keys',
        ['api_key'],
        unique=True,
    )

    try:
        from core.config import settings
        api_keys_map = settings.api_keys
    except Exception:
        api_keys_map = {}

    if api_keys_map:
        bind = op.get_bind()
        for api_key, org_id in api_keys_map.items():
            if not api_key:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO tb_orgs (org_id, name, is_deleted)
                    VALUES (:org_id, :name, false)
                    ON CONFLICT (org_id) DO NOTHING;
                    """
                ),
                {"org_id": org_id, "name": f"Org {org_id}"},
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO tb_org_api_keys (org_id, api_key, name, is_active)
                    VALUES (:org_id, :api_key, :name, true)
                    ON CONFLICT (org_id) DO UPDATE SET
                        api_key = EXCLUDED.api_key,
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active,
                        updated_at = now();
                    """
                ),
                {
                    "org_id": org_id,
                    "api_key": api_key,
                    "name": "Migrated from .env",
                },
            )


def downgrade() -> None:
    op.drop_index(
        'ix_tb_org_api_keys_api_key',
        table_name='tb_org_api_keys',
    )
    op.drop_table('tb_org_api_keys')
