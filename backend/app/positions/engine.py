from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from app.models import OperationType
from app.money import money, quantity as q

INCREASING = {OperationType.BUY, OperationType.TRANSFER_IN}
DECREASING = {OperationType.SELL, OperationType.REDEMPTION, OperationType.TRANSFER_OUT}

# Операции, которые двигают количество, но не создают закрытой сделки: ни ввод,
# ни вывод бумаг не несут финансового результата — у перевода нет цены.
# TRANSFER_OUT, закрывающий длинную позицию, — не продажа, выручки у него нет.
# TRANSFER_IN, закрывающий короткую позицию (так же, как её закрывает выкуп
# BUY), пришёл бы с нулевой ценой, и обычная ветка закрытия записала бы в
# realized выручку от продажи против нулевой себестоимости — сфабрикованную
# прибыль из воздуха. Считать перевод сделкой в любую сторону значило бы
# выдумать финансовый результат и испортить налоговую базу.
# ADJUSTMENT здесь по той же причине: ручная поправка количества — это
# исправление учёта, а не сделка с рынком, выручки у неё нет.
WITHOUT_REALIZED = {
    OperationType.TRANSFER_OUT,
    OperationType.TRANSFER_IN,
    OperationType.ADJUSTMENT,
}

# Операции, приносящие количество без себестоимости: брокер её при переводе не
# сообщает, а выдумывать нельзя.
WITHOUT_COST = {OperationType.TRANSFER_IN}

# Стороны конвертации. В INCREASING/DECREASING они не входят: их обработка
# отдельная — количество не открывает и не закрывает партии по цене операции,
# а переносит уже существующие партии из одной бумаги в другую.
CONVERSION = {OperationType.CONVERSION_OUT, OperationType.CONVERSION_IN}


def _sign(value: Decimal) -> int:
    return (value > 0) - (value < 0)


# ── Соглашение о знаке количества ────────────────────────────────────────────
#
# Количество в журнале беззнаковое, направление задаёт тип операции. У
# ADJUSTMENT типа-направления нет: он один на поправку в обе стороны, и
# направление несёт знак самого количества. Правило это домен обязан хранить в
# одном месте: производителей записей ADJUSTMENT двое — служба решений
# (app/decisions/service.py) и корректировка изменённой брокером операции
# (app/ledger/service.py), — и стоило одному из них проставить знак самому, как
# доисполненная продажа превращалась в покупку: разность +88 по продаже
# открывала партию на 88 бумаг по цене продажи. Обе функции ниже и есть это
# единственное место; ставить минус где-то ещё нельзя.


def signed_quantity(op_type: OperationType, quantity: Decimal) -> Decimal:
    """Количество со знаком, в каком операция двигает позицию.

    Плюс — приход, минус — расход, ноль — операция количество не двигает вовсе
    (деньги, комиссия, налог; сюда же попадает и всё, что не перечислено в
    INCREASING/DECREASING). У ADJUSTMENT знак уже в количестве, и трогать его
    нельзя — это и есть его направление.

    Предпосылка: у операции с собственным направлением (INCREASING, DECREASING)
    количество неотрицательно — знак несёт тип, а не число. Отрицательное
    количество продажи здесь стало бы приходом. Производители RawOperation
    обязаны это соблюдать; у единственного сегодняшнего — коннектора Т-Банка —
    предпосылка закреплена тестом (tests/test_tbank_mapper.py,
    test_mapper_never_produces_negative_quantity_for_directional_operations).
    У ADJUSTMENT всё наоборот: знак и есть направление, и трогать его нельзя.

    Стороны конвертации сюда не входят: они не открывают и не закрывают партии
    по своему количеству, а переносят чужие (см. CONVERSION и _apply_conversion).
    """
    if op_type is OperationType.ADJUSTMENT:
        return quantity
    if op_type in INCREASING:
        return quantity
    if op_type in DECREASING:
        return -quantity
    return Decimal("0")


def decreasing_adjustment(quantity: Decimal) -> Decimal:
    """Знаковое количество поправки, списывающей `quantity` бумаг.

    Владелец задаёт количество списания положительным (так же его отдаёт и
    интерфейс), а знак ставится здесь — в том же месте, где записано само
    соглашение, а не в службе решений.
    """
    return -abs(quantity)


