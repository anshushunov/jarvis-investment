import json
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import respx

from app.accounts.cash import store_cash
from app.connectors.base import BrokerAccount, BrokerCash, BrokerInstrument, BrokerPosition, BrokerPrice
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS
from app.connectors.tbank.connector import TBankConnector
from app.models import Account, CashBalance, OperationType

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


def _mock_empty_positions() -> respx.Route:
    """GetPositions без блокировок — для тестов fetch_positions, которым
    заблокированное количество безразлично: fetch_positions (задача 6) читает
    этот вызов наравне с GetPortfolio, и без мока respx роняет тест как
    непредусмотренный запрос."""
    return respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={"money": [], "blocked": [], "securities": []})
    )


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
def test_fetch_accounts_carries_opening_date():
    """Дата открытия счёта — единственный честный ориентир для глубины самой
    первой синхронизации: «сегодня минус N лет» обрезает историю ровно у тех
    счетов, что старше N (см. resolve_since_for_account)."""
    respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(200, json={
            "accounts": [
                {"id": "1000000001", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Инвестиционный",
                 "openedDate": "2020-07-15T00:00:00Z"},
            ]
        })
    )

    accounts = TBankConnector(TOKEN).fetch_accounts()

    assert accounts[0].opened_at == date(2020, 7, 15)


@respx.mock
def test_fetch_accounts_treats_epoch_zero_and_missing_opening_date_as_unknown():
    """Незаполненную дату T-Invest API отдаёт не пустой строкой, а нулём эпохи
    (так приходит closedDate у открытого счёта). Принять её за настоящую значит
    при первой синхронизации запросить историю с 1970 года."""
    respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(200, json={
            "accounts": [
                {"id": "1", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Нулевая дата",
                 "openedDate": "1970-01-01T00:00:00Z"},
                {"id": "2", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Без поля"},
            ]
        })
    )

    accounts = TBankConnector(TOKEN).fetch_accounts()

    assert accounts[0].opened_at is None
    assert accounts[1].opened_at is None


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


def _one_buy(figi: str, op_id: str = "500000004") -> httpx.Response:
    return httpx.Response(200, json={
        "hasNext": False,
        "nextCursor": "",
        "items": [
            {
                "id": op_id,
                "type": "OPERATION_TYPE_BUY",
                "state": "OPERATION_STATE_EXECUTED",
                "date": "2026-03-12T10:30:00Z",
                "figi": figi,
                "quantity": "1",
                "price": {"currency": "rub", "units": "100", "nano": 0},
                "payment": {"currency": "rub", "units": "-100", "nano": 0},
            },
        ],
    })


@respx.mock
def test_oversized_instrument_list_falls_back_to_base_status():
    """Полный справочник (ALL) включает переставшие торговаться инструменты и
    потому нужен, но для облигаций он весит 34 МБ и сервер обрывает ответ на
    ~30-й секунде. Сокращённый (BASE) — 3.4 МБ за 4 секунды (живой замер
    09.08.2026). Взять из него хотя бы торгуемые лучше, чем не взять ничего:
    остаток доберёт поштучное разрешение по FIGI."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(return_value=_one_buy("BBG00T22WKV5"))
    _mock_instrument_lists()

    def by_status(request: httpx.Request) -> httpx.Response:
        # Отказ на ALL — устойчивый, а не разовый: повторы клиента его не
        # переживают, и откат наступает только после того, как они исчерпаны.
        if b"INSTRUMENT_STATUS_ALL" in request.content:
            raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
        return httpx.Response(200, json={"instruments": [
            {"figi": "BBG00T22WKV5", "ticker": "SU26238RMFS4",
             "isin": "RU000A1038V6", "name": "ОФЗ 26238"}
        ]})

    bonds = respx.post(f"{INSTRUMENTS}/Bonds").mock(side_effect=by_status)
    by_figi = respx.post(f"{INSTRUMENTS}/GetInstrumentBy")

    operations = TBankConnector(TOKEN, sleep=lambda _: None).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert operations[0].isin == "RU000A1038V6"
    assert operations[0].payload["instrument_kind"] == "bond"
    # Последняя попытка ушла именно за сокращённым списком, и поштучный запрос не понадобился.
    assert b'"instrumentStatus":"INSTRUMENT_STATUS_BASE"' in bonds.calls[-1].request.content
    assert by_figi.call_count == 0


@respx.mock
def test_unavailable_instrument_list_degrades_to_per_figi_instead_of_failing():
    """Справочник облигаций — 34 МБ, и сервер обрывает его на ~30-й секунде,
    сколько ни повторяй (живой замер 09.08.2026: Shares 11.5 МБ проходят,
    Bonds 34.4 МБ — нет). Один недоступный список не должен ронять
    синхронизацию целого счёта: у коннектора есть поштучное разрешение по
    FIGI, и оно обязано подхватить то, чего не хватило в списках."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(return_value=_one_buy("BBG00T22WKV5"))
    _mock_instrument_lists(Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}])
    respx.post(f"{INSTRUMENTS}/Bonds").mock(
        side_effect=httpx.RemoteProtocolError("peer closed connection without sending complete message body")
    )
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "BBG00T22WKV5", "ticker": "SU26238RMFS4",
                           "isin": "RU000A1038V6", "instrumentType": "bond", "name": "ОФЗ 26238"}
        })
    )

    operations = TBankConnector(TOKEN, sleep=lambda _: None).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert len(operations) == 1
    assert operations[0].isin == "RU000A1038V6"
    assert operations[0].payload["instrument_kind"] == "bond"


