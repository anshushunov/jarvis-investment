"""fx rate

Revision ID: 0010
Revises: 0009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fx_rate',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('on_date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('currency', 'on_date', name='uq_fx_rate_currency_date'),
    )
    op.create_index(op.f('ix_fx_rate_currency'), 'fx_rate', ['currency'], unique=False)
    op.create_index(op.f('ix_fx_rate_on_date'), 'fx_rate', ['on_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fx_rate_on_date'), table_name='fx_rate')
    op.drop_index(op.f('ix_fx_rate_currency'), table_name='fx_rate')
    op.drop_table('fx_rate')