class ConversionError(RuntimeError):
    """Стороны конвертации не сошлись. Это порча данных, а не редкий случай:
    молча открыть партию с нулевой ценой значит подарить владельцу выдуманную
    доходность и неверную налоговую базу."""


class ReversalError(RuntimeError):
    """Отмена решения не может вернуть книгу партий к прежнему виду.

    Отмена адресная: она снимает те самые партии, которые открыло отменяемое
    решение, и возвращает те самые, которые оно сняло. Если этих партий в книге
    больше нет, промолчать нельзя — отмена сняла бы чужие партии, с чужой
    себестоимостью и чужой датой открытия, и трёхлетняя льгота досталась бы не
    той бумаге.
    """


@dataclass(frozen=True)
class LedgerEntry:
    op_type: OperationType
    executed_at: datetime
    instrument_id: int | None
    quantity: Decimal
    price: Decimal
    amount: Decimal
    fee: Decimal
    # Идентификатор решения владельца, связывающий две стороны конвертации
    # (payload.decision_id порождённых записей). None у всего остального.
    link_id: int | None = None
    # Идентификатор отменяемого решения (payload.reverts_decision_id). Запись с
    # ним не двигает количество по своим цене и количеству, а раскручивает след
    # названного решения: количество и цена у неё описательные, для чтения
    # журнала человеком.
    reverts_link_id: int | None = None
    # Номер строки в журнале (transaction.id). Задаёт порядок применения
    # записей, порождённых решениями владельца, внутри одного мгновения: отмена
    # обязана лечь после отменяемого решения, а вторая конвертация — после
    # первой, отдавшей ей бумагу. У операций брокера порядок внутри мгновения
    # задаётся не им, а смыслом операции (см. sort_key в fold).
    row_id: int | None = None


@dataclass
class OpenLot:
    """Открытая партия. `quantity_left` знаковое: положительное — длинная
    позиция (куплено и ещё не продано), отрицательное — короткая (продано без
    остатка и ещё не выкуплено). `price` — цена, по которой партию открыли:
    для длинной это цена покупки, для короткой — цена продажи."""

    instrument_id: int
    opened_at: datetime
    price: Decimal
    quantity_left: Decimal
    # Известна ли себестоимость партии. Ложь у партии, пришедшей переводом:
    # цена там ноль не потому, что бумага досталась даром, а потому, что
    # брокер себестоимости не прислал.
    cost_known: bool = True


@dataclass(frozen=True)
class RealizedSale:
    instrument_id: int
    sold_at: datetime
    quantity: Decimal
    proceeds: Decimal
    cost: Decimal
    opened_at: datetime


@dataclass
class PositionState:
    instrument_id: int
    quantity: Decimal
    average_price: Decimal
    lots: list[OpenLot] = field(default_factory=list)
    # Истина, когда себестоимость известна по всем партиям. Ложь — средняя цена
    # и доходность по позиции не показываются вовсе: усреднение с нулём даёт
    # правдоподобное, но неверное число, которое владелец примет за настоящее.
    cost_basis_known: bool = True


@dataclass
class DecisionEffect:
    """След решения владельца в книге партий: что оно открыло и что сняло.

    Нужен для адресной отмены. Отмена, выраженная просто встречной операцией,
    партий не знает, а угадывает их по FIFO — и промахивается. На живом примере:
    79 бумаг по 120, купленные в 2024-м, конвертируются в бумагу, где уже лежат
    79 по 10 от 2020 года. Зеркальный CONVERSION_OUT снял бы с целевой бумаги
    самые старые партии, то есть чужие: количества после отмены сходятся, а
    себестоимость и даты открытия меняются бумагами местами — трёхлетняя льгота
    достаётся не той бумаге. То же у поправки: зеркальное списание съедало бы
    старую брокерскую партию, оставляя в книге партию отменённого решения.
    """

    # Партии, открытые решением: сам объект в книге и количество, каким его
    # открыли. Количество нужно отдельно — партию могли частично закрыть
    # позднейшие продажи, и тогда отменять уже поздно.
    created: dict[int, list[tuple[OpenLot, Decimal]]] = field(default_factory=dict)
    # Партии, снятые решением, — копии с исходными датой, ценой и признаком
    # известной себестоимости. Отмена возвращает их в книгу как есть.
    removed: dict[int, list[OpenLot]] = field(default_factory=dict)
    # Закрытые сделки, порождённые решением: конвертация, погасившая короткую
    # позицию, даёт настоящий финансовый результат, и отмена обязана убрать его
    # из налоговой базы вместе с самой конвертацией.
    realized: list[RealizedSale] = field(default_factory=list)

    def record_created(self, instrument_id: int, lot: OpenLot) -> None:
        self.created.setdefault(instrument_id, []).append((lot, lot.quantity_left))

    def record_removed(self, instrument_id: int, lot: OpenLot) -> None:
        self.removed.setdefault(instrument_id, []).append(replace(lot))