@respx.mock
def test_per_figi_resolution_is_reused_across_calls():
    """Поштучный запрос — именно то, что раньше упиралось в ограничение частоты
    (429). Когда списочный метод недоступен, таких запросов становится много, и
    повторять их на каждом счёте прогона нельзя: один и тот же FIGI встречается
    в истории нескольких счетов."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(return_value=_one_buy("TCS00A0EXOTIC"))
    _mock_instrument_lists()
    by_figi = respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0EXOTIC", "ticker": "EXOTIC", "isin": "RU000AEXOTIC",
                           "instrumentType": "bond", "name": "Экзотика"}
        })
    )

    connector = TBankConnector(TOKEN)
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    connector.fetch_operations("1000000001", since)
    connector.fetch_operations("1000000002", since)

    assert by_figi.call_count == 1


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
def test_fetch_instruments_by_figi_is_keyed_by_figi_and_keeps_kind():
    """Справочник для разового дозаполнения (app/instruments/backfill.py):
    инструменты, купленные годы назад, в окно обычной синхронизации не попадают
    никогда — привести их в порядок можно только по справочнику целиком."""
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER",
                 "isin": "RU0009029540", "name": "Сбер Банк"}],
        Bonds=[{"figi": "BBG00T22WKV5", "ticker": "SU26238RMFS4",
                "isin": "RU000A1038V6", "name": "ОФЗ 26238"}],
        # Без ISIN, но с FIGI — в справочник по FIGI попадает наравне с прочими.
        Futures=[{"figi": "FUTSI0324000", "ticker": "SiH4", "name": "Si-3.24"}],
    )

    reference = TBankConnector(TOKEN).fetch_instruments_by_figi()

    assert set(reference) == {"BBG004730N88", "BBG00T22WKV5", "FUTSI0324000"}
    assert reference["BBG00T22WKV5"].kind == "bond"
    assert reference["BBG00T22WKV5"].name == "ОФЗ 26238"
    assert reference["BBG004730N88"].kind == "share"


@respx.mock
def test_fetch_instruments_by_figi_carries_availability_flags():
    """Признак ограничения в обороте (задача 7) собирается из buyAvailableFlag
    и sellAvailableFlag справочника. Флаги обязаны доехать уже через списочный
    путь — тот самый, которым справочник кормит backfill, — а не только через
    поштучный GetInstrumentBy ниже."""
    _mock_instrument_lists(
        Shares=[{"figi": "BBG000BJ35N5", "ticker": "9866", "isin": "HK0000009866",
                 "name": "Nio", "currency": "hkd",
                 "buyAvailableFlag": False, "sellAvailableFlag": False}],
    )

    reference = TBankConnector(TOKEN).fetch_instruments_by_figi()

    instrument = reference["BBG000BJ35N5"]
    assert instrument.buy_available is False
    assert instrument.sell_available is False


@respx.mock
def test_fetch_instruments_by_figi_keeps_every_board_of_the_same_isin():
    """Одному ISIN соответствует по записи на каждую площадку, и различаются
    они и флагами, и валютой: зеркало с рублёвыми расчётами доступно к покупке,
    сама бумага — нет. Коннектор обязан отдать их все: какая из них относится к
    бумаге владельца, знает только домен (по FIGI из журнала операций), а
    схлопывание по ISIN здесь безвозвратно теряет выбор."""
    _mock_instrument_lists(
        Shares=[
            {"figi": "BBG000BBJQV0", "ticker": "NVDA", "isin": "US67066G1040",
             "name": "NVIDIA", "currency": "usd",
             "buyAvailableFlag": False, "sellAvailableFlag": False},
            {"figi": "TCSC326G1040", "ticker": "NVDA-RM", "isin": "US67066G1040",
             "name": "NVIDIA", "currency": "rub",
             "buyAvailableFlag": True, "sellAvailableFlag": True},
        ],
    )

    reference = TBankConnector(TOKEN).fetch_instruments_by_figi()

    assert reference["BBG000BBJQV0"].currency == "USD"
    assert reference["BBG000BBJQV0"].buy_available is False
    assert reference["TCSC326G1040"].currency == "RUB"
    assert reference["TCSC326G1040"].buy_available is True


@respx.mock
def test_fetch_operations_carries_availability_flags_from_get_instrument_by():
    """Тот же признак — но по поштучному запасному пути (FIGI не нашёлся ни в
    одном списочном методе). Оба пути разбираются общей _to_broker_instrument,
    но по отдельности их пока не проверял ни один тест."""
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(return_value=_one_buy("TCS00A0EXOTIC"))
    _mock_instrument_lists()
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0EXOTIC", "ticker": "EXOTIC", "isin": "RU000AEXOTIC",
                           "instrumentType": "bond", "name": "Экзотика",
                           "buyAvailableFlag": False, "sellAvailableFlag": False}
        })
    )

    operations = TBankConnector(TOKEN).fetch_operations(
        "1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert operations[0].payload["instrument_buy_available"] is False
    assert operations[0].payload["instrument_sell_available"] is False


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
    _mock_empty_positions()

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.00000000"),
                       reference=BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share"))
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
    _mock_empty_positions()

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.12345679"),
                       reference=BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share"))
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
    _mock_empty_positions()

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0007661625", ticker="GAZP", quantity=Decimal("5.00000000"),
                       reference=BrokerInstrument(isin="RU0007661625", ticker="GAZP", kind="share"))
    ]


@respx.mock
def test_position_carries_blocked_quantity():
    """У владельца две заблокированные позиции: HK0000123577 с balance=0 и
    blocked=92, HK0000051877 с balance=0 и blocked=79. Проверено на живом API:
    balance + blocked в точности равно quantity из GetPortfolio на всех 43
    бумагах счёта — значит блокировка это часть количества, а не добавка."""
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "TCS000123577",
                    "instrumentType": "etf",
                    "quantity": {"units": "92", "nano": 0},
                    "ticker": "HK0000123577",
                },
            ],
        })
    )
    _mock_instrument_lists(
        Etfs=[{"figi": "TCS000123577", "ticker": "HK0000123577", "isin": "HK0000123577"}],
    )
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [], "blocked": [],
            "securities": [{"figi": "TCS000123577", "balance": "0", "blocked": "92",
                            "ticker": "HK0000123577", "instrumentType": "etf",
                            "exchangeBlocked": False}],
        })
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="HK0000123577", ticker="HK0000123577",
                       quantity=Decimal("92"), blocked=Decimal("92"),
                       reference=BrokerInstrument(isin="HK0000123577", ticker="HK0000123577", kind="etf"))
    ]


@respx.mock
def test_blocked_defaults_to_zero_when_positions_call_unavailable():
    """Счёт типа ACCOUNT_TYPE_DFA не отвечает на GetPositions. Позиции при этом
    читаются из GetPortfolio как раньше — просто без сведений о блокировке."""
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "BBG004730N88",
                    "instrumentType": "share",
                    "quantity": {"units": "10", "nano": 0},
                    "ticker": "SBER",
                },
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(404, json={
            "code": 5, "message": "Account not found", "description": "50004",
        })
    )

    positions = TBankConnector(TOKEN).fetch_positions("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0"),
                       reference=BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share"))
    ]


@respx.mock
def test_fetch_prices_returns_price_in_instrument_currency():
    """GetPortfolio отдаёт currentPrice в валюте бумаги: гонконгская акция — в
    гонконгских долларах, замещающая облигация — в юанях. Это единственный
    источник цены для того, чего MOEX не котирует."""
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "BBG015PB0HH9",
                    "instrumentType": "share",
                    "quantity": {"units": "40", "nano": 0},
                    "currentPrice": {"currency": "hkd", "units": "36", "nano": 900000000},
                },
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[{"figi": "BBG015PB0HH9", "ticker": "9866", "isin": "HK0000009866",
                 "currency": "hkd", "name": "Nio"}],
    )

    prices = TBankConnector(TOKEN).fetch_prices("1000000001")

    assert prices == [BrokerPrice(isin="HK0000009866", price=Decimal("36.9000"), currency="HKD")]


@respx.mock
def test_fetch_prices_skips_position_without_price():
    """Нулевая цена без валюты — то, что брокер присылает по псевдо-позиции
    закрытого счёта. Записать её значит обнулить оценку бумаги."""
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "RUB000UTSTOM",
                    "instrumentType": "currency",
                    "quantity": {"units": "0", "nano": 0},
                    "currentPrice": {"currency": "", "units": "0", "nano": 0},
                },
            ],
        })
    )
    _mock_instrument_lists()
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={"instrument": {}})
    )

    assert TBankConnector(TOKEN).fetch_prices("1000000001") == []


@respx.mock
def test_fetch_cash_reads_money_and_blocked():
    """Денежные остатки лежат в GetPositions.money по валютам. Золото приходит
    там же валютным кодом xau — граммами, и в брокерский итог по счёту оно
    входит наравне с валютами."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [
                {"currency": "rub", "units": "20782", "nano": 270000000},
                {"currency": "usd", "units": "0", "nano": 380000000},
                {"currency": "xau", "units": "10", "nano": 0},
            ],
            "blocked": [{"currency": "rub", "units": "500", "nano": 0}],
            "securities": [],
        })
    )

    cash = TBankConnector(TOKEN).fetch_cash("1000000001")

    assert sorted(cash, key=lambda c: c.currency) == [
        BrokerCash(currency="RUB", amount=Decimal("20782.2700"), blocked=Decimal("500.0000")),
        BrokerCash(currency="USD", amount=Decimal("0.3800"), blocked=Decimal("0")),
        BrokerCash(currency="XAU", amount=Decimal("10.0000"), blocked=Decimal("0")),
    ]


