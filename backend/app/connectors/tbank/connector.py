import logging
import time
from datetime import date, datetime, timezone
from typing import Callable

import httpx

from app.connectors.base import BrokerAccount, BrokerInstrument, BrokerPosition
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS, INSTRUMENT_STATUS_BASE, TBankClient
from app.connectors.tbank.mapper import map_operation
from app.connectors.tbank.quotation import to_quantity
from app.instruments import kinds
from app.ledger.schemas import RawOperation

ACCOUNT_KIND = {
    "ACCOUNT_TYPE_TINKOFF": "brokerage",
    "ACCOUNT_TYPE_TINKOFF_IIS": "iis",
}

# Вид инструмента по имени списочного метода справочника (INSTRUMENT_LIST_KINDS):
# сами объекты Share/Bond/Etf/... поля с видом не несут — вид известен только из
# того, каким методом список был получен. Значения — общие доменные (app/instruments/kinds.py).
KIND_BY_LIST_METHOD = {
    "Shares": kinds.SHARE,
    "Bonds": kinds.BOND,
    "Etfs": kinds.ETF,
    "Currencies": kinds.CURRENCY,
    "Futures": kinds.FUTURES,
}

# Вид инструмента по полю instrumentType поштучного ответа
# InstrumentsService/GetInstrumentBy — запасной путь, у которого вид приходит
# прямо в ответе. Всё, чему тут нет соответствия (структурные продукты, опционы,
# индексы), — kinds.OTHER: лучше честное «вид неизвестен», чем ложная акция.
logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

KIND_BY_INSTRUMENT_TYPE = {
    "share": kinds.SHARE,
    "bond": kinds.BOND,
    "etf": kinds.ETF,
    "currency": kinds.CURRENCY,
    "futures": kinds.FUTURES,
}


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opened_date(raw: dict) -> date | None:
    """Дата открытия счёта из GetAccounts, если она осмысленна.

    Незаполненную дату T-Invest API отдаёт не пустой строкой и не отсутствием
    ключа, а нулём эпохи — так, например, приходит closedDate у открытого
    счёта. Принять такое значение за настоящую дату открытия значит запросить
    при первой синхронизации историю с 1970 года."""
    value = raw.get("openedDate")
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    if moment <= EPOCH:
        return None
    return moment.date()


def _to_broker_instrument(raw: dict, kind: str) -> BrokerInstrument:
    """Общий разбор объекта справочника: и списочные методы, и GetInstrumentBy
    отдают одинаково названные поля (isin, ticker, name, currency) — различается
    только то, откуда берётся вид. Валюта у T-Invest в нижнем регистре ("usd"),
    в домене хранится в верхнем."""
    currency = raw.get("currency") or None
    return BrokerInstrument(
        isin=raw.get("isin") or None,
        ticker=raw.get("ticker") or None,
        kind=kind,
        name=raw.get("name") or None,
        currency=currency.upper() if currency else None,
    )


