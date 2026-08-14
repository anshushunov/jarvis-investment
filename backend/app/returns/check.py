"""Прогон доходности на живых данных.

Брат app/valuation_check.py: не тест, а способ увидеть цифры и проверить разом
три утверждения признака готовности фазы — сходимость XIRR по определению,
точность разложения прибыли и сходимость разрезов с целым.

    cd backend && uv run python -m app.returns.check
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.money import money
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, returns_report

PERIOD_TITLES = {PERIOD_ALL: "всё время", PERIOD_12M: "12 месяцев", PERIOD_YTD: "с начала года"}


def _rate(value: Decimal | None) -> str:
    return "—" if value is None else f"{value * 100:.2f} %"


def check_returns(session: Session) -> list[str]:
    lines: list[str] = []

    for period_key in (PERIOD_ALL, PERIOD_12M, PERIOD_YTD):
        report = returns_report(session, period_key)
        period = report.period
        if period.since is None:
            lines.append(f"Период «{PERIOD_TITLES[period_key]}»: истории нет — снимков в базе нет вовсе")
            continue

        suffix = "" if period.annualized else " (за период, не в годовых)"
        lines.append("")
        lines.append(f"=== {PERIOD_TITLES[period_key]}: {period.since} — {period.until}{suffix} ===")
        lines.append(f"XIRR {_rate(report.portfolio.xirr)} · TWR {_rate(report.portfolio.twr)}")
        lines.append(f"Прибыль портфеля {report.portfolio.profit} ₽, "
                     f"вложено {report.portfolio.invested} ₽, "
                     f"стоимость {report.portfolio.value} ₽")

        coverage = report.coverage
        lines.append(f"Покрытие: полная оценка у {coverage.days_valued} дат из "
                     f"{coverage.days_total}; позиций оценено "
                     f"{coverage.positions_valued} из {coverage.positions_total}; "
                     f"разрывов цепочки TWR {coverage.chain_breaks}")
        if coverage.currencies_without_rate:
            lines.append("Потоки без курса: " + ", ".join(coverage.currencies_without_rate))

        # Признак готовности, пункт 3: сумма частей против целого.
        instruments_profit = sum((row.profit for row in report.by_instrument
                                   if row.profit is not None), Decimal("0"))
        parts = money(instruments_profit + report.unattributed.profit)
        lines.append(f"Прочее (комиссии {report.unattributed.fees} ₽, налоги "
                     f"{report.unattributed.taxes} ₽, прочее {report.unattributed.other} ₽): "
                     f"{report.unattributed.profit} ₽")
        lines.append(f"Сумма по бумагам {money(instruments_profit)} ₽ + Прочее = {parts} ₽")
        lines.append(f"Расхождение с прибылью портфеля: {money(parts - report.portfolio.profit)} ₽")

        # Признак готовности, пункт 2: части сверяются с НЕРЕАЛИЗОВАННОЙ
        # прибылью, а не с прибылью за период. Прежняя проверка сравнивала
        # разные величины и потому тревожила почти на каждой открытой позиции:
        # прибыль периода содержит реализованный результат частичных продаж,
        # которого разложение не видит по устройству (дизайн, раздел 4.4).
        unrealized_total = sum((row.unrealized for row in report.by_instrument
                                if row.unrealized is not None), Decimal("0"))
        lines.append(f"Нереализованная прибыль открытых позиций: {money(unrealized_total)} ₽")
        mismatched = [
            row.name for row in report.by_instrument
            if row.price_part is not None and row.fx_part is not None
            and row.unrealized is not None
            and money(row.price_part + row.fx_part) != row.unrealized
        ]
        if mismatched:
            lines.append("Части разошлись с нереализованной прибылью у: " + ", ".join(mismatched))
        else:
            lines.append("Части сходятся с нереализованной прибылью по всем открытым позициям")

        for row in report.by_account:
            lines.append(f"  счёт {row.account_id}: XIRR {_rate(row.metric.xirr)} · "
                         f"TWR {_rate(row.metric.twr)} · прибыль {row.metric.profit} ₽")
        for row in report.by_asset_class:
            lines.append(f"  {row.asset_class}: XIRR {_rate(row.metric.xirr)} · "
                         f"TWR {_rate(row.metric.twr)} · стоимость {row.metric.value} ₽")

    if not lines:
        lines.append("Данных нет: журнал пуст")
    return lines


def main() -> None:
    with SessionLocal() as session:
        for line in check_returns(session):
            print(line)


if __name__ == "__main__":
    main()
