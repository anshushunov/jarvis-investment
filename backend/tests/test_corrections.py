"""Операция, изменённая брокером задним числом, даёт корректирующую запись.

До этой правки конфликт по (account_id, source, external_id) считался дублем и
молча пропускался — верно, когда содержание совпало, и неверно, когда брокер
переписал операцию. Журнал append-only, поэтому ответ — новая запись на
разницу, а не правка старой.

Частый случай доисполняющейся заявки закрыт отдельно, окном
STILL_FILLING_WINDOW в коннекторе, так что этот путь должен срабатывать редко.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event, select

from app.ledger.schemas import RawOperation
from app.ledger.service import append_operations
from app.models import Account, OperationType, Position, Transaction
from app.positions.service import rebuild_positions
from conftest import raw_operation


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _operation(quantity: str, amount: str, price: str = "100",
               op_type: str = "BUY") -> RawOperation:
    return _operation_with_id("op-1", quantity, amount, price, op_type)


def _operation_with_id(external_id: str, quantity: str, amount: str,
                       price: str = "100", op_type: str = "BUY") -> RawOperation:
    """Как _operation, но с произвольным external_id — нужна там, где в одном
    батче должна оказаться операция op-1 и независимая от неё новая операция."""
    return RawOperation(
        external_id=external_id, op_type=op_type,
        executed_at=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(amount), currency="RUB",
        fee=Decimal("0"), payload={},
    )


def _correction(session) -> Transaction:
    return session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalar_one()


def test_identical_repeat_is_still_skipped_silently(session):
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])

    result = append_operations(session, account, "tbank", [_operation("12", "-1200")])

    assert result.inserted == 0
    assert result.skipped == 1
    assert result.corrected == 0
    assert len(session.execute(select(Transaction)).scalars().all()) == 1


def test_changed_quantity_produces_a_correcting_entry(session):
    """Живой класс случая: заявка на 100 прочиталась как 12 и доисполнилась."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])

    result = append_operations(session, account, "tbank", [_operation("100", "-10000")])

    assert result.corrected == 1
    correction = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalar_one()
    assert correction.quantity == Decimal("88")
    assert correction.amount == Decimal("-8800")
    assert correction.source == "tbank"

    original = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.BUY)
    ).scalar_one()
    assert correction.payload["corrects_transaction_id"] == original.id
    # Исходная запись не тронута: журнал append-only.
    assert original.quantity == Decimal("12")


def test_correcting_entry_is_written_once_not_on_every_sync(session):
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])
    append_operations(session, account, "tbank", [_operation("100", "-10000")])

    result = append_operations(session, account, "tbank", [_operation("100", "-10000")])

    assert result.corrected == 0
    corrections = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalars().all()
    assert len(corrections) == 1


def test_changed_price_alone_produces_a_correcting_entry(session):
    """Брокер уточнил задним числом только цену исполнения — количество и сумма
    те же. Цена не складывается по записям операции, как количество и сумма,
    поэтому сравнивается отдельно: без этого правка проходила бы мимо
    _changed_against как «не изменилось», падала в to_insert со старым
    external_id и тихо гасилась построчным запасным путём без единой записи
    в лог — старая цена (а с ней и неверная себестоимость партии в движке
    позиций) оставалась бы в журнале навсегда."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200", price="100")])

    result = append_operations(session, account, "tbank", [_operation("12", "-1200", price="105")])

    assert result.corrected == 1
    assert result.inserted == 0
    correction = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalar_one()
    # Количество и сумма не изменились — на разницу в них корректировка нулевая,
    # но цену несёт целиком, как самую свежую известную.
    assert correction.quantity == Decimal("0")
    assert correction.amount == Decimal("0")
    assert correction.price == Decimal("105")

    original = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.BUY)
    ).scalar_one()
    assert original.price == Decimal("100")


def test_repeat_after_price_correction_is_still_skipped_silently(session):
    """Действующая цена после корректировки — цена самой последней записи, а не
    исходной: иначе одна и та же правка цены переписывалась бы заново на
    каждой синхронизации."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200", price="100")])
    append_operations(session, account, "tbank", [_operation("12", "-1200", price="105")])

    result = append_operations(session, account, "tbank", [_operation("12", "-1200", price="105")])

    assert result.corrected == 0
    corrections = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalars().all()
    assert len(corrections) == 1


