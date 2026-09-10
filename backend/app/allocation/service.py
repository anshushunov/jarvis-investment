"""Целевые доли: хранение, проверка набора и сравнение с фактом (дизайн 5a,
раздел 4.4).

Факт берётся из тех же расчётов, что и цифры на экране: класс — из разбивки
`portfolio_overview`, бумага — суммой `position_rows` по счетам. Второго
расчёта стоимости здесь нет.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.allocation.rebalance import Group, Rebalance, rebalance
from app.analytics.service import ASSET_CLASSES, asset_class_of, portfolio_overview, position_rows
from app.models import Instrument, TargetAllocation
from app.money import money

# Ключ подразумеваемой группы «не задано»: всё, что не покрыто целями.
UNASSIGNED_KEY = "unassigned"

SHARE_EXP = Decimal("0.0001")
ONE = Decimal("1")

# Оговорка едет с каждым расчётом: он говорит, сколько денег выправит доли, а
# не какие заявки выставить.
CAVEAT = ("Расчёт не знает про лотность, минимальные суммы сделок и налоговые "
          "последствия продаж: он называет сумму, которая выправит доли, а не заявки.")


class AllocationError(ValueError):
    """Набор целей противоречив; текст — для владельца, по-русски."""


@dataclass(frozen=True)
class TargetInput:
    share: Decimal
    asset_class: str | None = None
    isin: str | None = None


@dataclass(frozen=True)
class AllocationRow:
    kind: str                         # "asset_class" | "instrument" | "unassigned"
    key: str                          # класс, ISIN или UNASSIGNED_KEY
    title: str
    target: Decimal                   # целевая доля, 0..1
    value: Decimal                    # факт в рублях
    actual: Decimal | None            # фактическая доля; None — портфель пуст
    deviation_points: Decimal | None  # факт минус цель, в процентных пунктах
    deviation_rub: Decimal            # факт минус цель, в рублях


@dataclass(frozen=True)
class AllocationReport:
    total_value: Decimal
    as_of: date | None
    rows: list[AllocationRow]
    rebalance: Rebalance
    valued_positions: int
    positions_total: int
    unpriced: list[str]
    notes: list[str]


def list_targets(session: Session) -> list[TargetAllocation]:
    # Классы раньше бумаг, внутри — по алфавиту и порядку записи: у ответа
    # несколько читателей (API, инструмент), и порядок задан здесь.
    return list(session.execute(
        select(TargetAllocation).order_by(TargetAllocation.asset_class.nulls_last(),
                                          TargetAllocation.id)
    ).scalars().all())


def replace_targets(session: Session, targets: list[TargetInput]) -> list[TargetAllocation]:
    """Заменяет набор целей целиком. Проверки — до первой записи: набор либо
    принимается весь, либо не принимается вовсе."""
    rows: list[TargetAllocation] = []
    class_targets: set[str] = set()
    instruments: dict[int, Instrument] = {}
    total = Decimal("0")

    for target in targets:
        # Единое правило округления проекта (app.money.money) — ROUND_HALF_UP,
        # а не банковское округление decimal по умолчанию.
        share = target.share.quantize(SHARE_EXP, rounding=ROUND_HALF_UP)
        if share <= 0 or share > ONE:
            raise AllocationError(
                f"Доля должна быть больше нуля и не больше 100 %, получено {target.share}")
        if (target.asset_class is None) == (target.isin is None):
            raise AllocationError("У цели ровно один ключ: либо класс активов, либо бумага")
        total += share

        if target.asset_class is not None:
            if target.asset_class not in ASSET_CLASSES:
                raise AllocationError(f"Неизвестный класс активов «{target.asset_class}»; "
                                      f"известные: {', '.join(sorted(ASSET_CLASSES))}")
            if target.asset_class in class_targets:
                raise AllocationError(f"Класс «{target.asset_class}» назван дважды")
            class_targets.add(target.asset_class)
            rows.append(TargetAllocation(asset_class=target.asset_class, share=share))
            continue

        instrument = session.execute(
            select(Instrument).where(Instrument.isin == target.isin)).scalar_one_or_none()
        if instrument is None:
            raise AllocationError(f"Бумага {target.isin} не найдена в справочнике")
        if instrument.id in instruments:
            raise AllocationError(f"Бумага {target.isin} названа дважды")
        instruments[instrument.id] = instrument
        rows.append(TargetAllocation(instrument_id=instrument.id, share=share))

    if total > ONE:
        raise AllocationError(f"Сумма целей {total * 100:.2f} % превышает 100 %")

    # Одно пространство целей: бумага внутри класса, у которого есть своя
    # цель, посчитала бы один рубль дважды.
    for instrument in instruments.values():
        klass = asset_class_of(instrument)
        if klass in class_targets:
            name = instrument.issuer or instrument.ticker or instrument.isin
            raise AllocationError(f"У класса «{klass}» уже задана цель — бумага {name} внутри "
                                  "него отдельной цели иметь не может")

    session.execute(delete(TargetAllocation))
    session.add_all(rows)
    session.flush()
    return list_targets(session)


def _row(kind: str, key: str, title: str, target: Decimal, value: Decimal,
         total: Decimal) -> AllocationRow:
    # Единое правило округления проекта (app.money.money) — ROUND_HALF_UP.
    actual = (value / total).quantize(SHARE_EXP, rounding=ROUND_HALF_UP) if total else None
    return AllocationRow(
        kind=kind, key=key, title=title, target=target, value=money(value), actual=actual,
        deviation_points=(((actual - target) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                          if actual is not None else None),
        deviation_rub=money(value - target * total),
    )


def allocation_report(session: Session, contribution: Decimal | None = None) -> AllocationReport:
    """Факт против целей и выравнивание пополнением.

    Неоценённая позиция в факт не входит и в стоимость портфеля тоже — так же,
    как на дашборде; покрытие едет в отчёте, а бумага с целью и без цены
    названа в notes отдельно.
    """
    targets = list_targets(session)
    overview = portfolio_overview(session)
    positions = position_rows(session)
    total = overview.total_value

    instruments = {
        instrument.id: instrument
        for instrument in session.execute(select(Instrument).where(Instrument.id.in_(
            [target.instrument_id for target in targets if target.instrument_id is not None]
        ))).scalars()
    }

    groups: list[Group] = []
    rows: list[AllocationRow] = []
    notes: list[str] = [CAVEAT]
    assigned_share = Decimal("0")
    assigned_value = Decimal("0")

    for target in targets:
        if target.asset_class is not None:
            kind, key, title = "asset_class", target.asset_class, target.asset_class
            value = overview.by_asset_class.get(target.asset_class, Decimal("0"))
        else:
            instrument = instruments[target.instrument_id]
            title = instrument.issuer or instrument.ticker or instrument.isin or "—"
            kind, key = "instrument", instrument.isin or str(instrument.id)
            held = [row for row in positions if row.instrument_id == instrument.id]
            value = money(sum((row.value_base for row in held if row.value_base is not None),
                              Decimal("0")))
            if any(row.value_base is None for row in held):
                notes.append(f"{title}: часть позиции без оценки, факт занижен")
        groups.append(Group(key=key, target=target.share, value=value))
        rows.append(_row(kind, key, title, target.share, value, total))
        assigned_share += target.share
        assigned_value += value

    unassigned_share = ONE - assigned_share
    unassigned_value = money(max(Decimal("0"), total - assigned_value))
    if unassigned_share > 0 or unassigned_value > 0:
        groups.append(Group(key=UNASSIGNED_KEY, target=unassigned_share, value=unassigned_value))
        rows.append(_row("unassigned", UNASSIGNED_KEY, "не задано", unassigned_share,
                         unassigned_value, total))

    if not targets:
        notes.append("Целевые доли не заданы: задать их можно в «Настройках»")

    return AllocationReport(
        total_value=total, as_of=overview.as_of, rows=rows,
        rebalance=rebalance(groups, contribution),
        valued_positions=overview.valued_positions, positions_total=overview.positions_total,
        unpriced=overview.unpriced, notes=notes,
    )
