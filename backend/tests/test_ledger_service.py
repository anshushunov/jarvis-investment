from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event, func, select

import app.ledger.service as ledger_service
from app.instruments.service import _insert_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.ledger.service import _InstrumentCache, _insert_one, append_operations
from app.models import Account, Instrument, OperationType, Transaction


def make_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def buy_op(external_id: str | None = "op-1", executed_at: datetime | None = None) -> RawOperation:
    return RawOperation(
        external_id=external_id, op_type=OperationType.BUY,
        executed_at=executed_at or datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal("35"),
        price=Decimal("142.5"), amount=Decimal("-4987.5"), currency="RUB",
        fee=Decimal("1.4963"), payload={},
    )


def count_tx(session) -> int:
    return session.execute(select(func.count()).select_from(Transaction)).scalar_one()


def test_inserts_new_operation(session):
    account = make_account(session)
    result = append_operations(session, account, "tbank", [buy_op()])
    assert result.inserted == 1
    assert count_tx(session) == 1


def test_repeated_call_inserts_nothing(session):
    account = make_account(session)
    append_operations(session, account, "tbank", [buy_op()])
    result = append_operations(session, account, "tbank", [buy_op()])
    assert result.inserted == 0
    assert result.skipped == 1
    assert count_tx(session) == 1


def test_deduplicates_without_external_id(session):
    account = make_account(session)
    append_operations(session, account, "sber", [buy_op(external_id=None)])
    result = append_operations(session, account, "sber", [buy_op(external_id=None)])
    assert result.skipped == 1
    assert count_tx(session) == 1


def test_creates_instrument_on_first_sight(session):
    account = make_account(session)
    append_operations(session, account, "tbank", [buy_op()])
    tx = session.execute(select(Transaction)).scalar_one()
    assert tx.instrument is not None
    assert tx.instrument.isin == "RU0009029540"


def test_cash_operation_has_no_instrument(session):
    account = make_account(session)
    deposit = RawOperation(
        external_id="dep-1", op_type=OperationType.DEPOSIT,
        executed_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
        isin=None, ticker=None, quantity=Decimal("0"), price=Decimal("0"),
        amount=Decimal("100000"), currency="RUB", fee=Decimal("0"), payload={},
    )
    append_operations(session, account, "tbank", [deposit])
    tx = session.execute(select(Transaction)).scalar_one()
    assert tx.instrument_id is None


def test_dedup_conflict_at_insert_is_skipped_not_raised(session):
    """Гонка между двумя параллельными вызовами append_operations по одному счёту
    (например, плановая синхронизация и ручной POST /api/sync/tbank почти одновременно):
    оба видят один и тот же dedup_key ещё не занятым на этапе предварительного SELECT,
    и только на INSERT срабатывает uq_transaction_dedup_key. В одном потоке эту гонку
    через append_operations не воспроизвести — SELECT в начале второго вызова уже увидит
    строку первого. Поэтому обходим предварительную проверку и вызываем внутреннюю
    функцию вставки _insert_one дважды подряд с одним и тем же dedup_key — уникальный
    индекс срабатывает по-настоящему, а ветка обработки конфликта оказывается покрыта."""
    account = make_account(session)
    # external_id=None: конфликт должен проверяться именно по dedup_key, а не попутно
    # словить uq_transaction_source_external из-за одинакового external_id.
    op = buy_op(external_id=None)
    key = natural_key("tbank", account.external_id, op)

    assert _insert_one(session, account, "tbank", op, key, _InstrumentCache(session)) is True
    assert _insert_one(session, account, "tbank", op, key, _InstrumentCache(session)) is False
    assert count_tx(session) == 1


def test_instrument_isin_conflict_at_insert_reuses_existing(session):
    """Аналогичная гонка на уровне резолюции инструмента: два вызова append_operations
    впервые видят один и тот же новый ISIN одновременно. resolve_instrument сам её не
    воспроизведёт (предварительный select найдёт уже вставленную строку) — вызываем
    внутреннюю _insert_instrument дважды подряд, минуя select, чтобы сработал реальный
    уникальный индекс ix_instrument_isin."""
    op = buy_op()

    first = _insert_instrument(session, op)
    second = _insert_instrument(session, op)

    assert first.id == second.id
    count = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    assert count == 1


