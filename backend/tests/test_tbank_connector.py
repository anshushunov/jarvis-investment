from datetime import datetime, timezone
from decimal import Decimal

import httpx
import respx

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS
from app.connectors.tbank.connector import TBankConnector
from app.models import OperationType

BASE = "https://invest-public-api.tinkoff.ru/rest"
USERS = f"{BASE}/tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS = f"{BASE}/tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS = f"{BASE}/tinkoff.public.invest.api.contract.v1.InstrumentsService"

TOKEN = "test-token-not-real"  # nosec: тестовое значение, не боевой токен


def _mock_instrument_lists(**by_kind: list[dict]) -> dict[str, respx.Route]:
    """Мокает все пять списочных методов справочника инструментов
    (INSTRUMENT_LIST_KINDS). По умолчанию каждый отдаёт пустой список; нужный
    вид переопределяется через by_kind, например _mock_instrument_lists(Shares=[...])."""
    routes = {}
    for kind in INSTRUMENT_LIST_KINDS:
        routes[kind] = respx.post(f"{INSTRUMENTS}/{kind}").mock(
            return_value=httpx.Response(200, json={"instruments": by_kind.get(kind, [])})
        )
    return routes


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
def test_fetch_operations_resolves_instrument_via_bulk_list_and_skips_unexecuted():
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000001",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "10",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-910", "nano": 0},
                },
                {
                    "id": "500000002",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_CANCELED",
                    "date": "2026-03-12T11:00:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "5",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-455", "nano": 0},
                },
                {
                    "id": "500000003",
                    "type": "OPERATION_TYPE_INPUT",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-01T00:00:00Z",
                    "figi": "",
                    "quantity": "0",
                    "price": {"currency": "rub", "units": "0", "nano": 0},
                    "payment": {"currency": "rub", "units": "100000", "nano": 0},
                },
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )
    instrument_by_figi = respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={"instrument": {}})
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

    # Инструмент нашёлся в списочном индексе — поштучный запасной путь не нужен.
    assert instrument_by_figi.call_count == 0


@respx.mock
def test_fetch_operations_carries_instrument_kind_from_the_list_it_was_found_in():
    """Вид инструмента известен только по тому, каким списочным методом получен
    ответ (в самих объектах Bond/Etf поля с видом нет) — и обязан доехать до
    payload операции: домену больше неоткуда его узнать."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000010",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "BBG00T22WKV5",
                    "quantity": "5",
                    "price": {"currency": "rub", "units": "1000", "nano": 0},
                    "payment": {"currency": "rub", "units": "-5000", "nano": 0},
                },
                {
                    "id": "500000011",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T11:30:00Z",
                    "figi": "BBG333333333",
                    "quantity": "100",
                    "price": {"currency": "rub", "units": "7", "nano": 0},
                    "payment": {"currency": "rub", "units": "-700", "nano": 0},
                },
            ],
        })
    )
    _mock_instrument_lists(
        Bonds=[{"figi": "BBG00T22WKV5", "ticker": "SU26238RMFS4",
                "isin": "RU000A1038V6", "name": "ОФЗ 26238"}],
        Etfs=[{"figi": "BBG333333333", "ticker": "TMOS",
               "isin": "RU000A101X76", "name": "Тинькофф iMOEX"}],
    )

    operations = {
        op.external_id: op
        for op in TBankConnector(TOKEN).fetch_operations(
            "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
    }

    bond = operations["500000010"]
    assert bond.isin == "RU000A1038V6"
    assert bond.payload["instrument_kind"] == "bond"
    assert bond.payload["instrument_name"] == "ОФЗ 26238"

    etf = operations["500000011"]
    assert etf.payload["instrument_kind"] == "etf"
    assert etf.payload["instrument_name"] == "Тинькофф iMOEX"


@respx.mock
def test_fetch_operations_falls_back_to_get_instrument_by_when_not_in_bulk_lists():
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000004",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "TCS00A0EXOTIC",
                    "quantity": "1",
                    "price": {"currency": "rub", "units": "100", "nano": 0},
                    "payment": {"currency": "rub", "units": "-100", "nano": 0},
                },
            ],
        })
    )
    # Ни один списочный метод не знает этот FIGI (например, структурный продукт
    # или DFA — они не входят в INSTRUMENT_LIST_KINDS).
    _mock_instrument_lists()
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0EXOTIC", "ticker": "EXOTIC", "isin": "RU000AEXOTIC",
                           "instrumentType": "bond", "name": "Экзотика"}
        })
    )

    operations = TBankConnector(TOKEN).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert len(operations) == 1
    assert operations[0].isin == "RU000AEXOTIC"
    assert operations[0].ticker == "EXOTIC"
    # У поштучного запасного пути вид приходит своим полем instrumentType —
    # он тоже обязан доехать, а не потеряться.
    assert operations[0].payload["instrument_kind"] == "bond"
    assert operations[0].payload["instrument_name"] == "Экзотика"


@respx.mock
def test_unknown_instrument_type_becomes_other_not_share():
    """Структурный продукт/опцион/индекс — вид, которому у нас нет
    соответствия. Записать его акцией значит искать котировку не на том рынке и
    показать не в том классе активов; честный ответ — «вид неизвестен»."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000012",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "TCS00A0SPROD",
                    "quantity": "1",
                    "price": {"currency": "rub", "units": "100", "nano": 0},
                    "payment": {"currency": "rub", "units": "-100", "nano": 0},
                },
            ],
        })
    )
    _mock_instrument_lists()
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0SPROD", "ticker": "SP1", "isin": "RU000ASPROD1",
                           "instrumentType": "sp", "name": "Структурная нота"}
        })
    )

    operations = TBankConnector(TOKEN).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert operations[0].payload["instrument_kind"] == "other"