@dataclass(frozen=True)
class FoldResult:
    positions: dict[int, PositionState]
    realized: list[RealizedSale]
    cash: dict[str, Decimal]


def _average(lots: list[OpenLot]) -> Decimal:
    """Средняя цена открытых партий. По модулю количества: у короткой позиции
    партии отрицательные, а средняя цена — величина положительная (цена, по
    которой позицию открыли). Разнонаправленных партий в одной книге не
    бывает — встречная операция сначала закрывает противоположные (см. fold)."""
    total_qty = sum((abs(lot.quantity_left) for lot in lots), Decimal("0"))
    if total_qty == 0:
        return money("0")
    total_cost = sum((abs(lot.quantity_left) * lot.price for lot in lots), Decimal("0"))
    return money(total_cost / total_qty)


def _close_whole_position(
    lots: dict[int, list[OpenLot]],
    touched: set[int],
    realized: list[RealizedSale],
    entry: LedgerEntry,
) -> None:
    """Погашение облигации без количества закрывает выпуск целиком.

    Брокер по полному погашению присылает сумму выплаты, но не количество
    (quantity=0 — проверено на живом ответе T-Invest API), а номинала домен не
    знает. Опереться можно на смысл самой операции: выпуск погашен, держать
    больше нечего. Без этого погашенные бумаги остаются в портфеле навсегда —
    так на живом счёте висели ОФЗ 25083 и РУСАЛ БО-001Р-06.

    Выплата распределяется по открытым партиям пропорционально количеству:
    себестоимость у каждой своя, а общая выручка известна только целиком."""
    open_lots = lots.get(entry.instrument_id)
    if not open_lots:
        return

    total = q(sum((lot.quantity_left for lot in open_lots), Decimal("0")))
    if total <= 0:
        # Короткая позиция на момент погашения — случай, которого в живых
        # данных нет и смысл которого неочевиден; молча ничего не делаем,
        # чтобы не выдумать движение количества.
        return

    for lot in open_lots:
        realized.append(
            RealizedSale(
                instrument_id=entry.instrument_id,
                sold_at=entry.executed_at,
                quantity=lot.quantity_left,
                proceeds=money(entry.amount * lot.quantity_left / total),
                cost=money(lot.quantity_left * lot.price),
                opened_at=lot.opened_at,
            )
        )
    lots[entry.instrument_id] = []
    touched.add(entry.instrument_id)


def _effect_of(effects: dict[int, DecisionEffect], entry: LedgerEntry) -> DecisionEffect | None:
    """След решения, которому принадлежит запись.

    None у записей брокера (решения за ними нет) и у записей отмены: отмена
    собственного следа не оставляет, поэтому отменить отмену нельзя — попытка
    упрётся в понятный отказ, а не в порчу книги.
    """
    if entry.link_id is None or entry.reverts_link_id is not None:
        return None
    return effects.setdefault(entry.link_id, DecisionEffect())


