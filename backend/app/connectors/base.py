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


class BrokerConnector(Protocol):
    source: str

    def fetch_accounts(self) -> list[BrokerAccount]: ...

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]: ...

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]: ...
