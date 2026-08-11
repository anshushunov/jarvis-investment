import json

import httpx
import pytest
import respx

from app.connectors.tbank.client import (
    INITIAL_RETRY_DELAY_SECONDS,
    MAX_RETRY_ATTEMPTS,
    MAX_RETRY_DELAY_SECONDS,
    TBankClient,
)

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


@pytest.fixture
def client_with_null_items():
    """Транспорт, воспроизводящий реальный ответ T-Invest API на пустой раздел:
    ключ присутствует, но его значение — явный null, а не отсутствие ключа."""
    with respx.mock:
        respx.post(f"{USERS}/GetAccounts").mock(
            return_value=httpx.Response(200, json={"accounts": None})
        )
        respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
            return_value=httpx.Response(200, json={"items": None, "hasNext": False})
        )
        respx.post(f"{OPERATIONS}/GetPortfolio").mock(
            return_value=httpx.Response(200, json={"positions": None})
        )
        yield TBankClient(TOKEN)


def test_null_items_are_treated_as_empty(client_with_null_items):
    """JSON брокера отдаёт null там, где мы ждём список.

    `payload.get("items", [])` спасает от отсутствующего ключа, но не от явного
    null: значение по умолчанию не срабатывает, и наружу уходит None вместо
    списка — падение случается уже у вызывающего, вдали от причины.
    """
    assert client_with_null_items.get_operations("acc-1", "2026-01-01T00:00:00Z",
                                                 "2026-08-11T00:00:00Z") == []
    assert client_with_null_items.get_accounts() == []
    assert client_with_null_items.get_portfolio("acc-1") == []


def _operation_item(op_id: str, cursor: str) -> dict:
    return {
        "id": op_id,
        "cursor": cursor,
        "type": "OPERATION_TYPE_BUY",
        "state": "OPERATION_STATE_EXECUTED",
        "date": "2026-03-12T10:30:00Z",
        "figi": "BBG004730N88",
        "quantity": "10",
        "price": {"currency": "rub", "units": "91", "nano": 0},
        "payment": {"currency": "rub", "units": "-910", "nano": 0},
    }


@respx.mock
def test_get_operations_sends_account_and_period_and_parses_single_page():
    route = respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={
            "hasNext": False,
            "nextCursor": "",
            "items": [_operation_item("500000001", "cursor-1")],
        })
    )

    operations = TBankClient(TOKEN).get_operations(
        "1000000001", "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"
    )

    sent_body = route.calls.last.request.content
    assert b'"accountId":"1000000001"' in sent_body
    assert b'"from":"2026-01-01T00:00:00Z"' in sent_body
    assert b'"to":"2026-04-01T00:00:00Z"' in sent_body
    assert b'"cursor"' not in sent_body  # первая страница курсор не передаёт
    assert len(operations) == 1
    assert operations[0]["id"] == "500000001"


@respx.mock
def test_get_operations_follows_cursor_across_pages_without_loss_or_duplicates():
    # OperationsService/GetOperations (без курсора) молча режет ответ первой
    # страницей — вот почему get_operations обязана дочитать все страницы
    # GetOperationsByCursor, склеив их без потерь и без дублей.
    page_one = {
        "hasNext": True,
        "nextCursor": "cursor-2",
        "items": [_operation_item("500000001", "cursor-1")],
    }
    page_two = {
        "hasNext": False,
        "nextCursor": "",
        "items": [_operation_item("500000002", "cursor-2")],
    }

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("cursor"):
            assert body["cursor"] == "cursor-2"
            return httpx.Response(200, json=page_two)
        return httpx.Response(200, json=page_one)

    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(side_effect=responder)

    operations = TBankClient(TOKEN).get_operations(
        "1000000001", "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"
    )

    assert [op["id"] for op in operations] == ["500000001", "500000002"]


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


@respx.mock
def test_list_instruments_requests_status_all_and_parses_items():
    route = respx.post(f"{INSTRUMENTS}/Shares").mock(
        return_value=httpx.Response(200, json={
            "instruments": [
                {"figi": "BBG004730N88", "isin": "RU0009029540", "ticker": "SBER"},
            ]
        })
    )

    instruments = TBankClient(TOKEN).list_instruments("Shares")

    assert instruments == [{"figi": "BBG004730N88", "isin": "RU0009029540", "ticker": "SBER"}]
    sent_body = route.calls.last.request.content
    assert b'"instrumentStatus":"INSTRUMENT_STATUS_ALL"' in sent_body


@respx.mock
def test_list_instruments_returns_empty_list_when_no_instruments_key():
    respx.post(f"{INSTRUMENTS}/Bonds").mock(return_value=httpx.Response(200, json={}))
    assert TBankClient(TOKEN).list_instruments("Bonds") == []


