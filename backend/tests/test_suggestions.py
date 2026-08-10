"""Гипотезы конвертации: пара «исчезло / появилось ровно столько же».

Величины сравниваются точно. Подгонять близкие числа нельзя: в фазе 2a
«правдоподобный» выбор записи справочника дал ошибки на миллионы, и здесь та же
цена ошибки — неверная налоговая база.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.decisions.suggestions import suggestions_for_account
from app.models import (
    Account, BrokerHolding, Instrument, LedgerDecision, Reconciliation,
)
from app.models.ledger_decision import DecisionKind, DecisionStatus


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _finding(session, account, isin, ledger, broker, status, instrument_id=None):
    session.add(Reconciliation(
        account_id=account.id, instrument_id=instrument_id, isin=isin,
        ledger_quantity=Decimal(ledger), broker_quantity=Decimal(broker),
        status=status,
    ))
    session.flush()


def test_equal_quantities_produce_a_pair(session):
    """Живая пара: 79 iShares HK0000310034 → 79 HK0000051877."""
    account = _account(session)
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker")
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger")

    result = suggestions_for_account(session, account.id)

    assert list(result) == ["HK0000310034", "HK0000051877"]
    suggestion = result["HK0000310034"][0]
    assert suggestion.from_isin == "HK0000310034"
    assert suggestion.to_isin == "HK0000051877"
    assert suggestion.from_quantity == Decimal("79")
    assert suggestion.to_quantity == Decimal("79")
    assert suggestion.ambiguous is False


def test_full_block_at_broker_is_reported(session):
    account = _account(session)
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker")
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger")
    session.add(BrokerHolding(account_id=account.id, instrument_id=None,
                              isin="HK0000051877", quantity=Decimal("79"),
                              blocked=Decimal("79")))
    session.flush()

    suggestion = suggestions_for_account(session, account.id)["HK0000310034"][0]

    assert suggestion.blocked_fully is True


def test_mismatched_quantities_produce_nothing(session):
    """Икс 5 вырос на 45, а излишек ГДР — 5. Пары нет, и выдумывать её нельзя."""
    account = _account(session)
    _finding(session, account, "US98387E2054", "45", "40", "quantity_mismatch")
    _finding(session, account, "RU000A108X38", "96", "141", "quantity_mismatch")

    assert suggestions_for_account(session, account.id) == {}


def test_negative_ledger_quantity_is_not_a_candidate(session):
    """Kyndryl −2 и NVIDIA −3 — следы шортов, конвертировать нечего."""
    account = _account(session)
    _finding(session, account, "US50155Q1004", "-2", "0", "missing_at_broker")
    _finding(session, account, "XX0000000002", "0", "2", "missing_in_ledger")

    assert suggestions_for_account(session, account.id) == {}


def test_two_candidates_with_equal_quantity_are_both_offered_as_ambiguous(session):
    account = _account(session)
    _finding(session, account, "AA0000000001", "10", "0", "missing_at_broker")
    _finding(session, account, "BB0000000001", "0", "10", "missing_in_ledger")
    _finding(session, account, "CC0000000001", "0", "10", "missing_in_ledger")

    offered = suggestions_for_account(session, account.id)["AA0000000001"]

    assert {s.to_isin for s in offered} == {"BB0000000001", "CC0000000001"}
    assert all(s.ambiguous for s in offered)


def test_empty_isin_is_not_offered(session):
    """Строку без ISIN нечем подписать в словаре результата и не с чем сверять.

    Без фильтра «расхождение без ISIN» совпало бы по величине с обычным
    расхождением и породило бы гипотезу, указывающую на пустой ISIN.
    """
    account = _account(session)
    _finding(session, account, "DD0000000001", "15", "0", "missing_at_broker")
    _finding(session, account, None, "0", "15", "missing_in_ledger")

    assert suggestions_for_account(session, account.id) == {}


def test_negative_ledger_row_does_not_pollute_shortage_side(session):
    """Короткая позиция не должна выглядеть кандидатом и на стороне зачисления.

    Правило «шорт — не кандидат» из test_negative_ledger_quantity_is_not_a_candidate
    защищает списывающую сторону. Здесь то же самое проверяется для стороны
    зачисления: наивная арифметика (broker_quantity - ledger_quantity) даёт по
    шорту положительную величину и могла бы случайно совпасть с посторонним
    излишком, породив гипотезу конвертации в бумагу, которой брокер не выдавал.
    """
    account = _account(session)
    _finding(session, account, "US50155Q1004", "-2", "0", "missing_at_broker")
    _finding(session, account, "EE0000000001", "5", "3", "quantity_mismatch")

    assert suggestions_for_account(session, account.id) == {}


def test_rejected_pair_is_not_offered_again(session):
    account = _account(session)
    old = Instrument(isin="HK0000310034", ticker="3010", secid="3010",
                     kind="share", currency="HKD")
    new = Instrument(isin="HK0000051877", ticker="3690", secid="3690",
                     kind="share", currency="HKD")
    session.add_all([old, new])
    session.flush()
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker", old.id)
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger", new.id)

    session.add(LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.REJECTED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Не связаны", proposed={},
    ))
    session.flush()

    assert suggestions_for_account(session, account.id) == {}
