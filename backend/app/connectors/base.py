from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.ledger.schemas import RawOperation


@dataclass(frozen=True)
class BrokerAccount:
    external_id: str
    name: str
    kind: str


@dataclass(frozen=True)
class BrokerPosition:
    isin: str
    ticker: str | None
    quantity: Decimal


@dataclass(frozen=True)
class BrokerInstrument:
    """Сведения об инструменте из справочника брокера — ровно тот набор, что
    домен умеет записать в таблицу instrument.

    `kind` — уже доменный вид (share/bond/etf/currency/futures/other), а не
    сырое имя из API брокера: перевод делает коннектор, потому что только он
    знает, из какого именно вызова справочника пришёл ответ. Значения видов
    общие для всего проекта — их понимают и ENGINE_MARKET_BY_KIND
    (app/marketdata/service.py, выбор движка и рынка MOEX), и CLASS_BY_KIND
    (app/analytics/service.py, разбивка по классам активов).
    """

    isin: str | None
    ticker: str | None
    kind: str
    name: str | None = None
    # Валюта, в которой номинирован инструмент, — из справочника, а не из
    # платежа операции. Валюта платежа для одной и той же бумаги бывает разной
    # (комиссия и налог по валютной бумаге приходят в рублях), и та из них, что
    # случайно оказалась первой, определяла валюту инструмента навсегда.
    currency: str | None = None


class BrokerConnector(Protocol):
    source: str

    def fetch_accounts(self) -> list[BrokerAccount]: ...

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]: ...

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]: ...
