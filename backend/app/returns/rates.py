from bisect import bisect_right
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FxRate
from app.money import BASE_CURRENCY, money


class RateBook:
    """Курсы к рублю на любую дату прошлого, прочитанные один раз.

    `app.marketdata.fx.latest_rates` отвечает на вопрос «курсы на сегодня» и
    ходит в базу при каждом вызове. Здесь вопрос другой — «курс на дату каждой
    из двенадцати тысяч операций», и запрос на операцию превратил бы расчёт
    доходности в тысячи запросов.
    """

    def __init__(self, series: dict[str, tuple[list[date], list[Decimal]]]):
        self._series = series

    @classmethod
    def load(cls, session: Session) -> "RateBook":
        rows = session.execute(
            select(FxRate.currency, FxRate.on_date, FxRate.rate).order_by(FxRate.on_date)
        ).all()

        series: dict[str, tuple[list[date], list[Decimal]]] = {}
        for currency, on_date, rate in rows:
            dates, values = series.setdefault(currency.upper(), ([], []))
            dates.append(on_date)
            values.append(rate)
        return cls(series)

    def rate(self, currency: str, on_date: date) -> Decimal | None:
        """Самый свежий курс не позже даты. None — курса на эту дату нет вовсе.

        Ближайший будущий курс не подставляется: сегодняшний доллар ничего не
        говорит о том, сколько он стоил в день сделки 2021 года.
        """
        code = currency.upper()
        if code == BASE_CURRENCY:
            # Рубль к рублю — единица, и в таблице её нет: строка, которая
            # никогда не меняется, лишь создаёт впечатление, что её можно не
            # найти (то же решение, что в app/marketdata/fx.py).
            return Decimal("1")

        found = self._series.get(code)
        if found is None:
            return None

        dates, values = found
        index = bisect_right(dates, on_date)
        if index == 0:
            return None
        return values[index - 1]

    def to_base(self, amount: Decimal, currency: str, on_date: date) -> Decimal | None:
        rate = self.rate(currency, on_date)
        if rate is None:
            return None
        return money(amount * rate)
