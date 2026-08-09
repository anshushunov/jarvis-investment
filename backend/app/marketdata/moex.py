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
    ) -> list[tuple[date, Decimal]]:
        payload = self._get(
            f"/history/engines/{engine}/markets/{market}/securities/{secid}.json",
            params={
                "iss.meta": "off",
                "iss.only": "history",
                "history.columns": "TRADEDATE,SECID,CLOSE",
                "from": start.isoformat(),
                "till": end.isoformat(),
            },
        )
        result: list[tuple[date, Decimal]] = []
        for row in _rows(payload["history"]):
            if row.get("CLOSE") is None:
                continue
            traded = datetime.strptime(row["TRADEDATE"], "%Y-%m-%d").date()
            result.append((traded, money(str(row["CLOSE"]))))
        return result
