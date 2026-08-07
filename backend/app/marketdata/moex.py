from datetime import date, datetime
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money


def _rows(block: dict) -> list[dict]:
    columns = block["columns"]
    return [dict(zip(columns, row)) for row in block["data"]]


class MoexClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        response = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def last_price(self, secid: str, market: str = "shares", engine: str = "stock") -> Decimal | None:
        payload = self._get(
            f"/engines/{engine}/markets/{market}/securities/{secid}.json",
            params={"iss.meta": "off", "iss.only": "marketdata"},
        )
        for row in _rows(payload["marketdata"]):
            if row.get("LAST") is not None:
                return money(str(row["LAST"]))
        return None

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
