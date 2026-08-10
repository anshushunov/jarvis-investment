from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import FxRate
from app.money import BASE_CURRENCY, money

CBR_SOURCE = "cbr"


class RateSource(Protocol):
    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]: ...


def refresh_fx_rates(session: Session, client: RateSource, on_date: date) -> int:
    """Загружает курсы, действующие на `on_date`, под датой их установления.

    Пишутся все валюты ответа, а не только встречающиеся в портфеле: запрос
    один и тот же, а список валют портфеля меняется при каждой покупке — искать
    потом, почему у одной позиции курса нет, дороже, чем хранить сорок строк в
    сутки.
    """
    effective, rates = client.rates(on_date)

    for currency, rate in rates.items():
        statement = insert(FxRate).values(
            currency=currency, on_date=effective, rate=rate, source=CBR_SOURCE
        ).on_conflict_do_update(
            index_elements=[FxRate.currency, FxRate.on_date],
            set_={"rate": rate, "source": CBR_SOURCE},
        )
        session.execute(statement)

    session.flush()
    return len(rates)


def latest_rates(session: Session, on_date: date) -> dict[str, Decimal]:
    """Курсы, действующие на дату: по каждой валюте самый свежий курс не позже
    неё. Не «курс ровно на эту дату»: ЦБ не публикует курсы в выходные, и
    оценка портфеля в субботу иначе оставалась бы без валют вовсе."""
    ranked = select(
        FxRate.currency,
        FxRate.rate,
        func.row_number().over(
            partition_by=FxRate.currency, order_by=FxRate.on_date.desc()
        ).label("rn"),
    ).where(FxRate.on_date <= on_date).subquery()

    rows = session.execute(
        select(ranked.c.currency, ranked.c.rate).where(ranked.c.rn == 1)
    ).all()

    result = {currency: rate for currency, rate in rows}
    # Рубль к рублю — единица, и она не хранится: строка в таблице, которая
    # никогда не меняется, лишь создаёт впечатление, что её можно не найти.
    result[BASE_CURRENCY] = Decimal("1")
    return result


def latest_rate_dates(session: Session, on_date: date) -> dict[str, date]:
    """Дата самого свежего курса не позже указанной — по каждой валюте отдельно.

    По валюте, а не одним максимумом на всю таблицу: источники у курсов разные и
    обновляются они порознь. Золото приходит с MOEX и торгуется каждый день,
    курсы ЦБ по выходным не публикуются вовсе — общий максимум показывал бы
    сегодняшнее золото и молчал о том, что доллар в расчёте недельной давности.
    Какая из дат попадёт в «курсы на», решает читатель: она зависит от того,
    какие валюты участвовали в конкретном расчёте (см. portfolio_overview).
    """
    ranked = select(
        FxRate.currency,
        FxRate.on_date,
        func.row_number().over(
            partition_by=FxRate.currency, order_by=FxRate.on_date.desc()
        ).label("rn"),
    ).where(FxRate.on_date <= on_date).subquery()

    rows = session.execute(
        select(ranked.c.currency, ranked.c.on_date).where(ranked.c.rn == 1)
    ).all()
    return {currency.upper(): rate_date for currency, rate_date in rows}


MOEX_SOURCE = "moex"

# Металлы в денежных остатках Т-Банка приходят валютными кодами (`xau` — 10 это
# граммы). У ЦБ в XML_daily металлов нет вовсе, поэтому курс берётся с MOEX,
# где GLDRUB_TOM котируется в рублях за грамм. Серебро, платина и палладий
# добавляются сюда же, когда появятся в остатках: пока их нет, заводить
# непроверенные идентификаторы незачем.
METAL_SECIDS = {"XAU": "GLDRUB_TOM"}


class QuoteSource(Protocol):
    def quote(self, secid: str, market: str = ..., engine: str = ...) -> object: ...


def refresh_metal_rates(session: Session, client: QuoteSource, on_date: date) -> int:
    """Курсы металлов на дату, из тех же торгов MOEX, что и валюты (движок
    currency, рынок selt). Пишутся под запрошенной датой, а не под датой
    установления: у биржевой цены нет «даты установления», она торговая."""
    written = 0
    for currency, secid in METAL_SECIDS.items():
        quote = client.quote(secid, market="selt", engine="currency")
        price = getattr(quote, "price", None)
        if price is None:
            continue
        statement = insert(FxRate).values(
            currency=currency, on_date=on_date, rate=price, source=MOEX_SOURCE
        ).on_conflict_do_update(
            index_elements=[FxRate.currency, FxRate.on_date],
            set_={"rate": price, "source": MOEX_SOURCE},
        )
        session.execute(statement)
        written += 1

    session.flush()
    return written


def to_base(amount: Decimal, currency: str, rates: dict[str, Decimal]) -> Decimal | None:
    """Сумма в рублях либо None, если курса нет.

    None, а не сумма как есть: неизвестный курс означает неизвестную оценку.
    Подставить рубль вместо гонконгского доллара — занизить позицию вдесятеро и
    показать это как точную цифру.
    """
    rate = rates.get(currency.upper())
    if rate is None:
        return None
    return money(amount * rate)