def _restore_lot(open_lots: list[OpenLot], lot: OpenLot) -> None:
    """Возвращает в книгу партию, снятую отменяемым решением.

    Если остаток той же партии всё ещё в книге — совпали дата открытия, цена,
    признак себестоимости и направление, — количество складывается обратно, а
    не ложится второй строкой: списание 40 бумаг из партии в 100 и его отмена
    обязаны оставить ровно ту партию в 100, что была до решения. Партии с
    одинаковыми датой, ценой и признаком себестоимости неразличимы и для FIFO,
    и для налога, так что склейка ничего не теряет.
    """
    for existing in open_lots:
        if (
            existing.opened_at == lot.opened_at
            and existing.price == lot.price
            and existing.cost_known == lot.cost_known
            and _sign(existing.quantity_left) == _sign(lot.quantity_left)
        ):
            existing.quantity_left = q(existing.quantity_left + lot.quantity_left)
            return

    open_lots.insert(
        bisect_right(open_lots, lot.opened_at, key=lambda item: item.opened_at),
        replace(lot),
    )


def _revert_decision(
    lots: dict[int, list[OpenLot]],
    effects: dict[int, DecisionEffect],
    undone: set[tuple[int, int]],
    touched: set[int],
    realized: list[RealizedSale],
    entry: LedgerEntry,
) -> None:
    """Раскручивает по своей бумаге ровно то, что сделало отменяемое решение.

    Отмена адресная, а не «ещё одна операция в обратную сторону»: она убирает из
    книги те самые партии, которые решение открыло, и возвращает те самые,
    которые оно сняло, — с их исходными датами, ценами и признаком известной
    себестоимости. Количество и цена самой записи отмены при этом ни на что не
    влияют: они описательные, чтобы журнал читался человеком.

    Каждая сторона отмены отвечает за свою бумагу, поэтому пара зеркальных
    записей конвертации раскручивает след ровно один раз: одна снимает
    открытое, другая возвращает снятое. Кроме случая, когда бумага у сторон
    одна и та же: так записывают сплит и консолидацию (100 бумаг превращаются в
    200 тех же). Тогда обе стороны отмены указывают на один инструмент, и след
    по нему раскручивается только первой из них — второй проход не нашёл бы уже
    снятой партии и отказал бы, сославшись на израсходованные партии, то есть
    не на ту причину.
    """
    if (entry.reverts_link_id, entry.instrument_id) in undone:
        touched.add(entry.instrument_id)
        return

    effect = effects.get(entry.reverts_link_id)
    if effect is None:
        raise ReversalError(
            f"Отмена решения {entry.reverts_link_id} не нашла его следа в "
            "журнале: записей отменяемого решения нет, они идут позже или это "
            "попытка отменить саму отмену. Подобрать партии наугад нельзя — "
            "вернулись бы чужие даты и чужая себестоимость."
        )

    instrument_id = entry.instrument_id
    open_lots = lots.setdefault(instrument_id, [])

    for lot, opened_with in effect.created.get(instrument_id, []):
        # По тождеству объекта, а не по равенству полей: одинаковых по виду
        # партий в книге бывает несколько, и снять надо именно ту.
        position = next((index for index, item in enumerate(open_lots) if item is lot), None)
        if position is None or lot.quantity_left != opened_with:
            raise ReversalError(
                f"Партии, открытые решением {entry.reverts_link_id} по бумаге "
                f"{instrument_id}, уже израсходованы позднейшими операциями — "
                "отменять поздно. Иначе отмена сняла бы чужие партии, с чужой "
                "себестоимостью и чужой датой открытия."
            )
        open_lots.pop(position)

    for lot in effect.removed.get(instrument_id, []):
        _restore_lot(open_lots, lot)

    # Финансовый результат, порождённый отменяемым решением, уходит вместе с
    # ним: сделки, которой больше нет, в налоговой базе быть не должно.
    for sale in effect.realized:
        if sale.instrument_id != instrument_id:
            continue
        for index, item in enumerate(realized):
            if item is sale:
                del realized[index]
                break

    undone.add((entry.reverts_link_id, instrument_id))
    touched.add(instrument_id)


