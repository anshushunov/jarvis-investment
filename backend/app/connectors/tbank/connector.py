from datetime import datetime, timezone

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.client import TBankClient
from app.connectors.tbank.mapper import map_operation
from app.ledger.schemas import RawOperation
from app.money import quantity, quotation_to_decimal

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
            instrument = self._client.get_instrument_by_figi(figi)
            isin = instrument.get("isin") if instrument else None
            if not isin:
                continue
            ticker = item.get("ticker") or (instrument.get("ticker") if instrument else None)
            positions.append(
                BrokerPosition(
                    isin=isin,
                    ticker=ticker,
                    quantity=quantity(
                        quotation_to_decimal(int(item["quantity"]["units"]), int(item["quantity"]["nano"]))
                    ),
                )
            )
        return positions

    def _instrument_index(self, operations: list[dict]) -> dict[str, tuple[str | None, str | None]]:
        index: dict[str, tuple[str | None, str | None]] = {}
        for figi in {operation.get("figi") for operation in operations if operation.get("figi")}:
            instrument = self._client.get_instrument_by_figi(figi)
            if instrument:
                index[figi] = (instrument.get("isin") or None, instrument.get("ticker") or None)
        return index
