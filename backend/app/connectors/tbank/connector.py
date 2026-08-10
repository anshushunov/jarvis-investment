import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable

import httpx

from app.connectors.base import BrokerAccount, BrokerCash, BrokerInstrument, BrokerPosition, BrokerPrice
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS, INSTRUMENT_STATUS_BASE, TBankClient
from app.connectors.tbank.mapper import map_operation
from app.connectors.tbank.quotation import to_money, to_quantity
from app.instruments import kinds
from app.ledger.schemas import RawOperation
from app.money import money, quantity

ACCOUNT_KIND = {
    "ACCOUNT_TYPE_TINKOFF": "brokerage",
    "ACCOUNT_TYPE_TINKOFF_IIS": "iis",
}

# Коды ошибок HTTP, при которых счёт просто не поддерживает вызов, а не сломан.
# GetPositions отвечает 404 «Account not found» для счетов типа
# ACCOUNT_TYPE_DFA (цифровые финансовые активы) — денег и бумаг в привычном
# смысле там нет, и падать из-за этого всей синхронизацией незачем.
_NO_SUCH_ACCOUNT = 404

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
        # Флаги есть и в списочных методах справочника, и в поштучном
        # GetInstrumentBy — оба пути дают их одинаково.
        buy_available=raw.get("buyAvailableFlag"),
        sell_available=raw.get("sellAvailableFlag"),
    )