@respx.mock
def test_fetch_cash_keeps_negative_balance():
    """Минус на счёте — не ошибка разбора: на «Копилке» владельца рублёвый
    остаток равен −3571,34. Обнулить его значит завысить капитал."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [{"currency": "rub", "units": "-3571", "nano": -340000000}],
            "blocked": [],
            "securities": [],
        })
    )

    assert TBankConnector(TOKEN).fetch_cash("1000000001") == [
        BrokerCash(currency="RUB", amount=Decimal("-3571.3400"), blocked=Decimal("0"))
    ]


@respx.mock
def test_fetch_cash_returns_empty_when_account_has_no_positions_endpoint():
    """GetPositions отвечает 404 «Account not found» для счёта типа
    ACCOUNT_TYPE_DFA (у владельца это «Смарт-счет»). Один такой счёт не должен
    ронять синхронизацию остальных — денег на нём просто нет."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(404, json={
            "code": 5, "message": "Account not found", "description": "50004",
        })
    )

    assert TBankConnector(TOKEN).fetch_cash("1000000001") == []


@respx.mock
def test_fetch_cash_keeps_currency_blocked_only_without_money_entry():
    """Валюта, вся сумма которой зарезервирована, может отсутствовать в money
    целиком. Если собирать итог проходом только по money, такая валюта — и
    реальные деньги владельца в ней — молча пропадёт из капитала.

    Остаток в ней равен блокировке, а не нулю: по соглашению `blocked` — часть
    `amount` (см. докстринг BrokerCash), и раз распоряжаемой суммы нет вовсе,
    весь остаток и есть заблокированное. Ноль сохранил бы валюту в списке, но
    деньги из капитала всё равно бы выпали."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [{"currency": "rub", "units": "100", "nano": 0}],
            "blocked": [{"currency": "usd", "units": "20", "nano": 0}],
            "securities": [],
        })
    )

    cash = sorted(TBankConnector(TOKEN).fetch_cash("1000000001"), key=lambda c: c.currency)

    assert cash == [
        BrokerCash(currency="RUB", amount=Decimal("100.0000"), blocked=Decimal("0")),
        BrokerCash(currency="USD", amount=Decimal("20.0000"), blocked=Decimal("20.0000")),
    ]


@respx.mock
def test_fetch_cash_sums_duplicate_currency_in_blocked_too():
    """Дубль валюты в blocked сводится так же, как в money. «Последний
    побеждает» здесь занижал недоступную часть: rub 300 плюс rub 200 давали
    200 вместо 500 — деньги на месте, а «недоступно к продаже» врёт."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [{"currency": "rub", "units": "1000", "nano": 0}],
            "blocked": [
                {"currency": "rub", "units": "300", "nano": 0},
                {"currency": "RUB", "units": "200", "nano": 0},
            ],
            "securities": [],
        })
    )

    assert TBankConnector(TOKEN).fetch_cash("1000000001") == [
        BrokerCash(currency="RUB", amount=Decimal("1000.0000"), blocked=Decimal("500.0000"))
    ]