def _apply_conversion(
    lots: dict[int, list[OpenLot]],
    pockets: dict[int, list[OpenLot]],
    effects: dict[int, DecisionEffect],
    touched: set[int],
    realized: list[RealizedSale],
    entry: LedgerEntry,
) -> None:
    """Переносит открытые партии между бумагами при корпоративном действии.

    `CONVERSION_OUT` снимает партии по FIFO на указанное количество и кладёт их
    в карман под ключом `link_id`. `CONVERSION_IN` достаёт карман и
    раскладывает партии на новое количество: доля каждой партии сохраняется,
    суммарная себестоимость тоже, дата открытия переезжает как есть.

    Дата — не формальность. Трёхлетняя льгота по НДФЛ считается от неё, и
    свернуть партии в одну на дату конвертации значит сжечь льготу владельцу.
    """
    if entry.link_id is None:
        raise ConversionError(
            f"У стороны конвертации {entry.op_type.value} нет link_id: "
            "связать её со второй стороной нечем. Записи конвертации "
            "порождаются решением владельца и обязаны нести payload.decision_id."
        )

    # Защищаться обязан и сам движок, а не только служба решений: производитель
    # записей может оказаться другой. CONVERSION_IN с нулём — потеря молчаливая
    # и оттого худшая из всех: снятые партии разложились бы на ноль бумаг,
    # себестоимость исчезла бы, а позиция осталась бы помеченной как
    # «себестоимость известна» — портфель выглядел бы достоверным и был бы
    # неверен.
    if entry.quantity <= 0:
        raise ConversionError(
            f"У стороны конвертации {entry.op_type.value} количество "
            f"{entry.quantity}: перенести нулевое или отрицательное количество "
            "нельзя. Проверьте количество в решении владельца."
        )

    effect = _effect_of(effects, entry)

    if entry.op_type is OperationType.CONVERSION_OUT:
        open_lots = lots.get(entry.instrument_id, [])
        available = q(sum((lot.quantity_left for lot in open_lots), Decimal("0")))
        if available < entry.quantity:
            raise ConversionError(
                f"Конвертация списывает {entry.quantity} бумаг инструмента "
                f"{entry.instrument_id}, это больше, чем открыто ({available}). "
                "Проверьте количество в решении владельца."
            )

        taken_lots: list[OpenLot] = []
        remaining = q(entry.quantity)
        while remaining > 0:
            lot = open_lots[0]
            taken = min(lot.quantity_left, remaining)
            taken_lots.append(OpenLot(
                instrument_id=entry.instrument_id, opened_at=lot.opened_at,
                price=lot.price, quantity_left=taken, cost_known=lot.cost_known,
            ))
            lot.quantity_left = q(lot.quantity_left - taken)
            remaining = q(remaining - taken)
            if lot.quantity_left == 0:
                open_lots.pop(0)

        if effect is not None:
            for taken_lot in taken_lots:
                effect.record_removed(entry.instrument_id, taken_lot)

        pockets[entry.link_id] = taken_lots
        touched.add(entry.instrument_id)
        return

    taken_lots = pockets.pop(entry.link_id, None)
    if not taken_lots:
        raise ConversionError(
            f"CONVERSION_IN для решения {entry.link_id} не нашёл снятых партий: "
            "парного CONVERSION_OUT в журнале нет или он идёт позже. "
            "Открыть партию с нулевой ценой нельзя — это выдумало бы "
            "себестоимость и доходность."
        )

    old_quantity = q(sum((lot.quantity_left for lot in taken_lots), Decimal("0")))
    new_quantity = q(entry.quantity)
    open_lots = lots.setdefault(entry.instrument_id, [])
    distributed = Decimal("0")
    for index, lot in enumerate(taken_lots):
        # Доля партии в новом количестве та же, что была в старом; цена
        # меняется обратно пропорционально, поэтому себестоимость партии
        # (количество × цена) остаётся прежней с точностью до округления цены
        # до четырёх знаков: точное равенство сумм недостижимо в принципе —
        # 40000 / 1012 конечной десятичной дробью не записывается. Расхождение
        # ограничено половиной последнего знака цены на бумагу.
        if index == len(taken_lots) - 1:
            # Последней партии достаётся весь остаток количества. Иначе
            # округление долей до восьми знаков теряет или добавляет бумагу
            # (три партии по одной штуке в десять бумаг дают 3.33333333 × 3 =
            # 9.99999999), и позиция навсегда расходится со снимком брокера.
            share = q(new_quantity - distributed)
        else:
            share = q(lot.quantity_left * new_quantity / old_quantity)
        distributed = q(distributed + share)
        moved = OpenLot(
            instrument_id=entry.instrument_id,
            opened_at=lot.opened_at,
            price=money(lot.quantity_left * lot.price / share) if share else money("0"),
            quantity_left=share,
            cost_known=lot.cost_known,
        )
        # Сначала гасим встречные короткие партии целевой бумаги. Без этого в
        # книге оказывались партии разного знака сразу — инвариант «в книге
        # одного инструмента разнонаправленных партий не бывает» (см. _average
        # и fold) нарушался молча: продажа без остатка в тот же миг, что и
        # конвертация, оставляла +79 по 120 рядом с −79 по 200, финансовый
        # результат в 6320 в налоговую базу не попадал вовсе, а средняя цена
        # считалась по модулю количества и выходила 160.
        left = _close_short_lots(open_lots, moved, entry, realized, effect)
        if left <= 0:
            continue
        moved.quantity_left = left

        # Место в книге — по дате открытия, а не в хвост. Книга упорядочена по
        # ней, и весь движок считает open_lots[0] самой старой партией: на этом
        # стоят и закрытие встречных партий, и RealizedSale.opened_at. У
        # перенесённой партии дата старая, и если целевая бумага уже была в
        # портфеле, хвост поставил бы её в очередь последней — продажа закрыла
        # бы не ту партию, завысив себестоимость и спрятав трёхлетнюю льготу.
        # bisect_right, а не left: при равных датах партия, уже лежавшая в
        # книге, остаётся впереди, а сами перенесённые партии сохраняют свой
        # порядок между собой.
        open_lots.insert(
            bisect_right(open_lots, moved.opened_at, key=lambda item: item.opened_at),
            moved,
        )
        if effect is not None:
            effect.record_created(entry.instrument_id, moved)
    touched.add(entry.instrument_id)


