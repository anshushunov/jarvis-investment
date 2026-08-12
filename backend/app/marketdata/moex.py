from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money


@dataclass(frozen=True)
class MoexQuote:
    """Котировка MOEX как она есть, без интерпретации.

    `price` — число из торговых данных: для акций и фондов это цена бумаги, для
    облигаций — процент от номинала. Перевод в деньги делает вызывающий
    (app/marketdata/service.py): он знает вид инструмента, а клиент — нет.
    `face_unit` — валюта номинала в кодах MOEX (`SUR` — рубли)."""

    price: Decimal | None
    face_value: Decimal | None = None
    face_unit: str | None = None


@dataclass(frozen=True)
class MoexHistoryPoint:
    """Закрытие торгового дня как его отдаёт MOEX, без интерпретации.

    `close` для акций и фондов — цена бумаги, для облигаций — процент от
    номинала; `face_value` и `face_unit` относятся к той же дате. Перевод в
    деньги делает вызывающий (app/marketdata/service.py): он знает вид
    инструмента, а клиент — нет.
    """

    on_date: date
    close: Decimal
    face_value: Decimal | None = None
    face_unit: str | None = None


# Колонки истории. Оборот нужен, чтобы выбрать борд (см. _best_of_day); номинал
# — чтобы пересчитать процент облигации в деньги. Рынок, на котором такой
# колонки нет (валютный), молча отдаёт пересечение — поэтому все обращения к
# строке идут через .get().
HISTORY_COLUMNS = "BOARDID,TRADEDATE,CLOSE,VALUE,FACEVALUE,FACEUNIT"


# Поля цены из блока marketdata в порядке предпочтения. Сделка текущей сессии
# (LAST) — лучшее, что есть; за ней последняя текущая цена, затем расчётная
# рыночная цена MOEX и цена закрытия. Одного LAST недостаточно: инструмент,
# который сегодня не торговался, отдаёт по нему пусто — так по выходным ведут
# себя все фонды в портфеле (замер 09.08.2026: у EQMX LAST пуст, MARKETPRICE
# 124.9), и одиннадцать позиций оставались неоценёнными.
PRICE_COLUMNS = ("LAST", "LCURRENTPRICE", "MARKETPRICE", "CLOSEPRICE")


def _rows(block: dict) -> list[dict]:
    columns = block["columns"]
    return [dict(zip(columns, row)) for row in block["data"]]


def _price(rows: list[dict]) -> Decimal | None:
    """Цена из первого доступного поля PRICE_COLUMNS.

    Перебор идёт по полям, а не по строкам: инструмент приходит сразу с
    нескольких бордов, и настоящая сделка на одном важнее расчётной цены на
    другом."""
    for column in PRICE_COLUMNS:
        for row in rows:
            value = row.get(column)
            if value is not None:
                return money(str(value))
    return None


def _face_value(rows: list[dict]) -> tuple[Decimal | None, str | None]:
    for row in rows:
        value = row.get("FACEVALUE")
        if value:
            return money(str(value)), row.get("FACEUNIT")
    return None, None


def _cursor(block: dict | None) -> tuple[int, int, int] | None:
    """Позиция, всего строк и размер страницы. None — курсора в ответе нет,
    добирать нечем."""
    if not block or not block.get("data"):
        return None
    row = dict(zip(block["columns"], block["data"][0]))
    return int(row["INDEX"]), int(row["TOTAL"]), int(row["PAGESIZE"])


def _turnover(row: dict) -> Decimal:
    value = row.get("VALUE")
    return Decimal(str(value)) if value else Decimal("0")


def _best_of_day(rows: list[dict]) -> dict[date, dict]:
    """Одна строка на дату: та, где реально торговали.

    Инструмент приходит сразу с нескольких бордов. Замер 03.06.2024 по SBER:
    борд SMAL дал закрытие 315 при обороте 32 960 ₽, основной TQBR — 310.95
    при девятнадцати миллиардах; первая строка ответа — SMAL. Нулевое и пустое
    закрытие отбрасывается до выбора: ноль на бирже означает «не торговалось»,
    а не «стоило ноль». При равном обороте (на валютном рынке колонки оборота
    нет вовсе) остаётся первая строка ответа.
    """
    best: dict[date, dict] = {}
    for row in rows:
        close = row.get("CLOSE")
        if close is None or close == 0:
            continue
        traded = datetime.strptime(row["TRADEDATE"], "%Y-%m-%d").date()
        if traded not in best or _turnover(row) > _turnover(best[traded]):
            best[traded] = row
    return best


class MoexClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        response = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        """Котировка инструмента вместе с номиналом.

        Номинал приходит тем же запросом (блок securities), а не отдельным:
        облигации котируются в процентах от номинала, и без него котировка —
        не цена. Для акций и фондов он нулевой или отсутствует.
        """
        payload = self._get(
            f"/engines/{engine}/markets/{market}/securities/{secid}.json",
            params={"iss.meta": "off", "iss.only": "securities,marketdata"},
        )
        market_rows = _rows(payload["marketdata"])
        security_rows = _rows(payload.get("securities") or {"columns": [], "data": []})

        face_value, face_unit = _face_value(security_rows)
        return MoexQuote(price=_price(market_rows), face_value=face_value, face_unit=face_unit)

    def close_history(
        self, secid: str, start: date, end: date, market: str = "shares", engine: str = "stock"
    ) -> list[MoexHistoryPoint]:
        """Закрытия торговых дней за период, по одной строке на дату.

        ISS отдаёт историю страницами по сто строк и сообщает об этом курсором:
        у SBER за шесть лет строк 2851. Без добора страниц метод возвращал
        первые сто дней и выглядел работающим — дефект не проявляется на
        коротком диапазоне, а именно такими его и проверяли.
        """
        rows: list[dict] = []
        position = 0
        while True:
            payload = self._get(
                f"/history/engines/{engine}/markets/{market}/securities/{secid}.json",
                params={
                    "iss.meta": "off",
                    "iss.only": "history,history.cursor",
                    "history.columns": HISTORY_COLUMNS,
                    "from": start.isoformat(),
                    "till": end.isoformat(),
                    "start": str(position),
                },
            )
            page = _rows(payload["history"])
            rows.extend(page)
            cursor = _cursor(payload.get("history.cursor"))
            if not page or cursor is None:
                break
            index, total, page_size = cursor
            position = index + page_size
            if position >= total:
                break

        return [
            MoexHistoryPoint(
                on_date=traded,
                close=money(str(row["CLOSE"])),
                face_value=money(str(row["FACEVALUE"])) if row.get("FACEVALUE") else None,
                face_unit=row.get("FACEUNIT"),
            )
            for traded, row in sorted(_best_of_day(rows).items())
        ]