class TBankConnector:
    """Реализация BrokerConnector поверх TBankClient. Клиент не знает про
    доменные модели (RawOperation, BrokerAccount, ...), коннектор не знает
    про HTTP — вся сетевая часть спрятана в TBankClient."""

    source = "tbank"

    def __init__(self, token: str, sleep: Callable[[float], None] = time.sleep) -> None:
        # `sleep` пробрасывается в клиент и существует ровно затем же, зачем он
        # есть у клиента: тесты на исчерпание повторов не должны спать
        # по-настоящему. Откат к сокращённому справочнику (_list_instruments)
        # наступает только после того, как повторы клиента исчерпаны, — без
        # этого шва такой тест занимал бы полтора десятка секунд реального
        # времени.
        self._client = TBankClient(token, sleep=sleep)
        # Индекс FIGI → инструмент из списочных методов — построен лениво (при
        # первом обращении, которому реально есть что резолвить) и
        # переиспользуется всеми последующими fetch_operations/fetch_positions
        # на этом экземпляре коннектора, по всем счетам одного прогона
        # синхронизации. Оркестрация создаёт коннектор один раз на прогон, так
        # что за весь прогон список инструментов запрашивается ровно один раз,
        # а не по разу на каждый счёт и на каждый вид вызова. Справочник не
        # меняется за минуты одного прогона, так что такой кэш безопасен; это
        # не кэш в БД и не глобальный кэш на процесс — он живёт и умирает
        # вместе с этим объектом.
        self._bulk_instruments: dict[str, BrokerInstrument] | None = None

    def fetch_accounts(self) -> list[BrokerAccount]:
        return [
            BrokerAccount(
                external_id=account["id"],
                name=account.get("name") or "Счёт",
                kind=ACCOUNT_KIND.get(account.get("type"), "brokerage"),
                opened_at=_opened_date(account),
            )
            for account in self._client.get_accounts()
        ]

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]:
        # Одна точка отсчёта на весь батч: свежесть операции решает, записывать
        # ли её (см. map_operation), и внутри одного прогона это решение должно
        # приниматься по одному и тому же моменту времени.
        now = datetime.now(tz=timezone.utc)
        operations = self._client.get_operations(
            account_external_id, _rfc3339(since), _rfc3339(now)
        )
        figis = {operation.get("figi") for operation in operations if operation.get("figi")}
        instruments = self._resolve_instruments(figis)

        mapped: list[RawOperation] = []
        for operation in operations:
            figi = operation.get("figi") or None
            instrument = instruments.get(figi) if figi else None
            result = map_operation(operation, instrument, now=now)
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
            instrument = instruments.get(figi)
            if instrument is None or not instrument.isin:
                continue
            ticker = item.get("ticker") or instrument.ticker
            positions.append(BrokerPosition(isin=instrument.isin, ticker=ticker, quantity=qty))
        return positions

    def fetch_instrument_reference(self) -> dict[str, BrokerInstrument]:
        """Справочник инструментов брокера, ключ — ISIN. Нужен разовому
        дозаполнению уже записанных инструментов (app/instruments/backfill.py):
        обычная синхронизация видит только те инструменты, что встретились в
        операциях её окна, а привести в порядок надо всю таблицу целиком.
        Читающий вызов, состояние счёта не трогает."""
        return {
            instrument.isin: instrument
            for instrument in self._bulk_instrument_index().values()
            if instrument.isin
        }

    def _bulk_instrument_index(self) -> dict[str, BrokerInstrument]:
        """Полный список инструментов по видам (INSTRUMENT_LIST_KINDS),
        построенный за фиксированное число запросов вне зависимости от того,
        сколько уникальных FIGI встретилось. Строится один раз при первом
        обращении и кэшируется в self._bulk_instruments на весь срок жизни
        коннектора — см. комментарий в __init__.

        Вид инструмента известен здесь и только здесь: он определяется тем,
        каким списочным методом получен ответ (в самих объектах Share/Bond/...
        поля с видом нет). Поэтому индекс хранит уже разобранный
        BrokerInstrument с видом, а не сырой словарь ответа — иначе вид
        теряется, а домен вынужден угадывать (так и было: все инструменты
        записывались акциями)."""
        if self._bulk_instruments is None:
            index: dict[str, BrokerInstrument] = {}
            for list_method in INSTRUMENT_LIST_KINDS:
                kind = KIND_BY_LIST_METHOD.get(list_method, kinds.OTHER)
                for instrument in self._list_instruments(list_method):
                    figi = instrument.get("figi")
                    if figi:
                        index[figi] = _to_broker_instrument(instrument, kind)
            self._bulk_instruments = index
        return self._bulk_instruments

    def _list_instruments(self, list_method: str) -> list[dict]:
        """Один списочный метод справочника, с двумя ступенями отступления.

        Полный список (ALL) нужен потому, что только в нём есть инструменты,
        переставшие торговаться, — а в истории за годы их много. Но для
        облигаций он весит 34 МБ, и сервер обрывает ответ примерно на 30-й
        секунде: повторы в клиенте тут бессильны, отказ устойчивый (живой замер
        09.08.2026 — Shares 11.5 МБ проходят за 12 с, Bonds ALL не проходит
        никогда, Bonds BASE — 3.4 МБ за 4 с).

        Поэтому: не вышло ALL — берём BASE, там хотя бы торгуемые; не вышло и
        оно — отдаём пустой список и не роняем синхронизацию. Всё, чего не
        хватило, доберёт поштучное разрешение по FIGI в _resolve_instruments."""
        try:
            return self._client.list_instruments(list_method)
        except httpx.HTTPError as error:
            logger.warning(
                "Полный справочник %s недоступен (%s) — пробуем сокращённый", list_method, error
            )

        try:
            return self._client.list_instruments(list_method, INSTRUMENT_STATUS_BASE)
        except httpx.HTTPError as error:
            logger.warning(
                "Справочник %s недоступен и в сокращённом виде (%s) — "
                "эти инструменты будут разрешаться поштучно по FIGI",
                list_method,
                error,
            )
            return []

    def _resolve_instruments(self, figis: set[str]) -> dict[str, BrokerInstrument]:
        """Строит индекс FIGI → BrokerInstrument (isin, тикер, вид, название)
        для запрошенных FIGI из закэшированного на уровне коннектора списочного
        индекса; то, чего в нём не нашлось, разрешается поштучно через
        GetInstrumentBy — запасной путь, а не основной механизм. Раньше был один
        GetInstrumentBy на каждый уникальный FIGI: за годы истории счёта их
        набирались сотни, и это упиралось в ограничение частоты запросов
        T-Invest API."""
        if not figis:
            return {}

        bulk_index = self._bulk_instrument_index()

        index: dict[str, BrokerInstrument] = {}
        for figi in figis:
            found = bulk_index.get(figi)
            if found is not None:
                index[figi] = found
                continue
            # Запасной путь: у поштучного ответа вид приходит своим полем
            # instrumentType, отдельного словаря видов для него не нужно.
            raw = self._client.get_instrument_by_figi(figi)
            if raw:
                kind = KIND_BY_INSTRUMENT_TYPE.get(raw.get("instrumentType") or "", kinds.OTHER)
                resolved = _to_broker_instrument(raw, kind)
                index[figi] = resolved
                # Кладём находку в общий индекс коннектора, чтобы следующий
                # счёт того же прогона не запрашивал тот же FIGI заново.
                # Поштучные запросы — ровно то место, где раньше срабатывало
                # ограничение частоты (429); когда списочный метод недоступен,
                # их и без того становится много.
                bulk_index[figi] = resolved
        return index
