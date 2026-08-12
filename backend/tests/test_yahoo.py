from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.yahoo import YahooClient
from app.timeutils import moscow_today

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

# Ответ со сплитом. Yahoo отдаёт в `close` ряд, уже пересчитанный под все
# позднейшие сплиты: замер 12.08.2026 по NVDA за 20.01.2021 дал 13.3658 при
# фактическом закрытии 534.63 — делитель 40, то есть сплиты 4:1 (июль 2021) и
# 10:1 (июнь 2024) вместе. Событие приходит тем же запросом при events=split.
SPLIT_SAMPLE = {
    "chart": {
        "result": [{
            "meta": {"currency": "USD", "symbol": "NVDA", "gmtoffset": -18000},
            # 20.01.2021, 21.01.2021 и 21.07.2021 — последняя уже после сплита.
            "timestamp": [1611153000, 1611239400, 1626874200],
            "indicators": {"quote": [{"close": [13.3658, 13.5, 5.0]}]},
            "events": {"splits": {
                "1626768000": {"date": 1626768000, "numerator": 4, "denominator": 1,
                                "splitRatio": "4:1"},
            }},
        }],
        "error": None,
    }
}


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
    assert request.url.params["period1"] == "1717372800"
    assert request.url.params["interval"] == "1d"
    assert "Mozilla" in request.headers["user-agent"]
    # Без событий сплитов цену не восстановить: ряд приходит приведённым.
    assert request.url.params["events"] == "split"


@respx.mock
def test_window_reaches_today_so_that_later_splits_are_visible():
    """События сплитов Yahoo отдаёт только внутри запрошенного окна. Спросив
    ровно январь 2021 года, о сплитах 2021 и 2024 годов не узнать — и цена
    NVDA осталась бы приведённой в сорок раз. Лишние точки хвоста
    отбрасываются, в ответе только запрошенные дни."""
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(
        return_value=httpx.Response(200, json=SAMPLE))

    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 4))

    period2 = int(respx.calls[0].request.url.params["period2"])
    tomorrow = datetime.combine(moscow_today() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    assert period2 == int(tomorrow.timestamp())
    assert [day for day, _ in history.points] == [date(2024, 6, 3)]


@respx.mock
def test_price_before_a_split_is_restored_to_what_it_really_was():
    """Ряд Yahoo приведён к сегодняшнему масштабу бумаги, а количество в
    журнале записано таким, каким было на ту дату: 100 акций NVDA в 2021 году —
    это сто дособытийных акций. Перемножить их с приведённой ценой значит
    занизить позицию ровно в кратность сплита — вчетверо здесь и всорок раз на
    живых данных (сплиты 2021 и 2024 вместе)."""
    respx.get(f"{BASE}/v8/finance/chart/NVDA").mock(
        return_value=httpx.Response(200, json=SPLIT_SAMPLE))

    history = YahooClient(BASE).close_history("NVDA", date(2021, 1, 20), date(2021, 7, 21))

    assert history.points[0] == (date(2021, 1, 20), Decimal("53.4632"))
    assert history.points[1] == (date(2021, 1, 21), Decimal("54.0000"))


@respx.mock
def test_price_after_a_split_is_left_alone():
    """Сплит уже случился — цена того дня и есть цена того дня. Домножать её
    значило бы завысить позицию вчетверо там, где количество тоже выросло."""
    respx.get(f"{BASE}/v8/finance/chart/NVDA").mock(
        return_value=httpx.Response(200, json=SPLIT_SAMPLE))

    history = YahooClient(BASE).close_history("NVDA", date(2021, 1, 20), date(2021, 7, 21))

    assert history.points[2] == (date(2021, 7, 21), Decimal("5.0000"))


@respx.mock
def test_series_without_splits_is_taken_as_is():
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(
        return_value=httpx.Response(200, json=SAMPLE))

    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 5))

    assert history.points[0][1] == Decimal("76.6500")


@respx.mock
def test_server_error_raises():
    """Отказ сервера — не то же самое, что «нет такого символа»: молча вернуть
    None значит объявить бумагу неоценимой из-за пятисекундной аварии."""
    respx.get(f"{BASE}/v8/finance/chart/U").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        YahooClient(BASE).close_history("U", date(2024, 6, 3), date(2024, 6, 5))
