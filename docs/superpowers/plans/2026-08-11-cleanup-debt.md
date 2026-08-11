# Уборка попутного долга фаз 1–2b — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** закрыть накопленный попутный долг фаз 1–2b, не меняя ни одной цифры, которую владелец видит на экране.

**Architecture:** тринадцать независимых задач. Каждая — своя правка, свой тест, свой коммит; порядок между ними значения не имеет, кроме задачи 1 (её общую функцию используют задачи, трогающие тот же код) и задачи 12 (роадмеп подводит итог всем предыдущим). Ни одна задача не меняет модель предметной области: только устраняет дублирование, лишние запросы, тихие потери и дыры в контракте.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, pytest на настоящем PostgreSQL; React 18, TypeScript, TanStack Query, Vitest + React Testing Library.

## Global Constraints

- **Спека:** [`../specs/2026-08-11-cleanup-debt-design.md`](../specs/2026-08-11-cleanup-debt-design.md). Что в неё не входит — не делать, даже если по дороге захотелось.
- **Уборка не меняет наблюдаемых чисел.** Итоги по счетам, количества, расхождения и их статусы обязаны остаться прежними. Единственное новое число в базе — `sync_run.corrected`.
- **Журнал операций append-only.** Ни одна задача не переписывает и не удаляет строки `transaction`.
- **Все команды бэкенда — из каталога `backend`**, через `uv run`. `uv` лежит в `C:\Users\User\.local\bin` и в PATH может не быть: если `uv` не находится, звать полным путём.
- **Тесты бэкенда идут на настоящем PostgreSQL** (порт 5433, поднимается `docker compose up -d db`). SQLite в проекте не используется намеренно: типы `Enum`, `JSONB` и `on_conflict_do_update` на нём ведут себя иначе.
- **Тесты фронтенда:** `pnpm test` из каталога `frontend`. Компонентные требуют `defineConfig` из `vitest/config` (не из `vite`) и явного `afterEach(cleanup)` — это уже настроено в `frontend/src/setupTests.ts`, менять не нужно.
- **Комментарии и докстринги — на русском**, в том же тоне, что и соседний код: объясняют «почему», а не «что». Комментарий, пересказывающий код строкой ниже, — это не документация.
- **Коммиты** в стиле Conventional Commits, как в истории репозитория: `refactor:`, `fix:`, `feat:`, `test:`, `docs:`. Авторство LLM не указывать.
- **Ветка:** `chore/cleanup-debt`, уже создана и содержит коммит со спекой.
- Полный прогон в конце: `uv run pytest` (439 тестов до начала работы), `pnpm test`, `pnpm build`.

---

### Task 1: Правило «ограничена в обороте» — одна функция на проект

**Files:**
- Modify: `backend/app/instruments/service.py:109-121` (функция `_restricted` → публичная `trading_restricted_from_flags`)
- Modify: `backend/app/sync/holdings.py:161-172` (удалить `_restricted_from`, звать общую)
- Modify: `backend/app/instruments/backfill.py:135-141` (удалить `_restricted_from`, звать общую)
- Test: `backend/tests/test_restrictions.py`

**Interfaces:**
- Produces: `app.instruments.service.trading_restricted_from_flags(buy: object, sell: object) -> bool | None` — единственное на проект правило «ограничена в обороте». Возвращает `None`, если хотя бы один флаг не `bool`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_restrictions.py`:

```python
from app.instruments.backfill import _restricted_from as backfill_restricted
from app.instruments.service import trading_restricted_from_flags
from app.sync.holdings import _restricted_from as holdings_restricted


def test_trading_restricted_rule_lives_in_one_place():
    """Правило «ограничена в обороте» существует в одном экземпляре.

    Три копии этого правила уже расходились в проекте: два правила о знаке
    ADJUSTMENT дали позицию в 276 бумаг вместо 100. Тест проверяет не поведение,
    а само отсутствие копий — поведение проверяют тесты ниже.
    """
    assert backfill_restricted is trading_restricted_from_flags
    assert holdings_restricted is trading_restricted_from_flags


@pytest.mark.parametrize(
    ("buy", "sell", "expected"),
    [
        (False, False, True),    # ни купить, ни продать — ограничение
        (False, True, False),    # закрыта для покупки, но продать можно
        (True, False, False),
        (True, True, False),
        (None, False, None),     # сведений нет — прежнее значение не трогаем
        (False, None, None),
        (None, None, None),
        ("false", "false", None),  # не bool — не сведения
    ],
)
def test_trading_restricted_from_flags(buy, sell, expected):
    assert trading_restricted_from_flags(buy, sell) is expected
```

Импорт `pytest` в файле уже есть — проверить и добавить, если нет.

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

```bash
cd backend && uv run pytest tests/test_restrictions.py -v
```

Ожидается: `ImportError: cannot import name 'trading_restricted_from_flags'`.

- [ ] **Step 3: Переименовать функцию в публичную**

В `backend/app/instruments/service.py` заменить `def _restricted(buy: object, sell: object)` на:

```python
def trading_restricted_from_flags(buy: object, sell: object) -> bool | None:
    """Ограничена ли бумага в обороте: недоступны обе операции сразу.

    Единственное на проект место, где записано это правило. Его читают три
    источника справочных сведений — payload операции (_reference_from ниже),
    снимок позиций брокера (app/sync/holdings.py) и разовое дозаполнение
    справочника (app/instruments/backfill.py), — и раньше каждый нёс свою
    копию. Копии правил в этом проекте уже расходились: два правила о знаке
    ADJUSTMENT стоили позиции в 276 бумаг вместо 100.

    Одного флага мало. Бумага, которую нельзя купить, но можно продать,
    распоряжению поддаётся — именно так выглядят выпуски, закрытые для новых
    покупок, но не замороженные. Ограничением считается только пара.

    Хотя бы один флаг отсутствует — сведений нет, возвращаем None: прежнее
    значение в базе трогать нельзя (см. apply_reference выше, где None и False
    обрабатываются по-разному).

    Принимает object, а не bool | None, намеренно: два из трёх вызывающих
    достают флаги из JSON — payload операции и ответ справочника, — где вместо
    булева значения может лежать что угодно.
    """
    if not isinstance(buy, bool) or not isinstance(sell, bool):
        return None
    return not buy and not sell
```

Поправить единственный вызов внутри файла — в `_reference_from`, строка `_restricted(buy, sell)` → `trading_restricted_from_flags(buy, sell)`.

- [ ] **Step 4: Убрать копию в снимке позиций**

В `backend/app/sync/holdings.py`:

1. Удалить функцию `_restricted_from` целиком (строки 161-173).
2. Дополнить импорт:

```python
from app.instruments.service import apply_reference, secid_from_ticker, trading_restricted_from_flags
```

3. Сразу за импортами, рядом с константой `_ISIN_UNIQUE_INDEX`, добавить строку связывания. Короткое имя оставлено ради читаемости трёх вызовов ниже, а само присваивание — точка, по которой видно: правило здесь не своё, а общее.

```python
# Правило «ограничена в обороте» — одно на проект (app/instruments/service.py).
# Здесь то же самое имя указывает на ту же самую функцию, а не на копию.
_restricted_from = trading_restricted_from_flags
```

4. Заменить три вызова: аргументом теперь пара флагов, а не объект.

- строка 86: `_restricted_from(item.reference)` → `_restricted_from(item.reference.buy_available, item.reference.sell_available)`
- строка 136: `bool(_restricted_from(reference))` → `bool(_restricted_from(reference.buy_available, reference.sell_available))`
- строка 155: `_restricted_from(reference)` → `_restricted_from(reference.buy_available, reference.sell_available)`

- [ ] **Step 5: Убрать копию в дозаполнении справочника**

В `backend/app/instruments/backfill.py`:

1. Удалить функцию `_restricted_from` целиком (строки 135-142).
2. Дополнить импорт:

```python
from app.instruments.service import apply_reference, secid_from_ticker, trading_restricted_from_flags
```

3. Добавить ту же строку связывания после импортов:

```python
# Правило «ограничена в обороте» — одно на проект (app/instruments/service.py).
_restricted_from = trading_restricted_from_flags
```

4. Поправить единственный вызов в `backfill_instruments` (строка 71): `_restricted_from(found)` → `_restricted_from(found.buy_available, found.sell_available)`.

Функцию `_availability_rank` не трогать: она решает другую задачу — ранжирует записи справочника одного ISIN по свидетельству о свободе распоряжения, а не отвечает на вопрос «ограничена ли».

- [ ] **Step 6: Прогнать тесты**

```bash
cd backend && uv run pytest tests/test_restrictions.py tests/test_holdings_instruments.py tests/test_instrument_seam.py -v
```

Ожидается: PASS. Если какой-то тест звал `_restricted_from` со старой сигнатурой (один аргумент) — поправить вызов в тесте, поведение при этом не меняется.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/instruments/service.py backend/app/sync/holdings.py backend/app/instruments/backfill.py backend/tests/test_restrictions.py
git commit -m "refactor: правило ограничения в обороте — одна функция вместо трёх копий"
```