def _close_short_lots(
    open_lots: list[OpenLot],
    incoming: OpenLot,
    entry: LedgerEntry,
    realized: list[RealizedSale],
    effect: DecisionEffect | None,
) -> Decimal:
    """Гасит короткие партии бумаги перенесённой партией. Возвращает остаток.

    Короткую позицию закрывают пришедшие бумаги: выручка — цена, по которой их
    продали без остатка, себестоимость — цена перенесённой партии. Сама
    конвертация финансового результата не несёт, но закрытие короткой позиции
    несёт: бумага действительно ушла покупателю, и разница цен — настоящая
    прибыль владельца.
    """
    remaining = incoming.quantity_left
    while remaining > 0 and open_lots and open_lots[0].quantity_left < 0:
        short = open_lots[0]
        taken = min(-short.quantity_left, remaining)
        sale = RealizedSale(
            instrument_id=entry.instrument_id,
            sold_at=entry.executed_at,
            quantity=taken,
            proceeds=money(taken * short.price),
            cost=money(taken * incoming.price),
            opened_at=short.opened_at,
        )
        realized.append(sale)
        if effect is not None:
            effect.realized.append(sale)
            effect.record_removed(entry.instrument_id, replace(short, quantity_left=q(-taken)))
        short.quantity_left = q(short.quantity_left + taken)
        remaining = q(remaining - taken)
        if short.quantity_left == 0:
            open_lots.pop(0)
    return remaining


