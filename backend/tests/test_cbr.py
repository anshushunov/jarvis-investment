from datetime import date
from decimal import Decimal

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