---

### Task 2: Закрепить предпосылку `signed_quantity`

**Files:**
- Modify: `backend/app/positions/engine.py:56-73` (докстринг)
- Test: `backend/tests/test_tbank_mapper.py`

**Interfaces:**
- Consumes: ничего.
- Produces: ничего нового — только гарантия, на которую опирается `signed_quantity`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_tbank_mapper.py`:

```python
def test_mapper_never_produces_negative_quantity_for_directional_operations():
    """Количество у операции с собственным направлением неотрицательно.

    На этом молча стоит signed_quantity (app/positions/engine.py): она отрицает
    количество у DECREASING, и отрицательное количество продажи дало бы приход
    вместо расхода. Т-Банк — единственный сегодняшний производитель
    RawOperation, и предпосылку проверяем на нём: брокер отдаёт quantityDone
    беззнаковым, направление несёт тип операции.
    """
    operation = {
        "id": "77",
        "state": "OPERATION_STATE_EXECUTED",
        "type": "OPERATION_TYPE_SELL",
        "date": "2026-08-11T10:00:00Z",
        "quantityDone": "-100",
        "price": {"units": "50", "nano": 0},
        "payment": {"units": "5000", "nano": 0, "currency": "rub"},
    }

    mapped = map_operation(operation, None)

    assert mapped is not None
    assert mapped.quantity >= 0, (
        "Отрицательное количество у операции с собственным направлением "
        "разворачивает её в signed_quantity: продажа стала бы приходом."
    )
```

Проверить, что `map_operation` уже импортирован в файле; `EXECUTED`-константа в маппере — `"OPERATION_STATE_EXECUTED"`, сверить по `backend/app/connectors/tbank/mapper.py`.

- [ ] **Step 2: Прогнать тест и посмотреть, падает ли он**

```bash
cd backend && uv run pytest tests/test_tbank_mapper.py::test_mapper_never_produces_negative_quantity_for_directional_operations -v
```

Ожидается: FAIL — `_executed_quantity` берёт `quantityDone` как есть, и `mapped.quantity` окажется `-100`.

- [ ] **Step 3: Взять модуль по абсолютной величине в маппере**

В `backend/app/connectors/tbank/mapper.py`, функция `_executed_quantity`, заменить последнюю строку:

```python
    done = operation.get("quantityDone")
    raw = done if done not in (None, "") else operation.get("quantity")
    # Модуль, а не значение как есть: направление операции несёт её тип, и
    # signed_quantity (app/positions/engine.py) расставляет знак сама. Брокер
    # отдаёт количество беззнаковым, но отрицательное значение в ответе
    # развернуло бы операцию — продажа стала бы приходом, и позиция уехала бы
    # на двойную величину, ничем себя не выдав.
    return abs(Decimal(raw or "0"))
```

- [ ] **Step 4: Прогнать тест — должен пройти**

```bash
cd backend && uv run pytest tests/test_tbank_mapper.py -v
```

Ожидается: PASS, остальные тесты маппера тоже.

- [ ] **Step 5: Записать предпосылку в докстринг `signed_quantity`**

В `backend/app/positions/engine.py` дописать в докстринг `signed_quantity` абзац перед абзацем про конвертацию:

```python
    Предпосылка: у операции с собственным направлением (INCREASING, DECREASING)
    количество неотрицательно — знак несёт тип, а не число. Отрицательное
    количество продажи здесь стало бы приходом. Производители RawOperation
    обязаны это соблюдать; у единственного сегодняшнего — коннектора Т-Банка —
    предпосылка закреплена тестом (tests/test_tbank_mapper.py,
    test_mapper_never_produces_negative_quantity_for_directional_operations).
    У ADJUSTMENT всё наоборот: знак и есть направление, и трогать его нельзя.
```

- [ ] **Step 6: Прогнать тесты движка**

```bash
cd backend && uv run pytest tests/test_positions_engine.py tests/test_tbank_mapper.py -v
```

Ожидается: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/positions/engine.py backend/app/connectors/tbank/mapper.py backend/tests/test_tbank_mapper.py
git commit -m "fix: количество операции по модулю — знак ставит тип, а не брокер"
```

---

### Task 3: `_find_changed` — один запрос на батч вместо запроса на операцию

**Files:**
- Modify: `backend/app/ledger/service.py:142-210` (`_find_changed` → `_recorded_by_external_id` + чистая функция сравнения), `285-330` (`append_operations`)
- Test: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: `signed_quantity` из `app.positions.engine` (уже импортирован).
- Produces:
  - `_recorded_by_external_id(session: Session, account: Account, source: str, external_ids: list[str]) -> dict[str, list[Transaction]]` — уже записанные транзакции счёта, сгруппированные по внешнему идентификатору исходной операции, в порядке `id`.
  - `_changed_against(recorded: list[Transaction], op: RawOperation) -> tuple[Transaction, Decimal, Decimal, Decimal] | None` — то же решение, что принимал прежний `_find_changed`, но без обращения к базе.

- [ ] **Step 1: Написать падающий тест на число запросов**

Дописать в `backend/tests/test_corrections.py`:

```python
from sqlalchemy import event


def test_find_changed_does_not_query_per_operation(session, account):
    """Поиск переписанных брокером операций — один запрос на батч.

    Раньше запрос уходил на каждую операцию батча, включая совершенно новые:
    на первой полной синхронизации счёта это тысячи обращений там, где соседний
    код ради экономии специально держит кэш инструментов и пакетный flush.
    """
    operations = [
        raw_operation(external_id=str(index), quantity="10", amount="-1000")
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

    lookups = [s for s in statements if "corrects_external_id" in s]
    assert len(lookups) <= 1, (
        f"Поиск переписанных операций ушёл {len(lookups)} раз на батч из 50 — "
        "запрос обязан быть один на батч."
    )
```

`raw_operation` — вспомогательная фабрика; проверить, есть ли такая в `tests/test_corrections.py` или `tests/conftest.py`, и переиспользовать. Если её нет, написать рядом:

```python
def raw_operation(*, external_id: str, quantity: str, amount: str,
                  op_type: OperationType = OperationType.BUY,
                  price: str = "100", isin: str = "RU000A0JQUZ6") -> RawOperation:
    return RawOperation(
        external_id=external_id,
        op_type=op_type,
        executed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        isin=isin,
        ticker="AGRO",
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal(amount),
        currency="RUB",
        fee=Decimal("0"),
        payload={},
    )
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

```bash
cd backend && uv run pytest tests/test_corrections.py::test_find_changed_does_not_query_per_operation -v
```

Ожидается: FAIL, `lookups` порядка 50.

- [ ] **Step 3: Разделить `_find_changed` на запрос и решение**

В `backend/app/ledger/service.py` заменить функцию `_find_changed` целиком на две. Запрос:

```python
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
```

Решение (тот же текст докстринга, что был у `_find_changed`, — правило не меняется):

```python
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
```

- [ ] **Step 4: Переключить `append_operations` на предзагрузку**

В `append_operations`, сразу после строки `known = _load_known_keys(session, keys)`, добавить:

```python
    # Предзагрузка до цикла: раньше поиск переписанных брокером операций уходил
    # в базу на каждую операцию батча.
    recorded = _recorded_by_external_id(
        session, account, source,
        [op.external_id for op in operations if op.external_id is not None],
    )