@respx.mock
def test_fetch_instrument_reference_is_keyed_by_isin_and_keeps_kind():
    """Справочник для разового дозаполнения (app/instruments/backfill.py):
    инструменты, купленные годы назад, в окно обычной синхронизации не попадают
    никогда — привести их в порядок можно только по справочнику целиком."""
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER",
                 "isin": "RU0009029540", "name": "Сбер Банк"}],
        Bonds=[{"figi": "BBG00T22WKV5", "ticker": "SU26238RMFS4",
                "isin": "RU000A1038V6", "name": "ОФЗ 26238"}],
        # Без ISIN — в справочник по ISIN попасть не может.
        Futures=[{"figi": "FUTSI0324000", "ticker": "SiH4", "name": "Si-3.24"}],
    )

    reference = TBankConnector(TOKEN).fetch_instrument_reference()

    assert set(reference) == {"RU0009029540", "RU000A1038V6"}
    assert reference["RU000A1038V6"].kind == "bond"
    assert reference["RU000A1038V6"].name == "ОФЗ 26238"
    assert reference["RU0009029540"].kind == "share"


@respx.mock
def test_fetch_operations_without_figis_does_not_call_instrument_lists():
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000005",
                    "type": "OPERATION_TYPE_INPUT",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-01T00:00:00Z",
                    "figi": "",
                    "quantity": "0",
                    "price": {"currency": "rub", "units": "0", "nano": 0},
                    "payment": {"currency": "rub", "units": "100000", "nano": 0},
                },
            ],
        })
    )
    shares_route = respx.post(f"{INSTRUMENTS}/Shares").mock(
        return_value=httpx.Response(200, json={"instruments": []})
    )

    operations = TBankConnector(TOKEN).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert len(operations) == 1
    # Ни одного FIGI в операциях — строить списочный индекс незачем.
    assert shares_route.call_count == 0


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
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.00000000"))
    ]


