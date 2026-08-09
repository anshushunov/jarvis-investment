from app.connectors.base import BrokerInstrument
from app.instruments.service import apply_reference
from app.models import Instrument


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
    from app.instruments.backfill import backfill_instruments

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