```

и заменить в цикле строку `changed = _find_changed(session, account, source, op)` на:

```python
        # Операция без внешнего идентификатора сопоставлению не поддаётся:
        # ключа, по которому её узнать в журнале, попросту нет.
        changed = (
            _changed_against(recorded.get(op.external_id, []), op)
            if op.external_id is not None else None
        )
```

- [ ] **Step 5: Прогнать тесты корректировок и журнала**

```bash
cd backend && uv run pytest tests/test_corrections.py tests/test_ledger_service.py tests/test_dedup.py tests/test_sync_service.py -v
```

Ожидается: PASS, включая новый тест на число запросов.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/ledger/service.py backend/tests/test_corrections.py
git commit -m "perf: поиск переписанных операций — один запрос на батч вместо запроса на операцию"
```

---

### Task 4: `sync_run.corrected` — счётчик правок брокера доезжает до записи прогона

**Files:**
- Create: `backend/alembic/versions/0018_sync_run_corrected.py`
- Modify: `backend/app/models/sync_run.py`, `backend/app/sync/service.py:129-131`, `backend/app/api/schemas.py:186-193`, `backend/app/api/routes_sync.py:39`, `backend/app/scheduler.py:86-90`
- Modify: `frontend/src/api/client.ts:130-139`
- Test: `backend/tests/test_sync_service.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `AppendResult.corrected` из `app.ledger.service` (уже есть).
- Produces: колонка `sync_run.corrected` (`Integer`, `default=0`, `NOT NULL`), поле `SyncRunOut.corrected: int`, поле `SyncRunResult.corrected: number` во фронте.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_sync_service.py`:

```python
def test_sync_run_records_corrections(session):
    """Правки брокера задним числом видны в записи прогона.

    Счётчик считался, но не присваивался никуда: наблюдать его можно было
    только в логе. А это сигнал о поломке обхода STILL_FILLING_WINDOW — если он
    станет стабильно ненулевым, значит обход перестал работать.
    """
    connector = FakeConnector(operations=[
        raw_operation(external_id="1", op_type=OperationType.SELL,
                      quantity="12", price="120", amount="1440"),
    ])
    sync_broker(session, connector)

    # Тот же external_id, но брокер доисполнил заявку: 12 стало 100.
    connector.operations = [
        raw_operation(external_id="1", op_type=OperationType.SELL,
                      quantity="100", price="120", amount="12000"),
    ]
    runs = sync_broker(session, connector)

    assert runs[0].corrected == 1
```

`FakeConnector` — поддельный коннектор из этого же файла; посмотреть его имя и конструктор в `tests/test_sync_service.py` и следовать им, обеспечив изменяемость списка операций между двумя вызовами (если у существующего коннектора список задаётся только в конструкторе, присвоить атрибут напрямую, как в примере). `raw_operation` — та же фабрика, что заведена в задаче 3; если она осталась локальной для `tests/test_corrections.py`, перенести её в `tests/conftest.py` и импортировать в обоих файлах.

- [ ] **Step 2: Прогнать тест — падает**

```bash
cd backend && uv run pytest tests/test_sync_service.py::test_sync_run_records_corrections -v
```

Ожидается: FAIL — `AttributeError: 'SyncRun' object has no attribute 'corrected'`.

- [ ] **Step 3: Миграция**

Создать `backend/alembic/versions/0018_sync_run_corrected.py`:

```python
"""счётчик корректирующих записей у прогона синхронизации

Revision ID: 0018
Revises: 0017

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ноль у прошлых прогонов — честное значение, а не заглушка: корректирующие
    # записи появились в фазе 2b, и до неё их не было ни одной.
    op.add_column('sync_run', sa.Column('corrected', sa.Integer(), nullable=False,
                                        server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('sync_run', 'corrected')
```

- [ ] **Step 4: Колонка в модели**

В `backend/app/models/sync_run.py`, рядом с `mismatches`:

```python
    # Операции, которые брокер переписал задним числом: на разницу записана
    # корректирующая запись (см. AppendResult в app/ledger/service.py). Должно
    # быть редкостью — частый случай доисполняющейся заявки закрыт окном
    # STILL_FILLING_WINDOW в коннекторе. Стабильно ненулевой счётчик означает,
    # что обход перестал работать.
    corrected: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
```

Проверить, что `text` импортирован из `sqlalchemy`; если нет — добавить.

- [ ] **Step 5: Присваивание в синхронизации**

В `backend/app/sync/service.py`, рядом с `run.inserted` и `run.skipped`:

```python
            run.inserted = result.inserted
            run.skipped = result.skipped
            run.corrected = result.corrected
```

- [ ] **Step 6: Контракт наружу**

В `backend/app/api/schemas.py`, класс `SyncRunOut`, после `skipped`:

```python
    # Операции, которые брокер переписал задним числом (см. sync_run.corrected).
    corrected: int
```

В `backend/app/api/routes_sync.py:39` добавить в конструктор `SyncRunOut(...)`: `corrected=run.corrected,`.

В `backend/app/scheduler.py`, в `job_sync_tbank`, дополнить строку лога:

```python
            logger.info(
                "Синхронизация %s: %s, новых %s, исправлено %s, расхождений %s",
                run.broker, run.status, run.inserted, run.corrected, run.mismatches,
            )
```

В `frontend/src/api/client.ts`, интерфейс `SyncRunResult`, после `skipped`:

```typescript
  // Операции, которые брокер переписал задним числом: на разницу записана
  // корректирующая запись. Стабильно ненулевое значение означает поломку
  // обхода доисполняющихся заявок на стороне бэкенда.
  corrected: number;
```

- [ ] **Step 7: Прогнать тесты**

```bash
cd backend && uv run pytest tests/test_sync_service.py tests/test_migrations.py tests/test_api.py -v
```

Ожидается: PASS. `test_migrations.py` проверяет, что цепочка миграций поднимается и откатывается — если она сверяется со списком ревизий, дописать `0018`.

- [ ] **Step 8: Коммит**

```bash
git add backend/alembic/versions/0018_sync_run_corrected.py backend/app/models/sync_run.py backend/app/sync/service.py backend/app/api/schemas.py backend/app/api/routes_sync.py backend/app/scheduler.py backend/tests/test_sync_service.py frontend/src/api/client.ts
git commit -m "feat: счётчик корректирующих записей в прогоне синхронизации"
```

---

### Task 5: Разбивка снимка по счетам доезжает до `/portfolio/history`

