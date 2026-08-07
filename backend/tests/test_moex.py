from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.moex import MoexClient

BASE = "https://iss.moex.com/iss"


@respx.mock
def test_last_price_reads_column_by_name():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json={
            "marketdata": {
                "columns": ["SECID", "BOARDID", "LAST", "VALTODAY"],
                "data": [["SBER", "SMAL", None, 0], ["SBER", "TQBR", 314.28, 1000]],
            }
        })
    )
    assert MoexClient(BASE).last_price("SBER") == Decimal("314.2800")


@respx.mock
def test_last_price_returns_none_when_no_trades():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/XXXX.json").mock(
        return_value=httpx.Response(200, json={
            "marketdata": {"columns": ["SECID", "LAST"], "data": [["XXXX", None]]}
        })
    )
    assert MoexClient(BASE).last_price("XXXX") is None


@respx.mock
def test_last_price_returns_none_on_empty_data():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/NOPE.json").mock(
        return_value=httpx.Response(200, json={"marketdata": {"columns": ["SECID", "LAST"], "data": []}})
    )
    assert MoexClient(BASE).last_price("NOPE") is None


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
        MoexClient(BASE).last_price("SBER")