@respx.mock
def test_fetch_cash_deduplicates_same_currency_before_it_reaches_store_cash(session):
    """Дубль валюты в money (в т.ч. разным регистром — 'rub' и 'RUB' после
    нормализации одна и та же валюта) не должен превращаться в две строки
    CashBalance: у таблицы уникальный ключ (account_id, currency), и вторая
    вставка уронила бы SAVEPOINT всего счёта в sync_broker. Тест проходит путь
    целиком — от ответа брокера до store_cash, — потому что поломка была
    именно на стыке: проверка одной только длины списка из fetch_cash не
    поймала бы нарушение уникальности при записи."""
    respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [
                {"currency": "rub", "units": "100", "nano": 0},
                {"currency": "RUB", "units": "50", "nano": 0},
            ],
            "blocked": [],
            "securities": [],
        })
    )

    balances = TBankConnector(TOKEN).fetch_cash("1000000001")

    account = Account(broker="tbank", kind="brokerage", external_id="1000000001",
                      name="Счёт", currency="RUB")
    session.add(account)
    session.flush()

    written = store_cash(session, account, balances)

    assert written == 1
    stored = session.query(CashBalance).all()
    assert [(b.currency, b.amount) for b in stored] == [("RUB", Decimal("150.0000"))]


@respx.mock
def test_fetch_positions_snapshot_is_cached_across_repeated_cash_calls():
    """_get_positions — тот же образец кэша, что и _get_portfolio: второй
    вызов fetch_cash на том же счёте не должен снова ходить в сеть (задача 6
    добавит ещё одного читателя того же снимка)."""
    positions_route = respx.post(f"{OPERATIONS}/GetPositions").mock(
        return_value=httpx.Response(200, json={
            "money": [{"currency": "rub", "units": "100", "nano": 0}],
            "blocked": [],
            "securities": [],
        })
    )

    connector = TBankConnector(TOKEN)
    connector.fetch_cash("1000000001")
    connector.fetch_cash("1000000001")

    assert positions_route.call_count == 1