**Files:**
- Modify: `backend/app/api/schemas.py:104-110` (`HistoryPointOut`), `backend/app/api/routes_portfolio.py:96-105` (`get_history`)
- Modify: `frontend/src/api/client.ts:68-71` (`HistoryPoint`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `app.snapshots.service.snapshot_by_account(session, snapshot) -> dict[str, Decimal]` — ключ уже подписанный счёт.
- Produces: поле `HistoryPointOut.by_account: dict[str, Decimal]`, сериализуется как `{подпись: "0.0000"}`; поле `HistoryPoint.by_account: Record<string, string>` во фронте.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_api.py`:

```python
def test_history_returns_breakdown_by_account(client, session, account):
    """История отдаёт разбивку по счетам, а не только итог.

    Разбивка считается и хранится с фазы 2a, но читатель (snapshot_by_account)
    не вызывался из production-кода ни разу — данные копились в стол.
    """
    take_snapshot(session, moscow_today())
    session.commit()

    points = client.get("/api/portfolio/history").json()

    assert points, "снимок за сегодня должен попасть в окно истории"
    assert account_label(account) in points[-1]["by_account"]
```

Проверить фикстуры `client`, `session`, `account` в `tests/conftest.py` и следовать их именам; добавить импорты `take_snapshot`, `moscow_today`, `account_label`.

- [ ] **Step 2: Прогнать тест — падает**

```bash
cd backend && uv run pytest tests/test_api.py::test_history_returns_breakdown_by_account -v
```

Ожидается: FAIL — `KeyError: 'by_account'`.

- [ ] **Step 3: Расширить контракт**

В `backend/app/api/schemas.py`:

```python
class HistoryPointOut(BaseModel):
    date: date
    total_value: Decimal
    # Разбивка по счетам, подписанным той же единственной на проект функцией,
    # что и везде (app/accounts/labels.py). В самом снимке лежит устойчивый
    # идентификатор счёта — подпись строится при чтении.
    by_account: dict[str, Decimal] = {}

    @field_serializer("total_value")
    def serialize_total(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_account")
    def serialize_by_account(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}
```

- [ ] **Step 4: Подключить читателя в обработчике**

В `backend/app/api/routes_portfolio.py` дополнить импорты:

```python
from app.snapshots.service import snapshot_by_account
```

и заменить возврат `get_history`:

```python
    return [
        HistoryPointOut(
            date=row.on_date,
            total_value=row.total_value,
            by_account=snapshot_by_account(session, row),
        )
        for row in rows
    ]
```

- [ ] **Step 5: Тип во фронте**

В `frontend/src/api/client.ts`:

```typescript
export interface HistoryPoint {
  date: string;
  total_value: string;
  // Разбивка итога по счетам на эту дату; ключ — подпись счёта. Пусто у
  // снимков, снятых до появления разбивки.
  by_account: Record<string, string>;
}
```

- [ ] **Step 6: Прогнать тесты**

```bash
cd backend && uv run pytest tests/test_api.py -v
cd ../frontend && pnpm build
```

Ожидается: PASS и сборка без ошибок типов.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/api/schemas.py backend/app/api/routes_portfolio.py backend/tests/test_api.py frontend/src/api/client.ts
git commit -m "feat: разбивка снимка по счетам в истории стоимости"
```

---

### Task 6: Валюта записей, порождённых решением, — из инструмента

**Files:**
- Modify: `backend/app/decisions/service.py:107-165` (`_entry`, `_generate_entries`)
- Test: `backend/tests/test_decisions_service.py`

**Interfaces:**
- Consumes: `Instrument.currency` (`app/models/instrument.py`).
- Produces: `_entry(...)` получает дополнительный параметр `currency: str`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_decisions_service.py`:

```python
def test_conversion_entries_carry_instrument_currency(session, account, hkd_instruments):
    """Записи решения несут валюту своей бумаги, а не рубль по умолчанию.

    Суммы у них нулевые, и сегодня это безвредно, но у гонконгского ETF из
    решения №1 валюта HKD: первый же потребитель, посмотревший на валюту
    записи, соврал бы.
    """
    source, target = hkd_instruments  # обе в HKD

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

    entries = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalars().all()

    assert {entry.currency for entry in entries} == {"HKD"}
```

Фикстуру `hkd_instruments` собрать в файле рядом: два `Instrument` с `currency="HKD"`, ISIN `HK0000310034` и `HK0000051877` (реальные бумаги из решения №1). Перед конвертацией бумага-источник должна лежать в журнале — посмотреть, как это делают уже существующие тесты конвертации в `tests/test_conversion.py`, и повторить.

- [ ] **Step 2: Прогнать тест — падает**

```bash
cd backend && uv run pytest tests/test_decisions_service.py -k currency -v
```

Ожидается: FAIL — `{'RUB'} != {'HKD'}`.

- [ ] **Step 3: Передавать валюту в `_entry`**

В `backend/app/decisions/service.py` заменить сигнатуру и тело `_entry`:

```python
def _entry(
    decision: LedgerDecision, leg: str, op_type: OperationType,
    instrument_id: int, quantity, price, currency: str,
) -> Transaction:
    return Transaction(
        account_id=decision.account_id,
        instrument_id=instrument_id,
        op_type=op_type,
        executed_at=decision.effective_at,
        quantity=q(quantity),
        price=money(price),
        amount=money("0"),
        # Валюта своей бумаги, а не рубль по умолчанию. Суммы у этих записей
        # нулевые, и на оценку валюта пока не влияет, но у гонконгского ETF из
        # первого разобранного расхождения она HKD — прибитый гвоздём рубль
        # соврал бы первому же потребителю, который на неё посмотрит.
        currency=currency,
        fee=money("0"),
        external_id=f"decision:{decision.id}:{leg}",
        source=SOURCE,
        dedup_key=_dedup_key(decision.id, leg),
        # decision_id связывает две стороны конвертации: движок достаёт его в
        # LedgerEntry.link_id (app/positions/service.py).
        payload=_payload(decision),
    )
```

Добавить рядом функцию поиска валюты:

```python
def _currency_of(session: Session, instrument_id: int) -> str:
    """Валюта бумаги для записи, порождённой решением.

    Рубль остаётся запасным значением: колонка currency в журнале NOT NULL, а
    инструмент, заведённый из снимка без справочных сведений, валюты может не
    иметь вовсе.
    """
    instrument = session.get(Instrument, instrument_id)
    return (instrument.currency if instrument and instrument.currency else "RUB").upper()
```

Добавить `Instrument` в импорт из `app.models`.

- [ ] **Step 4: Передать валюту в трёх местах `_generate_entries`**

```python
    if decision.kind is DecisionKind.CONVERSION:
        session.add(_entry(decision, "out", OperationType.CONVERSION_OUT,
                           decision.from_instrument_id, decision.from_quantity, "0",
                           _currency_of(session, decision.from_instrument_id)))
        session.add(_entry(decision, "in", OperationType.CONVERSION_IN,
                           decision.to_instrument_id, decision.to_quantity, "0",
                           _currency_of(session, decision.to_instrument_id)))
    elif decision.kind is DecisionKind.ADJUSTMENT:
        if decision.to_instrument_id is not None:
            price = (money(decision.cost_basis / decision.to_quantity)
                     if decision.cost_basis is not None and decision.to_quantity
                     else money("0"))
            session.add(_entry(decision, "in", OperationType.ADJUSTMENT,
                               decision.to_instrument_id, decision.to_quantity, price,
                               _currency_of(session, decision.to_instrument_id)))
        else:
            session.add(_entry(decision, "out", OperationType.ADJUSTMENT,
                               decision.from_instrument_id,
                               decreasing_adjustment(decision.from_quantity), "0",
                               _currency_of(session, decision.from_instrument_id)))
```

Комментарии, стоявшие в этих ветках (про цену ноль как «неизвестно» и про знак списания), сохранить на местах — они объясняют не валюту.

- [ ] **Step 5: Прогнать тесты решений и конвертаций**

```bash
cd backend && uv run pytest tests/test_decisions_service.py tests/test_conversion.py tests/test_transfers.py -v
```

Ожидается: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/decisions/service.py backend/tests/test_decisions_service.py
git commit -m "fix: записи решения несут валюту своей бумаги, а не рубль по умолчанию"
```

---

### Task 7: Себестоимость заводится с экрана

**Files:**
- Modify: `frontend/src/components/DecisionPanel.tsx` (состояние, поле формы, тело запроса)
- Modify: `frontend/src/api/client.ts` (тип `DecisionInput`, если поля `cost_basis` там нет)
- Test: `frontend/src/components/DecisionPanel.test.tsx`

**Interfaces:**
- Consumes: `DecisionIn.cost_basis: Decimal | None` — контракт бэкенда уже принимает это поле (`backend/app/api/schemas.py:144`).
- Produces: поле `cost_basis` в теле `POST /api/decisions`, отправляемом панелью.

- [ ] **Step 1: Написать падающий тест**

Дописать в `frontend/src/components/DecisionPanel.test.tsx`:

```tsx
it("отправляет себестоимость зачисляемой бумаги, когда владелец её знает", async () => {
  const user = userEvent.setup();
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(jsonResponse({ id: 1 })));

  renderPanel({ ...ROW, suggestions: [] });

  await user.type(screen.getByLabelText(/в какую бумагу/i), "RU000A0JQUZ6");
  await user.type(screen.getByLabelText(/сколько зачислить/i), "351");
  await user.type(screen.getByLabelText(/себестоимость/i), "40000");
  await user.type(screen.getByLabelText(/пояснение/i), "Ввод бумаг извне");
  await user.click(screen.getByRole("button", { name: /подтвердить/i }));

  await waitFor(() => {
    const call = fetchSpy.mock.calls.find(
      ([url]) => typeof url === "string" && url.endsWith("/decisions"),
    );
    expect(call).toBeDefined();
    const body = JSON.parse((call![1] as RequestInit).body as string);
    // Без себестоимости позиция навсегда остаётся без средней цены и без
    // доходности — а владелец её знает и ввести не может.
    expect(body.cost_basis).toBe("40000");
  });
});

it("не отправляет себестоимость, когда поле пусто", async () => {
  const user = userEvent.setup();
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(jsonResponse({ id: 1 })));

  renderPanel({ ...ROW, suggestions: [] });

  await user.type(screen.getByLabelText(/в какую бумагу/i), "RU000A0JQUZ6");
  await user.type(screen.getByLabelText(/сколько зачислить/i), "351");
  await user.type(screen.getByLabelText(/пояснение/i), "Ввод бумаг извне");
  await user.click(screen.getByRole("button", { name: /подтвердить/i }));

  await waitFor(() => {
    const call = fetchSpy.mock.calls.find(
      ([url]) => typeof url === "string" && url.endsWith("/decisions"),
    );
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.cost_basis).toBeNull();
  });
});
```

Использовать уже имеющиеся в файле помощники (`renderPanel`, `jsonResponse`, `ROW`); если их нет — написать по образцу `ReconciliationBanner.test.tsx`.

- [ ] **Step 2: Прогнать тесты — падают**

```bash
cd frontend && pnpm test -- DecisionPanel
```

Ожидается: FAIL — поля «себестоимость» на экране нет.

- [ ] **Step 3: Состояние и поле формы**

В `frontend/src/components/DecisionPanel.tsx` добавить состояние рядом с `toQuantity`:

```tsx
  // Себестоимость всей зачисляемой партии, если владелец её знает. Пусто —
  // партия помечается неизвестной себестоимостью, и по позиции не
  // показываются ни средняя цена, ни доходность (backend/app/decisions/
  // service.py, _generate_entries).
  const [costBasis, setCostBasis] = useState("");
```

Сбрасывать её вместе с остальными полями в `changeKind` и `changeDirection` — дописать `setCostBasis("");` в обе функции, туда же, где сбрасываются `toQuantity` и прочие.

В ветке `direction === "CREDIT"` блока `kind === "ADJUSTMENT"`, следом за полем «Сколько зачислить», добавить:

```tsx
                <label style={{ fontSize: 12, gridColumn: "1 / -1" }}>
                  Себестоимость всей партии, ₽ — если знаете
                  <input value={costBasis} onChange={(e) => setCostBasis(e.target.value)}
                         placeholder="не знаю"
                         style={{ display: "block", width: "100%" }} />
                  <span style={{ display: "block", fontSize: 11, color: "var(--muted)" }}>
                    Пусто — себестоимость останется неизвестной, и по позиции не
                    будет ни средней цены, ни доходности.
                  </span>
                </label>
```

Если переменной `--muted` в теме нет, взять ту, которой пользуются соседние пояснительные подписи в этом же файле.

- [ ] **Step 4: Отправлять поле в запросе**

В `confirm` добавить переменную рядом с прочими `payload*`:

```tsx
    let payloadCostBasis: string | null = null;
```

в ветке `kind === "ADJUSTMENT"`, внутри `else` (зачисление):

```tsx
      } else {
        payloadToIsin = toIsin || null;
        payloadToQuantity = toQuantity || null;
        payloadCostBasis = costBasis || null;
      }
```

и в тело `submit.mutate`, после `to_quantity`:

```tsx
      cost_basis: payloadCostBasis,
```

- [ ] **Step 5: Тип запроса**

В `frontend/src/api/client.ts`, интерфейс `DecisionInput`, добавить (если поля ещё нет):

```typescript
  // Себестоимость всей зачисляемой партии; null — владелец её не знает, и
  // партия помечается партией с неизвестной себестоимостью.
  cost_basis: string | null;
```

- [ ] **Step 6: Прогнать тесты и сборку**

```bash
cd frontend && pnpm test && pnpm build
```

Ожидается: PASS, сборка без ошибок типов.

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/components/DecisionPanel.tsx frontend/src/components/DecisionPanel.test.tsx frontend/src/api/client.ts
git commit -m "feat: себестоимость зачисляемой партии заводится с экрана"
```

---

### Task 8: Дата события по-московски, направление поправки — из расхождения

**Files:**
- Modify: `frontend/src/components/DecisionPanel.tsx:16-20` (`today`), `:42` (начальное направление)
- Test: `frontend/src/components/DecisionPanel.test.tsx`

**Interfaces:**
- Produces: `defaultDirection(row: ReconciliationRow): Direction` — экспортируемая из модуля панели чистая функция, чтобы её можно было проверить без рендера.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `frontend/src/components/DecisionPanel.test.tsx`:

```tsx
import { DecisionPanel, defaultDirection, moscowToday } from "./DecisionPanel";

describe("подсказки по умолчанию", () => {
  it("берёт дату события по московскому поясу, а не по UTC", () => {
    // 01:30 MSK 12 августа — это ещё 22:30 UTC одиннадцатого. Весь проект
    // живёт по московской календарной дате: снимки, котировки, окно истории.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-11T22:30:00Z"));
    try {
      expect(moscowToday()).toBe("2026-08-12");
    } finally {
      vi.useRealTimers();
    }
  });

  it("предлагает списание, когда бумаги нет у брокера", () => {
    expect(defaultDirection({ ...ROW, status: "missing_at_broker" })).toBe("DEBIT");
  });

  it("предлагает зачисление, когда бумаги нет в журнале", () => {
    expect(defaultDirection({ ...ROW, status: "missing_in_ledger" })).toBe("CREDIT");
  });

  it("при расхождении количеств смотрит, в какую сторону оно", () => {
    expect(defaultDirection({
      ...ROW, status: "quantity_mismatch",
      ledger_quantity: "209.00000000", broker_quantity: "560.00000000",
    })).toBe("CREDIT");
    expect(defaultDirection({
      ...ROW, status: "quantity_mismatch",
      ledger_quantity: "45.00000000", broker_quantity: "40.00000000",
    })).toBe("DEBIT");
  });
});
```

- [ ] **Step 2: Прогнать — падают**

```bash
cd frontend && pnpm test -- DecisionPanel
```

Ожидается: FAIL — `moscowToday` и `defaultDirection` не экспортируются.

- [ ] **Step 3: Московская дата вместо UTC**

Заменить функцию `today` в `frontend/src/components/DecisionPanel.tsx`:

```tsx
// Дата события по умолчанию — сегодня по Москве. Конвертация случилась
// когда-то раньше, и владелец обычно знает когда; поле редактируемое именно
// поэтому. Пояс важен: toISOString даёт дату по UTC, и до 03:00 по Москве
// подставлялась бы вчерашняя. Весь остальной проект — снимки, котировки, окно
// истории — живёт по московской календарной дате (backend/app/timeutils.py).
export function moscowToday(): string {
  // en-CA даёт ISO-подобный «ГГГГ-ММ-ДД», который и ждёт <input type="date">.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}
```

и заменить вызов `useState(today())` на `useState(moscowToday())`.

- [ ] **Step 4: Направление из расхождения**

Добавить рядом с `moscowToday`:

```tsx
// Направление поправки по умолчанию задаёт само расхождение. Прежнее
// безусловное «зачислить» было подсказкой наугад: половина разбираемых строк —
// это бумага, которой у брокера нет, и её надо списывать.
export function defaultDirection(row: ReconciliationRow): Direction {
  if (row.status === "missing_at_broker") return "DEBIT";
  if (row.status === "missing_in_ledger") return "CREDIT";
  // quantity_mismatch: у брокера больше нашего — зачислить, меньше — списать.
  return Number(row.broker_quantity) >= Number(row.ledger_quantity) ? "CREDIT" : "DEBIT";
}
```

и заменить начальное состояние:

```tsx
  const [direction, setDirection] = useState<Direction>(defaultDirection(row));
```

- [ ] **Step 5: Прогнать тесты и сборку**

```bash
cd frontend && pnpm test && pnpm build
```

Ожидается: PASS.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/DecisionPanel.tsx frontend/src/components/DecisionPanel.test.tsx
git commit -m "fix: московская дата события и направление поправки из расхождения"
```

---

### Task 9: Позиция без ISIN больше не исчезает молча

**Files:**
- Modify: `backend/app/connectors/tbank/connector.py:185-215` (`fetch_positions`)
- Modify: `backend/app/sync/reconcile.py:17-27` (`reconcile_account`)
- Test: `backend/tests/test_tbank_connector.py`, `backend/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `logging.getLogger(__name__)` — проверить, что логгер в обоих модулях уже заведён; если нет, добавить.
- Produces: ничего нового в контракте.

- [ ] **Step 1: Написать падающие тесты**

В `backend/tests/test_tbank_connector.py`:

```python
def test_position_without_isin_is_logged(caplog, connector_with_isinless_position):
    """Позиция брокера без ISIN отбрасывается — но не молча.

    Бумага, пропавшая из сверки таким образом, выглядит как сошедшаяся: её нет
    ни в расхождениях, ни в позициях, и понять, что она вообще была, неоткуда.
    """
    with caplog.at_level(logging.WARNING):
        positions = connector_with_isinless_position.fetch_positions("acc-1")

    assert positions == []
    assert any("без ISIN" in record.getMessage() for record in caplog.records)
```

`record.getMessage()` — не `record.message`: второй существует только после форматирования, а сообщения в проекте пишутся с ленивыми `%s`-аргументами.

Фикстуру `connector_with_isinless_position` собрать по образцу существующих в файле: поддельный клиент, у которого `get_portfolio` отдаёт одну позицию с `figi`, а справочник разрешает её в `BrokerInstrument` с `isin=None`.

В `backend/tests/test_reconcile.py`:

```python
def test_ledger_position_without_isin_is_logged(caplog, session, account, instrument_without_isin):
    """Позиция журнала, инструмент которой без ISIN, в сверку не попадает — но
    оставляет след в логе: сверять её не с чем, а терять бесследно нельзя."""
    session.add(Position(account_id=account.id, instrument_id=instrument_without_isin.id,
                         quantity=Decimal("10"), average_price=Decimal("100"),
                         cost_basis_known=True))
    session.flush()

    with caplog.at_level(logging.WARNING):
        reconcile_account(session, account, [])

    assert any("без ISIN" in record.getMessage() for record in caplog.records)
```

Поля `Position` сверить с `backend/app/models/position.py` — набор обязательных колонок мог отличаться.

- [ ] **Step 2: Прогнать — падают**

```bash
cd backend && uv run pytest tests/test_tbank_connector.py -k isin tests/test_reconcile.py -k isin -v
```

Ожидается: FAIL — в логе ничего нет.

- [ ] **Step 3: Лог в коннекторе**

В `backend/app/connectors/tbank/connector.py`, в `fetch_positions`, заменить строку `if instrument is None or not instrument.isin: continue` на:

```python
            instrument = instruments.get(figi)
            if instrument is None or not instrument.isin:
                # Без ISIN позицию не с чем сверять: журнал ключуется им же.
                # Отбрасываем — но со следом: бумага, пропавшая отсюда молча,
                # выглядит дальше как сошедшаяся, а не как потерянная.
                logger.warning(
                    "Позиция счёта %s (FIGI %s, количество %s) пропущена: у бумаги нет ISIN "
                    "в справочнике брокера — сверять её не с чем.",
                    account_external_id, figi, qty,
                )
                continue
```

Проверить, что `logger = logging.getLogger(__name__)` в модуле есть.

- [ ] **Step 4: Лог в сверке**

В `backend/app/sync/reconcile.py` заменить построение словаря `ledger`:

```python
    ledger: dict[str, tuple[Position, Instrument]] = {}
    for position, instrument in rows:
        if not instrument.isin:
            # Сверять нечем: снимок брокера ключуется ISIN. Позиция остаётся в
            # портфеле и в капитале, но в расхождения не попадает никогда —
            # и без этой строки понять, почему её там нет, неоткуда.
            logger.warning(
                "Позиция счёта %s по инструменту %s (%s) не участвует в сверке: у него нет ISIN.",
                account.external_id, instrument.id, instrument.ticker or instrument.issuer,
            )
            continue
        ledger[instrument.isin] = (position, instrument)
```

Добавить в начало модуля:

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 5: Прогнать тесты**

```bash
cd backend && uv run pytest tests/test_tbank_connector.py tests/test_reconcile.py -v
```

Ожидается: PASS.

Замечание по `caplog`: в проекте уже отмечена порядко-зависимая ломкость `caplog` (см. попутный долг). Если тест проходит в одиночку и падает в общем прогоне, добавить в него `caplog.set_level(logging.WARNING, logger="app.sync.reconcile")` вместо `at_level` — это чинит зависимость от того, кто раньше трогал уровни.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/connectors/tbank/connector.py backend/app/sync/reconcile.py backend/tests/test_tbank_connector.py backend/tests/test_reconcile.py
git commit -m "fix: позиция без ISIN оставляет след в логе, а не исчезает молча"
```

---

### Task 10: `items: null` в ответах брокера, замороженный `payload`, счета без позиций в сверке

**Files:**
- Modify: `backend/app/connectors/tbank/client.py:157, 176, 186, 216`
- Modify: `backend/app/ledger/schemas.py:8-22`
- Modify: `backend/app/valuation_check.py:48-60`
- Test: `backend/tests/test_tbank_client.py`, `backend/tests/test_models.py`

**Interfaces:**
- Produces: `_list_field(payload: dict, key: str) -> list` в `app/connectors/tbank/client.py` — список из ответа брокера, где `null` равносилен отсутствию.

- [ ] **Step 1: Написать падающие тесты**

В `backend/tests/test_tbank_client.py`:

```python
def test_null_items_are_treated_as_empty(client_with_null_items):
    """JSON брокера отдаёт null там, где мы ждём список.

    `payload.get("items", [])` спасает от отсутствующего ключа, но не от явного
    null: значение по умолчанию не срабатывает, и наружу уходит None вместо
    списка — падение случается уже у вызывающего, вдали от причины.
    """
    assert client_with_null_items.get_operations("acc-1", "2026-01-01T00:00:00Z",
                                                 "2026-08-11T00:00:00Z") == []
    assert client_with_null_items.get_accounts() == []
    assert client_with_null_items.get_portfolio("acc-1") == []
```

Фикстуру собрать по образцу существующих в файле поддельных транспортов: `_post` отдаёт `{"items": None, "accounts": None, "positions": None, "hasNext": False}`.

В `backend/tests/test_models.py`:

```python
def test_raw_operation_payload_is_frozen():
    """frozen=True обязан замораживать и вложенный payload.

    Иначе обещание неизменности ложное: поля защищены, а словарь внутри —
    нет, и операция меняется у всех держателей ссылки разом.
    """
    operation = RawOperation(
        external_id="1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        isin="RU000A0JQUZ6", ticker="AGRO",
        quantity=Decimal("1"), price=Decimal("100"), amount=Decimal("-100"),
        currency="RUB", fee=Decimal("0"), payload={"figi": "BBG000000001"},
    )

    with pytest.raises(TypeError):
        operation.payload["figi"] = "подменено"
```

- [ ] **Step 2: Прогнать — падают**

```bash
cd backend && uv run pytest tests/test_tbank_client.py -k null tests/test_models.py -k frozen -v
```

Ожидается: FAIL в обоих.

- [ ] **Step 3: Помощник в клиенте**

В `backend/app/connectors/tbank/client.py` добавить рядом с прочими вспомогательными функциями модуля:

```python
def _list_field(payload: dict, key: str) -> list:
    """Список из ответа брокера: отсутствующий ключ и явный null — одно и то же.

    `payload.get(key, [])` спасает только от первого. T-Invest API отдаёт null
    там, где список пуст, и тогда наружу уходило None: падение случалось уже у
    вызывающего, за границей коннектора, где причину не видно.
    """
    return payload.get(key) or []
```

Заменить четыре места:

- `get_accounts`: `.get("accounts", [])` → обернуть вызов: `return _list_field(self._post(USERS_SERVICE, "GetAccounts", {}), "accounts")`
- `get_operations`: `items.extend(page.get("items", []))` → `items.extend(_list_field(page, "items"))`
- `get_portfolio`: `return _list_field(self._post(OPERATIONS_SERVICE, "GetPortfolio", {"accountId": account_id}), "positions")`
- `list_instruments`: `return _list_field(self._post(INSTRUMENTS_SERVICE, kind, body), "instruments")`

- [ ] **Step 4: Заморозить `payload`**

В `backend/app/ledger/schemas.py` заменить тип поля и добавить нормализацию:

```python
from types import MappingProxyType
from typing import Mapping


class RawOperation(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    ...
    # Только для чтения: frozen=True защищает поля модели, но не содержимое
    # вложенного словаря — правка payload у одного держателя ссылки меняла
    # операцию у всех сразу, а обещание неизменности оказывалось ложным.
    payload: Mapping

    @field_validator("payload", mode="before")
    @classmethod
    def payload_must_be_read_only(cls, value):
        if isinstance(value, MappingProxyType):
            return value
        return MappingProxyType(dict(value))
```

Проверить, что потребители `payload` только читают его. Кандидаты на проверку: `app/ledger/service.py` (`_build_transaction` кладёт `payload=op.payload` в `Transaction`), `app/instruments/service.py` (`_reference_from`), `app/connectors/tbank/mapper.py`. `MappingProxyType` в колонку `JSONB` SQLAlchemy не запишет — в `_build_transaction` передавать `dict(op.payload)`:

```python
        payload=dict(op.payload),
```

- [ ] **Step 5: Все счета брокера в сверке**

В `backend/app/valuation_check.py` заменить цикл: вместо перебора `overview.by_account` перебирать все счета брокера, беря наш итог из `by_account` с нулём по умолчанию.

```python
        total_ours = money("0")
        total_theirs = money("0")
        # Перебираем все счета брокера, а не только те, что попали в
        # by_account: счёт, синхронизация которого отвалилась целиком, не имеет
        # ни позиций, ни денег — и в прежней версии не появлялся в сверке
        # вовсе. Ровно тот случай, ради которого сверку и смотрят.
        for account in sorted(accounts.values(), key=lambda item: item.name):
            ours = overview.by_account.get(account.id, money("0"))
```

Дальше по телу цикла оставить как есть (запрос `GetPortfolio`, `raw_total`, вывод строки), удалив ставшие лишними `account = accounts.get(account_id)` и `if account is None: continue`.

- [ ] **Step 6: Прогнать тесты**

```bash
cd backend && uv run pytest -v
```

Ожидается: PASS целиком. `valuation_check` тестами не покрыт (он ходит в живой API) — проверить его импортируемость: `uv run python -c "import app.valuation_check"`.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/connectors/tbank/client.py backend/app/ledger/schemas.py backend/app/valuation_check.py backend/tests/test_tbank_client.py backend/tests/test_models.py
git commit -m "fix: null вместо списка, изменяемый payload и счета без позиций в сверке"
```

---

### Task 11: Подписи счетов в расхождениях, тест баннера, синхронизация без токена

**Files:**
- Modify: `backend/app/api/routes_portfolio.py:108-132` (`get_reconciliations`)
- Modify: `frontend/src/components/ReconciliationBanner.test.tsx:54, 65, 77, 100, 115`
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `account_label(account)` из `app.accounts.labels` (уже импортирован в модуле).

- [ ] **Step 1: Написать падающий тест на синхронизацию без токена**

Дописать в `backend/tests/test_scheduler.py`:

```python
def test_sync_job_without_token_does_nothing(monkeypatch, caplog):
    """Пустой TBANK_TOKEN — задача молча пропускается, а не падает.

    У задачи снимка такой тест есть, у синхронизации не было: отказ здесь
    остановил бы весь планировщик, а вместе с ним и снимки, и курсы.
    """
    monkeypatch.setattr(scheduler_module, "get_settings",
                        lambda: SimpleNamespace(tbank_token=""))

    def fail(*args, **kwargs):
        raise AssertionError("К брокеру ходить не за чем: токена нет")

    monkeypatch.setattr(scheduler_module, "TBankConnector", fail)

    with caplog.at_level(logging.WARNING):
        scheduler_module.job_sync_tbank()

    assert any("TBANK_TOKEN" in record.getMessage() for record in caplog.records)
```

Импорты: `from types import SimpleNamespace`, `import app.scheduler as scheduler_module`. Проверить, как соседние тесты в файле подменяют `get_settings` — `job_sync_tbank` импортирует её внутри модуля, поэтому подменять надо атрибут модуля `app.scheduler`.

- [ ] **Step 2: Прогнать — должен пройти или упасть осмысленно**

```bash
cd backend && uv run pytest tests/test_scheduler.py -k token -v
```

Если тест сразу зелёный — это нормально: поведение уже верное, тест закрывает дыру в покрытии, а не чинит дефект. Если падает на способе подмены — поправить подмену, а не производственный код.

- [ ] **Step 3: Предзагрузка подписей в расхождениях**

В `backend/app/api/routes_portfolio.py` заменить тело `get_reconciliations`:

```python
@router.get("/reconciliations", response_model=list[ReconciliationOut])
def get_reconciliations(session: Session = Depends(get_session)) -> list[ReconciliationOut]:
    rows = session.execute(select(Reconciliation).order_by(Reconciliation.isin)).scalars().all()
    account_ids = {row.account_id for row in rows}
    # Счета и гипотезы забираются до сборки ответа — так же, как в трёх соседних
    # обработчиках. Прежде подпись бралась построчно через account_label_by_id:
    # SQL при этом шёл один раз на счёт (identity map сессии), но обработчик был
    # единственным, кто делал это иначе, чем остальные.
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_(account_ids))
        ).scalars()
    }
    # Гипотезы считаются по счёту целиком: пара ищется среди расхождений
    # одного счёта, поэтому кэшируем результат на счёт, а не запрашиваем его
    # для каждой строки.
    by_account: dict[int, dict[str, list]] = {
        account_id: suggestions_for_account(session, account_id)
        for account_id in account_ids
    }

    return [
        ReconciliationOut(
            isin=row.isin, status=row.status,
            ledger_quantity=row.ledger_quantity, broker_quantity=row.broker_quantity,
            # Сверка считается по каждому счёту отдельно — один и тот же ISIN
            # может дать две строки на двух разных счетах, неразличимые без
            # подписи счёта (проверено на живых данных владельца).
            account=(account_label(accounts[row.account_id])
                     if row.account_id in accounts else UNKNOWN_ACCOUNT_LABEL),
            suggestions=[
                SuggestionOut(**suggestion.__dict__)
                for suggestion in by_account[row.account_id].get(row.isin, [])
            ],
        )
        for row in rows
    ]
