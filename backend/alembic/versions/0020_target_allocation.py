"""целевые доли портфеля

Revision ID: 0020
Revises: 0019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'target_allocation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_class', sa.String(32), nullable=True),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('share', sa.Numeric(7, 4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_class', name='uq_target_allocation_asset_class'),
        sa.UniqueConstraint('instrument_id', name='uq_target_allocation_instrument'),
        sa.CheckConstraint('(asset_class IS NULL) <> (instrument_id IS NULL)',
                           name='ck_target_allocation_one_key'),
    )


def downgrade() -> None:
    # Откат уносит цели владельца — их немного и они восстанавливаются с
    # экрана за минуту, в отличие от записей журнала (ср. 0016). Отказ здесь
    # был бы лишним.
    op.drop_table('target_allocation')
