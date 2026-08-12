from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.yahoo import YahooClient

BASE = "https://query1.finance.yahoo.com"

# Обрезанный настоящий ответ по 9988.HK за 03–06.06.2024. Закрытия приходят
# числами с плавающей точкой и мусором в хвосте (76.6500015258789), метки
# времени — в секундах эпохи на момент открытия торгов, gmtoffset — сдвиг
# биржи (Гонконг +8 часов).
SAMPLE = {
    "chart": {
        "result": [{
            "meta": {"currency": "HKD", "symbol": "9988.HK", "gmtoffset": 28800},
            "timestamp": [1717378200, 1717464600, 1717551000],
            "indicators": {"quote": [{"close": [76.6500015258789, None, 76.94999694824219]}]},
        }],
        "error": None,
    }
}

NOT_FOUND = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}


@respx.mock
def test_returns_daily_closes_and_currency():
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(return_value=httpx.Response(200, json=SAMPLE))

    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 5))

    assert history.currency == "HKD"
    assert history.points == [
        (date(2024, 6, 3), Decimal("76.6500")),
        (date(2024, 6, 5), Decimal("76.9500")),
    ]


@respx.mock
def test_skips_days_without_close():
    """Пустое закрытие — день без торгов, а не ноль: строки для него быть не
    должно вовсе, иначе бумага «подешевела до нуля» на праздник."""
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(return_value=httpx.Response(200, json=SAMPLE))
    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 5))
    assert date(2024, 6, 4) not in [day for day, _ in history.points]


@respx.mock
def test_unknown_symbol_returns_none_instead_of_raising():
    """Несопоставленный символ — обычный исход разовой загрузки истории по
    сотне бумаг, а не сбой: он оставляет бумагу неоценённой на её датах и не
    роняет прогон."""
    respx.get(f"{BASE}/v8/finance/chart/NOSUCH").mock(return_value=httpx.Response(404, json=NOT_FOUND))
    assert YahooClient(BASE).close_history("NOSUCH", date(2024, 6, 3), date(2024, 6, 5)) is None


@respx.mock
def test_requests_the_whole_day_range_and_identifies_itself():
    respx.get(f"{BASE}/v8/finance/chart/U").mock(return_value=httpx.Response(200, json=SAMPLE))

    YahooClient(BASE).close_history("U", date(2024, 6, 3), date(2024, 6, 5))

    request = respx.calls[0].request
    # Конец диапазона — начало следующих суток: иначе последний день выпадает.
    assert request.url.params["period1"] == "1717372800"
    assert request.url.params["period2"] == "1717632000"
    assert request.url.params["interval"] == "1d"
    assert "Mozilla" in request.headers["user-agent"]


@respx.mock
def test_server_error_raises():
    """Отказ сервера — не то же самое, что «нет такого символа»: молча вернуть
    None значит объявить бумагу неоценимой из-за пятисекундной аварии."""
    respx.get(f"{BASE}/v8/finance/chart/U").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        YahooClient(BASE).close_history("U", date(2024, 6, 3), date(2024, 6, 5))
