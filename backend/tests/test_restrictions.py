from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.connectors.base import BrokerInstrument
from app.instruments.backfill import _restricted_from as backfill_restricted
from app.instruments.backfill import backfill_instruments
from app.instruments.service import apply_reference, resolve_instrument, trading_restricted_from_flags
from app.ledger.schemas import RawOperation
from app.models import Instrument, OperationType
from app.sync.holdings import _restricted_from as holdings_restricted


def add_instrument(session, isin: str, restricted: bool = False) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="share",
                            currency="RUB", trading_restricted=restricted)
    session.add(instrument)
    session.flush()
    return instrument


def test_instrument_is_restricted_when_neither_buy_nor_sell_available(session):
    """Гонконгская акция: купить нельзя, продать нельзя. Именно так выглядят в
    справочнике все иностранные бумаги портфеля."""
    instrument = add_instrument(session, "HK0000009866")

    changed = apply_reference(instrument, "share", "Nio", "HKD", restricted=True)

    assert changed is True
    assert instrument.trading_restricted is True


def test_restriction_is_lifted_when_broker_says_so(session):
    """False — законное значение, а не «сведений нет». Если бумагу разблокируют,
    признак обязан сняться сам, без ручной правки базы."""
    instrument = add_instrument(session, "RU0009029540", restricted=True)

    changed = apply_reference(instrument, "share", "Сбербанк", "RUB", restricted=False)

    assert changed is True
    assert instrument.trading_restricted is False


def test_unknown_restriction_does_not_touch_the_flag(session):
    """Справочник флагов не дал — прежнее значение сохраняется. Так приходят
    операции, записанные до появления флагов в payload."""
    instrument = add_instrument(session, "RU0009029540", restricted=True)

    apply_reference(instrument, "share", "Сбербанк", "RUB", restricted=None)

    assert instrument.trading_restricted is True


def test_broker_instrument_carries_availability_flags():
    """Флаги едут через границу коннектора отдельными полями, а не одним уже
    вычисленным признаком: решение «оба false значит нельзя распорядиться» —
    доменное, и принимать его коннектору не положено."""
    instrument = BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                  buy_available=False, sell_available=False)

    assert (instrument.buy_available, instrument.sell_available) == (False, False)


def test_backfill_marks_restricted_instruments(session):
    add_instrument(session, "HK0000009866")
    # issuer выставлен заранее и совпадает с тем, что вернёт справочник: иначе
    # дозаполнение название всё равно засчитает как изменение (issuer был
    # None), и тест перестанет отличать эффект признака ограничения от эффекта
    # дозаполнения имени — а проверить нужно именно первое.
    sber = add_instrument(session, "RU0009029540")
    sber.issuer = "Сбербанк"
    session.flush()

    changed = backfill_instruments(session, {
        "HK0000009866": BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                         name="Nio", currency="HKD",
                                         buy_available=False, sell_available=False),
        "RU0009029540": BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share",
                                         name="Сбербанк", currency="RUB",
                                         buy_available=True, sell_available=True),
    })

    assert changed == 1
    restricted = {i.isin: i.trading_restricted for i in session.query(Instrument).all()}
    assert restricted == {"HK0000009866": True, "RU0009029540": False}


def test_sell_only_instrument_is_not_restricted(session):
    """Купить нельзя, продать можно — распоряжению поддаётся. Ограничением
    считается только пара недоступных операций."""
    instrument = add_instrument(session, "RU000A1054W1")

    apply_reference(instrument, "bond", "Выпуск", "RUB", restricted=None)
    changed = apply_reference(instrument, "bond", "Выпуск", "RUB", restricted=False)

    assert changed is False
    assert instrument.trading_restricted is False


