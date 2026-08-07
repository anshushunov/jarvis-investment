from datetime import datetime, timezone
from decimal import Decimal

import httpx
import respx

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.connector import TBankConnector
from app.models import OperationType

BASE = "https://invest-public-api.tinkoff.ru/rest"
USERS = f"{BASE}/tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS = f"{BASE}/tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS = f"{BASE}/tinkoff.public.invest.api.contract.v1.InstrumentsService"

TOKEN = "test-token-not-real"  # nosec: тестовое значение, не боевой токен


@respx.mock
def test_fetch_accounts_maps_iis_and_default_kind():
    respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(200, json={
            "accounts": [
                {"id": "1000000001", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Инвестиционный"},
                {"id": "1000000002", "type": "ACCOUNT_TYPE_TINKOFF_IIS", "name": "ИИС"},
                {"id": "1000000003", "type": "ACCOUNT_TYPE_DFA", "name": "Смарт-счет"},
            ]
        })
    )

    accounts = TBankConnector(TOKEN).fetch_accounts()

    assert accounts == [
        BrokerAccount(external_id="1000000001", name="Инвестиционный", kind="brokerage"),
        BrokerAccount(external_id="1000000002", name="ИИС", kind="iis"),
        BrokerAccount(external_id="1000000003", name="Смарт-счет", kind="brokerage"),
    ]


@respx.mock
def test_fetch_operations_resolves_instrument_and_skips_unexecuted():
    respx.post(f"{OPERATIONS}/GetOperations").mock(
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
                },
                {
                    "id": "500000002",
                    "operationType": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_CANCELED",
                    "date": "2026-03-12T11:00:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "5",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-455", "nano": 0},
                    "currency": "rub",
                },
                {
                    "id": "500000003",
                    "operationType": "OPERATION_TYPE_INPUT",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-01T00:00:00Z",
                    "figi": "",
                    "quantity": "0",
                    "price": {"currency": "rub", "units": "0", "nano": 0},
                    "payment": {"currency": "rub", "units": "100000", "nano": 0},
                    "currency": "rub",
                },
            ]
        })
    )
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}
        })
    )

    operations = TBankConnector(TOKEN).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert len(operations) == 2
    assert {op.external_id for op in operations} == {"500000001", "500000003"}

    buy = next(op for op in operations if op.external_id == "500000001")
    assert buy.op_type == OperationType.BUY
    assert buy.isin == "RU0009029540"
    assert buy.ticker == "SBER"
    assert buy.amount == Decimal("-910.0000")

    deposit = next(op for op in operations if op.external_id == "500000003")
    assert deposit.op_type == OperationType.DEPOSIT
    assert deposit.isin is None


@respx.mock
def test_fetch_positions_skips_entries_without_isin():
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "accountId": "1000000001",
            "positions": [
                {
                    "figi": "BBG004730N88",
                    "instrumentType": "share",
                    "quantity": {"units": "10", "nano": 0},
                    "ticker": "SBER",
                },
                {
                    "figi": "",
                    "instrumentType": "currency",
                    "quantity": {"units": "500", "nano": 0},
                    "ticker": "",
                },
            ],
        })
    )
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}
        })
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.00000000"))
    ]
