from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.moex import MoexClient, MoexHistoryPoint

BASE = "https://iss.moex.com/iss"
HISTORY = f"{BASE}/history/engines/stock/markets/shares/securities/SBER.json"


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


def _history(rows: list[list], columns: list[str], cursor: list[int] | None = None) -> dict:
    payload = {"history": {"columns": columns, "data": rows}}
    if cursor is not None:
        payload["history.cursor"] = {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [cursor]}
    return payload


@respx.mock
def test_close_history_parses_rows():
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json=_history(
        [["TQBR", "2026-03-10", 310.5, 1000.0], ["TQBR", "2026-03-11", 314.28, 1000.0]],
        ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"],
    )))
    assert MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11)) == [
        MoexHistoryPoint(on_date=date(2026, 3, 10), close=Decimal("310.5000")),
        MoexHistoryPoint(on_date=date(2026, 3, 11), close=Decimal("314.2800")),
    ]


@respx.mock
def test_close_history_walks_all_pages():
    """ISS отдаёт по сто строк на страницу и сообщает это курсором: у SBER за
    шесть лет строк 2851. Без добора страниц метод возвращал первые сто дней и
    выглядел успешным."""
    first = _history([["TQBR", "2026-03-10", 310.5, 1.0]], ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"], [0, 2, 1])
    second = _history([["TQBR", "2026-03-11", 314.28, 1.0]], ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"], [1, 2, 1])
    route = respx.get(HISTORY).mock(side_effect=[httpx.Response(200, json=first),
                                                 httpx.Response(200, json=second)])

    rows = MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11))

    assert [row.on_date for row in rows] == [date(2026, 3, 10), date(2026, 3, 11)]
    assert route.call_count == 2
    assert route.calls[1].request.url.params["start"] == "1"


@respx.mock
def test_close_history_takes_the_board_with_the_largest_turnover():
    """Живой замер 03.06.2024: у SBER борд SMAL дал закрытие 315 при обороте
    32 960 ₽, а основной TQBR — 310.95 при девятнадцати миллиардах. Первая
    строка ответа — SMAL, и брать её значит ошибаться на процент с лишним."""
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json=_history(
        [["SMAL", "2024-06-03", 315, 32960.77], ["TQBR", "2024-06-03", 310.95, 19130763055.2]],
        ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"],
    )))
    rows = MoexClient(BASE).close_history("SBER", date(2024, 6, 3), date(2024, 6, 3))
    assert [row.close for row in rows] == [Decimal("310.9500")]


@respx.mock
def test_close_history_skips_zero_and_missing_closes():
    """Ноль на валютном рынке означает «не торговалось», а не «стоило ноль»:
    живой замер по GLDRUB_TOM 03.06.2024 — CETS 6610, CNGD 0, LICU 0, SPEC 0.
    Колонки VALUE на этом рынке нет вовсе, поэтому при равном обороте
    побеждает первая строка ответа."""
    respx.get(f"{BASE}/history/engines/currency/markets/selt/securities/GLDRUB_TOM.json").mock(
        return_value=httpx.Response(200, json=_history(
            [["CETS", "2024-06-03", 6610], ["CNGD", "2024-06-03", 0],
             ["LICU", "2024-06-03", None], ["CETS", "2024-06-04", 6585], ["CNGD", "2024-06-04", 6617]],
            ["BOARDID", "TRADEDATE", "CLOSE"],
        ))
    )
    rows = MoexClient(BASE).close_history(
        "GLDRUB_TOM", date(2024, 6, 3), date(2024, 6, 4), market="selt", engine="currency"
    )
    assert [(row.on_date, row.close) for row in rows] == [
        (date(2024, 6, 3), Decimal("6610.0000")),
        (date(2024, 6, 4), Decimal("6585.0000")),
    ]


@respx.mock
def test_close_history_carries_face_value_of_the_day():
    """Номинал приходит на каждую дату, и у амортизируемого выпуска он
    меняется по ходу истории: пересчитывать старую цену нынешним номиналом
    нельзя. Живой замер по RU000A1054W1 03.06.2024: FACEVALUE 1000, FACEUNIT
    CNY — облигация российского эмитента с юаневым номиналом."""
    respx.get(f"{BASE}/history/engines/stock/markets/bonds/securities/RU000A1054W1.json").mock(
        return_value=httpx.Response(200, json=_history(
            [["TQCB", "2024-06-03", 91.3995, 2221429.39, 1000, "CNY"],
             ["TQOY", "2024-06-03", 92.7794, 1181540.36, 1000, "CNY"]],
            ["BOARDID", "TRADEDATE", "CLOSE", "VALUE", "FACEVALUE", "FACEUNIT"],
        ))
    )
    rows = MoexClient(BASE).close_history(
        "RU000A1054W1", date(2024, 6, 3), date(2024, 6, 3), market="bonds"
    )
    assert rows == [MoexHistoryPoint(on_date=date(2024, 6, 3), close=Decimal("91.3995"),
                                     face_value=Decimal("1000.0000"), face_unit="CNY")]


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
