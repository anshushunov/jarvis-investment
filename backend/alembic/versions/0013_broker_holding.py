"""снимок бумаг брокера с блокировкой

Revision ID: 0013
Revises: 0012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'broker_holding',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('isin', sa.String(length=12), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('blocked', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('as_of', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'isin', name='uq_broker_holding_account_isin'),
    )
    op.create_index(op.f('ix_broker_holding_account_id'), 'broker_holding', ['account_id'],
                    unique=False)
    op.create_index(op.f('ix_broker_holding_instrument_id'), 'broker_holding', ['instrument_id'],
                    unique=False)
    op.create_index(op.f('ix_broker_holding_isin'), 'broker_holding', ['isin'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_broker_holding_isin'), table_name='broker_holding')
    op.drop_index(op.f('ix_broker_holding_instrument_id'), table_name='broker_holding')
    op.drop_index(op.f('ix_broker_holding_account_id'), table_name='broker_holding')
    op.drop_table('broker_holding')
