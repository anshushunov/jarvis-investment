import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_errors import is_unique_violation
from app.instruments.service import resolve_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import CORRECTS_TRANSACTION_ID_PAYLOAD_KEY, Account, Instrument, OperationType, Transaction
from app.positions.engine import signed_quantity

logger = logging.getLogger(__name__)

# UniqueConstraint("dedup_key", name="uq_transaction_dedup_key") в app/models/transaction.py.
_DEDUP_KEY_UNIQUE_CONSTRAINT = "uq_transaction_dedup_key"
# UniqueConstraint("account_id", "source", "external_id", name="uq_transaction_source_external")
# там же. Тот же внешний идентификатор брокера на этом же счёте, но с иным dedup_key —
# например, брокер повторно отдал операцию с чуть изменившимся содержанием при
# пересекающемся окне повторной синхронизации (см. SYNC_OVERLAP_DAYS в app/sync/service.py).
# По смыслу задачи это тоже «уже записано», а не ошибка — живое подтверждение и разбор
# в docs/decisions/2026-08-08-ledger-external-id-per-account.md.
_SOURCE_EXTERNAL_UNIQUE_CONSTRAINT = "uq_transaction_source_external"


def _is_duplicate_conflict(exc: IntegrityError) -> bool:
    """True, если exc — конфликт по одному из двух уникальных ограничений журнала,
    которые по смыслу задачи означают «дубль, пропустить», а не ошибку. Любой другой
    IntegrityError (внешний ключ, NOT NULL) — ошибка вызывающего кода и обязан
    всплыть наружу, а не быть проглоченным."""
    return is_unique_violation(exc, _DEDUP_KEY_UNIQUE_CONSTRAINT) or is_unique_violation(
        exc, _SOURCE_EXTERNAL_UNIQUE_CONSTRAINT
    )


@dataclass(frozen=True)
class AppendResult:
    inserted: int
    skipped: int
    # Операции, которые брокер переписал задним числом: на разницу записана
    # корректирующая запись. Должно быть редкостью — частый случай
    # доисполняющейся заявки закрыт окном STILL_FILLING_WINDOW в коннекторе.
    # Если счётчик стабильно ненулевой, значит обход перестал работать.
    corrected: int = 0


