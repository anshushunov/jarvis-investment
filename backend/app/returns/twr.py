from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.returns.flows import CashFlow
from app.returns.xirr import DAYS_IN_YEAR

# Четыре знака — как у всех долей в проекте. Проценты и округление до десятых —
# дело интерфейса, здесь хранится величина.
PRECISION = Decimal("0.0001")

# Шаг цепочки — ровно сутки: точки, между которыми есть пропуск, соседями не
# считаются (см. twr).
ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Chain:
    """Результат цепочки. `breaks` — сколько шагов выпало из неё: у них не было
    базы для сравнения (нулевая или отрицательная стоимость накануне) либо один
    из концов оценён не полностью. Число важнее самой ставки: цепочка с
    разрывами отвечает на вопрос лишь частично, и молчать об этом нельзя."""

    rate: Decimal | None
    days: int
    breaks: int


def twr(values: list[tuple[date, Decimal]], flows: list[CashFlow],
        incomplete: set[date] | frozenset[date] | None = None) -> Chain:
    """Доходность, очищенная от влияния пополнений и изъятий.

    За каждый день стоимость сравнивается с предыдущей, увеличенной на вложения
    этого дня. Знак потока — владельческий (вложение отрицательно), поэтому
    вложение прибавляется к базе вычитанием: `V_prev - flow.amount`.

    Шаг берётся только между соседними календарными днями. Пропуск в ряду — не
    длинный шаг, а разрыв: потоки, случившиеся внутри дыры, в базу шага не
    попадают, и цепочка примет уход капитала за падение цены. Для портфеля
    целиком это ничего не меняет (`total_value` есть в каждом снимке), для
    разрезов — лечит: ключа класса или счёта в снимке может не быть вовсе.

    `incomplete` — даты, стоимость которых занижена не рынком, а отсутствием
    цены: их считает вызывающая сторона по покрытию снимка, а функция про
    `DailySnapshot` не знает. Замер 14.08.2026: полная оценка есть у 448 дат из
    2220, и цепочка по всем 2220 давала −11,27 % при прибыли +936 740 ₽ и XIRR
    +3,65 %, а классу `mixed` — −100 % при стоимости 4,97 млн ₽ (дизайн,
    раздел 4.3).
    """
    if len(values) < 2:
        return Chain(rate=None, days=0, breaks=0)

    incomplete = incomplete or frozenset()
    ordered = sorted(values)
    by_day: dict[date, Decimal] = {}
    for flow in flows:
        by_day[flow.on_date] = by_day.get(flow.on_date, Decimal("0")) + flow.amount

    product = Decimal("1")
    breaks = 0
    measured = 0
    for (previous_day, previous), (day, current) in zip(ordered, ordered[1:]):
        if day - previous_day != ONE_DAY:
            # Соседние точки ряда — не соседние дни: между ними дыра, а в ней
            # остались потоки, которых у шага нет. Замер 14.08.2026 по классу
            # `mixed`: 17.02.2021 — 213 494,51 ₽, следующая точка 28.06.2021 —
            # 8,90 ₽, четыре месяца снимков без этого класса, и продажа фондов
            # внутри дыры. Цепочка приняла её за падение в ноль и дала −100 %
            # при стоимости 4,97 млн ₽.
            breaks += 1
            continue
        if previous_day in incomplete or day in incomplete:
            # День с неполной оценкой выпадает и как измеряемая величина, и как
            # база следующего дня: занижённая стоимость врёт дважды — сначала
            # провалом, потом мнимым отскоком, — и перемножение этой пары
            # ошибку не гасит, а закрепляет.
            breaks += 1
            continue
        base = previous - by_day.get(day, Decimal("0"))
        if base <= 0:
            # Ни роста, ни падения измерить нельзя: сравнивать не с чем.
            # Множитель нейтральный, а факт разрыва уезжает наверх числом.
            breaks += 1
            continue
        product *= current / base
        measured += 1

    days = (ordered[-1][0] - ordered[0][0]).days
    if measured == 0:
        # Ни одного измеренного шага: цепочка не «дала ноль», а не построилась
        # вовсе. Ноль здесь утверждал бы, что портфель ничего не заработал, —
        # это ответ, а не его отсутствие, и на живых данных он был бы ложью:
        # с августа 2025 полной оценки нет ни у одного дня.
        return Chain(rate=None, days=days, breaks=breaks)
    return Chain(rate=(product - Decimal("1")).quantize(PRECISION), days=days,
                 breaks=breaks)


def annualize(rate: Decimal, days: int) -> Decimal:
    """Пересчёт доходности за период в годовую.

    Применяется только к периодам от года: на более коротких результат врёт
    кратно (два процента за месяц превращаются в двадцать семь годовых), и
    служба показывает такую доходность как есть, с подписью «за период».
    """
    if days <= 0:
        return rate.quantize(PRECISION)
    exponent = DAYS_IN_YEAR / Decimal(days)
    return ((Decimal("1") + rate) ** exponent - Decimal("1")).quantize(PRECISION)