@respx.mock
def test_fetch_portfolio_snapshot_is_cached_and_reused_between_positions_and_prices():
    """GetPortfolio — один и тот же снимок для fetch_positions и fetch_prices:
    без кэша каждый счёт синхронизации делал бы этот вызов дважды (тот же
    класс проблем, что уже решён для справочника инструментов кэшем
    _bulk_instruments, см. __init__ и комментарий к _portfolio_cache). Побочная
    выгода — позиции и цены читаются из одного снимка, а не из двух разных,
    между которыми цена могла успеть измениться."""
    portfolio_route = respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={
            "positions": [
                {
                    "figi": "BBG004730N88",
                    "instrumentType": "share",
                    "quantity": {"units": "10", "nano": 0},
                    "ticker": "SBER",
                    "currentPrice": {"currency": "rub", "units": "300", "nano": 0},
                },
            ],
        })
    )
    _mock_instrument_lists(
        Shares=[{"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"}],
    )
    _mock_empty_positions()

    connector = TBankConnector(TOKEN)
    positions = connector.fetch_positions("1000000001")
    prices = connector.fetch_prices("1000000001")

    assert positions == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.00000000"),
                       reference=BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share"))
    ]
    assert prices == [BrokerPrice(isin="RU0009029540", price=Decimal("300.0000"), currency="RUB")]
    assert portfolio_route.call_count == 1  # второй вызов взял закэшированный снимок, не сходил в сеть повторно


