from datetime import datetime, timezone

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.client import TBankClient
from app.connectors.tbank.mapper import map_operation
from app.connectors.tbank.quotation import to_quantity
from app.ledger.schemas import RawOperation

ACCOUNT_KIND = {
    "ACCOUNT_TYPE_TINKOFF": "brokerage",
    "ACCOUNT_TYPE_TINKOFF_IIS": "iis",
}


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TBankConnector:
    """Реализация BrokerConnector поверх TBankClient. Клиент не знает про
    доменные модели (RawOperation, BrokerAccount, ...), коннектор не знает
    про HTTP — вся сетевая часть спрятана в TBankClient."""

    source = "tbank"

    def __init__(self, token: str) -> None:
        self._client = TBankClient(token)

    def fetch_accounts(self) -> list[BrokerAccount]:
        return [
            BrokerAccount(
                external_id=account["id"],
                name=account.get("name") or "Счёт",
                kind=ACCOUNT_KIND.get(account.get("type"), "brokerage"),
            )
            for account in self._client.get_accounts()
        ]

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]:
        operations = self._client.get_operations(
            account_external_id, _rfc3339(since), _rfc3339(datetime.now(tz=timezone.utc))
        )
        instruments = self._instrument_index(operations)

        mapped: list[RawOperation] = []
        for operation in operations:
            figi = operation.get("figi") or None
            isin, ticker = instruments.get(figi, (None, None)) if figi else (None, None)
            result = map_operation(operation, isin=isin, ticker=ticker)
            if result is not None:
                mapped.append(result)
        return mapped

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]:
        positions = []
        for item in self._client.get_portfolio(account_external_id):
            figi = item.get("figi")
            if not figi:
                continue
            qty = to_quantity(item.get("quantity"))
            if qty is None:
                # Отсутствующий или битый объект количества — пропускаем именно
                # эту позицию, а не роняем весь вызов: остальные позиции счёта
                # валидны и должны дойти до журнала.
                continue
            instrument = self._client.get_instrument_by_figi(figi)
            isin = instrument.get("isin") if instrument else None
            if not isin:
                continue
            ticker = item.get("ticker") or (instrument.get("ticker") if instrument else None)
            positions.append(BrokerPosition(isin=isin, ticker=ticker, quantity=qty))
        return positions

    def _instrument_index(self, operations: list[dict]) -> dict[str, tuple[str | None, str | None]]:
        index: dict[str, tuple[str | None, str | None]] = {}
        for figi in {operation.get("figi") for operation in operations if operation.get("figi")}:
            instrument = self._client.get_instrument_by_figi(figi)
            if instrument:
                index[figi] = (instrument.get("isin") or None, instrument.get("ticker") or None)
        return index
