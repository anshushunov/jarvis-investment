import pytest

from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.models import Instrument


def instrument(**kwargs) -> Instrument:
    defaults = {"isin": "RU000A0JQUZ6", "ticker": "AGRO", "secid": "AGRO",
                "currency": "RUB", "kind": "share"}
    return Instrument(**{**defaults, **kwargs})


@pytest.mark.parametrize("isin,ticker,currency,expected", [
    ("RU000A0JQUZ6", "AGRO", "RUB", True),
    # Облигация российского эмитента с юаневым номиналом: на MOEX она есть, и
    # правило по одной валюте уводило её к брокеру.
    ("RU000A1054W1", "RU000A1054W1", "CNY", True),
    # ETF с рублёвым ISIN, но долларовой ценой — та же история.
    ("RU000A101X68", "TECH", "USD", True),
    ("US67066G1040", "NVDA", "USD", False),
    ("KYG875721634", "700", "HKD", False),
    ("HK0000651213", "3067", "HKD", False),
])
def test_moex_routing_does_not_follow_the_currency_alone(isin, ticker, currency, expected):
    assert priced_at_moex(
        instrument(isin=isin, ticker=ticker, secid=ticker, currency=currency)
    ) is expected


@pytest.mark.parametrize("isin,ticker,issuer", [
    ("US42207L1061", "HHRU", "HeadHunter"),
    ("US7496552057", "AGRO", "РусАгро"),
    ("US98387E2054", "FIVE", "X5"),
    ("XS0088543193", "XS0088543193", "Russia 2028"),
])
def test_depositary_receipts_stay_at_moex(isin, ticker, issuer):
    """Расписки и редомицилированные компании торгуются на MOEX с иностранным
    ISIN. Замер живой базы 12.08.2026: правило по одному ISIN уводило с биржи
    десять таких бумаг, три из них лежат в портфеле. Признак — рублёвые
    расчёты; тикер `AGRO` на Yahoo принадлежит аргентинской Adecoagro."""
    assert priced_at_moex(
        instrument(isin=isin, ticker=ticker, secid=ticker, currency="RUB")
    ) is True


def test_instrument_without_secid_is_not_priced_at_moex():
    """Без идентификатора площадки запрос строить не из чего."""
    assert priced_at_moex(instrument(secid=None)) is False


@pytest.mark.parametrize("isin,ticker,currency,expected", [
    ("US67066G1040", "NVDA", "USD", "NVDA"),
    ("US69608A1088", "PLTR", "USD", "PLTR"),
    # Гонконгская нумерация — четыре знака: 700 это 0700.HK.
    ("KYG875721634", "700", "HKD", "0700.HK"),
    ("KYG017191142", "9988", "HKD", "9988.HK"),
])
def test_yahoo_symbol_from_ticker(isin, ticker, currency, expected):
    assert yahoo_symbol(instrument(isin=isin, ticker=ticker, currency=currency)) == expected


@pytest.mark.parametrize("isin,expected", [
    # Тикер сменился после того, как бумага перестала торговаться у брокера.
    ("US8522341036", "XYZ"),
    ("US87918A1051", "TDOC"),
    ("US91332U1016", "U"),
    # Гонконгский фонд в двух валютных линейках: гонконгская и юаневая.
    ("HK0000051877", "3010.HK"),
    ("HK0000310034", "83010.HK"),
])
def test_known_exceptions_are_resolved_by_isin(isin, expected):
    """У этих бумаг справочник брокера положил в тикер сам ISIN — вывести
    символ из него нельзя, он задан поимённо."""
    assert yahoo_symbol(instrument(isin=isin, ticker=isin, currency="USD")) == expected


def test_delisted_instrument_has_no_symbol():
    """ТКС Холдинг делистингован: символа нет ни у Yahoo, ни где-либо ещё.
    None здесь — не ошибка, а честный ответ, который оставит бумагу
    неоценённой на её датах."""
    assert yahoo_symbol(instrument(isin="US87238U2033", ticker="US87238U2033", currency="USD")) is None


def test_ticker_equal_to_isin_gives_no_symbol():
    """Справочник брокера кладёт ISIN в тикер, когда настоящего тикера не
    знает. Отправлять ISIN на Yahoo бессмысленно, а угадывать — опасно."""
    assert yahoo_symbol(instrument(isin="US1234567890", ticker="US1234567890", currency="USD")) is None


def test_depositary_receipt_has_no_yahoo_symbol():
    """Тикер `AGRO` на Yahoo принадлежит аргентинской Adecoagro, а не РусАгро.
    Бумага с рублёвыми расчётами идёт на MOEX, и символа Yahoo у неё быть не
    должно — иначе защита по валюте окажется единственным, что стоит между
    портфелем и ценой чужой компании."""
    assert yahoo_symbol(
        instrument(isin="US7496552057", ticker="AGRO", secid="AGRO", currency="RUB")
    ) is None


def test_russian_instrument_has_no_yahoo_symbol():
    """Российская бумага идёт на MOEX; символа Yahoo у неё быть не должно —
    иначе один инструмент попадёт в оба прогона и получит две цены за день."""
    assert yahoo_symbol(instrument()) is None
