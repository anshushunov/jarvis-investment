"""денежные остатки счетов

Revision ID: 0012
Revises: 0011

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cash_balance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column('blocked', sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'currency', name='uq_cash_balance_account_currency'),
    )
    op.create_index(op.f('ix_cash_balance_account_id'), 'cash_balance', ['account_id'],
                    unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cash_balance_account_id'), table_name='cash_balance')
    op.drop_table('cash_balance')