```

Поправить импорт: `from app.accounts.labels import UNKNOWN_ACCOUNT_LABEL, account_label` — `account_label_by_id` здесь больше не нужен. Проверить, не остался ли он единственным потребителем этой функции: если да, функцию не удалять — её зовёт `routes_sync.py` (прогон синхронизации может не иметь счёта вовсе). Убедиться `rg -n "account_label_by_id" backend/app`.

- [ ] **Step 4: Своя `Response` на каждый вызов в тесте баннера**

В `frontend/src/components/ReconciliationBanner.test.tsx` заменить все пять вхождений `mockResolvedValue(jsonResponse(...))` на `mockImplementation(() => Promise.resolve(jsonResponse(...)))`.

Дописать комментарий над первым из них:

```tsx
    // Своя Response на каждый вызов: тело читается один раз, и общий объект
    // делал вторую и последующие проверки бессмысленными — например, проверку
    // «успешная отмена обновляет данные».
```

Проверить, что после этого проходит и тест отмены: `queryClient.invalidateQueries()` делает повторный запрос, и раньше он получал уже вычитанное тело.

- [ ] **Step 5: Прогнать всё затронутое**

```bash
cd backend && uv run pytest tests/test_api.py tests/test_scheduler.py -v
cd ../frontend && pnpm test
```

Ожидается: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/api/routes_portfolio.py backend/tests/test_scheduler.py frontend/src/components/ReconciliationBanner.test.tsx
git commit -m "test: своя Response на вызов в тесте баннера, покрытие синхронизации без токена"
```