class _InstrumentCache:
    """Разрешённые инструменты на время одного вызова append_operations.

    Разрешение инструмента — это отдельный SELECT по ISIN, и оно шло внутри
    цикла по всему батчу: на первой синхронизации счёта это тысячи обращений к
    базе — при том что рядом ради экономии на вставке специально сделан
    пакетный сброс. Уникальных ISIN в батче сотни, операций тысячи, так что кэш
    на время вызова снимает это целиком.

    Живёт ровно один вызов и не переживает его: инструменты меняются
    (дозаполняются справочными сведениями при следующей синхронизации), и
    держать их дольше — значит однажды отдать устаревшую запись.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._by_isin: dict[str, Instrument | None] = {}

    def resolve(self, op: RawOperation) -> Instrument | None:
        if op.isin is None:
            return None
        if op.isin not in self._by_isin:
            self._by_isin[op.isin] = resolve_instrument(self._session, op)
        return self._by_isin[op.isin]


def _build_transaction(
    account: Account, source: str, op: RawOperation, key: str, instrument_id: int | None
) -> Transaction:
    return Transaction(
        account_id=account.id,
        instrument_id=instrument_id,
        op_type=op.op_type,
        executed_at=op.executed_at,
        quantity=op.quantity,
        price=op.price,
        amount=op.amount,
        currency=op.currency,
        fee=op.fee,
        external_id=op.external_id,
        source=source,
        payload=op.payload,
        dedup_key=key,
    )


def _insert_one(
    session: Session,
    account: Account,
    source: str,
    op: RawOperation,
    key: str,
    instruments: _InstrumentCache,
) -> bool:
    """Вставляет одну операцию под собственным SAVEPOINT. Возвращает False, если это
    дубль — конфликт по dedup_key (гонка с параллельным вызовом append_operations по
    тому же счёту) или по (account_id, source, external_id) (тот же внешний
    идентификатор брокера уже записан для этого счёта, см. _is_duplicate_conflict) —
    обнаруженный только на вставке. Это медленный, но безопасный путь на единичную
    строку — append_operations прибегает к нему только тогда, когда быстрый пакетный
    flush всего батча уже столкнулся с конфликтом (см. append_operations)."""
    instrument = instruments.resolve(op)
    transaction = _build_transaction(account, source, op, key, instrument.id if instrument else None)
    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
    except IntegrityError as exc:
        if not _is_duplicate_conflict(exc):
            raise
        # SQLAlchemy сам изгоняет transaction из сессии при откате SAVEPOINT — повторный
        # explicit expunge здесь лишний и падает с InvalidRequestError.
        return False
    return True


def _load_known_keys(session: Session, keys: list[str]) -> set[str]:
    """Читает уже занятые dedup_key из БД. Вынесена в отдельную функцию модуля, а не
    инлайн в append_operations, только ради тестируемости: тесты подменяют её через
    monkeypatch, чтобы вернуть пустое множество и тем самым честно воспроизвести
    fallback-ветку append_operations на настоящем PostgreSQL (см.
    test_append_operations_falls_back_to_row_by_row_on_bulk_conflict) — сама вставка,
    конфликт уникальности и откат при этом остаются настоящими, подменяется только
    чтение известных ключей."""
    return set(
        session.execute(
            select(Transaction.dedup_key).where(Transaction.dedup_key.in_(keys))
        ).scalars()
    )


# Сколько внешних идентификаторов кладём в один IN. Батч синхронизации бывает
# в тысячи операций, а IN такой длины плох и планировщику запросов, и
# ограничению на число параметров у драйвера.
_LOOKUP_CHUNK = 500


def _recorded_by_external_id(
    session: Session, account: Account, source: str, external_ids: list[str]
) -> dict[str, list[Transaction]]:
    """Уже записанные транзакции счёта по каждому из присланных внешних
    идентификаторов, в порядке записи.

    Один запрос на батч (точнее — по запросу на _LOOKUP_CHUNK идентификаторов)
    вместо запроса на операцию. Прежняя версия ходила в базу внутри цикла по
    батчу, в том числе за операциями, которых там заведомо нет: на первой
    полной синхронизации счёта это тысячи обращений подряд.

    Ключ словаря — внешний идентификатор ИСХОДНОЙ операции, поэтому
    корректирующая запись попадает в список к той операции, которую исправляет:
    свой external_id у неё другой (correction:…, иначе столкнулась бы с
    uq_transaction_source_external), а связь хранится в payload. Без этого
    корректировки оставались бы невидимыми для подсчёта записанных итогов, и
    одна и та же правка брокера переписывалась бы на каждой синхронизации.
    """
    result: dict[str, list[Transaction]] = {}
    if not external_ids:
        return result

    for start in range(0, len(external_ids), _LOOKUP_CHUNK):
        chunk = external_ids[start:start + _LOOKUP_CHUNK]
        rows = session.execute(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.source == source,
                or_(
                    Transaction.external_id.in_(chunk),
                    Transaction.payload["corrects_external_id"].astext.in_(chunk),
                ),
            ).order_by(Transaction.id)
        ).scalars().all()

        for transaction in rows:
            corrects = (transaction.payload or {}).get("corrects_external_id")
            key = corrects if corrects is not None else transaction.external_id
            if key is not None:
                result.setdefault(key, []).append(transaction)

    return result


def _changed_against(
    recorded: list[Transaction], op: RawOperation
) -> tuple[Transaction, Decimal, Decimal, Decimal] | None:
    """Уже записанная операция, содержание которой разошлось с присланным,
    вместе с уже записанными итогами. None — расхождения нет.

    Разошлось — значит брокер переписал операцию задним числом. Совпало — это
    обычный дубль пересекающегося окна синхронизации, и говорить о нём нечего.

    Количество и записанное, и присланное приводится к общему знаковому виду
    (app/positions/engine.py, signed_quantity): в журнале количество продажи
    беззнаковое, а количество корректировки знаковое, и складывать их как есть
    нельзя — продажа 12, исправленная до 100, давала бы 12 + (−88) = −76 против
    присланных 100, и одна и та же правка переписывалась бы на каждой
    синхронизации. У операций, которые количество не двигают вовсе (деньги,
    комиссия, OTHER), знаковое количество нулевое с обеих сторон: правку такой
    операции видно по сумме и цене, а поправлять в позициях у неё нечего.
    """
    if not recorded:
        return None

    # Корректирующие записи уже учтены: сравниваем с суммой всего, что по этой
    # операции записано, иначе одна и та же правка порождала бы корректировку
    # при каждой синхронизации.
    recorded_quantity = sum(
        (signed_quantity(tx.op_type, tx.quantity) for tx in recorded), Decimal("0")
    )
    recorded_amount = sum((tx.amount for tx in recorded), Decimal("0"))
    # Цена — не поток, в отличие от количества и суммы, и по всем записям
    # операции не складывается. Действующая цена — та, что несёт самая
    # последняя запись: исходная, пока корректировок не было, иначе последняя
    # корректировка (она переносит вперёд самую свежую цену, присланную
    # брокером на момент своей записи). Без этого сравнения правка одной
    # только цены при тех же количестве и сумме проходила бы мимо как «не
    # изменилось», падала в to_insert со старым external_id и тихо гасилась
    # построчным запасным путём в _insert_one — без единой записи в лог.
    recorded_price = recorded[-1].price

    if (
        recorded_quantity == signed_quantity(op.op_type, op.quantity)
        and recorded_amount == op.amount
        and recorded_price == op.price
    ):
        return None
    return recorded[0], recorded_quantity, recorded_amount, recorded_price


def _correction_for(
    account: Account, source: str, op: RawOperation, original: Transaction,
    recorded_quantity: Decimal, recorded_amount: Decimal,
) -> Transaction:
    """Корректирующая запись на разницу между присланным и записанным.

    Одна запись на изменившуюся операцию, а не по записи на каждое поле:
    свёртка обязана увидеть изменение целиком, иначе цена уедет отдельно от
    количества.

    Разность считается по знаковому количеству, а не по сырому: у корректировки
    тип ADJUSTMENT, и её направление движок берёт из знака количества
    (app/positions/engine.py, signed_quantity — там же записано и само
    соглашение). Сырая разность верна только для покупок: доисполненная с 12 до
    100 продажа давала +88, и движок открывал партию на 88 бумаг по цене
    продажи — позиция выходила 276 вместо 100, да ещё с «известной»
    себестоимостью, равной цене продажи. `recorded_quantity` приходит уже
    знаковым (см. _changed_against).
    """
    return Transaction(
        account_id=account.id,
        instrument_id=original.instrument_id,
        op_type=OperationType.ADJUSTMENT,
        executed_at=op.executed_at,
        quantity=signed_quantity(op.op_type, op.quantity) - recorded_quantity,
        price=op.price,
        amount=op.amount - recorded_amount,
        currency=op.currency,
        fee=Decimal("0"),
        external_id=f"correction:{original.external_id}",
        source=source,
        dedup_key=hashlib.sha256(
            f"correction|{source}|{account.external_id}|{original.external_id}"
            f"|{op.quantity}|{op.amount}".encode()
        ).hexdigest(),
        payload={
            CORRECTS_TRANSACTION_ID_PAYLOAD_KEY: original.id,
            "corrects_external_id": original.external_id,
        },
    )


def _insert_correction(session: Session, account: Account, correction: Transaction) -> bool:
    """Вставляет одну корректирующую запись под собственным SAVEPOINT.

    В отличие от _insert_one, конфликт здесь — не безобидный дубль, который
    можно молча проглотить: коллизия по (account_id, source, external_id)
    корректировки означает, что эту же исходную операцию брокер переписывает
    уже не в первый раз, а external_id корректировки не рассчитан на две
    правки одной и той же исходной записи. Потерянная корректировка — это
    потерянная правка брокера, поэтому конфликт логируется как ошибка,
    требующая ручного разбора, а не гасится тихо.
    """
    try:
        with session.begin_nested():
            session.add(correction)
            session.flush()
    except IntegrityError as exc:
        if not _is_duplicate_conflict(exc):
            raise
        logger.error(
            "Не удалось записать корректирующую запись для операции %s на счёте %s "
            "(external_id корректировки %s): конфликт по уникальному ограничению журнала. "
            "Похоже, эта операция уже была скорректирована прежде, а повторная правка той же "
            "записи не предусмотрена — корректировка потеряна, нужен ручной разбор.",
            correction.payload.get("corrects_external_id"), account.external_id,
            correction.external_id,
        )
        return False
    return True


def append_operations(
    session: Session, account: Account, source: str, operations: list[RawOperation]
) -> AppendResult:
    if not operations:
        return AppendResult(inserted=0, skipped=0)

    # RawOperation несёт поле payload: dict, поэтому сам объект не hashable —
    # держим ключи в списке, параллельном operations, а не в словаре с op как ключом.
    keys = [natural_key(source, account.external_id, op) for op in operations]
    known = _load_known_keys(session, keys)
    # Предзагрузка до цикла: раньше поиск переписанных брокером операций уходил
    # в базу на каждую операцию батча.
    recorded = _recorded_by_external_id(
        session, account, source,
        [op.external_id for op in operations if op.external_id is not None],
    )

    to_insert: list[tuple[RawOperation, str]] = []
    corrections: list[Transaction] = []
    skipped = 0
    seen_in_batch: set[str] = set()

    for op, key in zip(operations, keys):
        if key in known or key in seen_in_batch:
            skipped += 1
            continue
        # Операция без внешнего идентификатора сопоставлению не поддаётся:
        # ключа, по которому её узнать в журнале, попросту нет.
        changed = (
            _changed_against(recorded.get(op.external_id, []), op)
            if op.external_id is not None else None
        )
        if changed is not None:
            original, recorded_quantity, recorded_amount, recorded_price = changed
            corrections.append(_correction_for(
                account, source, op, original, recorded_quantity, recorded_amount
            ))
            # Количество в обеих половинах сообщения знаковое: сравнивать в
            # одной строке беззнаковое присланное с уже сложенным знаковым
            # записанным значило бы читать «было −100, стало 100» там, где
            # изменилась одна цена.
            logger.warning(
                "Брокер изменил операцию %s на счёте %s: было количество %s на %s по цене %s, "
                "стало %s на %s по цене %s. Записана корректирующая запись.",
                op.external_id, account.external_id, recorded_quantity,
                recorded_amount, recorded_price,
                signed_quantity(op.op_type, op.quantity), op.amount, op.price,
            )
            skipped += 1
            continue
        seen_in_batch.add(key)
        to_insert.append((op, key))

    if not to_insert and not corrections:
        return AppendResult(inserted=0, skipped=skipped)

    # Корректировки вставляются раньше и отдельно от to_insert, а не заодно с ним:
    # обе ветки ниже (быстрый путь и построчный запасной) читают corrected_count уже
    # готовым, независимо от того, какая из них обработает остаток батча.
    corrected_count = 0
    if corrections:
        try:
            with session.begin_nested():
                session.add_all(corrections)
                session.flush()
            corrected_count = len(corrections)
        except IntegrityError as exc:
            if not _is_duplicate_conflict(exc):
                raise
            # Тот же приём, что и у to_insert ниже: SAVEPOINT откатил всю пачку
            # корректировок и изгнал их из сессии, поэтому вставляем по одной под
            # своим SAVEPOINT — но, в отличие от to_insert, конфликт для
            # корректировки не безобидный дубль (см. _insert_correction), а
            # потерянная правка брокера, которую нельзя списать молча.
            for correction in corrections:
                if _insert_correction(session, account, correction):
                    corrected_count += 1
            session.flush()

    if not to_insert:
        return AppendResult(inserted=0, skipped=skipped, corrected=corrected_count)

    # Быстрый путь: один общий flush на весь батч (SQLAlchemy сам батчирует вставку
    # через insertmanyvalues). Замер на 5000 операциях, три прогона, PostgreSQL 16 на
    # том же хосте: SAVEPOINT на каждую строку медленнее одного flush на батч на 63-95%.
    # При первой полной синхронизации истории счёта (тысячи
    # операций, синхронный вызов из POST /api/sync/tbank) это ощутимо, поэтому конфликт
    # по любому из двух уникальных ограничений журнала обрабатывается не построчным
    # SAVEPOINT сразу, а как редкое исключение из быстрого пути.
    instruments = _InstrumentCache(session)
    transactions = []
    for op, key in to_insert:
        instrument = instruments.resolve(op)
        transactions.append(_build_transaction(account, source, op, key, instrument.id if instrument else None))

    try:
        with session.begin_nested():
            session.add_all(transactions)
            session.flush()
    except IntegrityError as exc:
        if not _is_duplicate_conflict(exc):
            raise
        # Гонка/дубль: либо кто-то другой вставил такой же dedup_key между нашим SELECT
        # known и этим flush, либо в батче нашлась операция с уже занятым на этом счёте
        # (account_id, source, external_id), но другим содержанием (см.
        # _is_duplicate_conflict и docs/decisions/2026-08-08-ledger-external-id-per-account.md). SQLAlchemy откатил
        # SAVEPOINT и изгнал весь transactions из сессии. Медленный, но надёжный путь —
        # вставить по одной операции под своим SAVEPOINT, чтобы отделить реально
        # столкнувшуюся строку (или несколько) от легитимных новых.
        inserted = 0
        conflict_skipped = 0
        for op, key in to_insert:
            # Тот же кэш, что и у быстрого пути: инструменты уже разрешены,
            # переспрашивать базу по второму разу незачем.
            if _insert_one(session, account, source, op, key, instruments):
                inserted += 1
            else:
                conflict_skipped += 1
        session.flush()
        return AppendResult(inserted=inserted, skipped=skipped + conflict_skipped, corrected=corrected_count)

    # Второй flush() здесь не нужен: он уже случился внутри блока with session.begin_nested()
    # выше — к этому моменту нечего сбрасывать, добавление было бы чистым no-op.
    return AppendResult(inserted=len(transactions), skipped=skipped, corrected=corrected_count)
