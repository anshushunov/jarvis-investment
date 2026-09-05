"""Прогон доходности на живых данных.

Брат app/valuation_check.py: не тест, а способ увидеть цифры и проверить разом
три утверждения признака готовности фазы — сходимость XIRR по определению,
точность разложения прибыли и сходимость разрезов с целым.

    cd backend && uv run python -m app.returns.check
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import OperationType, Transaction
from app.money import money
from app.returns.flows import RAW_CASH_MOVE_TYPES, instrument_flows, portfolio_flows
from app.returns.metrics import rate_flows, series_start
from app.returns.rates import RateBook
from app.returns.service import (
    MONEY_ROW_CLASS,
    PERIOD_12M,
    PERIOD_ALL,
    PERIOD_YTD,
    ReturnsReport,
    opening_snapshot,
    returns_report,
)
from app.returns.xirr import NPV_TOLERANCE, npv, xirr
from app.timeutils import moscow_date

PERIOD_TITLES = {PERIOD_ALL: "всё время", PERIOD_12M: "12 месяцев", PERIOD_YTD: "с начала года"}


def _rate(value: Decimal | None) -> str:
    return "—" if value is None else f"{value * 100:.2f} %"


def _unattributed_by_query(session: Session, since, until) -> Decimal:
    """Комиссии, налоги и возвраты без бумаги — прямым запросом к журналу.

    Второй счёт того же числа, написанный намеренно другим способом: признак
    готовности (дизайн, раздел 7) требует сверять «Прочее» с журналом, а
    печатать величину, посчитанную тем же кодом, значит сверять число с самим
    собой. Правила ровно два и оба видны здесь: запись без `instrument_id`, не
    движение денег и не конверсия; сумма — `amount − fee` в рублях по курсу дня
    операции.
    """
    book = RateBook.load(session)
    total = Decimal("0")
    rows = session.execute(
        select(Transaction).where(Transaction.instrument_id.is_(None))
    ).scalars()
    for row in rows:
        if row.op_type in (OperationType.DEPOSIT, OperationType.WITHDRAWAL):
            continue
        if row.op_type in (OperationType.BUY, OperationType.SELL):
            continue  # конверсия валюты или металла — не результат
        if (row.payload or {}).get("operation_type") in RAW_CASH_MOVE_TYPES:
            continue
        day = moscow_date(row.executed_at)
        if since is not None and day < since or day > until:
            continue
        in_base = book.to_base(row.amount - abs(row.fee), row.currency, day)
        if in_base is not None:
            total += in_base
    return money(total)


def _xirr_convergence(session: Session, report: ReturnsReport) -> str:
    """Признак готовности, пункт 1: XIRR проверяет сам себя.

    Ставка — это корень уравнения «приведённая стоимость потоков равна нулю»,
    и проверяется она подстановкой, а не доверием к решателю: те же потоки
    дисконтируются по найденной ставке, и печатается невязка. Порог — копейка
    (`NPV_TOLERANCE`), та же, которой меряет сходимость сам решатель.

    Потоки собираются той же функцией, что кормит расчёт на экране
    (`metrics.rate_flows`), и от той же точки отсчёта (`opening_snapshot`):
    собери прогон свой список рядом — он проверял бы другую ставку.

    Ставка берётся не из отчёта, а считается по этим потокам заново: в отчёте
    у короткого периода лежит доходность ЗА ПЕРИОД (годовая пересчитана
    обратно, дизайн раздел 4.3), и дисконтировать по ней — значит проверять
    величину, которой уравнение не решали.
    """
    period = report.period
    book = RateBook.load(session)
    flows = rate_flows(
        portfolio_flows(session, book, period.since, period.until),
        series_start(opening_snapshot(session, period.since), lambda row: row.total_value),
        report.portfolio.value, period)

    rate = xirr(flows)
    if rate is None:
        return ("Сходимость XIRR: ставки нет (потоков недостаточно) — "
                "дисконтировать нечего")

    residual = npv(flows, rate)
    verdict = ("сходится" if abs(residual) < NPV_TOLERANCE
               else f"РАСХОДИТСЯ (порог {NPV_TOLERANCE} ₽)")
    # У короткого периода годовая ставка и та, что показана выше, — разные
    # числа по построению. Сказать об этом здесь дешевле, чем оставить читателя
    # сверять 6,43 % с 3,92 % и гадать, какое из них сломано.
    shown = "" if period.annualized else " (выше она же пересчитана за период)"
    return (f"Сходимость XIRR: {len(flows)} потоков по ставке {rate * 100:.2f} % годовых"
            f"{shown} дают приведённую стоимость {residual:.4f} ₽ — {verdict}")


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
        lines.append(_xirr_convergence(session, report))

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
        # Признак готовности требует сверять «Прочее» с прямым запросом к
        # журналу буквально: печатать то же число из того же кода — не
        # проверка, а эхо. Запрос ниже намеренно написан заново и не зовёт
        # unattributed_flows.
        direct = _unattributed_by_query(session, period.since, period.until)
        verdict = ("сходится" if direct == report.unattributed.profit
                   else f"РАСХОДИТСЯ на {money(direct - report.unattributed.profit)} ₽")
        lines.append(f"Сверка «Прочего» прямым запросом: {direct} ₽ — {verdict}")
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
