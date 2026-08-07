import httpx
import pytest
import respx

from app.connectors.tbank.client import TBankClient

BASE = "https://invest-public-api.tinkoff.ru/rest"
USERS = f"{BASE}/tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS = f"{BASE}/tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS = f"{BASE}/tinkoff.public.invest.api.contract.v1.InstrumentsService"

TOKEN = "test-token-not-real"  # nosec: тестовое значение, не боевой токен


@respx.mock
def test_get_accounts_sends_bearer_and_parses_list():
    route = respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(200, json={
            "accounts": [
                {
                    "id": "1000000001",
                    "type": "ACCOUNT_TYPE_TINKOFF",
                    "name": "Инвестиционный",
                    "status": "ACCOUNT_STATUS_OPEN",
                    "openedDate": "2020-07-15T00:00:00Z",
                    "closedDate": "1970-01-01T00:00:00Z",
                    "accessLevel": "ACCOUNT_ACCESS_LEVEL_READ_ONLY",
                }
            ]
        })
    )

    accounts = TBankClient(TOKEN).get_accounts()

    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert route.calls.last.request.headers["Content-Type"] == "application/json"
    assert accounts == [{
        "id": "1000000001",
        "type": "ACCOUNT_TYPE_TINKOFF",
        "name": "Инвестиционный",
        "status": "ACCOUNT_STATUS_OPEN",
        "openedDate": "2020-07-15T00:00:00Z",
        "closedDate": "1970-01-01T00:00:00Z",
        "accessLevel": "ACCOUNT_ACCESS_LEVEL_READ_ONLY",
    }]


@respx.mock
def test_get_accounts_returns_empty_list_when_no_accounts_key():
    respx.post(f"{USERS}/GetAccounts").mock(return_value=httpx.Response(200, json={}))
    assert TBankClient(TOKEN).get_accounts() == []


@respx.mock
def test_get_operations_sends_account_and_period_and_parses_list():
    route = respx.post(f"{OPERATIONS}/GetOperations").mock(
        return_value=httpx.Response(200, json={
            "operations": [
                {
                    "id": "500000001",
                    "operationType": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "10",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-910", "nano": 0},
                    "currency": "rub",
                }
            ]
        })
    )

    operations = TBankClient(TOKEN).get_operations(
        "1000000001", "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"
    )

    sent_body = respx.calls.last.request.content
    assert b'"accountId":"1000000001"' in sent_body
    assert b'"from":"2026-01-01T00:00:00Z"' in sent_body
    assert b'"to":"2026-04-01T00:00:00Z"' in sent_body
    assert len(operations) == 1
    assert operations[0]["id"] == "500000001"


@respx.mock
def test_get_portfolio_returns_positions_list():
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "accountId": "1000000001",
            "positions": [
                {
                    "figi": "BBG004730N88",
                    "instrumentType": "share",
                    "quantity": {"units": "10", "nano": 0},
                    "ticker": "SBER",
                    "classCode": "TQBR",
                }
            ],
        })
    )

    positions = TBankClient(TOKEN).get_portfolio("1000000001")

    assert positions == [{
        "figi": "BBG004730N88",
        "instrumentType": "share",
        "quantity": {"units": "10", "nano": 0},
        "ticker": "SBER",
        "classCode": "TQBR",
    }]


@respx.mock
def test_get_instrument_by_figi_returns_instrument_or_none():
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {
                "figi": "BBG004730N88",
                "ticker": "SBER",
                "isin": "RU0009029540",
                "name": "Сбер Банк",
            }
        })
    )

    instrument = TBankClient(TOKEN).get_instrument_by_figi("BBG004730N88")

    assert instrument["isin"] == "RU0009029540"
    sent_body = respx.calls.last.request.content
    assert b'"idType":"INSTRUMENT_ID_TYPE_FIGI"' in sent_body
    assert b'"id":"BBG004730N88"' in sent_body


@respx.mock
def test_http_error_raises():
    respx.post(f"{USERS}/GetAccounts").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        TBankClient(TOKEN).get_accounts()