---

### Task 12: Проверка на живых данных — уборка не сдвинула ни одной цифры

**Files:**
- Изменений в коде нет. Артефакт — отчёт в описании коммита и в хендоффе (задача 13).

**Interfaces:**
- Consumes: `app.valuation_check` (задача 10 его трогала).

- [ ] **Step 1: Снять сверку до пересборки контейнеров**

Убедиться, что база поднята и содержит настоящие данные владельца:

```bash
cd backend && uv run python -m app.valuation_check
```

Сохранить вывод. Ожидаемые числа — из хендоффа фазы 2b: итог наш 10 996 944,74 ₽ против 11 524 156,25 ₽ у брокера, разница −527 211,51 ₽. Точное совпадение до копейки не требуется: котировки и курсы с 10.08 изменились. Что обязано совпасть — структура: четыре счёта, три из них в пределах 0,2 %, весь остаток на «Инвестиционном».

- [ ] **Step 2: Применить миграцию и пересобрать контейнеры**

```bash
docker compose up -d --build backend frontend
```

Бэкенд применяет миграции сам при старте. Убедиться, что `0018` применилась:

```bash
cd backend && uv run alembic current
```

Ожидается: `0018 (head)`.

- [ ] **Step 3: Прогнать синхронизацию и сверку заново**

