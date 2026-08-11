import ssl
import time
from pathlib import Path
from typing import Any, Callable

import certifi
import httpx

DEFAULT_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"

USERS_SERVICE = "tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS_SERVICE = "tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS_SERVICE = "tinkoff.public.invest.api.contract.v1.InstrumentsService"

OPERATIONS_PAGE_LIMIT = 1000
# Чисто защита от зацикливания, если API когда-нибудь вернёт hasNext=true и
# непустой cursor бесконечно: 500 страниц по 1000 операций — 500 000 операций,
# заведомо больше истории любого реального счёта.
MAX_OPERATIONS_PAGES = 500

# Справочник инструментов отдаёт списки целиком по видам инструментов — это
# используется коннектором, чтобы построить индекс FIGI → инструмент за
# несколько вызовов вместо одного вызова GetInstrumentBy на каждый уникальный
# FIGI (при истории в годы уникальных инструментов набираются сотни, и именно
# это раньше упиралось в ограничение частоты запросов). instrumentStatus=ALL
# (а не BASE) выбран намеренно: BASE не включает инструменты, переставшие
# торговаться (делистинг, заморозка после 2022 года), а именно такие часто
# встречаются в истории операций за несколько лет.
INSTRUMENT_LIST_KINDS = ("Shares", "Bonds", "Etfs", "Currencies", "Futures")
INSTRUMENT_STATUS_ALL = "INSTRUMENT_STATUS_ALL"
# Сокращённый справочник — только торгуемые инструменты. Запасной путь
# коннектора для видов, полный список которых сервер не отдаёт целиком:
# облигации в ALL — 34 МБ и обрыв на ~30-й секунде, в BASE — 3.4 МБ.
INSTRUMENT_STATUS_BASE = "INSTRUMENT_STATUS_BASE"

# Устойчивость к 429 (Too Many Requests): T-Invest API ограничивает частоту
# запросов, и поштучные вызовы (GetInstrumentBy на инструмент, которого нет в
# списочном индексе) — ровно то место, где лимит реально срабатывает при
# синхронизации нескольких счетов подряд. Без повтора один 429 роняет весь
# fetch_operations/fetch_positions вместо того, чтобы подождать и попробовать
# снова.
MAX_RETRY_ATTEMPTS = 5
INITIAL_RETRY_DELAY_SECONDS = 1.0
RETRY_BACKOFF_MULTIPLIER = 2.0
MAX_RETRY_DELAY_SECONDS = 30.0
TOO_MANY_REQUESTS = 429


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Сколько ждать по заголовку Retry-After, если сервер его прислал и
    прислал вменяемое значение. Понимает только форму "число секунд"
    (delta-seconds из RFC 7231) — форму HTTP-date не разбираем: у T-Invest API
    это JSON-шлюз, а не CDN/кеш, и delta-seconds для лимита запросов ожидаема.

    Нечисловое или отрицательное значение трактуем как отсутствие заголовка —
    сервер не может законно просить ждать отрицательное время, а слепая
    передача такого значения в time.sleep() уронит клиент с ValueError вместо
    ожидаемого "попытки исчерпаны, ошибка наружу". Верхний предел
    (MAX_RETRY_DELAY_SECONDS) применяется здесь же, а не только к
    экспоненциальному шагу: без него абсурдно большое значение из заголовка
    заставит клиент спать часами или днями, молча блокируя синхронизацию, а
    не поднимая ошибку."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_DELAY_SECONDS)


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


def _list_field(payload: dict, key: str) -> list:
    """Список из ответа брокера: отсутствующий ключ и явный null — одно и то же.

    `payload.get(key, [])` спасает только от первого. T-Invest API отдаёт null
    там, где список пуст, и тогда наружу уходило None: падение случалось уже у
    вызывающего, за границей коннектора, где причину не видно.
    """
    return payload.get(key) or []