def fold(entries: list[LedgerEntry], currency: str = "RUB") -> FoldResult:
    """Сворачивает журнал в позиции и закрытые сделки по FIFO.

    Операции обрабатываются в хронологическом порядке; при совпадающей метке
    времени покупка идёт раньше продажи, чтобы внутри одного мгновения не
    возникало мнимого разворота позиции.

    Позиция знаковая: положительная — длинная, отрицательная — короткая.
    Раньше движок не давал остатку уйти в минус и молча отбрасывал излишек
    продажи. Это не безобидная защита: продажа без остатка — обычная короткая
    сделка (на живом счёте владельца 13.11.2020 продано 10000 АФК «Система»
    при нулевом остатке), и закрывающая её покупка оседала в портфеле
    бумагой, которой у владельца нет. Так набралось 14 фантомных позиций,
    каждая ровно в размер шорта — SBER, TSLA, DSKY и другие.

    Встречная операция сначала закрывает противоположные партии по FIFO и
    только остатком открывает новые, поэтому в книге одного инструмента
    никогда не лежат разнонаправленные партии. Это верно и для приходящей
    стороны конвертации: перенесённая партия сначала гасит короткие.

    Записи, порождённые решением владельца, оставляют след — какие партии
    решение открыло и какие сняло (DecisionEffect). Запись отмены раскручивает
    именно его, а не подбирает партии встречной операцией по FIFO: иначе отмена
    возвращает верные количества с чужими датами и чужой себестоимостью.

    Суммы знаковые с точки зрения счёта: покупки отрицательные, продажи и
    дивиденды положительные. Комиссия вычитается отдельно и в amount не входит.
    """
    lots: dict[int, list[OpenLot]] = {}
    touched: set[int] = set()  # инструменты, по которым вообще двигалось количество
    realized: list[RealizedSale] = []
    cash: dict[str, Decimal] = defaultdict(lambda: money("0"))

    # Партии, снятые CONVERSION_OUT и ждущие своего CONVERSION_IN. Ключ —
    # link_id решения: два разных корпоративных действия одной датой не должны
    # черпать из общего кармана.
    pockets: dict[int, list[OpenLot]] = {}

    # След каждого решения владельца: что оно открыло и что сняло. По нему
    # работает адресная отмена (см. DecisionEffect и _revert_decision).
    effects: dict[int, DecisionEffect] = {}
    # Уже раскрученные пары «отменяемое решение, бумага»: у конвертации бумаги
    # в саму себя обе стороны отмены указывают на один инструмент.
    undone: set[tuple[int, int]] = set()

    # Порядок применения решений владельца внутри одного мгновения — тот, в
    # каком их записи легли в журнал (transaction.id). Решения применяются одно
    # за другим, и каждое следующее опирается на книгу, оставленную предыдущим:
    # отмена обязана лечь после отменяемого решения, а конвертация Y→Z — после
    # конвертации X→Y, отдавшей ей бумагу. Порядок берётся из строк журнала, а
    # не из идентификаторов решений: импорт решений с заданными номерами тогда
    # ничего не сломает. Группа — решение целиком, чтобы внутри него порядок
    # сторон задавал priority, а не случайность нумерации строк.
    group_order: dict[int, int] = {}
    for entry in entries:
        if entry.link_id is None:
            continue
        row = entry.row_id or 0
        if entry.link_id not in group_order or row < group_order[entry.link_id]:
            group_order[entry.link_id] = row

    # Порядок внутри одной группы. Покупка раньше продажи — чтобы не возникало
    # мнимого разворота позиции. CONVERSION_OUT строго раньше CONVERSION_IN:
    # иначе карман пуст и себестоимость теряется. IN идёт последним, потому что
    # снятые партии должны быть уже в кармане. Операции брокера — группа 0: они
    # и раньше стояли перед конвертациями по приоритету.
    def sort_key(entry):
        if entry.op_type in INCREASING:
            priority = 0
        elif entry.op_type is OperationType.CONVERSION_OUT:
            priority = 2
        elif entry.op_type is OperationType.CONVERSION_IN:
            priority = 3
        else:
            priority = 1
        group = 0 if entry.link_id is None else group_order[entry.link_id]
        return (entry.executed_at, group, priority)

    for entry in sorted(entries, key=sort_key):
        cash[currency] = money(cash[currency] + entry.amount - entry.fee)

        if entry.instrument_id is None:
            continue

        # Запись отмены не двигает количество по своим цене и количеству: она
        # раскручивает след названного решения — те самые партии, с их датами и
        # себестоимостью.
        if entry.reverts_link_id is not None:
            _revert_decision(lots, effects, undone, touched, realized, entry)
            continue

        if entry.op_type in CONVERSION:
            _apply_conversion(lots, pockets, effects, touched, realized, entry)
            continue

        effect = _effect_of(effects, entry)

        # Направление — из общего соглашения о знаке (signed_quantity), а не из
        # разбора типов на месте: то же правило читают производители записей
        # ADJUSTMENT, и разъехаться им нельзя.
        direction = _sign(signed_quantity(entry.op_type, entry.quantity))

        if direction == 0:
            # Ноль означает одно из двух: тип количество не двигает (деньги,
            # комиссия) либо количество нулевое — например, поправка, которой
            # брокер изменил одну только сумму. Единственное исключение —
            # полное погашение: оно приходит без количества и закрывает выпуск
            # целиком.
            if entry.quantity == 0 and entry.op_type is OperationType.REDEMPTION:
                _close_whole_position(lots, touched, realized, entry)
            continue

        open_lots = lots.setdefault(entry.instrument_id, [])
        touched.add(entry.instrument_id)

        # По модулю: у отрицательной поправки количество меньше нуля, а
        # remaining в цикле FIFO обязан быть положительным — направление уже
        # снято отдельно в direction.
        remaining = q(abs(entry.quantity))
        unit_price = money(entry.price)

        # Сначала гасим встречные партии: продажа закрывает длинные, покупка
        # выкупает короткие. Условие — знак партии противоположен направлению
        # операции.
        while remaining > 0 and open_lots and _sign(open_lots[0].quantity_left) == -direction:
            lot = open_lots[0]
            taken = min(abs(lot.quantity_left), remaining)
            # У длинной позиции выручка — цена продажи, себестоимость — цена
            # покупки. У короткой ровно наоборот: заработок в том, что выкупили
            # дешевле, чем продали, поэтому выручка берётся из цены открытия
            # партии, а себестоимость — из цены текущего выкупа.
            if direction < 0:
                proceeds, cost = unit_price, lot.price
            else:
                proceeds, cost = lot.price, unit_price
            if entry.op_type not in WITHOUT_REALIZED:
                sale = RealizedSale(
                    instrument_id=entry.instrument_id,
                    sold_at=entry.executed_at,
                    quantity=taken,
                    proceeds=money(taken * proceeds),
                    cost=money(taken * cost),
                    opened_at=lot.opened_at,
                )
                realized.append(sale)
                if effect is not None:
                    effect.realized.append(sale)
            # Съеденная часть встречной партии — след решения: отмена вернёт её
            # с исходными датой, ценой и признаком себестоимости. Без этого
            # отмена списания стирала бы себестоимость: зеркальная поправка
            # открывала бы партию по цене ноль, а ноль в поправке означает
            # «неизвестно», и позиция переставала показывать среднюю и
            # доходность вовсе.
            if effect is not None:
                effect.record_removed(
                    entry.instrument_id,
                    replace(lot, quantity_left=q(_sign(lot.quantity_left) * taken)),
                )
            lot.quantity_left = q(lot.quantity_left + direction * taken)
            remaining = q(remaining - taken)
            if lot.quantity_left == 0:
                open_lots.pop(0)

        # Что не пошло на закрытие встречных партий — открывает новую в
        # направлении самой операции.
        if remaining > 0:
            opened = OpenLot(
                instrument_id=entry.instrument_id,
                opened_at=entry.executed_at,
                price=unit_price,
                quantity_left=q(direction * remaining),
                # Себестоимость положительной поправки берётся из цены
                # записи: record_decision кладёт туда cost_basis /
                # to_quantity, а при неизвестной себестоимости — ноль. Ноль
                # в цене поправки означает ровно «неизвестно», поэтому
                # ADJUSTMENT нельзя записать в WITHOUT_COST целиком: иначе
                # поправка с указанной владельцем себестоимостью тоже
                # помечалась бы неизвестной.
                cost_known=(
                    unit_price != 0
                    if entry.op_type is OperationType.ADJUSTMENT
                    else entry.op_type not in WITHOUT_COST
                ),
            )
            open_lots.append(opened)
            if effect is not None:
                effect.record_created(entry.instrument_id, opened)

    if pockets:
        raise ConversionError(
            f"Партии, снятые конвертациями {sorted(pockets)}, остались "
            "невостребованными: у них нет парного CONVERSION_IN. Бумаги "
            "исчезли бы из портфеля бесследно."
        )

    positions = {}
    for instrument_id in touched:
        open_lots = lots.get(instrument_id, [])
        positions[instrument_id] = PositionState(
            instrument_id=instrument_id,
            quantity=q(sum((lot.quantity_left for lot in open_lots), Decimal("0"))),
            average_price=_average(open_lots),
            lots=open_lots,
            cost_basis_known=all(lot.cost_known for lot in open_lots),
        )
    return FoldResult(positions=positions, realized=realized, cash=dict(cash))