```bash
curl -X POST http://localhost:8001/api/sync/tbank
cd backend && uv run python -m app.valuation_check
```

- [ ] **Step 4: Сверить два вывода**

Сравнить построчно. Обязано совпасть:

- набор счетов и их подписи;
- количество расхождений на «Инвестиционном» — девять;
- доля расхождения по каждому счёту, с точностью до дрейфа котировок.

Если что-то разошлось качественно (появился счёт, изменилось число расхождений, счёт съехал за 1 %) — **остановиться**: это не дрейф котировок, а последствие уборки. Разбираться через `superpowers:systematic-debugging`, а не подгонять.

- [ ] **Step 5: Проверить новый счётчик**

```bash
docker compose exec db psql -U jarvis -d jarvis -c "select id, broker, status, inserted, skipped, corrected, mismatches from sync_run order by id desc limit 6;"
```

Имя пользователя и базы взять из `docker-compose.yml`, если отличаются. Ожидается: колонка `corrected` существует и заполнена (скорее всего нулями — брокер задним числом ничего не переписывал, см. хендофф 2b).

- [ ] **Step 6: Полный прогон тестов**

```bash
cd backend && uv run pytest
cd ../frontend && pnpm test && pnpm build
```

Ожидается: бэкенд — не меньше 439 тестов, все зелёные; фронтенд — все зелёные, сборка без ошибок типов.