class TBankClient:
    """Тонкий HTTP-клиент REST-шлюза T-Invest API. Никакой бизнес-логики:
    только вызовы читающих методов и разбор JSON-конвертов вида {"поле": [...]}.
    """

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ssl_context = _build_ssl_context()
        # Внедряемая функция паузы — в тестах подменяется на фейк, чтобы
        # повтор при 429 не спал по-настоящему.
        self._sleep = sleep

    def _post(self, service: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{service}/{method}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        delay = INITIAL_RETRY_DELAY_SECONDS
        attempt = 1
        while True:
            try:
                response = httpx.post(
                    url, json=body, headers=headers, timeout=self.timeout, verify=self._ssl_context
                )
            except httpx.TransportError:
                # Обрыв соединения, тайм-аут, сброс сети. Главный источник —
                # списочные методы справочника инструментов: ответ на десятки
                # мегабайт, и он регулярно приходит недокачанным
                # (RemoteProtocolError «peer closed connection without sending
                # complete message body»). Без повтора один такой обрыв ронял
                # синхронизацию целого счёта, а поскольку индекс инструментов
                # строится заново на каждом счёте, за которым он не успел
                # закэшироваться, — подряд и все остальные счета тоже.
                # Исчерпав попытки, ошибку поднимаем: неполный справочник
                # молча превратил бы часть инструментов в неразрешённые.
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise
                self._sleep(delay)
                delay = min(delay * RETRY_BACKOFF_MULTIPLIER, MAX_RETRY_DELAY_SECONDS)
                attempt += 1
                continue
            if response.status_code == TOO_MANY_REQUESTS and attempt < MAX_RETRY_ATTEMPTS:
                retry_after = _retry_after_seconds(response)
                # Ноль — законное "повторяй немедленно"; сравниваем с None
                # явно, чтобы его не подменило собственным экспоненциальным
                # шагом проверкой на истинность (0.0 ложно как bool).
                wait_seconds = retry_after if retry_after is not None else delay
                self._sleep(wait_seconds)
                delay = min(delay * RETRY_BACKOFF_MULTIPLIER, MAX_RETRY_DELAY_SECONDS)
                attempt += 1
                continue
            # Не 429 — обычный успех/ошибка. 429 на последней попытке — тоже
            # сюда: попытки исчерпаны, ошибка обязана всплыть наружу, а не
            # тихо вернуть неполные данные.
            response.raise_for_status()
            return response.json()

    def get_accounts(self) -> list[dict]:
        return _list_field(self._post(USERS_SERVICE, "GetAccounts", {}), "accounts")

    def get_operations(self, account_id: str, from_iso: str, to_iso: str) -> list[dict]:
        """Все операции за период. OperationsService/GetOperations (без курсора)
        молча обрезает ответ первой страницей (на практике — 1000 записей) без
        какого-либо признака обрезки в ответе; для полной истории счёта нужен
        GetOperationsByCursor, который вычитывается здесь до конца (hasNext=false)."""
        items: list[dict] = []
        cursor = ""
        for _ in range(MAX_OPERATIONS_PAGES):
            body: dict[str, Any] = {
                "accountId": account_id,
                "from": from_iso,
                "to": to_iso,
                "limit": OPERATIONS_PAGE_LIMIT,
            }
            if cursor:
                body["cursor"] = cursor
            page = self._post(OPERATIONS_SERVICE, "GetOperationsByCursor", body)
            items.extend(_list_field(page, "items"))
            cursor = page.get("nextCursor") or ""
            if not page.get("hasNext") or not cursor:
                return items
        raise RuntimeError(
            f"GetOperationsByCursor не завершился за {MAX_OPERATIONS_PAGES} страниц "
            "— похоже на зацикливание курсора, а не на реальный объём данных"
        )

    def get_portfolio(self, account_id: str) -> list[dict]:
        return _list_field(self._post(OPERATIONS_SERVICE, "GetPortfolio", {"accountId": account_id}), "positions")

    def get_positions(self, account_id: str) -> dict:
        """OperationsService/GetPositions — денежные остатки и заблокированные
        количества бумаг.

        Это не то же самое, что GetPortfolio: там позиции с оценкой, здесь
        остатки. Заблокированная часть есть только здесь, а деньги здесь
        приходят массивом по валютам, тогда как в GetPortfolio они размазаны по
        псевдо-инструментам (RUB000UTSTOM и подобным)."""
        return self._post(OPERATIONS_SERVICE, "GetPositions", {"accountId": account_id})

    def get_instrument_by_figi(self, figi: str) -> dict | None:
        """Поштучное разрешение одного инструмента по FIGI. Оставлен как
        запасной путь для того, чего не нашлось в list_instruments (см. там же) —
        не как основной способ резолвинга множества инструментов."""
        body = {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}
        return self._post(INSTRUMENTS_SERVICE, "GetInstrumentBy", body).get("instrument")

    def list_instruments(self, kind: str, status: str = INSTRUMENT_STATUS_ALL) -> list[dict]:
        """Список инструментов одного вида (kind — literal-имя метода
        InstrumentsService: один из INSTRUMENT_LIST_KINDS). Несколько таких
        вызовов дают почти полное покрытие FIGI → инструмент за фиксированное
        число запросов вместо одного запроса на каждый уникальный инструмент
        в истории счёта.

        `status` — INSTRUMENT_STATUS_ALL по умолчанию; сокращённый
        INSTRUMENT_STATUS_BASE нужен коннектору как запасной путь для видов,
        полный список которых сервер не отдаёт целиком (см. там же)."""
        body = {"instrumentStatus": status}
        return _list_field(self._post(INSTRUMENTS_SERVICE, kind, body), "instruments")