def test_mixed_batch_with_changed_and_new_operations(session):
    """Регрессия на смешанный батч: изменённая операция и независимые новые в
    одном вызове append_operations. Корректировка не должна теряться и не
    должна вставляться дважды ни на быстром пути, ни на построчном запасном —
    и не должна мешать вставке новых операций того же батча."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation_with_id("op-1", "12", "-1200")])

    result = append_operations(session, account, "tbank", [
        _operation_with_id("op-1", "100", "-10000"),  # изменённая
        _operation_with_id("op-2", "5", "-500"),       # новая
        _operation_with_id("op-3", "7", "-700"),       # новая
    ])

    assert result.corrected == 1
    assert result.inserted == 2
    assert result.skipped == 1

    all_tx = session.execute(select(Transaction)).scalars().all()
    assert len(all_tx) == 4
    external_ids = sorted(tx.external_id for tx in all_tx)
    assert external_ids == ["correction:op-1", "op-1", "op-2", "op-3"]


def test_second_change_of_already_corrected_operation_does_not_crash_the_batch(session, caplog):
    """Повторное изменение уже скорректированной операции не рассчитано на
    вторую правку (у корректировки фиксированный external_id
    "correction:<исходный>"), поэтому вставка второй корректировки сталкивается
    с уникальным ограничением журнала. Это не должно ронять весь вызов
    append_operations необработанным исключением — иначе одна такая операция
    обрушивала бы синхронизацию всего счёта вместе с независимыми новыми
    операциями того же батча. Конфликт логируется как ошибка, а не гасится
    молча: потерянная корректировка — это потерянная правка брокера."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation_with_id("op-1", "12", "-1200")])
    append_operations(session, account, "tbank", [_operation_with_id("op-1", "100", "-10000")])

    with caplog.at_level(logging.ERROR, logger="app.ledger.service"):
        result = append_operations(session, account, "tbank", [
            _operation_with_id("op-1", "150", "-15000"),  # повторная правка той же операции
            _operation_with_id("op-2", "5", "-500"),       # независимая новая операция
        ])

    # Вызов не упал — независимая новая операция того же батча всё равно вставлена.
    assert result.inserted == 1
    # Вторая корректировка потеряна (конфликт по external_id), это не выдаётся за успех.
    assert result.corrected == 0
    assert any("конфликт" in record.getMessage().lower() for record in caplog.records)

    corrections = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalars().all()
    assert len(corrections) == 1  # только первая корректировка дожила до конца


def test_changed_sell_is_corrected_in_the_direction_of_the_sale(session):
    """Доисполнилась продажа, а не покупка: было записано 12, брокер отдал 100.

    Количество в журнале беззнаковое, направление задаёт тип операции. У
    корректировки тип ADJUSTMENT, а его направление движок берёт из знака
    количества (app/positions/engine.py) — значит корректировка продажи обязана
    нести минус. С сырой разностью +88 движок открывал бы партию на 88 бумаг по
    цене продажи: позиция после покупки 200 и продажи 100 выходила бы 276
    вместо 100, да ещё с ценой продажи в качестве себестоимости.
    """
    account = _account(session)
    append_operations(session, account, "tbank", [
        _operation_with_id("buy-1", "200", "-20000", op_type="BUY"),
    ])
    append_operations(session, account, "tbank", [_operation("12", "1200", price="120", op_type="SELL")])

    result = append_operations(session, account, "tbank", [
        _operation("100", "10000", price="120", op_type="SELL"),
    ])

    assert result.corrected == 1
    assert _correction(session).quantity == Decimal("-88")

    rebuild_positions(session, account)
    position = session.execute(select(Position)).scalars().one()
    assert position.quantity == Decimal("100.00000000")


def test_changed_transfer_out_is_corrected_in_its_own_direction(session):
    """То же правило у второго уменьшающего типа: вывод бумаг.

    Проверяется не тот же путь ещё раз, а то, что направление берётся из общего
    множества DECREASING, а не перечислено где-то списком из одной продажи.
    """
    account = _account(session)
    append_operations(session, account, "tbank", [
        _operation_with_id("buy-1", "200", "-20000", op_type="BUY"),
    ])
    append_operations(session, account, "tbank", [
        _operation("12", "0", price="0", op_type="TRANSFER_OUT"),
    ])

    result = append_operations(session, account, "tbank", [
        _operation("100", "0", price="0", op_type="TRANSFER_OUT"),
    ])

    assert result.corrected == 1
    assert _correction(session).quantity == Decimal("-88")

    rebuild_positions(session, account)
    position = session.execute(select(Position)).scalars().one()
    assert position.quantity == Decimal("100.00000000")


