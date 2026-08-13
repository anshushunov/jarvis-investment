from datetime import date, datetime, time
from decimal import Decimal
from itertools import count

from app.models import Account, FxRate, OperationType, Transaction
from app.returns.flows import account_flows, portfolio_flows
from app.returns.rates import RateBook
from app.timeutils import MOSCOW_TZ

_ids = count(1)


def add_tx(session, *, account_id: int, op_type: OperationType, day: date, amount: str,
           currency: str = "RUB", instrument_id: int | None = None,
           quantity: str = "0", price: str = "0", fee: str = "0",
           payload: dict | None = None, at_hour: int = 12) -> Transaction:
    """Запись журнала для теста. Тесты потоков поднимают данные ИЗ БАЗЫ, а не
    строят LedgerEntry в памяти: op_type приходит из строковой колонки, и
    сравнение с членом enum на объекте из памяти ничего не доказывает
    (правило фазы 2b, tests/test_operation_type_enum.py)."""
    number = next(_ids)
    tx = Transaction(
        account_id=account_id, instrument_id=instrument_id, op_type=op_type,
        executed_at=datetime.combine(day, time(at_hour, 0), tzinfo=MOSCOW_TZ),
        quantity=Decimal(quantity), price=Decimal(price), amount=Decimal(amount),
        currency=currency, fee=Decimal(fee), external_id=f"ext-{number}",
        source="test", dedup_key=f"dedup-{number}", payload=payload or {},
    )
    session.add(tx)
    session.flush()
    return tx


def second_account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-2",
                      name="Копилка", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_deposit_is_negative_flow(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert [(flow.on_date, flow.amount) for flow in flows] == [
        (date(2024, 3, 1), Decimal("-100000.0000"))
    ]


def test_withdrawal_is_positive_flow(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-25000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].amount == Decimal("25000.0000")


def test_transfer_between_own_accounts_is_not_a_flow(session, account):
    """Живой случай 12.09.2022: 25 000 ₽ со счёта 7 на счёт 1. Для портфеля это
    перекладывание, а не приход капитала извне."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2022, 9, 12), amount="25000")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2022, 9, 12), amount="-25000")
    assert portfolio_flows(session, RateBook.load(session)) == []


def test_multi_transfer_hidden_in_other_is_also_a_pair(session, account):
    """Живой случай 13.04.2026: та же пара переводов лежит в журнале с
    op_type=OTHER, потому что брокер прислал её как INP_MULTI/OUT_MULTI. Читать
    только op_type — значит не увидеть 40 000 ₽ движения вовсе."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.OTHER,
           day=date(2026, 4, 13), amount="40000",
           payload={"operation_type": "OPERATION_TYPE_INP_MULTI"})
    add_tx(session, account_id=other.id, op_type=OperationType.OTHER,
           day=date(2026, 4, 13), amount="-40000",
           payload={"operation_type": "OPERATION_TYPE_OUT_MULTI"})
    assert portfolio_flows(session, RateBook.load(session)) == []


def test_same_account_pair_is_not_a_transfer(session, account):
    """Ввод и вывод одной суммы в один день на ОДНОМ счёте переводом между
    своими счетами не являются: перекладывать некуда."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="10000")
    add_tx(session, account_id=account.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-10000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert sorted(flow.amount for flow in flows) == [
        Decimal("-10000.0000"), Decimal("10000.0000")
    ]


def test_different_currency_is_not_a_pair(session, account):
    other = second_account(session)
    session.add(FxRate(currency="USD", on_date=date(2024, 3, 1),
                       rate=Decimal("90"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="1000", currency="USD")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-1000", currency="RUB")
    flows = portfolio_flows(session, RateBook.load(session))
    assert len(flows) == 2


def test_account_perimeter_keeps_the_transfer(session, account):
    """Тот же перевод в разрезе по счёту — настоящий поток: для счёта деньги
    действительно пришли."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2022, 9, 12), amount="25000")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2022, 9, 12), amount="-25000")
    flows = account_flows(session, RateBook.load(session), account.id)
    assert [flow.amount for flow in flows] == [Decimal("-25000.0000")]


def test_currency_flow_is_converted_by_rate_of_its_day(session, account):
    """Курс берётся на дату операции, а не сегодняшний: доллар 2021 года стоил
    других денег, и пересчёт по сегодняшнему курсу превратил бы вложение в
    другое число."""
    session.add(FxRate(currency="USD", on_date=date(2021, 6, 1),
                       rate=Decimal("72.5"), source="cbr"))
    session.add(FxRate(currency="USD", on_date=date(2026, 8, 1),
                       rate=Decimal("81"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 6, 1), amount="1000", currency="USD")
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].amount == Decimal("-72500.0000")


def test_flow_without_rate_is_reported_not_dropped(session, account):
    """Поток без курса не выбрасывается молча: он попадает в отдельный список,
    и служба обязана назвать его в покрытии."""
    from app.returns.flows import unconverted_flows

    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 6, 1), amount="1000", currency="HKD")
    book = RateBook.load(session)
    assert portfolio_flows(session, book) == []
    assert unconverted_flows(session, book) == ["HKD"]


def test_period_bounds_are_inclusive(session, account):
    for day in (date(2024, 1, 1), date(2024, 6, 1), date(2024, 12, 31)):
        add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
               day=day, amount="1000")
    flows = portfolio_flows(session, RateBook.load(session),
                            since=date(2024, 6, 1), until=date(2024, 12, 31))
    assert [flow.on_date for flow in flows] == [date(2024, 6, 1), date(2024, 12, 31)]


def test_late_evening_operation_belongs_to_moscow_day(session, account):
    """23:30 по Москве — это ещё сегодня, хотя по UTC уже 20:30. Дата потока
    обязана считаться в том же поясе, что и дата снимка (app/timeutils.py)."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="1000", at_hour=23)
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].on_date == date(2024, 3, 1)
