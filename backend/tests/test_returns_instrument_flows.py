from datetime import date
from decimal import Decimal

from app.models import Instrument, OperationType
from app.returns.flows import instrument_flows, unattributed_flows
from app.returns.rates import RateBook
from tests.test_returns_flows import add_tx


def add_instrument(session, *, isin: str = "RU000A0JQUZ6", ticker: str = "AGRO",
                   kind: str = "share", currency: str = "RUB") -> Instrument:
    instrument = Instrument(isin=isin, ticker=ticker, kind=kind, currency=currency,
                            issuer=ticker)
    session.add(instrument)
    session.flush()
    return instrument


def test_buy_is_negative_and_sell_is_positive(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-50000", quantity="100", price="500",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 10), amount="60000", quantity="-100", price="600",
           instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert [(flow.on_date, flow.amount) for flow in flows[instrument.id]] == [
        (date(2024, 1, 10), Decimal("-50000.0000")),
        (date(2024, 6, 10), Decimal("60000.0000")),
    ]


def test_dividend_and_coupon_are_positive_flows(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DIVIDEND,
           day=date(2024, 7, 1), amount="3500", instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.COUPON,
           day=date(2024, 8, 1), amount="1200", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert sum(flow.amount for flow in flows[instrument.id]) == Decimal("4700.0000")


def test_fee_of_a_trade_belongs_to_that_trade(session, account):
    """Комиссия сделки — часть её цены, а не отдельное событие: она вычитается
    из потока той же записи."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-50000", fee="150",
           quantity="100", price="500", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert flows[instrument.id][0].amount == Decimal("-50150.0000")


def test_fee_of_a_sale_reduces_the_proceeds(session, account):
    """У продажи комиссия уменьшает выручку, а не увеличивает её: знак у
    потока противоположный покупке, и общее правило «комиссия всегда против
    владельца» проверяется именно здесь."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 10), amount="60000", fee="180",
           quantity="-100", price="600", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert flows[instrument.id][0].amount == Decimal("59820.0000")


def test_flows_without_instrument_go_to_unattributed(session, account):
    """718 комиссий и 20 налогов живых данных не относятся ни к какой бумаге.
    Их место — отдельная строка, а не молчание."""
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 2, 1), amount="-450")
    add_tx(session, account_id=account.id, op_type=OperationType.TAX,
           day=date(2024, 3, 1), amount="-12000")
    add_tx(session, account_id=account.id, op_type=OperationType.OTHER,
           day=date(2024, 4, 1), amount="800",
           payload={"operation_type": "OPERATION_TYPE_TAX_CORRECTION"})

    result = unattributed_flows(session, RateBook.load(session))
    assert result.fees == Decimal("-450.0000")
    assert result.taxes == Decimal("-12000.0000")
    assert result.other == Decimal("800.0000")
    assert result.profit == Decimal("-11650.0000")


def test_cash_moves_are_not_unattributed(session, account):
    """Пополнение счёта — не убыток и не прибыль: это капитал владельца. В
    строке «Прочее» ему делать нечего."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 2, 1), amount="100000")
    result = unattributed_flows(session, RateBook.load(session))
    assert result.profit == Decimal("0.0000")


def test_currency_flows_use_rate_of_their_day(session, account):
    from app.models import FxRate

    instrument = add_instrument(session, isin="US0378331005", ticker="AAPL",
                                currency="USD")
    session.add(FxRate(currency="USD", on_date=date(2021, 5, 4),
                       rate=Decimal("74"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2021, 5, 4), amount="-1000", currency="USD",
           quantity="8", price="125", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert flows[instrument.id][0].amount == Decimal("-74000.0000")


def test_trade_without_rate_is_reported_not_dropped(session, account):
    """Покупка в валюте, у которой нет курса на её дату, выпадает из потоков
    бумаги — и обязана быть названа: иначе сумма по бумагам разойдётся с
    портфелем, а объяснить расхождение будет нечем."""
    from app.returns.flows import unconverted_flows

    instrument = add_instrument(session, isin="HK0000123577", ticker="MEITUAN",
                                currency="HKD")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2021, 6, 1), amount="-5000", currency="HKD",
           quantity="100", price="50", instrument_id=instrument.id)

    book = RateBook.load(session)
    assert instrument_flows(session, book) == {}
    assert unconverted_flows(session, book) == ["HKD"]


def test_period_filters_instrument_flows(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2023, 1, 10), amount="-10000", instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-20000", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session), since=date(2024, 1, 1))
    assert [flow.amount for flow in flows[instrument.id]] == [Decimal("-20000.0000")]
