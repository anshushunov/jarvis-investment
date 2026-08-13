from datetime import date
from decimal import Decimal

from app.models import FxRate
from app.returns.rates import RateBook


def add_rate(session, currency: str, on_date: date, rate: str) -> None:
    session.add(FxRate(currency=currency, on_date=on_date, rate=Decimal(rate), source="cbr"))
    session.flush()


def test_rate_on_exact_date(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("USD", date(2024, 3, 1)) == Decimal("92.5")


def test_weekend_takes_last_published_rate(session):
    """ЦБ не публикует курсы по выходным. Операция субботы обязана считаться по
    пятничному курсу, а не оставаться без курса вовсе."""
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    add_rate(session, "USD", date(2024, 3, 5), "93.1")
    book = RateBook.load(session)
    assert book.rate("USD", date(2024, 3, 3)) == Decimal("92.5")


def test_before_first_publication_there_is_no_rate(session):
    """До первой известной даты курса нет. Ближайший будущий курс сюда
    подставлять нельзя: это выдумка о прошлом."""
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("USD", date(2020, 1, 1)) is None


def test_base_currency_is_always_one(session):
    book = RateBook.load(session)
    assert book.rate("RUB", date(2020, 1, 1)) == Decimal("1")


def test_unknown_currency_has_no_rate(session):
    book = RateBook.load(session)
    assert book.rate("SGD", date(2024, 3, 1)) is None


def test_to_base_converts_and_rounds(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.to_base(Decimal("10"), "USD", date(2024, 3, 1)) == Decimal("925.0000")


def test_to_base_without_rate_is_none(session):
    book = RateBook.load(session)
    assert book.to_base(Decimal("10"), "USD", date(2024, 3, 1)) is None


def test_case_of_currency_does_not_matter(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("usd", date(2024, 3, 1)) == Decimal("92.5")