def _buy_with_flags(isin: str, buy: bool, sell: bool) -> RawOperation:
    """Операция покупки с флагами доступности в payload — ровно то, что кладёт
    туда app/connectors/tbank/mapper.py. Нужна, чтобы гонять правило
    ограничения через настоящий канал операций (resolve_instrument), а не
    подставлять готовый restricted напрямую."""
    return RawOperation(
        external_id=f"op-{isin}", op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        isin=isin, ticker=isin, quantity=Decimal("1"),
        price=Decimal("1"), amount=Decimal("-1"), currency="RUB",
        fee=Decimal("0"),
        payload={
            "instrument_kind": "share",
            "instrument_name": "Тест",
            "instrument_currency": "RUB",
            "instrument_buy_available": buy,
            "instrument_sell_available": sell,
        },
    )


# Четыре комбинации флагов, короткий код для ISIN и единственно верный
# результат правила «ограничена только пара недоступных операций сразу».
# Одна и та же таблица используется для обоих каналов ниже — так расхождение
# между ними стало бы видно сразу. Код — не префикс имени (у "both_available"
# и "both_unavailable" он совпал бы и склеил ISIN двух разных случаев).
_FLAG_COMBINATIONS = [
    ("both_available", "BA", True, True, False),
    ("both_unavailable", "BU", False, False, True),
    ("buy_only", "BO", True, False, False),
    ("sell_only", "SO", False, True, False),
]


def test_restriction_rule_covers_all_four_flag_combinations_via_operations_channel(session):
    """Самое рискованное место всей задачи: правило «ограничением считается
    недоступность ОБЕИХ операций сразу» (trading_restricted_from_flags в
    app/instruments/service.py). Опечатка `and` -> `or` даёт то же самое на
    двух прежних тестах (там всегда обе доступны или обе недоступны) — здесь
    же участвуют все четыре комбинации, и смешанные обязаны остаться
    неограниченными.

    Канал — настоящий: resolve_instrument на новой операции создаёт
    инструмент через _insert_instrument -> _reference_from ->
    trading_restricted_from_flags, а не через подстановку restricted в
    apply_reference напрямую."""
    for name, code, buy, sell, expected in _FLAG_COMBINATIONS:
        isin = f"RU0OPCH000{code}"
        instrument = resolve_instrument(session, _buy_with_flags(isin, buy, sell))
        assert instrument.trading_restricted is expected, name


def test_restriction_rule_covers_all_four_flag_combinations_via_backfill_channel(session):
    """То же правило, но второй, независимый путь его вычисления —
    _restricted_from в app/instruments/backfill.py, по флагам
    BrokerInstrument напрямую, без похода через RawOperation.payload."""
    reference = {}
    for name, code, buy, sell, _expected in _FLAG_COMBINATIONS:
        isin = f"RU0BFCH000{code}"
        add_instrument(session, isin)
        reference[isin] = BrokerInstrument(isin=isin, ticker=isin, kind="share",
                                           buy_available=buy, sell_available=sell)

    backfill_instruments(session, reference)

    for name, code, _buy, _sell, expected in _FLAG_COMBINATIONS:
        isin = f"RU0BFCH000{code}"
        instrument = session.query(Instrument).filter_by(isin=isin).one()
        assert instrument.trading_restricted is expected, name


def test_trading_restricted_rule_lives_in_one_place():
    """Правило «ограничена в обороте» существует в одном экземпляре.

    Три копии этого правила уже расходились в проекте: два правила о знаке
    ADJUSTMENT дали позицию в 276 бумаг вместо 100. Тест проверяет не поведение,
    а само отсутствие копий — поведение проверяют тесты ниже.
    """
    assert backfill_restricted is trading_restricted_from_flags
    assert holdings_restricted is trading_restricted_from_flags


@pytest.mark.parametrize(
    ("buy", "sell", "expected"),
    [
        (False, False, True),    # ни купить, ни продать — ограничение
        (False, True, False),    # закрыта для покупки, но продать можно
        (True, False, False),
        (True, True, False),
        (None, False, None),     # сведений нет — прежнее значение не трогаем
        (False, None, None),
        (None, None, None),
        ("false", "false", None),  # не bool — не сведения
    ],
)
def test_trading_restricted_from_flags(buy, sell, expected):
    assert trading_restricted_from_flags(buy, sell) is expected