def _availability_rank(instrument: BrokerInstrument) -> int:
    """Насколько запись справочника свидетельствует о свободе распоряжения
    бумагой. Порядок важен только внутри одного ISIN — см.
    TBankConnector.fetch_instrument_reference.

    Ноль — сведений нет вовсе (хотя бы одного флага не хватает), и такая запись
    проигрывает любой другой: по ней всё равно ничего не решить. Единица — обе
    операции недоступны. Двойка — доступна хотя бы одна, а этого достаточно,
    чтобы бумага ограниченной не считалась (правило то же, что в
    app/instruments/service.py: ограничение — недоступность обеих сразу).
    """
    if not isinstance(instrument.buy_available, bool):
        return 0
    if not isinstance(instrument.sell_available, bool):
        return 0
    return 2 if (instrument.buy_available or instrument.sell_available) else 1


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
        # Снимок GetPortfolio по счёту — построен лениво, при первом обращении
        # (из fetch_positions либо fetch_prices, смотря что вызвали раньше), и
        # переиспользуется вторым вызовом на этом же счёте в рамках прогона.
        # Без этого кэша оркестрация (app/sync/service.py, sync_broker) на
        # каждый счёт делает GetPortfolio дважды — тот самый класс проблем,
        # что уже описан выше для справочника инструментов: ограничение
        # частоты запросов T-Invest API, ответ 429. Ключ — внешний
        # идентификатор счёта: счетов в прогоне несколько, и перепутать их
        # снимки означает подставить одному счёту позиции и цены другого.
        # Как и _bulk_instruments, это не кэш в БД и не кэш на процесс — он
        # живёт минуты одного прогона и умирает вместе с этим объектом
        # коннектора, который оркестрация создаёт заново на каждый прогон.
        # Побочная выгода не только в экономии запросов: позиции и цены при
        # этом читаются из одного и того же снимка брокера, а не из двух
        # разных, между которыми цена могла успеть измениться, — сверка
        # количества и оценка стоимости теперь согласованы.
        self._portfolio_cache: dict[str, list[dict]] = {}
        # Снимок GetPositions по счёту — тот же образец кэша, что и у
        # _portfolio_cache выше, и по той же причине: fetch_cash (задача 5) и
        # заблокированное количество бумаг (задача 6) читают один и тот же
        # вызов, и второй из них не должен снова ходить в сеть за тем же
        # счётом. Значение — None для счетов, которые GetPositions не
        # поддерживает (_NO_SUCH_ACCOUNT), чтобы такой отказ тоже кэшировался,
        # а не повторял неудачный запрос на каждое обращение.
        self._positions_cache: dict[str, dict | None] = {}

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

    def _get_portfolio(self, account_external_id: str) -> list[dict]:
        """Снимок GetPortfolio по счёту, закэшированный на срок жизни
        коннектора — см. комментарий к self._portfolio_cache в __init__."""
        if account_external_id not in self._portfolio_cache:
            self._portfolio_cache[account_external_id] = self._client.get_portfolio(account_external_id)
        return self._portfolio_cache[account_external_id]

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]:
        raw_positions = self._get_portfolio(account_external_id)
        figis = {item.get("figi") for item in raw_positions if item.get("figi")}
        instruments = self._resolve_instruments(figis)
        blocked_by_figi = self._blocked_by_figi(account_external_id)

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
            positions.append(BrokerPosition(
                isin=instrument.isin, ticker=ticker, quantity=qty,
                blocked=blocked_by_figi.get(figi, quantity("0")),
            ))
        return positions

    def _blocked_by_figi(self, account_external_id: str) -> dict[str, Decimal]:
        """Заблокированные количества бумаг счёта, ключ — FIGI.

        Сведения есть только в GetPositions; счёт, который этого вызова не
        поддерживает, отдаёт пустое отображение, и позиции читаются как раньше,
        просто без блокировок."""
        payload = self._get_positions(account_external_id)
        if payload is None:
            return {}

        result: dict[str, Decimal] = {}
        for item in payload.get("securities") or []:
            figi = item.get("figi")
            raw_blocked = item.get("blocked")
            if not figi or raw_blocked in (None, "", "0"):
                continue
            result[figi] = quantity(str(raw_blocked))
        return result

    def fetch_prices(self, account_external_id: str) -> list[BrokerPrice]:
        """Текущие цены бумаг счёта по данным брокера.

        Берётся из того же GetPortfolio, что и позиции — и из того же
        закэшированного снимка (см. _get_portfolio), если fetch_positions по
        этому счёту в рамках прогона уже вызывался. Цена приходит в валюте
        бумаги (`hkd`, `usd`, `cny`, `rub`), у облигаций — деньгами за штуку, а
        не процентом от номинала, в отличие от MOEX.
        """
        raw_positions = self._get_portfolio(account_external_id)
        figis = {item.get("figi") for item in raw_positions if item.get("figi")}
        instruments = self._resolve_instruments(figis)

        prices: list[BrokerPrice] = []
        for item in raw_positions:
            figi = item.get("figi")
            instrument = instruments.get(figi) if figi else None
            if instrument is None or not instrument.isin:
                continue
            raw_price = item.get("currentPrice") or {}
            currency = (raw_price.get("currency") or "").upper()
            price = to_money(raw_price)
            # Пустая валюта — признак псевдо-позиции (рублёвый остаток закрытого
            # счёта приходит именно так), нулевая цена — отсутствие оценки.
            # Записать такое значит обнулить стоимость бумаги.
            if not currency or price == 0:
                continue
            prices.append(BrokerPrice(isin=instrument.isin, price=price, currency=currency))
        return prices

    def fetch_cash(self, account_external_id: str) -> list[BrokerCash]:
        """Денежные остатки счёта по данным OperationsService/GetPositions.

        Источник намеренно один: то же самое (в рублях, долларах, юанях и
        золоте) приходит и здесь массивом по валютам, и в GetPortfolio
        псевдо-инструментами (RUB000UTSTOM и подобными). Взять оба значило бы
        удвоить деньги в капитале — вторые в систему и так не попадают
        (fetch_positions/fetch_prices пропускают всё без ISIN)."""
        payload = self._get_positions(account_external_id)
        if payload is None:
            return []

        blocked_by_currency: dict[str, Decimal] = {}
        for item in payload.get("blocked") or []:
            currency = (item.get("currency") or "").upper()
            if currency:
                blocked_by_currency[currency] = to_money(item)

        # Валюта в money изредка повторяется (в т.ч. в разном регистре —
        # 'rub' и 'RUB' нормализуются в одну и ту же валюту). Дубль
        # складываем, а не берём последний: у cash_balance уникальный ключ
        # (account_id, currency), и если бы здесь осталось две записи на одну
        # валюту, store_cash упал бы на вставке второй, откатив SAVEPOINT
        # всего счёта. Сложение — это ещё и единственный вариант, который не
        # теряет деньги молча: обе записи брокер прислал как часть остатка,
        # отбросить любую из них значило бы занизить капитал без всякого
        # признака этого в данных.
        money_by_currency: dict[str, Decimal] = {}
        for item in payload.get("money") or []:
            currency = (item.get("currency") or "").upper()
            if not currency:
                continue
            money_by_currency[currency] = money_by_currency.get(currency, money("0")) + to_money(item)

        # Итог — объединение валют money и blocked, а не проход только по
        # money: валюта, которая целиком зарезервирована, может не попасть в
        # money вовсе (распоряжаемой суммы в ней нет), но деньги в ней
        # реальны и обязаны остаться в капитале, а не пропасть из-за того,
        # что цикл раньше видел только money.
        balances: list[BrokerCash] = []
        for currency in sorted(set(money_by_currency) | set(blocked_by_currency)):
            balances.append(BrokerCash(
                currency=currency,
                amount=money_by_currency.get(currency, money("0")),
                # Ноль amount при ненулевом blocked — не нарушение соглашения
                # «blocked — часть amount» (см. докстринг BrokerCash), а его
                # крайний случай: money и blocked — два независимых массива
                # ответа брокера, и money не обязана перечислять валюту, для
                # которой распоряжаемой суммы нет вовсе. Подставить сюда сам
                # blocked вместо нуля значило бы придумать за брокера число,
                # которого он в money не прислал.
                blocked=blocked_by_currency.get(currency, money("0")),
            ))
        return balances

    def _get_positions(self, account_external_id: str) -> dict | None:
        """Ответ GetPositions, закэшированный на срок жизни коннектора — по
        тому же образцу, что и _get_portfolio (см. self._portfolio_cache в
        __init__): вызывается и fetch_cash (задача 5), и заблокированным
        количеством бумаг (задача 6), и второй вызов на том же счёте не должен
        снова ходить в сеть.

        Возвращает None, если счёт этот вызов не поддерживает (см.
        _NO_SUCH_ACCOUNT) — это не ошибка, а особенность типа счёта."""
        if account_external_id not in self._positions_cache:
            try:
                self._positions_cache[account_external_id] = self._client.get_positions(account_external_id)
            except httpx.HTTPStatusError as error:
                if error.response.status_code != _NO_SUCH_ACCOUNT:
                    raise
                logger.info(
                    "GetPositions недоступен для счёта %s (счёт особого типа) — "
                    "остатки и блокировки по нему не читаются",
                    account_external_id,
                )
                self._positions_cache[account_external_id] = None
        return self._positions_cache[account_external_id]

    def fetch_instrument_reference(self) -> dict[str, BrokerInstrument]:
        """Справочник инструментов брокера, ключ — ISIN. Нужен разовому
        дозаполнению уже записанных инструментов (app/instruments/backfill.py):
        обычная синхронизация видит только те инструменты, что встретились в
        операциях её окна, а привести в порядок надо всю таблицу целиком.
        Читающий вызов, состояние счёта не трогает.

        Одному ISIN в справочнике брокера соответствует не одна запись, а по
        одной на каждый режим торгов: у OZON их четыре (TQBR, SPBXM, A36, A53),
        у NVDA — десяток. Флаги доступности у них разные: основной режим TQBR
        отдаёт `buyAvailableFlag: true`, а внебиржевые и служебные доски —
        `false`. Взять «последнюю по порядку ответа» значит с вероятностью три
        четверти записать свободно торгуемой бумаге ограничение в обороте
        (живая проверка 10.08.2026: так ограниченными оказались OZON, EQMX,
        GOLD, T, SBBY, OBLG, DATA и ДОМ.РФ — на 2.45 млн ₽). Поэтому при
        совпадении ISIN выигрывает самая «доступная» запись."""
        reference: dict[str, BrokerInstrument] = {}
        for instrument in self._bulk_instrument_index().values():
            if not instrument.isin:
                continue
            known = reference.get(instrument.isin)
            if known is None or _availability_rank(instrument) > _availability_rank(known):
                reference[instrument.isin] = instrument
        return reference

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