class _FakeSleep:
    """Записывает паузы вместо того, чтобы реально спать — тесты на повтор
    при 429 не должны занимать секунды реального времени."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@respx.mock
def test_post_retries_on_429_then_succeeds():
    route = respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"accounts": []}),
        ]
    )
    sleep = _FakeSleep()

    accounts = TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert accounts == []
    assert route.call_count == 2
    assert sleep.calls == [INITIAL_RETRY_DELAY_SECONDS]  # без Retry-After — свой экспоненциальный шаг


@respx.mock
def test_post_waits_according_to_retry_after_header():
    respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"accounts": []}),
        ]
    )
    sleep = _FakeSleep()

    TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert sleep.calls == [3.0]


@respx.mock
def test_post_caps_absurdly_large_retry_after_header_at_max_delay():
    # Без верхнего предела клиент честно заснул бы на "сотни лет" — сервер не
    # должен иметь возможность заблокировать суточную синхронизацию значением
    # заголовка. Предел — тот же MAX_RETRY_DELAY_SECONDS, что и у
    # экспоненциального шага.
    respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "999999999"}),
            httpx.Response(200, json={"accounts": []}),
        ]
    )
    sleep = _FakeSleep()

    TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert sleep.calls == [MAX_RETRY_DELAY_SECONDS]


@respx.mock
def test_post_ignores_negative_retry_after_header():
    # Отрицательное значение — не бывает законным Retry-After; наивная
    # передача его в time.sleep() уронила бы клиент с ValueError вместо
    # ожидаемого поведения "повторить с собственной паузой".
    respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "-5"}),
            httpx.Response(200, json={"accounts": []}),
        ]
    )
    sleep = _FakeSleep()

    accounts = TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert accounts == []
    assert sleep.calls == [INITIAL_RETRY_DELAY_SECONDS]


@respx.mock
def test_post_respects_zero_retry_after_header():
    # 0 — законное "повторяй немедленно"; проверка на истинность (0.0 or x)
    # молча подменила бы его на экспоненциальный шаг.
    respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"accounts": []}),
        ]
    )
    sleep = _FakeSleep()

    TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert sleep.calls == [0.0]


@respx.mock
def test_post_retries_when_connection_drops_mid_response():
    """Справочник инструментов — ответ на десятки мегабайт, и он регулярно
    обрывается на полпути (RemoteProtocolError «peer closed connection without
    sending complete message body»). Без повтора один такой обрыв ронял всю
    синхронизацию счёта: на живом прогоне 09.08.2026 так упали пять счетов из
    шести подряд."""
    route = respx.post(f"{INSTRUMENTS}/Shares").mock(
        side_effect=[
            httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
            httpx.Response(200, json={"instruments": [{"figi": "BBG004730N88"}]}),
        ]
    )
    sleep = _FakeSleep()

    instruments = TBankClient(TOKEN, sleep=sleep).list_instruments("Shares")

    assert instruments == [{"figi": "BBG004730N88"}]
    assert route.call_count == 2
    assert sleep.calls == [INITIAL_RETRY_DELAY_SECONDS]


@respx.mock
def test_post_retries_on_read_timeout():
    route = respx.post(f"{USERS}/GetAccounts").mock(
        side_effect=[httpx.ReadTimeout("тайм-аут"), httpx.Response(200, json={"accounts": []})]
    )
    sleep = _FakeSleep()

    assert TBankClient(TOKEN, sleep=sleep).get_accounts() == []
    assert route.call_count == 2


@respx.mock
def test_post_raises_transport_error_after_exhausting_retries():
    """Повтор не должен превращать устойчивый сетевой отказ в тихий неполный
    ответ: попытки исчерпаны — ошибка обязана всплыть наружу."""
    route = respx.post(f"{USERS}/GetAccounts").mock(side_effect=httpx.ConnectError("нет сети"))
    sleep = _FakeSleep()

    with pytest.raises(httpx.TransportError):
        TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert route.call_count == MAX_RETRY_ATTEMPTS
    assert len(sleep.calls) == MAX_RETRY_ATTEMPTS - 1


@respx.mock
def test_post_raises_after_exhausting_retries():
    route = respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(429)
    )
    sleep = _FakeSleep()

    with pytest.raises(httpx.HTTPStatusError):
        TBankClient(TOKEN, sleep=sleep).get_accounts()

    assert route.call_count == MAX_RETRY_ATTEMPTS
    # Пауза только между попытками, после последней — не спим, а поднимаем ошибку.
    assert len(sleep.calls) == MAX_RETRY_ATTEMPTS - 1
