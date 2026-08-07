import ssl
from pathlib import Path
from typing import Any

import certifi
import httpx

DEFAULT_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"

USERS_SERVICE = "tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS_SERVICE = "tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS_SERVICE = "tinkoff.public.invest.api.contract.v1.InstrumentsService"

# T-Bank (бывший Tinkoff) выпускает сертификат *.tinkoff.ru через цепочку
# Минцифры (Russian Trusted Root CA), которой нет в стандартном наборе
# доверенных корней (certifi/Mozilla). Без явного добавления этой цепочки
# TLS-хендшейк с invest-public-api.tinkoff.ru падает с
# CERTIFICATE_VERIFY_FAILED на любой машине, где эта цепочка не установлена
# в системное хранилище. Файл — публичный корневой сертификат, не секрет.
_EXTRA_CA_FILE = Path(__file__).parent / "russian_trusted_ca.pem"


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(_EXTRA_CA_FILE))
    return context


class TBankClient:
    """Тонкий HTTP-клиент REST-шлюза T-Invest API. Никакой бизнес-логики:
    только вызовы читающих методов и разбор JSON-конвертов вида {"поле": [...]}.
    """

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 15.0) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ssl_context = _build_ssl_context()

    def _post(self, service: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}/{service}/{method}",
            json=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            verify=self._ssl_context,
        )
        response.raise_for_status()
        return response.json()

    def get_accounts(self) -> list[dict]:
        return self._post(USERS_SERVICE, "GetAccounts", {}).get("accounts", [])

    def get_operations(self, account_id: str, from_iso: str, to_iso: str) -> list[dict]:
        body = {"accountId": account_id, "from": from_iso, "to": to_iso}
        return self._post(OPERATIONS_SERVICE, "GetOperations", body).get("operations", [])

    def get_portfolio(self, account_id: str) -> list[dict]:
        return self._post(OPERATIONS_SERVICE, "GetPortfolio", {"accountId": account_id}).get("positions", [])

    def get_instrument_by_figi(self, figi: str) -> dict | None:
        body = {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}
        return self._post(INSTRUMENTS_SERVICE, "GetInstrumentBy", body).get("instrument")
