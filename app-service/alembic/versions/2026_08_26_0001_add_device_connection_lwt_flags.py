"""add device connection lwt flags

Revision ID: 0001_lwt_flags
Revises:
Create Date: 2026-08-26 02:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_lwt_flags'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tb_device_connections',
        sa.Column('app_connect', sa.Boolean(), nullable=True, default=None),
    )
    op.add_column(
        'tb_device_connections',
        sa.Column('svc_connect', sa.Boolean(), nullable=True, default=None),
    )
    op.create_index(
        'ix_tb_device_connections_lwt_flags',
        'tb_device_connections',
        ['app_connect', 'svc_connect'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_tb_device_connections_lwt_flags',
        table_name='tb_device_connections',
    )
    op.drop_column('tb_device_connections', 'svc_connect')
    op.drop_column('tb_device_connections', 'app_connect')
