"""add device provisioning operations

Revision ID: 0005_device_provisioning_operations
Revises: 0004_remote_session_events
Create Date: 2026-09-18 19:00:00.000000

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0005_device_provisioning_operations'
down_revision: str | None = '0004_remote_session_events'
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        'tb_device_provisionings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('operation_id', sa.String(length=64), nullable=False),
        sa.Column('contract_version', sa.String(length=16), server_default='1.0.0', nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('terminal_id', sa.Integer(), nullable=False),
        sa.Column('sn', sa.String(length=64), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='requested', nullable=False),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('requested_by_user_id', sa.String(length=64), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('provisioning_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('provisioned_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_tb_device_provisionings'),
    )
    op.create_index(
        'ix_tb_device_provisionings_operation_id',
        'tb_device_provisionings',
        ['operation_id'],
        unique=True,
    )
    op.create_index(
        'ix_tb_device_provisionings_tenant_id',
        'tb_device_provisionings',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_provisionings_terminal_id',
        'tb_device_provisionings',
        ['terminal_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_provisionings_sn',
        'tb_device_provisionings',
        ['sn'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_provisionings_device_id',
        'tb_device_provisionings',
        ['device_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_provisionings_status',
        'tb_device_provisionings',
        ['status'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_provisionings_tenant_terminal',
        'tb_device_provisionings',
        ['tenant_id', 'terminal_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_tb_device_provisionings_tenant_terminal', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_status', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_device_id', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_sn', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_terminal_id', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_tenant_id', table_name='tb_device_provisionings')
    op.drop_index('ix_tb_device_provisionings_operation_id', table_name='tb_device_provisionings')
    op.drop_table('tb_device_provisionings')