def test_corrected_sell_is_not_corrected_again_on_the_next_sync(session):
    """Уже учтённая правка продажи не переписывается на каждой синхронизации.

    Сумма записанного по операции считается со знаком: продажа 12 плюс поправка
    −88 дают −100, ровно столько же несёт присланная продажа 100. Складывать
    беззнаковое количество продажи со знаковым количеством поправки нельзя —
    получилось бы −76 против 100, и корректировка писалась бы заново каждый раз
    (а точнее, падала бы в конфликт по external_id с записью в журнал ошибок).
    """
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "1200", price="120", op_type="SELL")])
    append_operations(session, account, "tbank", [_operation("100", "10000", price="120", op_type="SELL")])

    result = append_operations(session, account, "tbank", [
        _operation("100", "10000", price="120", op_type="SELL"),
    ])

    assert result.corrected == 0
    corrections = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalars().all()
    assert len(corrections) == 1


def test_find_changed_does_not_query_per_operation(session, account):
    """Поиск переписанных брокером операций — один запрос на батч.

    Раньше запрос уходил на каждую операцию батча, включая совершенно новые:
    на первой полной синхронизации счёта это тысячи обращений там, где соседний
    код ради экономии специально держит кэш инструментов и пакетный flush.

    Количество и сумма варьируются по индексу, а не общие на все 50: dedup_key
    (app/ledger/dedup.py) не зависит от external_id, и при одинаковом
    содержании операции 2..50 совпали бы по dedup_key с первой и были бы молча
    отсеяны как дубль внутри батча ещё до обращения к _find_changed — тест
    тогда не отличал бы старое поведение от нового.
    """
    operations = [
        raw_operation(external_id=str(index), quantity=str(10 + index), amount=str(-1000 - index))
        for index in range(50)
    ]

    statements: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        append_operations(session, account, "tbank", operations)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)

    # Значение 'corrects_external_id' в скомпилированный текст запроса не
    # попадает — драйвер шлёт его отдельным параметром, а не подставляет в
    # SQL. Литеральный маркер этого запроса в тексте — оператор доступа к
    # JSONB-полю payload (astext), других обращений к payload -> ->> в модуле
    # нет.
    lookups = [s for s in statements if "payload ->>" in s]
    assert len(lookups) <= 1, (
        f"Поиск переписанных операций ушёл {len(lookups)} раз на батч из 50 — "
        "запрос обязан быть один на батч."
    )


def test_recorded_lookup_deduplicates_external_id_before_chunking(session, account, monkeypatch):
    """Один и тот же external_id может встретиться в батче дважды — например,
    повтор на стыке страниц GetOperationsByCursor (app/connectors/tbank/client.py).

    Без дедупликации списка идентификаторов перед разбиением на куски повтор,
    оказавшийся по разные стороны границы куска, заставляет каждый кусок, в
    который он попал, вернуть одну и ту же уже записанную операцию заново:
    recorded_quantity/recorded_amount в _changed_against удваиваются ещё до
    сравнения. Разница с присланным при этом считается от вдвое завышенного
    «было», и корректирующая запись выходит на неверную величину — здесь
    100 − 24 = 76 вместо настоящих 100 − 12 = 88 (единственная уже записанная
    операция — 12, а не 24: удвоение целиком на совести бага).

    Дедупликация count/словаря не проверяет умышленно: она переживает
    рефакторинг `_recorded_by_external_id` хуже, чем наблюдаемый результат
    `append_operations` — итоговая (и единственная допустимая) сумма
    корректировки.
    """
    # Один идентификатор — один кусок: тот же повтор в батче гарантированно
    # разносится по разным кускам без искусственно большого батча в 500+ операций.
    monkeypatch.setattr("app.ledger.service._LOOKUP_CHUNK", 1)

    append_operations(session, account, "tbank", [raw_operation(external_id="op-1", quantity="12", amount="-1200")])

    # op-1 в батче дважды — тот самый повтор на стыке страниц: обе копии
    # несут одно и то же (реальное) новое содержание брокера.
    result = append_operations(session, account, "tbank", [
        raw_operation(external_id="op-1", quantity="100", amount="-10000"),
        raw_operation(external_id="op-1", quantity="100", amount="-10000"),
    ])

    assert result.corrected == 1
    correction = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalar_one()
    assert correction.quantity == Decimal("88")
    assert correction.amount == Decimal("-8800")