@respx.mock
def test_fetch_positions_keeps_full_precision_for_fractional_quantity():
    # units=10, nano=123456789: если бы количество сначала округлялось до
    # денежных 4 знаков (money()), а потом расширялось до 8 (quantity()),
    # получилось бы 10.1235 вместо 10.12345679 — регрессия, которую эта
    # проверка и ловит.
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "BBG004730N88",
                    "quantity": {"units": "10", "nano": 123456789},
                    "ticker": "SBER",
                },
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.12345679"))
    ]


@respx.mock
def test_fetch_positions_skips_entry_with_missing_quantity_but_keeps_the_rest():
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {"figi": "BBG004730N88", "quantity": None, "ticker": "SBER"},
                {"figi": "BBG0047315Y7", "quantity": {"units": "5", "nano": 0}, "ticker": "GAZP"},
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[
            {"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"},
            {"figi": "BBG0047315Y7", "ticker": "GAZP", "isin": "RU0007661625"},
        ],
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0007661625", ticker="GAZP", quantity=Decimal("5.00000000"))
    ]


@respx.mock
def test_bulk_instrument_index_is_built_once_and_reused_across_operations_and_positions():
    # Оркестрация создаёт TBankConnector один раз на весь прогон синхронизации
    # (несколько счетов, и операции, и позиции по каждому) — списочные методы
    # не должны запрашиваться заново на каждый такой вызов.
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000001",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "10",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-910", "nano": 0},
                },
            ],
        })
    )
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {"figi": "BBG0047315Y7", "quantity": {"units": "1", "nano": 0}, "ticker": "GAZP"},
            ],
        })
    )
    routes = _mock_instrument_lists(
        Shares=[
            {"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"},
            {"figi": "BBG0047315Y7", "ticker": "GAZP", "isin": "RU0007661625"},
        ],
    )
    instrument_by_figi = respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={"instrument": {}})
    )

    connector = TBankConnector(TOKEN)
    # Разные счета одного прогона на одном и том же экземпляре коннектора —
    # ровно так, как это будет вызывать оркестрация из задачи 16.
    operations = connector.fetch_operations("1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc))
    positions = connector.fetch_positions("1000000002")

    assert len(operations) == 1
    assert operations[0].isin == "RU0009029540"
    assert positions == [
        BrokerPosition(isin="RU0007661625", ticker="GAZP", quantity=Decimal("1.00000000"))
    ]

    for kind, route in routes.items():
        assert route.call_count == 1, f"{kind} должен был запроситься один раз за оба вызова, а не по разу на каждый"
    assert instrument_by_figi.call_count == 0


@respx.mock
def test_fallback_to_get_instrument_by_still_works_after_index_is_cached():
    # Первый вызов строит и кэширует списочный индекс; второй вызов не должен
    # снова дёргать списочные методы, но обязан по-прежнему уметь резолвить
    # через поштучный запасной путь то, чего в закэшированном индексе нет.
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [
                {
                    "id": "500000001",
                    "type": "OPERATION_TYPE_BUY",
                    "state": "OPERATION_STATE_EXECUTED",
                    "date": "2026-03-12T10:30:00Z",
                    "figi": "BBG004730N88",
                    "quantity": "10",
                    "price": {"currency": "rub", "units": "91", "nano": 0},
                    "payment": {"currency": "rub", "units": "-910", "nano": 0},
                },
            ],
        })
    )
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {"figi": "TCS00A0EXOTIC", "quantity": {"units": "1", "nano": 0}, "ticker": ""},
            ],
        })
    )
    routes = _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )
    instrument_by_figi = respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0EXOTIC", "ticker": "EXOTIC", "isin": "RU000AEXOTIC"}
        })
    )

    connector = TBankConnector(TOKEN)
    connector.fetch_operations("1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc))
    positions = connector.fetch_positions("1000000002")

    assert positions == [
        BrokerPosition(isin="RU000AEXOTIC", ticker="EXOTIC", quantity=Decimal("1.00000000"))
    ]
    for route in routes.values():
        assert route.call_count == 1  # индекс не перестраивался на второй вызов
    assert instrument_by_figi.call_count == 1  # но запасной путь всё равно сработал
