from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.marketdata.backfill import _guarded, history_currencies
from app.models import CashBalance, Instrument, OperationType, Transaction


def test_history_currencies_collects_from_all_three_places(session, account):
    """Валюта может встретиться только в одном из трёх мест: в расчётах по
    операции, в справочнике инструмента, в сегодняшнем остатке. Пропустить любое
    значит оставить часть капитала без курса и не узнать об этом."""
    session.add(Instrument(isin="KYG017191142", ticker="9988", secid="9988",
                           kind="share", currency="HKD"))
    session.add(CashBalance(account_id=account.id, currency="EUR",
                            amount=Decimal("1"), blocked=Decimal("0")))
    session.add(Transaction(
        account_id=account.id, instrument_id=None, op_type=OperationType.DEPOSIT,
        executed_at="2024-06-05T10:00:00+00:00", quantity=Decimal("0"),
        price=Decimal("0"), amount=Decimal("1"), currency="CNY", fee=Decimal("0"),
        external_id="a", source="tbank", dedup_key="k-a", payload={},
    ))
    session.flush()

    assert history_currencies(session) == ["CNY", "EUR", "HKD"]


def test_history_currencies_leaves_out_the_base_and_the_metals(session, account):
    """Рубль к рублю — единица, у ЦБ его нет; металлов у ЦБ нет тоже, они идут
    с биржи отдельным прогоном. Спросить их у ЦБ значит получить KeyError."""
    session.add(CashBalance(account_id=account.id, currency="XAU",
                            amount=Decimal("10"), blocked=Decimal("0")))
    session.flush()

    assert history_currencies(session) == []


def test_a_failing_source_does_not_undo_what_another_one_loaded(session):
    """Замер 12.08.2026: MOEX отказал на золоте, и общий коммит на курсы и
    металлы откатил шесть лет уже загруженных курсов ЦБ — работа, к отказу
    отношения не имевшая. Части загрузки независимы, и коммит у каждой свой."""
    def broken():
        raise httpx.ConnectTimeout("биржа недоступна")

    assert _guarded(session, "курсов металлов", broken) == 0


def test_a_successful_load_reports_what_it_wrote(session):
    assert _guarded(session, "курсов ЦБ", lambda: 42) == 42
