from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money

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


class YahooClient:
    """Дневные закрытия Yahoo Finance.

    Берётся неприведённое закрытие (`indicators.quote[0].close`), а не
    `adjclose`: количество бумаг в журнале записано таким, каким оно было на ту
    дату, и приведённая к сплитам цена дала бы стоимость позиции мимо в разы —
    у NVDA сплит 10:1 в 2024 году.
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
        response = httpx.get(
            f"{self.base_url}/v8/finance/chart/{symbol}",
            params={
                "period1": str(_day_start(start)),
                # Начало следующих суток: иначе последний день диапазона выпадает.
                "period2": str(_day_start(end + timedelta(days=1))),
                "interval": "1d",
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

        points: list[tuple[date, Decimal]] = []
        for stamp, close in zip(stamps, closes):
            if close is None:
                continue
            # Метка времени — момент открытия торгов в UTC; торговый день
            # берётся в поясе самой биржи, иначе гонконгская сессия у полуночи
            # уезжает на сутки.
            traded = datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date()
            points.append((traded, money(str(close))))

        return YahooHistory(currency=(meta.get("currency") or "").upper(), points=points)
