"""add remote session events and facts

Revision ID: 0004_remote_session_events
Revises: 0003_device_audit_logs
Create Date: 2026-09-17 22:50:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0004_remote_session_events'
down_revision: str | None = '0003_device_audit_logs'
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # 1. Create tb_remote_sessions
    op.create_table(
        'tb_remote_sessions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('terminal_id', sa.String(length=64), nullable=True),
        sa.Column('device_id', sa.Integer(), nullable=True),
        sa.Column('sn', sa.String(length=64), nullable=False),
        sa.Column('session_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='requested', nullable=False),
        sa.Column('requested_by_user_id', sa.String(length=64), nullable=True),
        sa.Column('operation_id', sa.String(length=64), nullable=True),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('close_reason', sa.String(length=128), nullable=True),
        sa.Column('session_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_tb_remote_sessions'),
    )
    op.create_index(
        'ix_tb_remote_sessions_session_id',
        'tb_remote_sessions',
        ['session_id'],
        unique=True,
    )
    op.create_index(
        'ix_tb_remote_sessions_tenant_id',
        'tb_remote_sessions',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_sessions_sn',
        'tb_remote_sessions',
        ['sn'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_sessions_status',
        'tb_remote_sessions',
        ['status'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_sessions_operation_id',
        'tb_remote_sessions',
        ['operation_id'],
        unique=False,
    )

    # 2. Create tb_remote_session_events
    op.create_table(
        'tb_remote_session_events',
        sa.Column('cursor', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('terminal_id', sa.String(length=64), nullable=True),
        sa.Column('device_id', sa.Integer(), nullable=True),
        sa.Column('sn', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('session_type', sa.String(length=32), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('event_version', sa.String(length=16), server_default='1.0.0', nullable=False),
        sa.Column('lifecycle_state', sa.String(length=32), nullable=True),
        sa.Column('reason', sa.String(length=128), nullable=True),
        sa.Column('operation_id', sa.String(length=64), nullable=True),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('cursor', name='pk_tb_remote_session_events'),
    )
    op.create_index(
        'ix_tb_remote_session_events_cursor',
        'tb_remote_session_events',
        ['cursor'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_event_id',
        'tb_remote_session_events',
        ['event_id'],
        unique=True,
    )
    op.create_index(
        'ix_tb_remote_session_events_tenant_id',
        'tb_remote_session_events',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_sn',
        'tb_remote_session_events',
        ['sn'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_session_id',
        'tb_remote_session_events',
        ['session_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_operation_id',
        'tb_remote_session_events',
        ['operation_id'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_event_type',
        'tb_remote_session_events',
        ['event_type'],
        unique=False,
    )
    op.create_index(
        'ix_tb_remote_session_events_occurred_at',
        'tb_remote_session_events',
        ['occurred_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_tb_remote_session_events_occurred_at', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_event_type', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_operation_id', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_session_id', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_sn', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_tenant_id', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_event_id', table_name='tb_remote_session_events')
    op.drop_index('ix_tb_remote_session_events_cursor', table_name='tb_remote_session_events')
    op.drop_table('tb_remote_session_events')

    op.drop_index('ix_tb_remote_sessions_operation_id', table_name='tb_remote_sessions')
    op.drop_index('ix_tb_remote_sessions_status', table_name='tb_remote_sessions')
    op.drop_index('ix_tb_remote_sessions_sn', table_name='tb_remote_sessions')
    op.drop_index('ix_tb_remote_sessions_tenant_id', table_name='tb_remote_sessions')
    op.drop_index('ix_tb_remote_sessions_session_id', table_name='tb_remote_sessions')
    op.drop_table('tb_remote_sessions')
