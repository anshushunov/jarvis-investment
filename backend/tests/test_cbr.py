from datetime import date
from decimal import Decimal

import pytest

from app.marketdata.cbr import CbrClient

# Обрезанный настоящий ответ ЦБ: кодировка windows-1251, десятичная запятая,
# номинал не всегда единица (иена — сто). Атрибут Date корня — дата, НА которую
# курс установлен: запрос на воскресенье 09.08.2026 вернул 08.08.2026.
SAMPLE = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="08.08.2026" name="Foreign Currency Market">
<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Доллар США</Name><Value>82,1665</Value><VunitRate>82,1665</VunitRate></Valute>
<Valute ID="R01200"><NumCode>344</NumCode><CharCode>HKD</CharCode><Nominal>1</Nominal><Name>Гонконгских долларов</Name><Value>10,4724</Value><VunitRate>10,4724</VunitRate></Valute>
<Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal><Name>Китайский юань</Name><Value>12,1655</Value><VunitRate>12,1655</VunitRate></Valute>
<Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Японских иен</Name><Value>55,7100</Value><VunitRate>0,557100</VunitRate></Valute>
</ValCurs>"""


class FakeTransport:
    def __init__(self, body: str) -> None:
        self.body = body
        self.params: dict[str, str] | None = None

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> bytes:
        self.params = params
        return self.body.encode("windows-1251")


def test_parses_rates_and_effective_date():
    transport = FakeTransport(SAMPLE)
    client = CbrClient(fetch=transport)

    on_date, rates = client.rates(date(2026, 8, 9))

    assert on_date == date(2026, 8, 8)
    assert rates["USD"] == Decimal("82.1665")
    assert rates["HKD"] == Decimal("10.4724")
    assert transport.params == {"date_req": "09/08/2026"}


def test_divides_value_by_nominal():
    """Иена котируется за сотню: без деления на номинал позиция в иенах
    завысилась бы ровно в сто раз."""
    on_date, rates = CbrClient(fetch=FakeTransport(SAMPLE)).rates(date(2026, 8, 9))

    assert rates["JPY"] == Decimal("0.55710000")


def test_rouble_is_not_in_the_answer():
    """Рубль ЦБ не котирует сам к себе; единицу подставляет читающая сторона
    (latest_rates), а не разбор ответа."""
    _, rates = CbrClient(fetch=FakeTransport(SAMPLE)).rates(date(2026, 8, 9))

    assert "RUB" not in rates


# Обрезанный настоящий ответ XML_dynamic по доллару за 01–10.03.2022: курса на
# 07–09 марта нет вовсе — праздники, ЦБ их не публикует.
DYNAMIC = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs ID="R01235" DateRange1="01.03.2022" DateRange2="10.03.2022" name="Foreign Currency Market Dynamic">
<Record Date="01.03.2022" Id="R01235"><Nominal>1</Nominal><Value>93,5589</Value><VunitRate>93,5589</VunitRate></Record>
<Record Date="02.03.2022" Id="R01235"><Nominal>1</Nominal><Value>91,7457</Value><VunitRate>91,7457</VunitRate></Record>
<Record Date="10.03.2022" Id="R01235"><Nominal>1</Nominal><Value>116,0847</Value><VunitRate>116,0847</VunitRate></Record>
</ValCurs>"""

# Обрезанный XML_valFull: соответствие ISO-кода внутреннему коду ЦБ. Иена
# котируется за сотню — номинал здесь тоже есть, но делит на него разбор
# самого курса.
VAL_FULL = """<?xml version="1.0" encoding="windows-1251"?>
<Valuta name="Foreign Currency Market Lib">
<Item ID="R01235"><Name>Доллар США</Name><Nominal>1</Nominal><ISO_Char_Code>USD</ISO_Char_Code></Item>
<Item ID="R01200"><Name>Гонконгский доллар</Name><Nominal>1</Nominal><ISO_Char_Code>HKD</ISO_Char_Code></Item>
<Item ID="R01375"><Name>Юань</Name><Nominal>1</Nominal><ISO_Char_Code>CNY</ISO_Char_Code></Item>
<Item ID="R01720A"><Name>Украинский карбованец</Name><Nominal>1</Nominal><ISO_Char_Code></ISO_Char_Code></Item>
</Valuta>"""


class RoutingTransport:
    """Отвечает по адресу: истории курсов и справочнику кодов — разные ответы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> bytes:
        self.calls.append((url, params))
        body = VAL_FULL if url.endswith("XML_valFull.asp") else DYNAMIC
        return body.encode("windows-1251")


def test_rate_history_returns_published_days_only():
    """Курса на 07–09.03.2022 нет: ЦБ в праздники не публикует. Достраивать
    пропущенные дни здесь нельзя — «курс, действующий на дату» выводит
    читающая сторона (latest_rates), и делает это одним правилом на проект."""
    client = CbrClient(fetch=RoutingTransport())

    rows = client.rate_history("USD", date(2022, 3, 1), date(2022, 3, 10))

    assert rows == [
        (date(2022, 3, 1), Decimal("93.55890000")),
        (date(2022, 3, 2), Decimal("91.74570000")),
        (date(2022, 3, 10), Decimal("116.08470000")),
    ]


def test_rate_history_asks_the_internal_code_of_the_currency():
    transport = RoutingTransport()

    CbrClient(fetch=transport).rate_history("HKD", date(2022, 3, 1), date(2022, 3, 10))

    dynamic = [params for url, params in transport.calls if url.endswith("XML_dynamic.asp")]
    assert dynamic == [{"date_req1": "01/03/2022", "date_req2": "10/03/2022", "VAL_NM_RQ": "R01200"}]


def test_currency_codes_are_fetched_once_per_client():
    """Справочник кодов не меняется в течение прогона, а бумаг и валют в нём
    сотни: второй запрос за тем же ответом — чистая трата."""
    transport = RoutingTransport()
    client = CbrClient(fetch=transport)

    client.rate_history("USD", date(2022, 3, 1), date(2022, 3, 10))
    client.rate_history("CNY", date(2022, 3, 1), date(2022, 3, 10))

    assert sum(1 for url, _ in transport.calls if url.endswith("XML_valFull.asp")) == 1


def test_unknown_currency_raises():
    """Валюта без кода ЦБ — это ошибка сопоставления, а не пустая история:
    молчаливый пустой ответ выглядел бы как «курса не публиковали»."""
    with pytest.raises(KeyError):
        CbrClient(fetch=RoutingTransport()).rate_history("XAU", date(2022, 3, 1), date(2022, 3, 10))