@respx.mock
def test_fetch_portfolio_snapshot_is_not_mixed_between_accounts():
    """Кэш без ключа по счёту молча подставил бы одному счёту позиции другого —
    это была бы уже не экономия запросов, а порча данных."""
    def by_account(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["accountId"] == "1000000001":
            return httpx.Response(200, json={
                "positions": [
                    {"figi": "BBG004730N88", "instrumentType": "share",
                     "quantity": {"units": "10", "nano": 0}, "ticker": "SBER",
                     "currentPrice": {"currency": "rub", "units": "300", "nano": 0}},
                ],
            })
        return httpx.Response(200, json={
            "positions": [
                {"figi": "BBG0047315Y7", "instrumentType": "share",
                 "quantity": {"units": "5", "nano": 0}, "ticker": "GAZP",
                 "currentPrice": {"currency": "rub", "units": "150", "nano": 0}},
            ],
        })

    portfolio_route = respx.post(f"{OPERATIONS}/GetPortfolio").mock(side_effect=by_account)
    _mock_instrument_lists(
        Shares=[
            {"figi": "BBG004730N88", "ticker": "SBER", "isin": "RU0009029540"},
            {"figi": "BBG0047315Y7", "ticker": "GAZP", "isin": "RU0007661625"},
        ],
    )
    _mock_empty_positions()

    connector = TBankConnector(TOKEN)
    positions_1 = connector.fetch_positions("1000000001")
    prices_1 = connector.fetch_prices("1000000001")
    positions_2 = connector.fetch_positions("1000000002")
    prices_2 = connector.fetch_prices("1000000002")

    assert positions_1 == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10.00000000"),
                       reference=BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share"))
    ]
    assert prices_1 == [BrokerPrice(isin="RU0009029540", price=Decimal("300.0000"), currency="RUB")]
    assert positions_2 == [
        BrokerPosition(isin="RU0007661625", ticker="GAZP", quantity=Decimal("5.00000000"),
                       reference=BrokerInstrument(isin="RU0007661625", ticker="GAZP", kind="share"))
    ]
    assert prices_2 == [BrokerPrice(isin="RU0007661625", price=Decimal("150.0000"), currency="RUB")]
    assert portfolio_route.call_count == 2  # по разу на каждый счёт, снимки не перепутаны


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
    _mock_empty_positions()

    connector = TBankConnector(TOKEN)
    # Разные счета одного прогона на одном и том же экземпляре коннектора —
    # ровно так, как это будет вызывать оркестрация из задачи 16.
    operations = connector.fetch_operations("1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc))
    positions = connector.fetch_positions("1000000002")

    assert len(operations) == 1
    assert operations[0].isin == "RU0009029540"
    assert positions == [
        BrokerPosition(isin="RU0007661625", ticker="GAZP", quantity=Decimal("1.00000000"),
                       reference=BrokerInstrument(isin="RU0007661625", ticker="GAZP", kind="share"))
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
    _mock_empty_positions()

    connector = TBankConnector(TOKEN)
    connector.fetch_operations("1000000001", datetime(2026, 1, 1, tzinfo=timezone.utc))
    positions = connector.fetch_positions("1000000002")

    assert positions == [
        BrokerPosition(isin="RU000AEXOTIC", ticker="EXOTIC", quantity=Decimal("1.00000000"),
                       reference=BrokerInstrument(isin="RU000AEXOTIC", ticker="EXOTIC", kind="other"))
    ]
    for route in routes.values():
        assert route.call_count == 1  # индекс не перестраивался на второй вызов
    assert instrument_by_figi.call_count == 1  # но запасной путь всё равно сработал
