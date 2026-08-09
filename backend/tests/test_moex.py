from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.moex import MoexClient

BASE = "https://iss.moex.com/iss"


def _payload(marketdata: dict, securities: dict | None = None) -> dict:
    return {"marketdata": marketdata, "securities": securities or {"columns": [], "data": []}}


@respx.mock
def test_quote_reads_column_by_name():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json=_payload({
            "columns": ["SECID", "BOARDID", "LAST", "VALTODAY"],
            "data": [["SBER", "SMAL", None, 0], ["SBER", "TQBR", 314.28, 1000]],
        }))
    )
    assert MoexClient(BASE).quote("SBER").price == Decimal("314.2800")


@respx.mock
def test_quote_falls_back_to_market_price_when_nothing_traded_today():
    """Фонды не торгуются по выходным: LAST пуст на всех бордах, а расчётная
    рыночная цена есть. Замер 09.08.2026 по EQMX: LAST=None, MARKETPRICE=124.9.
    Без этого отката одиннадцать фондов в портфеле оставались неоценёнными."""
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/EQMX.json").mock(
        return_value=httpx.Response(200, json=_payload({
            "columns": ["SECID", "BOARDID", "LAST", "LCURRENTPRICE", "MARKETPRICE"],
            "data": [["EQMX", "TQBR", None, None, 124.9]],
        }))
    )
    assert MoexClient(BASE).quote("EQMX").price == Decimal("124.9000")


@respx.mock
def test_quote_prefers_traded_price_over_calculated_one_across_boards():
    """Отбор идёт по полю, а не по строке: сделка на одном борде важнее
    расчётной цены на другом."""
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json=_payload({
            "columns": ["SECID", "BOARDID", "LAST", "MARKETPRICE"],
            "data": [["SBER", "SPEQ", None, 282.75], ["SBER", "TQBR", 284.14, 282.75]],
        }))
    )
    assert MoexClient(BASE).quote("SBER").price == Decimal("284.1400")


@respx.mock
def test_quote_carries_bond_face_value_and_unit():
    """Облигации котируются в процентах от номинала, поэтому номинал нужен для
    пересчёта в деньги — и приходит он тем же запросом, отдельного не нужно."""
    respx.get(f"{BASE}/engines/stock/markets/bonds/securities/RU000A10EJQ7.json").mock(
        return_value=httpx.Response(200, json=_payload(
            {"columns": ["SECID", "LAST"], "data": [["RU000A10EJQ7", 100.19]]},
            {"columns": ["SECID", "FACEVALUE", "FACEUNIT"], "data": [["RU000A10EJQ7", 1000, "SUR"]]},
        ))
    )
    quote = MoexClient(BASE).quote("RU000A10EJQ7", market="bonds")
    assert quote.price == Decimal("100.1900")
    assert quote.face_value == Decimal("1000.0000")
    assert quote.face_unit == "SUR"


@respx.mock
def test_quote_returns_no_price_when_no_trades():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/XXXX.json").mock(
        return_value=httpx.Response(200, json=_payload(
            {"columns": ["SECID", "LAST"], "data": [["XXXX", None]]}
        ))
    )
    assert MoexClient(BASE).quote("XXXX").price is None


@respx.mock
def test_quote_returns_no_price_on_empty_data():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/NOPE.json").mock(
        return_value=httpx.Response(200, json=_payload({"columns": ["SECID", "LAST"], "data": []}))
    )
    assert MoexClient(BASE).quote("NOPE").price is None


@respx.mock
def test_close_history_parses_rows():
    respx.get(f"{BASE}/history/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json={
            "history": {
                "columns": ["TRADEDATE", "SECID", "CLOSE"],
                "data": [["2026-03-10", "SBER", 310.5], ["2026-03-11", "SBER", 314.28]],
            }
        })
    )
    rows = MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11))
    assert rows == [(date(2026, 3, 10), Decimal("310.5000")), (date(2026, 3, 11), Decimal("314.2800"))]


@respx.mock
def test_http_error_raises():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(httpx.HTTPStatusError):
        MoexClient(BASE).quote("SBER")


@respx.mock
def test_quote_uses_currency_engine_for_currency_market():
    respx.get(f"{BASE}/engines/currency/markets/selt/securities/USD000UTSTOM.json").mock(
        return_value=httpx.Response(200, json=_payload({
            "columns": ["SECID", "LAST"],
            "data": [["USD000UTSTOM", 92.5]],
        }))
    )
    quote = MoexClient(BASE).quote("USD000UTSTOM", market="selt", engine="currency")
    assert quote.price == Decimal("92.5000")