def test_append_operations_falls_back_to_row_by_row_on_bulk_conflict(session, monkeypatch):
    """append_operations сначала пытается вставить весь батч одним общим flush (быстрый
    путь). Эта гонка та же, что в test_dedup_conflict_at_insert_is_skipped_not_raised, но
    здесь нужно проверить именно обвязку append_operations вокруг неё — пакетный
    add_all()+flush() под общим SAVEPOINT, перехват IntegrityError, построчный
    fallback-цикл через _insert_one и пересчёт inserted/skipped — а не саму _insert_one.

    Настоящую параллельность здесь не воспроизвести (фикстура session живёт во внешней
    транзакции с откатом, а append-only триггер не даст убрать committed-мусор от второй
    сессии). Поэтому подменяем только чтение уже известных ключей (_load_known_keys) —
    единственный управляемый шов, — чтобы оно вернуло пустое множество. Тогда
    append_operations по-настоящему попытается вставить уже существующую в БД операцию,
    пакетный flush по-настоящему упадёт на uq_transaction_dedup_key, и по-настоящему
    отработает fallback: сама вставка, конфликт и откат — не мок."""
    account = make_account(session)

    existing_op = buy_op(external_id=None)
    existing_key = natural_key("tbank", account.external_id, existing_op)
    assert _insert_one(session, account, "tbank", existing_op, existing_key, _InstrumentCache(session)) is True

    new_op = buy_op(external_id=None, executed_at=datetime(2026, 3, 13, 10, 30, tzinfo=timezone.utc))

    monkeypatch.setattr(ledger_service, "_load_known_keys", lambda session, keys: set())

    result = append_operations(session, account, "tbank", [existing_op, new_op])

    assert result.inserted == 1
    assert result.skipped == 1
    assert count_tx(session) == 2


def _count_instrument_selects(session) -> list[int]:
    """Считает SELECT'ы по таблице instrument, реально ушедшие в PostgreSQL."""
    counter = [0]

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: PLR0913
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and "from instrument" in normalized:
            counter[0] += 1

    return counter


def test_instrument_is_resolved_once_per_isin_not_once_per_operation(session):
    """Разрешение инструмента — отдельный SELECT по ISIN, и оно шло внутри
    цикла по всему батчу: на первой синхронизации счёта это тысячи обращений к
    базе, при том что рядом ради экономии на вставке специально сделан пакетный
    сброс. Уникальных ISIN сотни, операций тысячи."""
    account = make_account(session)
    operations = [
        buy_op(external_id=f"op-{index}",
               executed_at=datetime(2026, 3, 12, 10, index, tzinfo=timezone.utc))
        for index in range(12)
    ]

    selects = _count_instrument_selects(session)
    result = append_operations(session, account, "tbank", operations)

    assert result.inserted == 12
    # Один ISIN на весь батч — ровно один поиск инструмента, а не двенадцать.
    # Вторая допустимая выборка — та, которой resolve_instrument перечитывает
    # запись после гонки; в этом сценарии её нет.
    assert selects[0] == 1


def test_append_operations_skips_external_id_conflict_without_losing_rest_of_batch(session, monkeypatch):
    """Живой дефект: у T-Invest один и тот же внешний идентификатор операции (external_id)
    иногда переиспользуется для двух записей с РАЗНЫМ содержанием (например, брокер
    повторно отдаёт операцию с чуть изменившимся содержанием в пересекающееся окно
    повторной синхронизации, SYNC_OVERLAP_DAYS) — то есть с разными dedup_key. Такая пара
    не ловится проверкой по dedup_key, а падает только на uq_transaction_source_external.
    До этой правки append_operations не перехватывал это ограничение — конфликт всплывал
    наружу как DBAPIError и ронял batch целиком (см. docs/decisions/2026-08-08-ledger-external-id-per-account.md), хотя по
    смыслу задачи это тоже дубль, который нужно пропустить, а не потерять остальные
    легитимные операции того же батча.

    Тот же управляемый шов, что и в test_append_operations_falls_back_to_row_by_row_on_bulk_conflict:
    подменяем только чтение известных dedup_key (_load_known_keys), чтобы дойти до
    настоящей вставки и настоящего конфликта — на этот раз по external_id, а не по
    dedup_key."""
    account = make_account(session)

    existing_op = buy_op(external_id="ext-shared")
    existing_key = natural_key("tbank", account.external_id, existing_op)
    assert _insert_one(session, account, "tbank", existing_op, existing_key, _InstrumentCache(session)) is True

    # Тот же external_id, что и existing_op, но другое содержание (другой executed_at) —
    # значит другой dedup_key. Дубль по uq_transaction_source_external, а не по dedup_key.
    conflicting_op = buy_op(
        external_id="ext-shared", executed_at=datetime(2026, 3, 13, 10, 30, tzinfo=timezone.utc)
    )
    new_op = buy_op(external_id="ext-2", executed_at=datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc))

    monkeypatch.setattr(ledger_service, "_load_known_keys", lambda session, keys: set())

    result = append_operations(session, account, "tbank", [conflicting_op, new_op])

    assert result.inserted == 1
    assert result.skipped == 1
    assert count_tx(session) == 2
