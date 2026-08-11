"""тип операции — нативный enum вместо строки

Revision ID: 0015
Revises: 0014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Порядок значений тот же, что в app/models/transaction.py: SQLAlchemy сверяет
# состав типа, а не порядок, но расхождение в списке ловится
# test_full_chain_upgrades_matches_models_and_downgrades.
OPERATION_TYPES = (
    'BUY', 'SELL', 'DIVIDEND', 'COUPON', 'FEE', 'TAX', 'DEPOSIT', 'WITHDRAWAL',
    'REDEMPTION', 'AMORTIZATION', 'VARIATION_MARGIN', 'OTHER',
    'TRANSFER_IN', 'TRANSFER_OUT', 'CONVERSION_OUT', 'CONVERSION_IN', 'ADJUSTMENT',
)


def upgrade() -> None:
    operation_type = sa.Enum(*OPERATION_TYPES, name='operation_type')
    operation_type.create(op.get_bind())
    # USING обязателен: PostgreSQL не приводит varchar к enum неявно. Значения
    # в живой базе проверены — все семнадцать входят в тип, посторонних строк
    # в transaction.op_type нет.
    op.execute(
        'ALTER TABLE transaction ALTER COLUMN op_type '
        'TYPE operation_type USING op_type::operation_type'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE transaction ALTER COLUMN op_type '
        'TYPE VARCHAR(24) USING op_type::text'
    )
    sa.Enum(name='operation_type').drop(op.get_bind())
