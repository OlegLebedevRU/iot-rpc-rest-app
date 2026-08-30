"""add device audit logs and connection blocking

Revision ID: 0003_device_audit_logs
Revises: 0002_org_api_keys
Create Date: 2026-08-30 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0003_device_audit_logs'
down_revision: str | None = '0002_org_api_keys'
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # 1. Extend tb_device_connections
    op.add_column(
        'tb_device_connections',
        sa.Column('is_blocked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column(
        'tb_device_connections',
        sa.Column('violation_type', sa.String(length=50), nullable=True),
    )
    op.add_column(
        'tb_device_connections',
        sa.Column('violation_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        'ix_tb_device_connections_is_blocked',
        'tb_device_connections',
        ['is_blocked'],
        unique=False,
    )

    # 2. Create tb_device_audit_logs
    op.create_table(
        'tb_device_audit_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('actor', sa.String(length=100), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['tb_devices.device_id'], name='fk_tb_device_audit_logs_device_id_tb_devices', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_tb_device_audit_logs'),
    )
    op.create_index(
        'ix_tb_device_audit_logs_device_id',
        'tb_device_audit_logs',
        ['device_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_audit_logs_org_id',
        'tb_device_audit_logs',
        ['org_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_audit_logs_event_type',
        'tb_device_audit_logs',
        ['event_type'],
        unique=False,
    )
    op.create_index(
        'ix_tb_device_audit_logs_created_at',
        'tb_device_audit_logs',
        ['created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_tb_device_audit_logs_created_at', table_name='tb_device_audit_logs')
    op.drop_index('ix_tb_device_audit_logs_event_type', table_name='tb_device_audit_logs')
    op.drop_index('ix_tb_device_audit_logs_org_id', table_name='tb_device_audit_logs')
    op.drop_index('ix_tb_device_audit_logs_device_id', table_name='tb_device_audit_logs')
    op.drop_table('tb_device_audit_logs')

    op.drop_index('ix_tb_device_connections_is_blocked', table_name='tb_device_connections')
    op.drop_column('tb_device_connections', 'violation_details')
    op.drop_column('tb_device_connections', 'violation_type')
    op.drop_column('tb_device_connections', 'is_blocked')
