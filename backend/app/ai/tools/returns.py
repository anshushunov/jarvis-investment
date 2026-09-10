"""Инструмент returns: XIRR, TWR с измеренной долей периода, прибыль, разрезы."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.models import Account
from app.returns.metrics import Metric, PeriodError
from app.returns.service import (
    PERIOD_CUSTOM,
    REASON_CASH,
    REASON_EMPTY_PERIOD,
    REASON_NO_FLOWS,
    REASON_NO_FULL_DAYS,
    REASON_NO_HISTORY,
    REASON_NO_SOLUTION,
    REASON_SERIES_GAPS,
    returns_report,
)

# Причины — словами, теми же, что на экране «Аналитика». Четыре последних —
# ключи разложения прибыли (app/returns/fx_split.py) — записаны литералами,
# как во фронте: это контракт строки разреза, а не внутренняя константа.
REASON_TEXTS = {
    REASON_NO_FLOWS: "пополнений и изъятий за период не было — доходность вложений посчитать не из чего",
    REASON_NO_SOLUTION: "потоки есть, но уравнение ставки решения не имеет: недостаточно данных",
    REASON_NO_HISTORY: "истории стоимости за период нет",
    REASON_NO_FULL_DAYS: "ни одного дня с полной оценкой — TWR измерить не на чем, не хватает цен",
    REASON_SERIES_GAPS: "в ряду стоимостей дыры — цепочка TWR рвётся",
    REASON_CASH: "у денег доходности нет: проценты приходят отдельными записями",
    REASON_EMPTY_PERIOD: "период нулевой длины — ещё не прошло ни дня",
    "no_price": "нет цены на конец периода",
    "no_rate": "нет курса валюты",
    "no_cost_basis": "бумага пришла переводом, себестоимость неизвестна",
    "currency_mismatch": "расчёты и котировка в разных валютах",
}

Breakdown = Literal["none", "accounts", "asset_classes", "instruments", "all"]


def _reason(code: str | None) -> str | None:
    return None if code is None else REASON_TEXTS.get(code, code)


def _metric(metric: Metric) -> dict:
    return {
        "xirr": s.rate(metric.xirr), "twr": s.rate(metric.twr),
        "profit_rub": s.amount(metric.profit), "invested_rub": s.amount(metric.invested),
        "value_rub": s.amount(metric.value), "twr_measured_days": metric.chain_days,
        "reason": _reason(metric.reason),
    }


def returns(
    session: Session,
    period: Annotated[Literal["all", "12m", "ytd", "custom"], Field(
        description="Период: всё время, 12 месяцев, с начала года или custom с границами since/until")] = "all",
    since: Annotated[date | None, Field(
        description="Начало произвольного периода, ГГГГ-ММ-ДД (только при period=custom)")] = None,
    until: Annotated[date | None, Field(
        description="Конец произвольного периода; по умолчанию сегодня (только при period=custom)")] = None,
    breakdown: Annotated[Breakdown, Field(
        description="Какие разрезы вернуть: accounts, asset_classes, instruments, all или none")] = "asset_classes",
    instruments_limit: Annotated[int, Field(ge=1, le=300, description=(
        "Сколько строк разреза по бумагам вернуть; порядок: открытые раньше закрытых, "
        "по стоимости и модулю прибыли"))] = 30,
) -> dict:
    if period != PERIOD_CUSTOM and (since is not None or until is not None):
        raise ToolRefusal("Границы since/until действуют только при period=custom")
    try:
        report = returns_report(session, period, since=since, until=until)
    except PeriodError as error:
        raise ToolRefusal(str(error)) from error

    bounds = report.period
    if bounds.since is None:
        raise ToolRefusal("Истории стоимости нет: снимков в базе ещё нет, доходность считать не из чего")

    coverage = report.coverage
    result: dict = {
        "period": {
            "key": bounds.key, "from": s.day(bounds.since), "to": s.day(bounds.until),
            "annualized": bounds.annualized,
            "note": None if bounds.annualized else "период короче года: ставки за период, не в годовых",
        },
        "portfolio": _metric(report.portfolio),
        "twr_coverage": {
            "measured_days": coverage.chain_days, "days_total": coverage.days_total,
            "days_fully_valued": coverage.days_valued, "chain_breaks": coverage.chain_breaks,
            "note": ("TWR измерен только на днях с полной оценкой; годовая ставка приведена по "
                     "measured_days, а не по длине периода. XIRR от дыр в ценах не зависит."),
        },
        "coverage": {
            "positions_total": coverage.positions_total, "positions_valued": coverage.positions_valued,
            "unpriced": coverage.unpriced, "currencies_without_rate": coverage.currencies_without_rate,
        },
        "unattributed": {
            "profit_rub": s.amount(report.unattributed.profit),
            "fees_rub": s.amount(report.unattributed.fees),
            "taxes_rub": s.amount(report.unattributed.taxes),
            "other_rub": s.amount(report.unattributed.other),
            "note": "комиссии, налоги и возвраты без привязки к бумаге — строка «Прочее»",
        },
    }

    if breakdown in ("accounts", "all"):
        accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
        result["by_account"] = [
            {**s.account_ref(accounts[row.account_id]), **_metric(row.metric)}
            for row in report.by_account if row.account_id in accounts
        ]
    if breakdown in ("asset_classes", "all"):
        result["by_asset_class"] = [
            {"asset_class": row.asset_class, **_metric(row.metric)} for row in report.by_asset_class
        ]
    if breakdown in ("instruments", "all"):
        rows = report.by_instrument
        result["by_instrument"] = [
            {"instrument_id": row.instrument_id, "name": row.name, "ticker": row.ticker,
             "xirr": s.rate(row.xirr), "profit_rub": s.amount(row.profit),
             "value_rub": s.amount(row.value), "closed": row.closed,
             "unrealized_rub": s.amount(row.unrealized),
             "price_part_rub": s.amount(row.price_part), "fx_part_rub": s.amount(row.fx_part),
             "reason": _reason(row.reason)}
            for row in rows[:instruments_limit]
        ]
        result["by_instrument_total"] = len(rows)
        result["by_instrument_truncated"] = len(rows) > instruments_limit
        result["instruments_without_profit"] = [row.name for row in rows if row.profit is None]
    return result
