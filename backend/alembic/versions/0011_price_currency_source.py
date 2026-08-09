"""валюта и источник у цены

Revision ID: 0011
Revises: 0010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Все ранее записанные цены — биржевые и рублёвые: MOEX котирует в рублях,
    # а других источников до сих пор не было.
    op.add_column('price', sa.Column('currency', sa.String(length=3), nullable=False,
                                     server_default='RUB'))
    op.alter_column('price', 'currency', server_default=None)

    # Рублёвые котировки MOEX, записанные для инструментов, чья валюта позже
    # была исправлена по справочнику брокера на иностранную. При оценке они
    # никогда не использовались (отбрасывались фильтром при чтении), но с
    # приходом пересчёта по курсам стали бы применяться как рублёвые — и
    # занизили бы такую позицию в разы. Удаляем: терять нечего.
    op.execute("""
        DELETE FROM price
        WHERE source = 'moex'
          AND instrument_id IN (SELECT id FROM instrument WHERE upper(currency) <> 'RUB')
    """)

    op.drop_constraint('uq_price_instrument_date', 'price', type_='unique')
    op.create_unique_constraint(
        'uq_price_instrument_date_source', 'price', ['instrument_id', 'on_date', 'source']
    )


def downgrade() -> None:
    op.drop_constraint('uq_price_instrument_date_source', 'price', type_='unique')
    op.create_unique_constraint('uq_price_instrument_date', 'price', ['instrument_id', 'on_date'])
    op.drop_column('price', 'currency')
