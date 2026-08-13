from datetime import date
from decimal import Decimal

from app.models import DailySnapshot, FxRate, OperationType
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, period_bounds, returns_report
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument


def add_snapshot(session, day: date, total: str, by_account: dict | None = None,
                 valued: int = 1, total_positions: int = 1) -> None:
    session.add(DailySnapshot(
        on_date=day, total_value=Decimal(total), by_asset_class={"equity": total},
        by_account=by_account or {}, source="backfill",
        positions_total=total_positions, valued_positions=valued, unpriced=[]))
    session.flush()


def test_all_period_starts_at_first_day():
    period = period_bounds(PERIOD_ALL, date(2026, 8, 13), date(2020, 7, 16))
    assert period.since == date(2020, 7, 16)
    assert period.until == date(2026, 8, 13)
    assert period.annualized is True


def test_twelve_months_is_a_year_back():
    period = period_bounds(PERIOD_12M, date(2026, 8, 13), date(2020, 7, 16))
    assert period.since == date(2025, 8, 13)
    assert period.annualized is True


def test_ytd_in_february_is_not_annualized():
    """Полтора месяца в годовых врут кратно: два процента за это время
    показались бы как двадцать семь годовых."""
    period = period_bounds(PERIOD_YTD, date(2026, 2, 14), date(2020, 7, 16))
    assert period.since == date(2026, 1, 1)
    assert period.annualized is False


def test_profit_is_growth_minus_contributions(session, account):
    """Занёс 100 000, портфель стоит 130 000 — заработано 30 000. Ни рублём
    больше: остальное принёс не рынок, а владелец."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 1, 10), amount="100000")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 11), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 10), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={account.id: Decimal("130000")},
                            by_class_now={"equity": Decimal("130000")})
    assert report.portfolio.profit == Decimal("30000.0000")
    assert report.portfolio.invested == Decimal("100000.0000")


def test_xirr_is_positive_when_portfolio_grew(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={account.id: Decimal("130000")},
                            by_class_now={"equity": Decimal("130000")})
    assert report.portfolio.xirr is not None
    assert report.portfolio.xirr > Decimal("0.13")
    assert report.portfolio.xirr < Decimal("0.15")


def test_portfolio_without_flows_has_named_reason(session, account):
    """Капитал есть, а внешних потоков в периоде нет: ставки не существует, и
    экран обязан сказать почему, а не показать прочерк."""
    add_snapshot(session, date(2026, 8, 12), "130000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={},
                            by_class_now={})
    assert report.portfolio.xirr is None
    assert report.portfolio.reason == "no_flows"


def test_period_starts_from_the_value_of_the_day_before(session, account):
    """Стоимость на начало периода — снимок ДО его первого дня, а не в первый
    день: снимок первого дня уже содержит пополнение этого дня, и взятый
    началом отсчёта он вычел бы пополнение дважды. Здесь до периода накоплено
    900 000, за период занесено 100 000, стало 1 100 000 — заработано 100 000.
    """
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2026, 3, 10), amount="100000")
    add_snapshot(session, date(2025, 8, 12), "900000")
    add_snapshot(session, date(2026, 3, 10), "1000000")
    add_snapshot(session, date(2026, 8, 13), "1100000")

    report = returns_report(session, PERIOD_12M, today=date(2026, 8, 13),
                            value_now=Decimal("1100000"), by_account_now={},
                            by_class_now={})
    assert report.portfolio.profit == Decimal("100000.0000")
    assert report.portfolio.invested == Decimal("100000.0000")


def test_short_period_shows_return_over_the_period(session, account):
    """XIRR по устройству годовой, и на сорока днях он врёт кратно: два процента
    показались бы двадцатью. На коротком периоде показывается доходность за
    период (дизайн, раздел 4.3), а не прочерк: число известно, врёт лишь
    годовая подпись под ним."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2026, 1, 5), amount="100000")
    add_snapshot(session, date(2026, 1, 5), "100000")
    add_snapshot(session, date(2026, 2, 14), "102000")

    report = returns_report(session, PERIOD_YTD, today=date(2026, 2, 14),
                            value_now=Decimal("102000"), by_account_now={},
                            by_class_now={})
    assert report.period.annualized is False
    assert report.portfolio.xirr is not None
    assert report.portfolio.xirr > Decimal("0.01")
    assert report.portfolio.xirr < Decimal("0.05")


def test_closed_instrument_is_listed_with_a_mark(session, account):
    """Проданная целиком бумага остаётся в разрезе: без неё сумма по бумагам не
    сойдётся с портфелем."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 11), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    # Количество продажи беззнаковое: направление задаёт тип операции
    # (app/positions/engine.py, signed_quantity). Минус здесь превратил бы
    # продажу в покупку, и бумага осталась бы открытой.
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 11), amount="120000", quantity="100", price="1200",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 11), "100000")
    add_snapshot(session, date(2026, 8, 13), "120000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("120000"), by_account_now={},
                            by_class_now={})
    row = next(row for row in report.by_instrument if row.instrument_id == instrument.id)
    assert row.closed is True
    assert row.profit == Decimal("20000.0000")
    assert row.value == Decimal("0.0000")


def test_class_of_a_sold_out_position_keeps_its_row(session, account):
    """Класс, из которого всё продано, стоит сегодня ноль — но прибыль за период
    он принёс. Без строки сумма по классам не сойдётся с портфелем ровно на неё.
    """
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 11), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 11), amount="120000", quantity="100", price="1200",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 11), "100000")
    add_snapshot(session, date(2026, 8, 13), "120000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("120000"), by_account_now={},
                            by_class_now={})
    row = next(row for row in report.by_asset_class if row.asset_class == "equity")
    assert row.metric.profit == Decimal("20000.0000")
    assert row.metric.value == Decimal("0.0000")


def test_unattributed_row_is_part_of_the_report(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 2, 1), amount="-450")
    add_snapshot(session, date(2024, 2, 1), "100000")
    add_snapshot(session, date(2026, 8, 13), "100000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("100000"), by_account_now={},
                            by_class_now={})
    assert report.unattributed.fees == Decimal("-450.0000")


def test_coverage_reports_unvalued_days_and_currencies(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 2, 1), amount="1000", currency="HKD")
    add_snapshot(session, date(2024, 2, 1), "100000", valued=1, total_positions=2)
    add_snapshot(session, date(2026, 8, 13), "100000", valued=2, total_positions=2)

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("100000"), by_account_now={},
                            by_class_now={})
    assert report.coverage.days_total == 2
    assert report.coverage.days_valued == 1
    assert report.coverage.currencies_without_rate == ["HKD"]


def test_period_cuts_off_earlier_flows(session, account):
    session.add(FxRate(currency="USD", on_date=date(2020, 1, 1),
                       rate=Decimal("70"), source="cbr"))
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 1, 10), amount="500000")
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2026, 3, 10), amount="100000")
    add_snapshot(session, date(2021, 1, 10), "500000")
    add_snapshot(session, date(2025, 8, 13), "900000")
    add_snapshot(session, date(2026, 8, 13), "1100000")

    report = returns_report(session, PERIOD_12M, today=date(2026, 8, 13),
                            value_now=Decimal("1100000"), by_account_now={},
                            by_class_now={})
    assert report.period.since == date(2025, 8, 13)
    assert report.portfolio.invested == Decimal("100000.0000")
