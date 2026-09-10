"""Инструмент positions: что есть, доли, цена покупки против текущей, прибыль
по каждой — с причиной там, где числа нет."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.analytics.service import ASSET_CLASSES, PositionRow, portfolio_overview, position_rows
from app.models import Account

REASON_NO_COST_BASIS = "себестоимость неизвестна: бумаги пришли переводом"
REASON_NO_PRICE = "котировки нет — стоимость и прибыль неизвестны"
REASON_NO_RATE = "цена есть, курса валюты к рублю нет"
REASON_CURRENCY_MISMATCH = ("средняя цена и котировка в разных валютах — прибыль без курса на "
                            "дату покупки не считается")


def _profit_reason(row: PositionRow) -> str | None:
    """Причина отсутствия нереализованной прибыли в валюте бумаги.

    Проверяется в порядке: если прибыль есть, причины нет. Иначе:
    - отсутствие себестоимости (бумаги пришли переводом)
    - отсутствие котировки (нет цены и, следовательно, прибыли)
    - несовпадение валют (цена и котировка в разных валютах)

    Отсутствие курса валюты (value_base is None при наличии market_value) не причина
    отсутствия прибыли — это причина отсутствия value_base (см. value_reason).
    """
    if row.profit is not None:
        return None
    if not row.cost_basis_known:
        return REASON_NO_COST_BASIS
    if row.market_value is None:
        return REASON_NO_PRICE
    return REASON_CURRENCY_MISMATCH


def _value_reason(row: PositionRow) -> str | None:
    """Причина отсутствия стоимости позиции в рублях (value_base)."""
    if row.market_value is None:
        return REASON_NO_PRICE
    if row.value_base is None:
        return REASON_NO_RATE
    return None


def positions(
    session: Session,
    account_id: Annotated[int | None, Field(
        description="Только этот счёт (account_id из portfolio_overview)")] = None,
    asset_class: Annotated[str | None, Field(
        description="Только этот класс: equity, bonds, cash, gold, mixed, derivatives, other…")] = None,
    unpriced_only: Annotated[bool, Field(description="Только позиции без оценки")] = False,
) -> dict:
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    if account_id is not None and account_id not in accounts:
        known = ", ".join(f"{account.id} — {s.account_ref(account)['title']}"
                          for account in accounts.values())
        raise ToolRefusal(f"Счёта {account_id} нет. Известные счета: {known or 'ни одного'}")
    if asset_class is not None and asset_class not in ASSET_CLASSES:
        raise ToolRefusal(f"Класса «{asset_class}» нет. Известные: {', '.join(sorted(ASSET_CLASSES))}")

    overview = portfolio_overview(session)
    total = overview.total_value
    # Дорогие первыми, неоценённые — в конце своим списком: у них стоимости
    # нет, и ноль поставил бы их среди дешёвых.
    ordered = sorted(position_rows(session),
                     key=lambda row: (row.value_base is None, -(row.value_base or Decimal("0")), row.name))

    rows = []
    for row in ordered:
        if account_id is not None and row.account_id != account_id:
            continue
        if asset_class is not None and row.asset_class != asset_class:
            continue
        if unpriced_only and row.value_base is not None:
            continue
        rows.append({
            "instrument_id": row.instrument_id, "name": row.name, "ticker": row.ticker,
            "isin": row.isin, "asset_class": row.asset_class,
            "account": s.account_ref(accounts[row.account_id]),
            "quantity": s.qty(row.quantity), "blocked": s.qty(row.blocked),
            "restricted": row.restricted, "currency": row.currency,
            "average_price": s.price(row.average_price),
            "average_price_currency": row.average_price_currency,
            "last_price": s.price(row.last_price), "price_source": row.price_source,
            "market_value": s.amount(row.market_value),
            "value_rub": s.amount(row.value_base),
            "value_reason": _value_reason(row),
            "share": (s.rate(row.value_base / total)
                      if row.value_base is not None and total else None),
            "profit": s.amount(row.profit), "profit_percent": s.percent(row.profit_percent),
            "profit_reason": _profit_reason(row),
        })

    return {
        "as_of": s.day(overview.as_of),
        "filter": {"account_id": account_id, "asset_class": asset_class,
                   "unpriced_only": unpriced_only},
        "count": len(rows),
        "total_value_rub": s.amount(total),
        "coverage": {
            "positions_total": overview.positions_total,
            "valued_positions": overview.valued_positions,
            "unpriced": overview.unpriced,
            "currencies_without_rate": overview.currencies_without_rate,
        },
        "rows": rows,
        "note": ("share — доля от всего портфеля (total_value_rub), включая деньги. value_reason — "
                 "причина отсутствия value_rub (нет цены или курса). profit — "
                 "нереализованная прибыль к средней цене, в валюте бумаги; null с причиной в "
                 "profit_reason. Цена с price_source=tbank — оценка брокера, не биржи."),
    }
