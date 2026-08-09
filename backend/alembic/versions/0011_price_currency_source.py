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
    """Откат возвращает схему, но не данные.

    Две вещи назад не едут в принципе, и никакая проверка тут не поможет:
    строки, удалённые в upgrade (рублёвые котировки moex у инструментов,
    валюта которых на момент апгрейда была не рублёвой), физически стёрты
    и восстанавливать их не из чего; колонка currency вместе со всем, что в
    неё успело записаться после апгрейда (валюта каждой цены, включая
    валютные номиналы облигаций), падает вместе с drop_column ниже.

    Проверяется — и здесь проверка уместна, в отличие от двух пунктов выше, —
    только то, что действительно можно поймать заранее: узкий ключ
    (instrument_id, on_date) не переживёт две цены на одну дату из разных
    источников (moex и tbank), а именно их сосуществование эта миграция и
    разрешила. Без проверки create_unique_constraint всё равно упадёт —
    голым UniqueViolation от драйвера; с ней откат останавливается заранее
    с понятным сообщением на русском (по образцу 0008). Цена ошибки здесь
    ниже, чем в 0008: там откат тихо ломал бы уникальность живых финансовых
    операций, здесь price — это переснимаемый кэш котировок, и после отказа
    возврата достаточно вручную решить, какую из двух цен за день оставить.
    """
    bind = op.get_bind()
    conflict = bind.execute(sa.text(
        """
        SELECT instrument_id, on_date, COUNT(DISTINCT source) AS sources
        FROM price
        GROUP BY instrument_id, on_date
        HAVING COUNT(DISTINCT source) > 1
        LIMIT 1
        """
    )).first()
    if conflict is not None:
        raise RuntimeError(
            "Откат миграции 0011 невозможен: у инструмента "
            f"{conflict.instrument_id} на дату {conflict.on_date} есть цены от "
            f"{conflict.sources} разных источников. Ограничение "
            "uq_price_instrument_date (без source) допускает только одну "
            "строку на дату — именно сосуществование источников (например, "
            "moex и tbank) эта миграция и разрешила. Автоматический откат "
            "данные не трогает; чтобы продолжить, нужно вручную оставить "
            "одну цену на дату (например, удалить более старый источник) и "
            "повторить откат."
        )

    op.drop_constraint('uq_price_instrument_date_source', 'price', type_='unique')
    op.create_unique_constraint('uq_price_instrument_date', 'price', ['instrument_id', 'on_date'])
    op.drop_column('price', 'currency')
