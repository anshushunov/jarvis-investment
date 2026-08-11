"""Решения владельца по расхождениям: хранение и целостность.

Хранятся только принятые решения. Гипотезы в базу не пишутся — они
пересчитываются из сверки (app/decisions/suggestions.py); в таблице они
оставляют след только тогда, когда владелец их отклонил, и этот след глушит
повторный показ.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Account, Instrument, LedgerDecision
from app.models.ledger_decision import DecisionKind, DecisionStatus


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _instrument(session, isin: str) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin[:4], secid=isin[:4],
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def _buy(session, account, isin: str, quantity: str, price: str, when: datetime,
         external_id: str = "1") -> None:
    from app.ledger.schemas import RawOperation
    from app.ledger.service import append_operations

    append_operations(session, account, "tbank", [RawOperation(
        external_id=external_id, op_type="BUY", executed_at=when,
        isin=isin, ticker=isin[:4], quantity=Decimal(quantity),
        price=Decimal(price), amount=-Decimal(quantity) * Decimal(price),
        currency="RUB", fee=Decimal("0"), payload={},
    )])


def _sell(session, account, isin: str, quantity: str, price: str, when: datetime,
          external_id: str = "s1") -> None:
    from app.ledger.schemas import RawOperation
    from app.ledger.service import append_operations

    append_operations(session, account, "tbank", [RawOperation(
        external_id=external_id, op_type="SELL", executed_at=when,
        isin=isin, ticker=isin[:4], quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(quantity) * Decimal(price),
        currency="RUB", fee=Decimal("0"), payload={},
    )])


def _dividend(session, account, isin: str, amount: str, when: datetime,
              external_id: str = "d1") -> None:
    from app.ledger.schemas import RawOperation
    from app.ledger.service import append_operations

    append_operations(session, account, "tbank", [RawOperation(
        external_id=external_id, op_type="DIVIDEND", executed_at=when,
        isin=isin, ticker=isin[:4], quantity=Decimal("0"), price=Decimal("0"),
        amount=Decimal(amount), currency="RUB", fee=Decimal("0"), payload={},
    )])


def _book(session, account) -> dict[int, list[tuple]]:
    """Книга открытых партий счёта: количество, цена, дата открытия и признак
    известной себестоимости по каждой партии.

    Таблица позиций этого не хранит — в ней только итог по бумаге, — поэтому
    сравнить состояние до решения и после его отмены можно только здесь. А
    сравнивать надо именно партии: количества сходятся и тогда, когда отмена
    вернула чужие даты и чужую себестоимость.
    """
    from app.positions.engine import fold
    from app.positions.service import _entries

    result = fold(_entries(session, account), currency=account.currency)
    return {
        instrument_id: [
            (lot.quantity_left, lot.price, lot.opened_at, lot.cost_known)
            for lot in state.lots
        ]
        for instrument_id, state in result.positions.items()
        if state.lots
    }


def test_conversion_decision_round_trip(session):
    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    decision = LedgerDecision(
        account_id=account.id,
        kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация гонконгского ETF, обе стороны заблокированы целиком",
        proposed={"reason": "равные количества", "blocked_fully": True},
    )
    session.add(decision)
    session.flush()
    session.expire_all()

    loaded = session.get(LedgerDecision, decision.id)
    assert loaded.kind is DecisionKind.CONVERSION
    assert loaded.status is DecisionStatus.CONFIRMED
    assert loaded.to_quantity == Decimal("79")
    assert loaded.proposed["blocked_fully"] is True


def test_note_is_required(session):
    account = _account(session)

    session.add(LedgerDecision(
        account_id=account.id,
        kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.CONFIRMED,
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note=None,
        proposed={},
    ))

    with pytest.raises(IntegrityError):
        session.flush()


def test_confirmed_conversion_moves_quantity_between_instruments(session):
    """Решение владельца порождает пару записей журнала, и после пересборки
    количество переезжает из старой бумаги в новую."""
    from app.decisions.service import record_decision
    from app.ledger.service import append_operations
    from app.ledger.schemas import RawOperation
    from app.models import Position, Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    append_operations(session, account, "tbank", [RawOperation(
        external_id="1", op_type="BUY",
        executed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        isin="HK0000310034", ticker="3010", quantity=Decimal("79"),
        price=Decimal("120"), amount=Decimal("-9480"), currency="HKD",
        fee=Decimal("0"), payload={},
    )])

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация гонконгского ETF", proposed={},
    ))

    generated = session.execute(
        select(Transaction).where(Transaction.source == "manual")
        .order_by(Transaction.external_id)
    ).scalars().all()
    assert [tx.op_type.value for tx in generated] == ["CONVERSION_IN", "CONVERSION_OUT"]
    assert all(tx.payload["decision_id"] == decision.id for tx in generated)

    positions = {
        p.instrument_id: p.quantity
        for p in session.execute(select(Position)).scalars()
    }
    assert positions == {new.id: Decimal("79")}


def test_adjustment_decision_changes_quantity_by_the_difference(session):
    from app.decisions.service import record_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("1012"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Редомициляция ТКС: расписки заменены акциями по отчёту брокера",
        proposed={},
    ))

    position = session.execute(select(Position)).scalar_one()
    assert position.quantity == Decimal("1012")
    # Себестоимость владелец не указал — позиция помечена.
    assert position.cost_basis_known is False


def test_rejected_decision_generates_no_ledger_entries(session):
    from app.decisions.service import record_decision
    from app.models import Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.REJECTED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Это не конвертация, бумаги не связаны", proposed={},
    ))

    assert session.execute(select(Transaction)).scalars().all() == []


def test_revert_returns_positions_to_the_previous_state(session):
    from app.decisions.service import record_decision, revert_decision
    from app.ledger.service import append_operations
    from app.ledger.schemas import RawOperation
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    append_operations(session, account, "tbank", [RawOperation(
        external_id="1", op_type="BUY",
        executed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        isin="HK0000310034", ticker="3010", quantity=Decimal("79"),
        price=Decimal("120"), amount=Decimal("-9480"), currency="HKD",
        fee=Decimal("0"), payload={},
    )])
    before = _book(session, account)

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))

    revert_decision(session, decision.id, note="Ошибся бумагой")

    assert session.get(LedgerDecision, decision.id).status is DecisionStatus.REVERTED
    positions = {
        p.instrument_id: p.quantity
        for p in session.execute(select(Position)).scalars()
    }
    assert positions == {old.id: Decimal("79")}
    # Не только количества: книга партий обязана совпасть с прежней целиком.
    assert _book(session, account) == before


def test_revert_restores_the_lot_book_of_a_non_empty_target(session):
    """Целевая бумага уже была в портфеле — отмена не должна их перепутать.

    Живой разбор: 79 бумаг по 120, купленные в 2024-м, конвертируются в бумагу,
    где уже лежат 79 по 10 от 2020 года. Отмена, выраженная встречной
    конвертацией, снимала бы с целевой бумаги самые старые партии — то есть
    чужие: количества сходились, а себестоимость и даты открытия менялись
    бумагами местами, и трёхлетняя льгота доставалась не той бумаге.
    """
    from app.decisions.service import record_decision, revert_decision

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc), external_id="1")
    _buy(session, account, "HK0000051877", "79", "10",
         datetime(2020, 1, 1, tzinfo=timezone.utc), external_id="2")
    before = _book(session, account)

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация гонконгского ETF", proposed={},
    ))
    revert_decision(session, decision.id, note="Ошибся бумагой")

    assert _book(session, account) == before
    # То же по существу, но явным текстом: своя себестоимость у каждой бумаги.
    assert [(lot[0], lot[1], lot[2].year) for lot in _book(session, account)[old.id]] == [
        (Decimal("79"), Decimal("120"), 2024)
    ]
    assert [(lot[0], lot[1], lot[2].year) for lot in _book(session, account)[new.id]] == [
        (Decimal("79"), Decimal("10"), 2020)
    ]


def test_revert_of_an_adjustment_keeps_the_old_broker_lot(session):
    """Отмена поправки-зачисления не должна съедать старую партию брокера.

    Зеркальная поправка — списание, а оно закрывает партии с головы книги, где
    лежит самая старая. Так после отмены выживала партия отменённого решения:
    100 бумаг оставались, но по цене поправки и с её датой.
    """
    from app.decisions.service import record_decision, revert_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    _buy(session, account, "RU000A107UL4", "100", "50",
         datetime(2024, 5, 1, tzinfo=timezone.utc))
    before = _book(session, account)

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("1012"),
        cost_basis=Decimal("40000"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Редомициляция ТКС", proposed={},
    ))
    revert_decision(session, decision.id, note="Поправка оказалась лишней")

    assert _book(session, account) == before
    position = session.execute(select(Position)).scalar_one()
    assert position.quantity == Decimal("100")
    assert position.average_price == Decimal("50")
    assert position.cost_basis_known is True


def test_revert_of_a_write_off_restores_the_cost_basis(session):
    """Отмена списания возвращает себестоимость, а не стирает её.

    Зеркальная поправка приходит без цены, а ноль в поправке означает
    «себестоимость неизвестна»: позиция после отмены переставала показывать
    среднюю цену и доходность вовсе, хотя владелец всего лишь передумал.
    """
    from app.decisions.service import record_decision, revert_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    _buy(session, account, "RU000A107UL4", "100", "50",
         datetime(2024, 5, 1, tzinfo=timezone.utc))
    before = _book(session, account)

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=instrument.id, from_quantity=Decimal("40"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Сорок бумаг в журнале лишние", proposed={},
    ))
    assert session.execute(select(Position)).scalar_one().quantity == Decimal("60")

    revert_decision(session, decision.id, note="Списание оказалось ошибкой")

    assert _book(session, account) == before
    position = session.execute(select(Position)).scalar_one()
    assert position.quantity == Decimal("100")
    assert position.average_price == Decimal("50")
    assert position.cost_basis_known is True


def test_revert_is_refused_when_the_paper_was_traded_afterwards(session):
    """Бумагу, зачисленную решением, успели продать — отменять нельзя.

    Движок такого не заметит: зеркальные записи несут дату отменяемого решения и
    ложатся в журнал раньше позднейшей продажи, поэтому отмена проходит, а
    продажа остаётся висеть в пустоте. Итог прогона до правки: 79 бумаг вернулись
    в исходную бумагу, а по целевой осталась короткая позиция −40 по 200, и
    реальная продажа на 8000 исчезла из налоговой базы вовсе.
    """
    from app.decisions.service import DecisionError, record_decision, revert_decision

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))
    _sell(session, account, "HK0000051877", "40", "200",
          datetime(2026, 4, 1, tzinfo=timezone.utc))

    with pytest.raises(DecisionError, match="бумагу расходовали"):
        revert_decision(session, decision.id, note="Ошибся бумагой")

    assert session.get(LedgerDecision, decision.id).status is DecisionStatus.CONFIRMED


def test_later_dividend_and_purchase_do_not_block_the_revert(session):
    """Дивиденд и докупка по зачисленной бумаге отмене не мешают.

    Партий, которые отмена собирается убрать, они не трогают. Проверка сначала
    смотрела на любую операцию, и очередной дивиденд, приехавший синхронизацией,
    делал уже записанную конвертацию неотменяемой навсегда — а отказ при этом
    советовал приводить позиции новым решением, хотя ничего не случилось.
    """
    from app.decisions.service import record_decision, revert_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))
    _dividend(session, account, "HK0000051877", "500",
              datetime(2026, 3, 15, tzinfo=timezone.utc))
    _buy(session, account, "HK0000051877", "10", "200",
         datetime(2026, 4, 1, tzinfo=timezone.utc), external_id="2")

    revert_decision(session, decision.id, note="Ошибся бумагой")

    positions = {
        p.instrument_id: p.quantity
        for p in session.execute(select(Position)).scalars()
    }
    assert positions == {old.id: Decimal("79"), new.id: Decimal("10")}
    # Возвращённая партия своя, докупленная — своя: ни та, ни другая не съедена.
    assert _book(session, account) == {
        old.id: [(Decimal("79"), Decimal("120"),
                  datetime(2024, 5, 1, tzinfo=timezone.utc), True)],
        new.id: [(Decimal("10"), Decimal("200"),
                  datetime(2026, 4, 1, tzinfo=timezone.utc), True)],
    }


def test_split_recorded_as_conversion_into_the_same_paper_is_revertable(session):
    """Сплит записан конвертацией бумаги в саму себя — и отменяется.

    Обе стороны зеркального решения указывают на один инструмент, и след по нему
    раскручивается ровно один раз: второй проход отказывал, ссылаясь на
    израсходованные партии, то есть не на ту причину.
    """
    from app.decisions.service import record_decision, revert_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    _buy(session, account, "RU000A107UL4", "100", "50",
         datetime(2024, 5, 1, tzinfo=timezone.utc))
    before = _book(session, account)

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=instrument.id, from_quantity=Decimal("100"),
        to_instrument_id=instrument.id, to_quantity=Decimal("200"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Сплит один к двум", proposed={},
    ))

    split = session.execute(select(Position)).scalar_one()
    assert (split.quantity, split.average_price) == (Decimal("200"), Decimal("25"))
    # Дата открытия пережила сплит: трёхлетняя льгота считается от неё.
    assert _book(session, account)[instrument.id][0][2] == datetime(2024, 5, 1, tzinfo=timezone.utc)

    revert_decision(session, decision.id, note="Сплита не было")

    assert _book(session, account) == before
    restored = session.execute(select(Position)).scalar_one()
    assert (restored.quantity, restored.average_price) == (Decimal("100"), Decimal("50"))


def test_failed_record_leaves_neither_decision_nor_entries(session):
    """Отказ движка не должен оставить в сессии половину записанного.

    Решение и порождённые им записи ложатся в сессию раньше, чем движок
    добирается до пересборки. Закоммить такое значит получить счёт, позиции
    которого не сворачиваются больше никогда: журнал append-only, и починить
    его можно было бы только правкой базы.
    """
    from app.decisions.service import DecisionError, record_decision
    from app.models import Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "10", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    with pytest.raises(DecisionError, match="не сходится с журналом"):
        record_decision(session, LedgerDecision(
            account_id=account.id, kind=DecisionKind.CONVERSION,
            status=DecisionStatus.CONFIRMED,
            from_instrument_id=old.id, from_quantity=Decimal("79"),
            to_instrument_id=new.id, to_quantity=Decimal("79"),
            effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            note="Бумаг столько нет", proposed={},
        ))

    assert session.execute(select(LedgerDecision)).scalars().all() == []
    manual = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalars().all()
    assert manual == []


def test_failed_revert_leaves_the_original_decision_intact(session, monkeypatch):
    """То же для отмены: отказ движка не оставляет зеркала и статуса REVERTED.

    Отказ подменён на шве пересборки: сквозь службу движок здесь уже не уронить —
    все известные способы закрыты проверками до записи, — но предохранитель
    обязан работать и для тех, что найдутся позже.
    """
    import app.decisions.service as decisions
    from app.decisions.service import DecisionError, record_decision, revert_decision
    from app.models import Transaction
    from app.positions.engine import ReversalError
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))
    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))

    def boom(*args, **kwargs):
        raise ReversalError("движок отказал")

    monkeypatch.setattr(decisions, "rebuild_after_decision", boom)

    with pytest.raises(DecisionError, match="не сходится с журналом"):
        revert_decision(session, decision.id, note="Ошибся бумагой")

    assert session.get(LedgerDecision, decision.id).status is DecisionStatus.CONFIRMED
    assert session.execute(select(LedgerDecision)).scalars().all() == [decision]
    manual = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalars().all()
    assert len(manual) == 2


def test_reverting_a_revert_is_refused(session):
    """Отменить отмену нельзя: своего следа в книге партий она не оставляет.

    Раньше это уходило в движок и падало там на «не нашла следа» уже после того,
    как зеркальное решение записалось в сессию.
    """
    from app.decisions.service import DecisionError, record_decision, revert_decision

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))
    mirror = revert_decision(session, decision.id, note="Ошибся бумагой")

    with pytest.raises(DecisionError, match="отменять отмену нельзя"):
        revert_decision(session, mirror.id, note="И снова передумал")


def test_revert_is_refused_when_a_later_decision_touches_the_same_papers(session):
    """Отменить решение, поверх которого лежит более позднее, нельзя.

    Партий, которые открыло первое решение, в книге уже нет — они ушли во
    вторую конвертацию. Отказ обязан назвать настоящую причину: раньше владелец
    получал ошибку движка про «количество в решении» и правил не то.
    """
    from app.decisions.service import DecisionError, record_decision, revert_decision

    account = _account(session)
    first = _instrument(session, "HK0000310034")
    second = _instrument(session, "HK0000051877")
    third = _instrument(session, "RU000A107UL4")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    earlier = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=first.id, from_quantity=Decimal("79"),
        to_instrument_id=second.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Первая конвертация", proposed={},
    ))
    later = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=second.id, from_quantity=Decimal("79"),
        to_instrument_id=third.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        note="Вторая конвертация", proposed={},
    ))

    with pytest.raises(DecisionError, match=f"более поздние решения по тем же бумагам \\({later.id}\\)"):
        revert_decision(session, earlier.id, note="Передумал")

    assert session.get(LedgerDecision, earlier.id).status is DecisionStatus.CONFIRMED


def test_revert_unblocks_once_the_independent_later_decision_is_reverted(session):
    """Отменённое решение больше не держит предыдущее.

    Пара «решение и его отмена» друг друга гасит и следа в книге не оставляет.
    Пока она считалась помехой, первое решение оказывалось неотменяемым
    навсегда: зеркало — тоже подтверждённое решение по тем же бумагам, и
    совет «сначала отмените более поздние» вёл по кругу.
    """
    from app.decisions.service import record_decision, revert_decision

    account = _account(session)
    source = _instrument(session, "HK0000310034")
    target = _instrument(session, "HK0000051877")
    other = _instrument(session, "RU000A107UL4")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc), external_id="1")
    _buy(session, account, "RU000A107UL4", "50", "10",
         datetime(2024, 5, 1, tzinfo=timezone.utc), external_id="2")
    before = _book(session, account)

    earlier = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=source.id, from_quantity=Decimal("79"),
        to_instrument_id=target.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Первая конвертация", proposed={},
    ))
    # Вторая конвертация приходит в ту же бумагу, но черпает из другой —
    # на бумаги первой она не опирается.
    independent = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=other.id, from_quantity=Decimal("50"),
        to_instrument_id=target.id, to_quantity=Decimal("50"),
        effective_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        note="Вторая конвертация", proposed={},
    ))

    revert_decision(session, independent.id, note="Вторая была ошибкой")
    revert_decision(session, earlier.id, note="И первая тоже")

    assert _book(session, account) == before


def test_a_dependent_later_decision_keeps_blocking_after_its_own_revert(session):
    """А решение, черпавшее из зачисленной бумаги, держит и после своей отмены.

    Его CONVERSION_OUT остался в журнале на своей, более поздней дате и
    по-прежнему требует эти бумаги в книге: отмена первого решения вырвала бы у
    него опору, и свернуть журнал стало бы нельзя вовсе.
    """
    from app.decisions.service import DecisionError, record_decision, revert_decision

    account = _account(session)
    first = _instrument(session, "HK0000310034")
    second = _instrument(session, "HK0000051877")
    third = _instrument(session, "RU000A107UL4")

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    earlier = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=first.id, from_quantity=Decimal("79"),
        to_instrument_id=second.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Первая конвертация", proposed={},
    ))
    dependent = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=second.id, from_quantity=Decimal("79"),
        to_instrument_id=third.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        note="Вторая конвертация", proposed={},
    ))

    revert_decision(session, dependent.id, note="Вторая была ошибкой")

    with pytest.raises(DecisionError, match=f"решение {dependent.id} черпало бумагу"):
        revert_decision(session, earlier.id, note="И первая тоже")

    assert session.get(LedgerDecision, earlier.id).status is DecisionStatus.CONFIRMED


@pytest.mark.parametrize("from_quantity, to_quantity", [
    (Decimal("79"), Decimal("0")),
    (Decimal("0"), Decimal("79")),
    (Decimal("79"), Decimal("-79")),
])
def test_conversion_with_non_positive_quantity_is_refused(session, from_quantity, to_quantity):
    """Нулевая и отрицательная конвертация отклоняются в службе решений.

    Дальше по дороге такое решение падало с чужим текстом («CONVERSION_IN не
    нашёл снятых партий»), а нулевое количество на зачисляющей стороне не
    падало вовсе: движок раскладывал снятые партии на ноль бумаг, себестоимость
    исчезала, а признак «себестоимость известна» оставался истинным.
    """
    from app.decisions.service import DecisionError, record_decision
    from app.models import Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    with pytest.raises(DecisionError, match="строго больше нуля"):
        record_decision(session, LedgerDecision(
            account_id=account.id, kind=DecisionKind.CONVERSION,
            status=DecisionStatus.CONFIRMED,
            from_instrument_id=old.id, from_quantity=from_quantity,
            to_instrument_id=new.id, to_quantity=to_quantity,
            effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            note="Конвертация с негодным количеством", proposed={},
        ))

    assert session.execute(select(Transaction)).scalars().all() == []


def test_adjustment_write_off_is_given_as_a_positive_quantity(session):
    """Списывающая поправка задаётся положительным количеством.

    Минус ставит сама служба при порождении записи журнала. Отрицательное
    значение от владельца означало бы двойное отрицание — поправка сработала бы
    в обратную сторону.
    """
    from app.decisions.service import DecisionError, record_decision

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    with pytest.raises(DecisionError, match="строго больше нуля"):
        record_decision(session, LedgerDecision(
            account_id=account.id, kind=DecisionKind.ADJUSTMENT,
            status=DecisionStatus.CONFIRMED,
            from_instrument_id=instrument.id, from_quantity=Decimal("-5"),
            effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            note="Лишние бумаги в журнале", proposed={},
        ))


def test_generated_entry_is_read_back_through_the_shared_payload_key(session):
    """Ключ payload у службы решений и у сборщика позиций общий.

    Разъедься они при переименовании — конвертация упала бы с «нет link_id»,
    и текст ошибки увёл бы от настоящей причины.
    """
    from app.decisions.service import record_decision
    from app.models.ledger_decision import DECISION_PAYLOAD_KEY
    from app.positions.service import _entries

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("1012"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Редомициляция ТКС", proposed={},
    ))

    generated = _entries(session, account)
    assert [entry.link_id for entry in generated] == [decision.id]
    assert DECISION_PAYLOAD_KEY == "decision_id"


@pytest.fixture
def convertible_instruments(session, account) -> tuple[Instrument, Instrument]:
    """Бумага-источник решения №1 в HKD, бумага-получатель — в USD: разные
    валюты по разные стороны конвертации, а не одна и та же на обеих.

    Пока обе бумаги были в HKD, тест по ним не заметил бы перепутанные
    стороны: если бы _generate_entries по опечатке отдал CONVERSION_OUT и
    CONVERSION_IN валюту одного и того же инструмента (строки там отличаются
    ровно одним словом — from_instrument_id/to_instrument_id), обе записи
    всё равно вышли бы HKD, и проверка по множеству валют осталась бы
    зелёной. Разные валюты делают это различимым.

    Бумага-источник заранее лежит в журнале: без этого движок откажет при
    свёртке конвертации («списывает больше, чем открыто») — тот же приём, что
    и в существующих тестах конвертации этого файла (см. _buy выше).
    """
    source = Instrument(isin="HK0000310034", ticker="HK03", secid="HK03",
                        kind="share", currency="HKD")
    target = Instrument(isin="US0378331005", ticker="AAPL", secid="AAPL",
                        kind="share", currency="USD")
    session.add_all([source, target])
    session.flush()

    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    return source, target


def test_conversion_entries_carry_each_sides_own_currency(session, account, convertible_instruments):
    """CONVERSION_OUT несёт валюту бумаги-источника, CONVERSION_IN — бумаги-получателя.

    Суммы у этих записей нулевые, и сегодня это безвредно, но у гонконгского
    ETF из решения №1 валюта HKD, а у бумаги, в которую он превращается, может
    быть любая другая: первый же потребитель, посмотревший на валюту записи,
    соврал бы, если бы стороны в _generate_entries перепутались местами.
    """
    from app.decisions.service import record_decision
    from app.models import OperationType, Transaction
    from sqlalchemy import select

    source, target = convertible_instruments  # HKD -> USD

    decision = LedgerDecision(
        account_id=account.id,
        kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=source.id, from_quantity=Decimal("79"),
        to_instrument_id=target.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        note="Смена ISIN гонконгского ETF",
    )
    record_decision(session, decision)

    entries = {
        entry.op_type: entry.currency
        for entry in session.execute(
            select(Transaction).where(Transaction.source == "manual")
        ).scalars()
    }

    assert entries[OperationType.CONVERSION_OUT] == "HKD"
    assert entries[OperationType.CONVERSION_IN] == "USD"


def test_adjustment_credit_entry_carries_instrument_currency(session, account):
    """Зачисляющая поправка несёт валюту своей бумаги, а не рубль счёта.

    Ветка ADJUSTMENT/CREDIT (to_instrument_id) до этого теста валюту записи
    не проверял ни один тест этого файла."""
    from app.decisions.service import record_decision
    from app.models import Transaction
    from sqlalchemy import select

    instrument = Instrument(isin="HK0000310034", ticker="HK03", secid="HK03",
                            kind="share", currency="HKD")
    session.add(instrument)
    session.flush()

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("10"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Зачисление по отчёту брокера", proposed={},
    ))

    entry = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalar_one()
    assert entry.currency == "HKD"


def test_adjustment_debit_entry_carries_instrument_currency(session, account):
    """Списывающая поправка тоже несёт валюту своей бумаги, а не рубль счёта.

    Ветка ADJUSTMENT/DEBIT (from_instrument_id) до этого теста валюту записи
    не проверял ни один тест этого файла."""
    from app.decisions.service import record_decision
    from app.models import Transaction
    from sqlalchemy import select

    instrument = Instrument(isin="HK0000310034", ticker="HK03", secid="HK03",
                            kind="share", currency="HKD")
    session.add(instrument)
    session.flush()
    _buy(session, account, "HK0000310034", "79", "120",
         datetime(2024, 5, 1, tzinfo=timezone.utc))

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=instrument.id, from_quantity=Decimal("40"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Сорок бумаг в журнале лишние", proposed={},
    ))

    entry = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalar_one()
    assert entry.currency == "HKD"


def test_decision_can_point_at_the_one_it_reverts(session):
    account = _account(session)
    original = LedgerDecision(
        account_id=account.id, kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.REVERTED,
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Первое решение", proposed={},
    )
    session.add(original)
    session.flush()

    revert = LedgerDecision(
        account_id=account.id, kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.CONFIRMED,
        effective_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        note="Передумал", proposed={}, reverts_id=original.id,
    )
    session.add(revert)
    session.flush()

    assert session.get(LedgerDecision, revert.id).reverts_id == original.id
