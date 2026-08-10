from decimal import Decimal

from app.accounts.cash import (
    all_balances,
    blocked_cash_by_account,
    cash_by_account,
    store_cash,
)
from app.connectors.base import BrokerCash
from app.models import Account, CashBalance


def add_account(session, external_id: str = "acc-1") -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id=external_id,
                      name="Счёт", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_stores_balances_per_currency(session):
    account = add_account(session)

    written = store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("20782.27"), blocked=Decimal("0")),
        BrokerCash(currency="XAU", amount=Decimal("10"), blocked=Decimal("0")),
    ])

    assert written == 2
    stored = session.query(CashBalance).order_by(CashBalance.currency).all()
    assert [(b.currency, b.amount) for b in stored] == [
        ("RUB", Decimal("20782.2700")), ("XAU", Decimal("10.0000"))
    ]


def test_currency_gone_from_broker_is_removed(session):
    """Остаток — снимок, а не журнал: валюта, которой у брокера больше нет,
    обязана исчезнуть, иначе проданная валюта вечно висит в капитале."""
    account = add_account(session)
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("100"), blocked=Decimal("0")),
        BrokerCash(currency="EUR", amount=Decimal("1"), blocked=Decimal("0")),
    ])

    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                             blocked=Decimal("0"))])

    assert [b.currency for b in session.query(CashBalance).all()] == ["RUB"]


def test_balances_of_other_accounts_are_untouched(session):
    first = add_account(session, "acc-1")
    second = add_account(session, "acc-2")
    store_cash(session, first, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                           blocked=Decimal("0"))])
    store_cash(session, second, [BrokerCash(currency="USD", amount=Decimal("5"),
                                            blocked=Decimal("0"))])

    store_cash(session, first, [])

    assert [(b.account_id, b.currency) for b in session.query(CashBalance).all()] == [
        (second.id, "USD")
    ]


def test_all_balances_are_ordered_by_account_then_currency(session):
    """Порядок — свойство ответа модуля, а не вкус экрана: он же задаёт порядок
    строк в карточке остатков, и без него две синхронизации подряд могли бы
    переставить строки местами без единого изменения в данных."""
    first = add_account(session, external_id="acc-1")
    second = add_account(session, external_id="acc-2")
    # Второй счёт наполняется раньше первого: порядок задаётся запросом, а не
    # порядком записи.
    store_cash(session, second, [BrokerCash(currency="RUB", amount=Decimal("1"),
                                            blocked=Decimal("0"))])
    store_cash(session, first, [
        BrokerCash(currency="USD", amount=Decimal("2"), blocked=Decimal("0")),
        BrokerCash(currency="CNY", amount=Decimal("3"), blocked=Decimal("0")),
    ])

    assert [(b.account_id, b.currency) for b in all_balances(session)] == [
        (first.id, "CNY"), (first.id, "USD"), (second.id, "RUB"),
    ]


def test_cash_by_account_groups_balances(session):
    account = add_account(session)
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("100"), blocked=Decimal("10")),
        BrokerCash(currency="USD", amount=Decimal("5"), blocked=Decimal("0")),
    ])

    grouped = cash_by_account(session)

    assert grouped[account.id] == {"RUB": Decimal("100.0000"), "USD": Decimal("5.0000")}


def test_blocked_cash_is_reported_apart_from_the_balance(session):
    """Заблокированная часть входит в остаток, а не прибавляется к нему, и
    вопрос про неё — отдельный: «чем нельзя распорядиться», а не «сколько
    денег». Поэтому и функция отдельная, и валюта без блокировки в её ответ не
    попадает вовсе — «заблокировано 0» ничего не сообщает."""
    account = add_account(session)
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("100"), blocked=Decimal("10")),
        BrokerCash(currency="USD", amount=Decimal("5"), blocked=Decimal("0")),
    ])

    assert blocked_cash_by_account(session) == {account.id: {"RUB": Decimal("10.0000")}}


def test_blocked_cash_is_empty_when_nothing_is_blocked(session):
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                             blocked=Decimal("0"))])

    assert blocked_cash_by_account(session) == {}
