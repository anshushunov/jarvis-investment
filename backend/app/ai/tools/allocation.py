"""Инструмент allocation: факт против целей, отклонения, сколько докинуть и
куда. Расчёт — в app/allocation/, здесь только форма ответа."""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import Field
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.allocation.service import allocation_report


def allocation(
    session: Session,
    contribution_rub: Annotated[str | None, Field(description=(
        "Своя сумма пополнения в рублях строкой, например \"100000\". Без неё считается "
        "минимальная сумма, после которой ни одна группа не превышает цель"))] = None,
) -> dict:
    contribution = None
    if contribution_rub is not None:
        try:
            contribution = Decimal(contribution_rub.replace(" ", "").replace(" ", "").replace(",", "."))
        except InvalidOperation:
            raise ToolRefusal(f"Сумма пополнения «{contribution_rub}» не читается как число") from None
        if not contribution.is_finite():
            raise ToolRefusal(f"Сумма пополнения «{contribution_rub}» не читается как число")
        if contribution < 0:
            raise ToolRefusal("Сумма пополнения не может быть отрицательной: продаж расчёт не предлагает")

    report = allocation_report(session, contribution)
    plan = report.rebalance
    notes = list(report.notes)
    if plan.unfixable:
        surplus = s.amount(plan.buy_total - plan.contribution)
        notes.append(
            f"Покупки на {s.amount(plan.buy_total)} ₽ больше пополнения на {surplus} ₽: "
            "разница финансируется продажей групп из unfixable_without_selling — "
            "пополнением их не выправить"
        )
    return {
        "as_of": s.day(report.as_of),
        "total_value_rub": s.amount(report.total_value),
        "targets": [
            {"kind": row.kind, "key": row.key, "title": row.title,
             "target_share": s.rate(row.target), "actual_share": s.rate(row.actual),
             "value_rub": s.amount(row.value),
             "deviation_points": s.percent(row.deviation_points),
             "deviation_rub": s.amount(row.deviation_rub)}
            for row in report.rows
        ],
        "rebalance": {
            "minimal_contribution_rub": s.amount(plan.minimal_contribution),
            "contribution_rub": s.amount(plan.contribution),
            "contribution_is_custom": contribution is not None,
            "short_by_rub": s.amount(plan.short_by),
            "buy_total_rub": s.amount(plan.buy_total),
            "buy_by_group": {key: s.amount(value) for key, value in plan.deficits.items()},
            "not_closed_by_contribution": plan.not_closed,
            "unfixable_without_selling": {key: s.amount(value) for key, value in plan.unfixable.items()},
        },
        "coverage": {"positions_total": report.positions_total,
                     "valued_positions": report.valued_positions, "unpriced": report.unpriced},
        "notes": notes,
    }
