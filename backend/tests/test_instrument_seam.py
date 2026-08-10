"""Стык коннектора и домена: от ответа брокера до строки в таблице instrument.

Именно этого теста и не было — обе стороны стыка проверялись по отдельности
(тесты коннектора собирали RawOperation, тесты аналитики и рыночных данных
заводили Instrument руками с уже проставленным видом), а сам стык был пуст:
вид инструмента терялся, и все инструменты записывались акциями.
"""

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import respx

from app.connectors.base import BrokerInstrument
from app.connectors.tbank.client import INSTRUMENT_LIST_KINDS
from app.connectors.tbank.connector import TBankConnector
from app.instruments.backfill import backfill_instruments
from app.instruments.service import resolve_instrument, secid_from_ticker
from app.ledger.schemas import RawOperation
from app.marketdata.service import ENGINE_MARKET_BY_KIND
from app.models import Account, Instrument, OperationType, Transaction
from app.sync.service import sync_broker

BASE = "https://invest-public-api.tinkoff.ru/rest"
USERS = f"{BASE}/tinkoff.public.invest.api.contract.v1.UsersService"
OPERATIONS = f"{BASE}/tinkoff.public.invest.api.contract.v1.OperationsService"
INSTRUMENTS = f"{BASE}/tinkoff.public.invest.api.contract.v1.InstrumentsService"

TOKEN = "test-token-not-real"  # nosec: тестовое значение, не боевой токен

BOND_FIGI = "BBG00T22WKV5"
BOND_ISIN = "RU000A1038V6"
ETF_FIGI = "BBG333333333"
ETF_ISIN = "RU000A101X76"
FOREIGN_FIGI = "BBG000BJ35N5"
FOREIGN_ISIN = "KYG875721634"


def _buy(op_id: str, figi: str, payment_currency: str = "rub") -> dict:
    return {
        "id": op_id,
        "type": "OPERATION_TYPE_BUY",
        "state": "OPERATION_STATE_EXECUTED",
        "date": "2026-03-12T10:30:00Z",
        "figi": figi,
        "quantity": "5",
        "price": {"currency": payment_currency, "units": "1000", "nano": 0},
        "payment": {"currency": payment_currency, "units": "-5000", "nano": 0},
    }


def _fee(op_id: str, figi: str) -> dict:
    """Комиссия по валютной бумаге приходит в рублях — именно такая операция и
    записывала валютной бумаге рублёвую валюту навсегда."""
    return {
        "id": op_id,
        "type": "OPERATION_TYPE_BROKER_FEE",
        "state": "OPERATION_STATE_EXECUTED",
        "date": "2026-03-11T10:30:00Z",
        "figi": figi,
        "quantity": "0",
        "price": {"currency": "rub", "units": "0", "nano": 0},
        "payment": {"currency": "rub", "units": "-3", "nano": 0},
    }


