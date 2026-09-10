from decimal import Decimal

from app.ai.registry import run_tool
from app.models import Instrument
from tests.test_analytics import add_account, add_priced_position, seed


def test_positions_are_sorted_by_value_with_shares_of_the_whole(session):
    seed(session)
    result = run_tool(session, "positions", {})
    assert [row["name"] for row in result["rows"]] == ["OFZ", "Сбербанк", "TMOS"]
    assert result["rows"][0]["value_rub"] == "5050.00"
    assert result["rows"][0]["share"] == "0.6871"
    assert result["rows"][0]["account"]["title"] == "Брокерский (acc-1)"
    assert result["total_value_rub"] == "7350.00"
    assert isinstance(result["rows"][0]["instrument_id"], int)


def test_positions_filter_by_class_and_refuse_unknown_class(session):
    seed(session)
    bonds = run_tool(session, "positions", {"asset_class": "bonds"})
    assert [row["name"] for row in bonds["rows"]] == ["OFZ"]
    assert "Класса «equities» нет" in run_tool(session, "positions", {"asset_class": "equities"})["error"]


def test_unknown_account_is_refused_with_the_list_of_known(session):
    seed(session)
    error = run_tool(session, "positions", {"account_id": 999})["error"]
    assert "Счёта 999 нет" in error
    assert "Брокерский (acc-1)" in error


def test_unpriced_only_names_the_reason(session):
    account = add_account(session)
    add_priced_position(session, account, "RU000A0JQUZ6", Decimal("5"), price=None)
    add_priced_position(session, account, "RU0009029540", Decimal("1"), Decimal("100"))
    result = run_tool(session, "positions", {"unpriced_only": True})
    assert [row["isin"] for row in result["rows"]] == ["RU000A0JQUZ6"]
    assert result["rows"][0]["value_rub"] is None
    assert "котировки нет" in result["rows"][0]["profit_reason"]


def test_find_instrument_ranks_exact_ticker_first_and_flags_held(session):
    """Два инструмента под одним тикером T — AT&T и Т-Технологии (попутный
    долг роадмепа): оба возвращаются, различить их даёт название и валюта."""
    seed(session)
    session.add_all([
        Instrument(isin="US00206R1023", ticker="T", secid="T", kind="share", currency="USD",
                   issuer="AT&T"),
        Instrument(isin="RU000A107UL4", ticker="T", secid="T", kind="share", currency="RUB",
                   issuer="Т-Технологии"),
    ])
    session.flush()
    result = run_tool(session, "find_instrument", {"query": "T"})
    names = [candidate["name"] for candidate in result["candidates"]]
    assert names[:2] == ["AT&T", "Т-Технологии"]
    assert "разные бумаги" in result["note"]

    sber = run_tool(session, "find_instrument", {"query": "сбер"})["candidates"][0]
    assert sber["ticker"] == "SBER"
    assert sber["held"] is True
    assert sber["asset_class"] == "equity"


def test_find_instrument_with_nothing_found_says_so(session):
    result = run_tool(session, "find_instrument", {"query": "несуществующее"})
    assert result["candidates"] == []
    assert "Ничего не найдено" in result["note"]
