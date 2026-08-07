from datetime import datetime, timezone

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS, TBankClient
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
        figis = {operation.get("figi") for operation in operations if operation.get("figi")}
        instruments = self._resolve_instruments(figis)

        mapped: list[RawOperation] = []
        for operation in operations:
            figi = operation.get("figi") or None
            isin, ticker = instruments.get(figi, (None, None)) if figi else (None, None)
            result = map_operation(operation, isin=isin, ticker=ticker)
            if result is not None:
                mapped.append(result)
        return mapped

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]:
        raw_positions = self._client.get_portfolio(account_external_id)
        figis = {item.get("figi") for item in raw_positions if item.get("figi")}
        instruments = self._resolve_instruments(figis)

        positions = []
        for item in raw_positions:
            figi = item.get("figi")
            if not figi:
                continue
            qty = to_quantity(item.get("quantity"))
            if qty is None:
                # Отсутствующий или битый объект количества — пропускаем именно
                # эту позицию, а не роняем весь вызов: остальные позиции счёта
                # валидны и должны дойти до журнала.
                continue
            isin, ticker_from_index = instruments.get(figi, (None, None))
            if not isin:
                continue
            ticker = item.get("ticker") or ticker_from_index
            positions.append(BrokerPosition(isin=isin, ticker=ticker, quantity=qty))
        return positions

    def _resolve_instruments(self, figis: set[str]) -> dict[str, tuple[str | None, str | None]]:
        """Строит индекс FIGI → (isin, ticker) для запрошенных FIGI. Сначала
        строится и живёт только в пределах этого вызова полный список
        инструментов по видам (INSTRUMENT_LIST_KINDS — несколько запросов вне
        зависимости от того, сколько уникальных FIGI встретилось), и только то,
        чего в нём не нашлось, разрешается поштучно через GetInstrumentBy —
        запасной путь, а не основной механизм. Раньше был один GetInstrumentBy
        на каждый уникальный FIGI: за годы истории счёта их набирались сотни,
        и это упиралось в ограничение частоты запросов T-Invest API."""
        if not figis:
            return {}

        bulk_index: dict[str, dict] = {}
        for kind in INSTRUMENT_LIST_KINDS:
            for instrument in self._client.list_instruments(kind):
                bulk_figi = instrument.get("figi")
                if bulk_figi:
                    bulk_index[bulk_figi] = instrument

        index: dict[str, tuple[str | None, str | None]] = {}
        for figi in figis:
            instrument = bulk_index.get(figi) or self._client.get_instrument_by_figi(figi)
            if instrument:
                index[figi] = (instrument.get("isin") or None, instrument.get("ticker") or None)
        return index
