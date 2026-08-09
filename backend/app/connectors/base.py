from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.ledger.schemas import RawOperation


@dataclass(frozen=True)
class BrokerAccount:
    external_id: str
    name: str
    kind: str
    # Дата открытия счёта у брокера, если он её отдаёт. Нужна ровно для одного:
    # задать глубину самой первой синхронизации этого счёта (см.
    # app/sync/service.py, resolve_since_for_account). Необязательное поле —
    # не всякий брокер такое сообщает.
    opened_at: date | None = None


@dataclass(frozen=True)
class BrokerPosition:
    isin: str
    ticker: str | None
    quantity: Decimal


@dataclass(frozen=True)
class BrokerPrice:
    """Цена одной бумаги по данным брокера, в валюте бумаги.

    Запасной источник оценки: у брокера есть цена на всё, что у него лежит,
    включая бумаги, которых нет на MOEX. Независимой такая оценка не является —
    брокер тот же, с чьим снимком мы сверяемся, — поэтому источник цены
    хранится вместе с ней и виден на экране.
    """

    isin: str
    price: Decimal
    currency: str


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

    def fetch_prices(self, account_external_id: str) -> list[BrokerPrice]: ...