- [ ] **Step 7: Коммит отчёта не нужен — переходим к задаче 13**

Вывод обеих сверок сохранить: он идёт в хендофф.

---

### Task 13: Роадмеп и хендофф

**Files:**
- Modify: `docs/roadmap.md` (раздел «Попутный долг», статус фазы 2b в таблице, раздел «Где мы сейчас»)
- Create: `docs/handoff/2026-08-11-cleanup-handoff.md`

**Interfaces:**
- Consumes: результаты задачи 12.

- [ ] **Step 1: Сократить список попутного долга в роадмепе**

В `docs/roadmap.md`, раздел «Попутный долг», **удалить** пункты, закрытые этой работой:

- `frozen=True` у `RawOperation` (задача 10);
- трижды вызванный `lots.get` и докстринг `fold` про «sells» (закрылись сами, задача 3 спеки);
- `page.get("items", [])` (задача 10);
- дубли ISIN во входном списке брокера и позиции без ISIN (первое закрылось само, второе — задача 9);
- пункт «Прямые SQL-запросы в обработчиках истории и расхождений вместо сервисного слоя; N+1 при построении подписей счетов в расхождениях» — заменить целиком на, без второй половины (она закрыта задачей 11):

```markdown
- Прямые SQL-запросы в обработчиках истории и расхождений вместо сервисного
  слоя. Оба обработчика сами строят `select(...)` по моделям, тогда как
  остальные ходят через `app/analytics` и `app/accounts`. Не чинилось уборкой:
  вынос в сервисный слой — это выбор границы слоя, а не правка.
```
- нет отдельного теста на задачу синхронизации при пустом токене (задача 11);
- `snapshot_by_account` не вызывается из production-кода (задача 5);
- `app.valuation_check` перебирает только счета из `by_account` (задача 10).

**Оставить** с записанной причиной: `secid = "T"`, подпись счёта без брокера, дозаполнение справочника без FIGI. К каждому дописать, почему он остаётся, — по формулировкам из раздела 5 спеки.

- [ ] **Step 2: Добавить в роадмеп раздел про долг фазы 2b**

После раздела «2b. Журнал без белых пятен» добавить подраздел:

```markdown
### Уборка попутного долга — завершена 11.08.2026

**Зачем.** Долг копился три фазы и в каждом хендоффе переписывался заново.
Фаза 2c трогает снимки, курсы и оценку — тот же код, где жила половина
пунктов.

**Что вошло.** Правило «ограничена в обороте» сведено в одну функцию вместо
трёх копий. Поиск переписанных брокером операций — один запрос на батч вместо
запроса на операцию. Счётчик корректирующих записей доехал до записи прогона и
до контракта. Разбивка снимка по счетам — до `/portfolio/history`.
Себестоимость заводится с экрана. Валюта записей решения берётся из бумаги.
Дата события считается по Москве, направление поправки — из статуса
расхождения. Позиция без ISIN оставляет след в логе. Закреплена предпосылка
`signed_quantity`.

**Что осознанно не вошло** — [дизайн уборки](superpowers/specs/2026-08-11-cleanup-debt-design.md),
раздел 5: пересмотр механизма решений целиком, полная пересборка позиций после
решения, плывущая цена при доисполнении.

**Признак готовности достигнут.** Сверка с брокером после уборки совпала со
снятой до неё по структуре: те же счета, те же девять расхождений, тот же
порядок величин.
```

- [ ] **Step 3: Поправить статус фазы 2b в таблице**

В таблице «Статус» строка `2b. Журнал без белых пятен | следующая` устарела ещё в прошлой сессии — фаза завершена и слита в `main`. Заменить на `завершена 10.08.2026, механизм проверен на живых данных`. Добавить строку `Уборка попутного долга | завершена 11.08.2026`.

- [ ] **Step 4: Обновить «Где мы сейчас»**

Заменить таблицу сверки на снятую в задаче 12 и дописать дату обновления в шапке раздела. Пункт «График стоимости пуст» оставить — он про фазу 2c и в силе.

- [ ] **Step 5: Написать хендофф**

Создать `docs/handoff/2026-08-11-cleanup-handoff.md` по образцу
`docs/handoff/2026-08-10-phase-2b-handoff.md`: где мы, что сделано, что
установлено на живых данных, что осталось в долге и почему, что делать дальше
(разбор девяти расхождений — работа владельца; фаза 2c — следующая по
роадмепу). Самодостаточный: рабочие артефакты в `.superpowers/` не
версионируются.

Обязательно перенести в него: вывод обеих сверок из задачи 12; правило из
задачи 1 («правило, записанное трижды, разъезжается — в этом проекте уже
разъезжалось»); то, что предпосылка `signed_quantity` теперь закреплена тестом
на маппере, и что новый производитель `RawOperation` (фаза 6, другие брокеры)
обязан ей соответствовать.

- [ ] **Step 6: Коммит**

```bash
git add docs/roadmap.md docs/handoff/2026-08-11-cleanup-handoff.md
git commit -m "docs: роадмеп и хендофф после уборки попутного долга"
```

---

## Проверка перед слиянием

- [ ] `cd backend && uv run pytest` — зелёный, тестов не меньше 439.
- [ ] `cd frontend && pnpm test` — зелёный.
- [ ] `cd frontend && pnpm build` — без ошибок типов.
- [ ] `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` — миграция `0018` откатывается и накатывается.
- [ ] Сверка на живых данных совпадает по структуре со снятой до уборки (задача 12).
- [ ] `rg -n "_restricted_from|_find_changed" backend/app` — старых имён с прежними сигнатурами не осталось там, где они не задумывались.