def _mock_broker(operations: list[dict]) -> None:
    respx.post(f"{USERS}/GetAccounts").mock(
        return_value=httpx.Response(200, json={
            "accounts": [{"id": "1000000001", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Брокерский"}]
        })
    )
    respx.post(f"{OPERATIONS}/GetOperationsByCursor").mock(
        return_value=httpx.Response(200, json={"hasNext": False, "nextCursor": "", "items": operations})
    )
    respx.post(f"{OPERATIONS}/GetPortfolio").mock(
        return_value=httpx.Response(200, json={"positions": []})
    )
    lists = {
        "Bonds": [{"figi": BOND_FIGI, "ticker": "SU26238RMFS4", "isin": BOND_ISIN,
                   "name": "ОФЗ 26238", "currency": "rub"}],
        "Etfs": [{"figi": ETF_FIGI, "ticker": "TMOS", "isin": ETF_ISIN,
                  "name": "Тинькофф iMOEX", "currency": "rub"}],
        "Shares": [{"figi": FOREIGN_FIGI, "ticker": "700", "isin": FOREIGN_ISIN,
                    "name": "Tencent", "currency": "hkd"}],
    }
    for list_method in INSTRUMENT_LIST_KINDS:
        respx.post(f"{INSTRUMENTS}/{list_method}").mock(
            return_value=httpx.Response(200, json={"instruments": lists.get(list_method, [])})
        )


@respx.mock
def test_instrument_kind_survives_the_whole_way_from_broker_to_database(session):
    _mock_broker([_buy("op-bond", BOND_FIGI), _buy("op-etf", ETF_FIGI)])

    sync_broker(session, TBankConnector(TOKEN), datetime(2026, 1, 1, tzinfo=timezone.utc))

    stored = {i.isin: i for i in session.query(Instrument).all()}

    assert stored[BOND_ISIN].kind == "bond"
    assert stored[BOND_ISIN].issuer == "ОФЗ 26238"
    assert stored[ETF_ISIN].kind == "etf"
    assert stored[ETF_ISIN].issuer == "Тинькофф iMOEX"

    # Тот самый практический смысл вида: облигация должна искаться на рынке
    # облигаций, а не акций — иначе котировки для неё не найдётся никогда.
    assert ENGINE_MARKET_BY_KIND[stored[BOND_ISIN].kind] == ("stock", "bonds")


@respx.mock
def test_existing_instrument_is_enriched_not_ignored(session):
    """Инструмент, заведённый раньше (когда вид ещё терялся на стыке), при
    следующей синхронизации обязан дозаполниться, а не остаться акцией
    навсегда: резолвер раньше только создавал запись и никогда не обновлял."""
    session.add(Instrument(isin=BOND_ISIN, ticker="SU26238RMFS4", secid="SU26238RMFS4",
                           kind="share", currency="RUB"))
    session.flush()

    _mock_broker([_buy("op-bond", BOND_FIGI)])
    sync_broker(session, TBankConnector(TOKEN), datetime(2026, 1, 1, tzinfo=timezone.utc))

    stored = session.query(Instrument).filter_by(isin=BOND_ISIN).one()
    assert stored.kind == "bond"
    assert stored.issuer == "ОФЗ 26238"
    # Дозаполнение, а не заведение дубля.
    assert session.query(Instrument).filter_by(isin=BOND_ISIN).count() == 1


@respx.mock
def test_reference_currency_wins_over_payment_currency(session):
    """Валюта бралась из платежа первой операции, создавшей строку. Комиссия по
    гонконгской бумаге приходит в рублях — и бумага навсегда оставалась
    рублёвой. На живых данных так получилось у шести инструментов, чьи сделки
    шли в USD и HKD, у двух из них есть открытая позиция. Теперь поле решает,
    попадёт ли позиция в совокупный капитал, так что источник истины —
    справочник брокера, а не платёж."""
    # Комиссия в рублях идёт ПЕРВОЙ — именно она раньше и создавала запись.
    _mock_broker([_fee("op-fee", FOREIGN_FIGI), _buy("op-buy", FOREIGN_FIGI, "hkd")])

    sync_broker(session, TBankConnector(TOKEN), datetime(2026, 1, 1, tzinfo=timezone.utc))

    stored = session.query(Instrument).filter_by(isin=FOREIGN_ISIN).one()
    assert stored.currency == "HKD"


def test_payment_currency_is_used_only_when_reference_gives_nothing(session):
    """Колонка NOT NULL, а платёж хоть какую-то валюту всегда несёт — но это
    именно запасное значение, а не источник истины."""
    op = RawOperation(
        external_id="op-1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        isin="RU000NOREFER", ticker="NOREF", quantity=Decimal("1"),
        price=Decimal("1"), amount=Decimal("-1"), currency="USD",
        fee=Decimal("0"), payload={},
    )

    instrument = resolve_instrument(session, op)

    assert instrument.currency == "USD"
    assert instrument.kind == "other"


def test_secid_drops_broker_suffix_from_ticker():
    """Т-Банк помечает часть фондов тикером с «@» (TMOS@, TLCB@), а на MOEX
    такого идентификатора нет — котировка не находится вовсе. Проверено на
    живых данных: TMOS стоит 5.69 ₽ при средней цене позиции 6.07, TLCB — 10.83
    при 9.92. Сам тикер остаётся как у брокера, чтобы позиция называлась так же,
    как в его приложении; чинится только идентификатор для биржи."""
    assert secid_from_ticker("TMOS@") == "TMOS"
    assert secid_from_ticker("SBER") == "SBER"
    assert secid_from_ticker(None) is None
    assert secid_from_ticker("@") is None


def test_new_instrument_gets_exchange_secid_without_suffix(session):
    op = RawOperation(
        external_id="op-1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        isin="RU000A101X76", ticker="TMOS@", quantity=Decimal("1"),
        price=Decimal("6"), amount=Decimal("-6"), currency="RUB",
        fee=Decimal("0"), payload={},
    )

    instrument = resolve_instrument(session, op)

    assert instrument.ticker == "TMOS@"
    assert instrument.secid == "TMOS"


def test_backfill_keeps_currency_when_reference_has_none(session):
    """Справочник может не знать инструмент или не отдать валюту — уже
    записанное значение при этом терять нельзя."""
    session.add(Instrument(isin=FOREIGN_ISIN, ticker="700", secid="700",
                           kind="share", currency="HKD", issuer="Tencent"))
    session.flush()

    changed = backfill_instruments(session, {
        FOREIGN_FIGI: BrokerInstrument(isin=FOREIGN_ISIN, ticker="700",
                                       kind="share", name="Tencent", currency=None),
    })

    assert changed == 0
    assert session.query(Instrument).filter_by(isin=FOREIGN_ISIN).one().currency == "HKD"


def test_backfill_fixes_currency_written_from_payment(session):
    session.add(Instrument(isin=FOREIGN_ISIN, ticker="700", secid="700",
                           kind="share", currency="RUB"))
    session.flush()

    changed = backfill_instruments(session, {
        FOREIGN_FIGI: BrokerInstrument(isin=FOREIGN_ISIN, ticker="700",
                                       kind="share", name="Tencent", currency="HKD"),
    })

    assert changed == 1
    assert session.query(Instrument).filter_by(isin=FOREIGN_ISIN).one().currency == "HKD"


def test_backfill_fixes_instruments_never_seen_in_the_sync_window(session):
    """Инструменты, купленные годы назад, в окно обычной синхронизации не
    попадают — их приводит в порядок разовый прогон по справочнику целиком."""
    session.add_all([
        Instrument(isin=BOND_ISIN, ticker="SU26238RMFS4", secid="SU26238RMFS4",
                   kind="share", currency="RUB"),
        Instrument(isin="RU000UNKNOWN", ticker="UNKN", secid="UNKN", kind="share", currency="RUB"),
    ])
    session.flush()

    changed = backfill_instruments(session, {
        BOND_FIGI: BrokerInstrument(isin=BOND_ISIN, ticker="SU26238RMFS4",
                                    kind="bond", name="ОФЗ 26238"),
    })

    assert changed == 1
    assert session.query(Instrument).filter_by(isin=BOND_ISIN).one().kind == "bond"
    # Чего нет в справочнике брокера — не трогаем вовсе.
    assert session.query(Instrument).filter_by(isin="RU000UNKNOWN").one().kind == "share"


def test_backfill_repairs_exchange_secid_even_without_reference_entry(session):
    """Инструменты, записанные до того, как «@» начали отбрасывать, стоят с
    биржевым идентификатором, которого на MOEX нет. Чинить их обязано то же
    разовое дозаполнение — и без справочника брокера: тикер уже записан, этого
    достаточно."""
    session.add(Instrument(isin=ETF_ISIN, ticker="TMOS@", secid="TMOS@",
                           kind="etf", currency="RUB"))
    session.flush()

    assert backfill_instruments(session, {}) == 1

    instrument = session.query(Instrument).filter_by(isin=ETF_ISIN).one()
    assert instrument.secid == "TMOS"
    assert instrument.ticker == "TMOS@"


def test_backfill_is_idempotent(session):
    session.add(Instrument(isin=BOND_ISIN, ticker="SU26238RMFS4", secid="SU26238RMFS4",
                           kind="share", currency="RUB"))
    session.flush()
    reference = {
        BOND_FIGI: BrokerInstrument(isin=BOND_ISIN, ticker="SU26238RMFS4",
                                    kind="bond", name="ОФЗ 26238"),
    }

    assert backfill_instruments(session, reference) == 1
    assert backfill_instruments(session, reference) == 0


# Площадка бумаги: у одного ISIN в справочнике брокера до двенадцати записей,
# и берётся из них та, на которой бумага у владельца лежит. Ниже — обе стороны
# правила и то, что вместе с флагами из той же записи приезжают валюта, вид и
# название.

MIRROR_FIGI = "TCSC326G1040"


def _instrument_traded_at(session, figi: str, **fields) -> Instrument:
    """Инструмент, у которого в журнале есть операция на площадке `figi`.
    Именно эта операция и сообщает дозаполнению, какая из записей справочника
    относится к бумаге владельца."""
    account = Account(broker="tbank", external_id="1000000001", name="Брокерский", kind="brokerage")
    instrument = Instrument(**fields)
    session.add_all([account, instrument])
    session.flush()
    session.add(Transaction(
        account_id=account.id, instrument_id=instrument.id, op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc), quantity=Decimal("1"),
        price=Decimal("100"), amount=Decimal("-100"), currency="USD", fee=Decimal("0"),
        external_id="op-1", source="tbank", dedup_key=f"tbank:{figi}:op-1",
        payload={"figi": figi},
    ))
    session.flush()
    return instrument


def test_backfill_restricts_when_the_owners_board_forbids_both(session):
    """Основная площадка запрещает обе операции, зеркальная разрешает обе.
    Бумага владельца лежит на основной — значит она ограничена в обороте, и
    наличие живого зеркала этого не отменяет. Так на живых данных были потеряны
    Unity, Block и Teladoc: правило «побеждает самая доступная запись»
    объявляло их свободными."""
    instrument = _instrument_traded_at(
        session, "BBG000BBJQV0",
        isin="US67066G1040", ticker="NVDA", secid="NVDA", kind="share", currency="USD",
    )

    backfill_instruments(session, {
        "BBG000BBJQV0": BrokerInstrument(isin="US67066G1040", ticker="NVDA", kind="share",
                                         name="NVIDIA", currency="USD",
                                         buy_available=False, sell_available=False),
        MIRROR_FIGI: BrokerInstrument(isin="US67066G1040", ticker="NVDA-RM", kind="share",
                                      name="NVIDIA", currency="RUB",
                                      buy_available=True, sell_available=True),
    })

    assert instrument.trading_restricted is True


def test_backfill_frees_when_the_owners_board_allows(session):
    """Обратная сторона: бумага владельца лежит на основной площадке, которая
    операции разрешает, а служебные доски того же ISIN — нет. Ограничения быть
    не должно. Так на живых данных ограниченными оказывались OZON, EQMX и GOLD:
    правило «побеждает последняя запись по порядку ответа» ловило служебную
    доску."""
    instrument = _instrument_traded_at(
        session, "TCS80A10CW95",
        isin="RU000A10CW95", ticker="OZON", secid="OZON", kind="share", currency="RUB",
        trading_restricted=True,
    )

    backfill_instruments(session, {
        "TCS80A10CW95": BrokerInstrument(isin="RU000A10CW95", ticker="OZON", kind="share",
                                         name="Озон", currency="RUB",
                                         buy_available=True, sell_available=True),
        "TCS70A10CW95": BrokerInstrument(isin="RU000A10CW95", ticker="RU000A10CW95",
                                         kind="share", name="Озон", currency="RUB",
                                         buy_available=False, sell_available=False),
    })

    assert instrument.trading_restricted is False


def test_backfill_takes_currency_kind_and_name_from_the_owners_board(session):
    """Из записи площадки приезжают не только флаги: у зеркала другая валюта и
    другое название. Живая проверка 10.08.2026: выбор чужой записи переписал
    валюту 79 американским акциям на рубли, и AT&T с secid «T» после этого
    поехала за котировкой на MOEX, где под тем же идентификатором торгуются
    Т-Технологии."""
    instrument = _instrument_traded_at(
        session, "BBG000BSJK37",
        isin="US00206R1023", ticker="T", secid="T", kind="other", currency="RUB",
    )

    backfill_instruments(session, {
        "BBG000BSJK37": BrokerInstrument(isin="US00206R1023", ticker="T", kind="share",
                                         name="AT&T", currency="USD",
                                         buy_available=False, sell_available=False),
        "TCSC432R1023": BrokerInstrument(isin="US00206R1023", ticker="AT-RM", kind="share",
                                         name="AT&T (рубли)", currency="RUB",
                                         buy_available=True, sell_available=True),
    })

    assert instrument.currency == "USD"
    assert instrument.kind == "share"
    assert instrument.issuer == "AT&T"


def test_backfill_falls_back_to_isin_when_the_board_is_unknown(session):
    """Инструмент без единой операции в журнале — например заведённый из снимка
    позиций брокера — площадкой не опознаётся. Тогда справочник сводится по
    ISIN, и из записей выигрывает та, что сообщает о доступности больше:
    правило грубее, но лучше, чем не дозаполнить бумагу вовсе."""
    session.add(Instrument(isin="US67066G1040", ticker="NVDA", secid="NVDA",
                           kind="other", currency="RUB"))
    session.flush()

    backfill_instruments(session, {
        "BBG000BBJQV0": BrokerInstrument(isin="US67066G1040", ticker="NVDA", kind="share",
                                         name="NVIDIA", currency="USD",
                                         buy_available=False, sell_available=False),
        MIRROR_FIGI: BrokerInstrument(isin="US67066G1040", ticker="NVDA-RM", kind="share",
                                      name="NVIDIA", currency="RUB",
                                      buy_available=True, sell_available=True),
    })

    stored = session.query(Instrument).filter_by(isin="US67066G1040").one()
    assert stored.kind == "share"
    assert stored.trading_restricted is False


def test_backfill_does_not_erase_known_kind_with_unknown(session):
    """Поштучный справочник может не знать экзотический инструмент и ответить
    видом «прочее» — терять из-за этого уже установленный вид незачем."""
    session.add(Instrument(isin=BOND_ISIN, ticker="SU26238RMFS4", secid="SU26238RMFS4",
                           kind="bond", currency="RUB", issuer="ОФЗ 26238"))
    session.flush()

    changed = backfill_instruments(session, {
        BOND_ISIN: BrokerInstrument(isin=BOND_ISIN, ticker="SU26238RMFS4", kind="other", name=None),
    })

    assert changed == 0
    assert session.query(Instrument).filter_by(isin=BOND_ISIN).one().kind == "bond"


@respx.mock
def test_instrument_without_reference_entry_is_recorded_as_other_not_share(session):
    """FIGI, которого нет ни в списках, ни в поштучном ответе, инструмент в
    журнале не порождает вовсе (ISIN неизвестен) — а вот известный по ISIN, но
    с неизвестным видом обязан лечь «прочим», а не подразумеваемой акцией."""
    _mock_broker([_buy("op-exotic", "TCS00A0SPROD")])
    respx.post(f"{INSTRUMENTS}/GetInstrumentBy").mock(
        return_value=httpx.Response(200, json={
            "instrument": {"figi": "TCS00A0SPROD", "ticker": "SP1", "isin": "RU000ASPROD1",
                           "instrumentType": "sp", "name": "Структурная нота"}
        })
    )

    sync_broker(session, TBankConnector(TOKEN), datetime(2026, 1, 1, tzinfo=timezone.utc))

    stored = session.query(Instrument).filter_by(isin="RU000ASPROD1").one()
    assert stored.kind == "other"
    assert stored.issuer == "Структурная нота"
    assert stored.currency == "RUB"
