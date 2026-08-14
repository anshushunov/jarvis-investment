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
from app.returns.flows import instrument_flows
from app.returns.rates import RateBook
from app.returns.service import (
    MONEY_ROW_CLASS,
    PERIOD_12M,
    PERIOD_ALL,
    PERIOD_YTD,
    returns_report,
)

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
                     f"цепочка TWR измерила {coverage.chain_days} дней, "
                     f"разрывов {coverage.chain_breaks}")
        if coverage.currencies_without_rate:
            lines.append("Потоки без курса: " + ", ".join(coverage.currencies_without_rate))

        # Признак готовности, пункт 3: сумма по бумагам, деньгам и строке
        # «Прочее» против прибыли портфеля — ровно то тождество, которое
        # обещает дизайн (раздел 7). Без слагаемого «деньги» рублёвая
        # переоценка валютного остатка не входила никуда, и на неё расходились
        # разрезы.
        instruments_profit = sum((row.profit for row in report.by_instrument
                                   if row.profit is not None), Decimal("0"))
        money_profit = sum((row.metric.profit for row in report.by_asset_class
                            if row.asset_class == MONEY_ROW_CLASS), Decimal("0"))
        parts = money(instruments_profit + money_profit + report.unattributed.profit)
        lines.append(f"Прочее (комиссии {report.unattributed.fees} ₽, налоги "
                     f"{report.unattributed.taxes} ₽, прочее {report.unattributed.other} ₽): "
                     f"{report.unattributed.profit} ₽")
        lines.append(f"Деньги и металлы: {money(money_profit)} ₽")
        lines.append(f"Сумма по бумагам {money(instruments_profit)} ₽ + Деньги + Прочее = {parts} ₽")
        mismatch = money(parts - report.portfolio.profit)
        lines.append(f"Расхождение с прибылью портфеля: {mismatch} ₽")

        # Признак готовности, пункт 3: расхождение обязано объясняться поимённо,
        # а не оставаться невязкой. Бумага, прибыль которой посчитать нечем,
        # выпадает из суммы целиком — и называется здесь вместе с причиной и
        # своей стоимостью, чтобы остаток читался списком причин, а не одним
        # числом. На живых данных это четыре редомицилированные бумаги, чья
        # цена лежит под новым тикером.
        unknown = [row for row in report.by_instrument if row.profit is None]
        if unknown:
            lines.append(f"Прибыль не посчитана у бумаг ({len(unknown)}):")
            moves = instrument_flows(session, RateBook.load(session),
                                     period.since, period.until)
            explained = Decimal("0")
            for row in unknown:
                moved = sum((flow.amount for flow in moves.get(row.instrument_id, [])),
                            Decimal("0"))
                # Вклад — то, что сумма по бумагам получила бы, посчитай мы
                # бумагу по известным частям: потоки периода плюс сегодняшняя
                # стоимость. У бумаги без начальной стоимости (no_history) он
                # завышен ровно на неё — она неизвестна, потому строка и здесь.
                known = moved + (row.value or Decimal("0"))
                explained += known
                value = f"{row.value} ₽" if row.value is not None else "стоимость неизвестна"
                lines.append(f"  {row.name} ({row.reason}): потоки {money(moved)} ₽, "
                             f"{value} → вклад {money(known)} ₽")
            lines.append(f"Названные бумаги объясняют {money(-explained)} ₽ расхождения; "
                         f"остаётся {money(mismatch + explained)} ₽")
        else:
            lines.append("Прибыль посчитана у всех бумаг разреза")

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
                         f"TWR {_rate(row.metric.twr)} · прибыль {row.metric.profit} ₽ · "
                         f"стоимость {row.metric.value} ₽")

    if not lines:
        lines.append("Данных нет: журнал пуст")
    return lines


def main() -> None:
    with SessionLocal() as session:
        for line in check_returns(session):
            print(line)


if __name__ == "__main__":
    main()
