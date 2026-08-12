from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money
from app.timeutils import moscow_today

# Yahoo отвечает 429 на запросы без опознавательных знаков.
USER_AGENT = "Mozilla/5.0 (compatible; jarvis-investment/1.0)"


@dataclass(frozen=True)
class YahooHistory:
    """Дневные закрытия и валюта, в которой они номинированы.

    Валюта здесь не справочная: по ней вызывающий проверяет, что символ
    сопоставлен верно (см. app/marketdata/symbols.py). Тикер `700` на
    американском рынке — не Tencent, и цена чужой бумаги ничем не отличается
    от настоящей, кроме того, что неверна.
    """

    currency: str
    points: list[tuple[date, Decimal]]


def _day_start(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=timezone.utc).timestamp())


def _splits(result: dict) -> list[tuple[date, Decimal]]:
    """Сплиты периода: дата и во сколько раз выросло количество бумаг."""
    events = ((result.get("events") or {}).get("splits") or {}).values()
    parsed: list[tuple[date, Decimal]] = []
    for event in events:
        numerator = Decimal(str(event.get("numerator") or 0))
        denominator = Decimal(str(event.get("denominator") or 0))
        if not numerator or not denominator:
            continue
        happened = datetime.fromtimestamp(event["date"], tz=timezone.utc).date()
        parsed.append((happened, numerator / denominator))
    return sorted(parsed)


def _unadjust(traded: date, close: Decimal, splits: list[tuple[date, Decimal]]) -> Decimal:
    """Возвращает цену дня такой, какой она в тот день была.

    Yahoo отдаёт ряд, пересчитанный под все позднейшие сплиты: замер 12.08.2026
    по NVDA за 20.01.2021 дал 13.3658 при фактическом закрытии 534.63 —
    делитель 40, сплиты 4:1 (2021) и 10:1 (2024) вместе. Количество бумаг в
    журнале записано дособытийным, и перемножать его с приведённой ценой
    нельзя: позиция занизилась бы ровно в кратность сплита.
    """
    factor = Decimal("1")
    for happened, ratio in splits:
        if happened > traded:
            factor *= ratio
    return close * factor


class YahooClient:
    """Дневные закрытия Yahoo Finance.

    Берётся `indicators.quote[0].close`, а не `adjclose`: второй приведён ещё и
    к дивидендам, а стоимость позиции считается по цене бумаги. Но и первый
    приведён к сплитам, поэтому цена восстанавливается по событиям того же
    ответа (`events=split`, см. `_unadjust`).
    """

    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = (base_url or get_settings().yahoo_base_url).rstrip("/")
        self.timeout = timeout

    def close_history(self, symbol: str, start: date, end: date) -> YahooHistory | None:
        """Закрытия за период включительно. None — такого символа у Yahoo нет.

        Ненайденный символ — обычный исход разовой загрузки по сотне бумаг
        (делистинг, переименование тикера), и он обязан отличаться от отказа
        сервера: первое оставляет бумагу неоценённой, второе требует повтора.
        """
        # Окно запроса тянется до сегодняшнего дня, даже когда спрошен кусок
        # прошлого: события сплитов Yahoo отдаёт только внутри запрошенного
        # окна, а восстановить цену января 2021 года нужно по сплитам, которые
        # случились в 2021 и 2024. Лишние точки отбрасываются ниже; в боевом
        # прогоне их нет вовсе — он и так грузит историю по сегодня.
        last = max(end, moscow_today())
        response = httpx.get(
            f"{self.base_url}/v8/finance/chart/{symbol}",
            params={
                "period1": str(_day_start(start)),
                # Начало следующих суток: иначе последний день диапазона выпадает.
                "period2": str(_day_start(last + timedelta(days=1))),
                "interval": "1d",
                # Сплиты приходят тем же запросом: без них ряд `close`
                # остаётся приведённым, и восстановить цену дня нечем.
                "events": "split",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=self.timeout,
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()

        result = ((response.json().get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None

        meta = result.get("meta") or {}
        offset = int(meta.get("gmtoffset") or 0)
        stamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []

        splits = _splits(result)

        points: list[tuple[date, Decimal]] = []
        for stamp, close in zip(stamps, closes):
            if close is None:
                continue
            # Метка времени — момент открытия торгов в UTC; торговый день
            # берётся в поясе самой биржи, иначе гонконгская сессия у полуночи
            # уезжает на сутки.
            traded = datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date()
            if not start <= traded <= end:
                # Точка из хвоста, добранного ради событий сплитов.
                continue
            points.append((traded, money(_unadjust(traded, Decimal(str(close)), splits))))

        return YahooHistory(currency=(meta.get("currency") or "").upper(), points=points)
