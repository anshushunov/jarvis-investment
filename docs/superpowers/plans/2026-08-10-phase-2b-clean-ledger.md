# Фаза 2b «Журнал без белых пятен» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Количества бумаг в журнале сходятся с брокером: система сама читает
переводы бумаг, а корпоративные действия и всё прочее закрываются
зафиксированными решениями владельца.

**Architecture:** Решения владельца живут в новой таблице `ledger_decision` и
**порождают** записи журнала с `source='manual'`. Движок позиций по-прежнему
читает ровно один вход — журнал; он учится переносить открытые партии из старой
бумаги в новую, не теряя дат открытия. Гипотезы конвертации не хранятся, а
пересчитываются из сверки. `op_type` переезжает со `String(24)` на нативный enum
PostgreSQL.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16,
pytest на настоящей базе; React 19 + TypeScript + Vite, Vitest.

Спека: [`../specs/2026-08-10-phase-2b-design.md`](../specs/2026-08-10-phase-2b-design.md).
Хендофф предыдущей фазы: [`../../handoff/2026-08-10-phase-2a-handoff.md`](../../handoff/2026-08-10-phase-2a-handoff.md).

## Global Constraints

- Все денежные величины — `Decimal` через `app.money.money()` / `quantity()`,
  нигде не `float`. `money()` квантует до 4 знаков, `quantity()` — до 8.
- Базовая валюта — `app.money.BASE_CURRENCY` (`"RUB"`).
- Комментарии, докстринги, сообщения об ошибках и коммиты — по-русски.
  Авторство LLM в коммитах не указывается.
- Тесты запускаются на настоящем PostgreSQL: `cd backend && uv run pytest`.
  `uv` лежит в `C:\Users\User\.local\bin` и не в PATH —
  `export PATH="$PATH:/c/Users/User/.local/bin"`.
- База разработки — `localhost:5433`, бэкенд — `8001`, фронтенд — `3000`.
  Порты 5432 и 8000 заняты посторонними контейнерами, их не трогать.
- Проверка типа операции, читаемой из БД, покрывается тестом, поднимающим
  данные из базы. До Task 1 `Transaction.op_type` хранится как `String(24)` и
  после чтения это `str`; после Task 1 — `OperationType`. Правило остаётся в
  силе и после перехода: именно оно и проверяет, что переход состоялся.
- Журнал операций append-only: `UPDATE` и `DELETE` по `transaction` запрещены
  триггером БД. Исправления вносятся только новыми записями.
- `POST /api/sync/tbank` ходит в живой счёт владельца. Запускать только по
  явному согласию; читающие вызовы брокера (`GetPortfolio`, `GetPositions`) —
  свободно, они ничего не меняют.
- Фронтенд собирается без ошибок типов: `cd frontend && pnpm build`.
- Ветка работы — `feature/phase-2b`, ответвлена от `main` (`bd68dd8`).

## Что установлено разведкой живой базы 10.08.2026

Проверено на настоящих данных владельца, заново выяснять не нужно.

- Все двенадцать расхождений — на счёте «Инвестиционный».
- **РусАгро `RU000A0JQUZ6`**: журнал 209, брокер 560, разница ровно 351. В
  журнале лежит операция с `payload.operation_type =
  'OPERATION_TYPE_INPUT_SECURITIES'` от 19.12.2024, `quantity = 351`, записанная
  как `OperationType.OTHER`. `OTHER` движок не считает движением количества —
  отсюда расхождение. Это единственная такая операция в журнале.
- **`HK0000310034` (iShares Core MSCI Asia ex Japan) 79 в журнале ↔
  `HK0000051877` 79 у брокера** — пара с точно равным количеством.
- **`HK0000123577` 92 и `HK0000051877` 79 заблокированы у брокера целиком**
  (`blocked == quantity`) и **не имеют записи в `instrument`**:
  `broker_holding.instrument_id IS NULL` у обеих.
- Прочие расхождения пар не образуют: Икс 5 вырос на 45 при излишке ГДР 5;
  ТКС Холдинг 40 против роста Т-Технологий на 1012; Kyndryl −2 и NVIDIA −3 —
  отрицательные остатки (следы шортов), Meituan — на 1 штуку.
- Распределение `op_type` в журнале: `FEE` 4846, `BUY` 4714, `SELL` 983,
  `DEPOSIT` 901, `COUPON` 148, `OTHER` 121, `DIVIDEND` 94, `TAX` 72,
  `WITHDRAWAL` 23, `REDEMPTION` 2, `AMORTIZATION` 1. Значений вне
  `OperationType` в базе нет — миграция на enum не встретит неожиданных строк.
- Внутри `OTHER` живут: `OUT_STAMP_DUTY` 65, `BOND_TAX` 24, `TAX_CORRECTION` 17,
  `WRITING_OFF_VARMARGIN` 7, `ACCRUING_VARMARGIN` 2, `BENEFIT_TAX` 2,
  `OUT_MULTI` 1, `OVERNIGHT` 1, `INP_MULTI` 1, `INPUT_SECURITIES` 1. Ни одна,
  кроме `INPUT_SECURITIES`, количество не двигает (`quantity = 0` у всех).
- `TinkoffConnector.fetch_positions` уже резолвит `BrokerInstrument` по FIGI и
  выбрасывает всё, кроме ISIN и тикера.

## Структура файлов

Создаются:

| Файл | Ответственность |
|---|---|
| `backend/app/models/ledger_decision.py` | таблица решений владельца по расхождениям |
| `backend/app/decisions/__init__.py` | пакет решений |
| `backend/app/decisions/service.py` | запись решения, порождение записей журнала, отмена |
| `backend/app/decisions/suggestions.py` | построение гипотез конвертации из сверки |
| `backend/app/api/routes_decisions.py` | REST-контур решений |
| `backend/alembic/versions/0015_operation_type_enum.py` | enum-тип для `op_type` |
| `backend/alembic/versions/0016_ledger_decision.py` | таблица решений |
| `backend/alembic/versions/0017_position_cost_basis_known.py` | признак известной себестоимости |
| `backend/tests/test_operation_type_enum.py` | тип операции читается из БД как enum |
| `backend/tests/test_transfers.py` | ввод и вывод бумаг |
| `backend/tests/test_conversion.py` | перенос партий при конвертации |
| `backend/tests/test_decisions_service.py` | запись и отмена решения |
| `backend/tests/test_suggestions.py` | гипотезы конвертации |
| `backend/tests/test_corrections.py` | корректирующая запись при изменённой операции |
| `backend/tests/test_holdings_instruments.py` | заведение бумаги из снимка брокера |
| `frontend/src/components/DecisionPanel.tsx` | панель разбора расхождения |
| `frontend/src/components/DecisionPanel.test.tsx` | первые компонентные тесты проекта |

Изменяются:

| Файл | Что меняется |
|---|---|
| `backend/app/models/transaction.py` | пять новых значений `OperationType`, enum-колонка |
| `backend/app/models/position.py` | колонка `cost_basis_known` |
| `backend/app/models/__init__.py` | экспорт `LedgerDecision` |
| `backend/app/connectors/tbank/mapper.py` | `INPUT_SECURITIES` / `OUTPUT_SECURITIES` в `TYPE_MAP` |
| `backend/app/connectors/base.py` | `BrokerPosition.reference` |
| `backend/app/connectors/tbank/connector.py` | перенос `BrokerInstrument` в `BrokerPosition` |
| `backend/app/sync/holdings.py` | заведение недостающего инструмента из снимка |
| `backend/app/positions/engine.py` | перенос партий, `cost_known`, `link_id`, порядок |
| `backend/app/positions/service.py` | чтение `link_id` из payload, запись `cost_basis_known` |
| `backend/app/ledger/service.py` | различение дубля и изменённой операции |
| `backend/app/sync/reconcile.py` | сверка из `broker_holding` вместо аргумента |
| `backend/app/analytics/service.py` | `average_price` и доходность при неизвестной себестоимости |
| `backend/app/api/schemas.py` | `average_price: Decimal \| None`, `suggestion`, схемы решений |
| `backend/app/api/routes_portfolio.py` | `suggestion` в строке расхождения |
| `backend/app/main.py` | подключение роутера решений |
| `frontend/src/api/client.ts` | `average_price: string \| null`, `suggestion`, вызовы решений |
| `frontend/src/components/ReconciliationBanner.tsx` | кнопка «Разобрать» и панель |
| `frontend/package.json`, `vite.config.ts` | окружение для компонентных тестов |
| `docs/roadmap.md` | статус 2b, выделение 2c |

---

### Task 1: Enum-столбец для `op_type`

Первой задачей, потому что все следующие добавляют значения `OperationType`, и
делать это дважды (в строке, потом в enum) — лишняя работа. Заодно снимается
класс ошибок, из-за которого `entry.op_type is OperationType.REDEMPTION` молча
возвращало ложь.

**Files:**
- Modify: `backend/app/models/transaction.py:12-24` (значения), `:44` (колонка)
- Modify: `backend/app/positions/engine.py:166-172`
- Create: `backend/alembic/versions/0015_operation_type_enum.py`
- Create: `backend/tests/test_operation_type_enum.py`

**Interfaces:**
- Produces: `OperationType.TRANSFER_IN`, `TRANSFER_OUT`, `CONVERSION_OUT`,
  `CONVERSION_IN`, `ADJUSTMENT` — значения enum, строки совпадают с именами.
  `Transaction.op_type` после чтения из БД — экземпляр `OperationType`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_operation_type_enum.py`:

```python
"""Тип операции, прочитанный из базы, — это OperationType, а не строка.

Тест на объекте, собранном в памяти, ничего не доказывал бы: там тип и так
тот, что положили. Значение обязано пройти через настоящий PostgreSQL —
именно на этом пути `is` молча возвращал ложь, пока колонка была String(24),
и погашение облигаций переставало закрывать позицию.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import Account, OperationType, Transaction


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Тест", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_op_type_read_from_db_is_enum_not_string(session):
    account = _account(session)
    session.add(Transaction(
        account_id=account.id, op_type=OperationType.REDEMPTION,
        executed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000"),
        currency="RUB", fee=Decimal("0"), source="tbank", dedup_key="k-1",
    ))
    session.flush()
    session.expire_all()

    loaded = session.execute(select(Transaction)).scalar_one()

    assert loaded.op_type is OperationType.REDEMPTION


def test_all_new_operation_types_survive_a_round_trip(session):
    account = _account(session)
    new_types = [
        OperationType.TRANSFER_IN, OperationType.TRANSFER_OUT,
        OperationType.CONVERSION_OUT, OperationType.CONVERSION_IN,
        OperationType.ADJUSTMENT,
    ]
    for index, op_type in enumerate(new_types):
        session.add(Transaction(
            account_id=account.id, op_type=op_type,
            executed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            quantity=Decimal("1"), price=Decimal("0"), amount=Decimal("0"),
            currency="RUB", fee=Decimal("0"), source="manual",
            dedup_key=f"k-new-{index}",
        ))
    session.flush()
    session.expire_all()

    loaded = session.execute(
        select(Transaction).where(Transaction.source == "manual")
        .order_by(Transaction.dedup_key)
    ).scalars().all()

    assert [tx.op_type for tx in loaded] == new_types
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_operation_type_enum.py -v`
Expected: FAIL — `AttributeError: TRANSFER_IN` (значения ещё нет) и
`assert loaded.op_type is OperationType.REDEMPTION` не выполняется, потому что
из базы приходит `str`.

- [ ] **Step 3: Добавить значения и enum-колонку**

В `backend/app/models/transaction.py` дописать в `OperationType` после
`VARIATION_MARGIN`:

```python
    # Ввод и вывод бумаг: перевод от другого брокера или между счетами.
    # Количество двигают, себестоимости не несут — брокер её не сообщает.
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    # Две стороны корпоративного действия. Порождаются только решением
    # владельца (app/decisions/service.py) и связаны через payload.decision_id:
    # OUT снимает открытые партии, IN раскладывает их на новую бумагу.
    CONVERSION_OUT = "CONVERSION_OUT"
    CONVERSION_IN = "CONVERSION_IN"
    # Ручная поправка количества и корректировка операции, изменённой брокером
    # задним числом. Журнал append-only — правок нет, есть только новые записи.
    ADJUSTMENT = "ADJUSTMENT"
```

Заменить объявление колонки (`transaction.py:44`):

```python
    # Нативный enum PostgreSQL, а не String(24): из строковой колонки значение
    # приходило как str, и `entry.op_type is OperationType.REDEMPTION` молча
    # возвращало ложь — погашение облигаций не закрывало позицию, а юнит-тест
    # на объекте из памяти при этом проходил.
    op_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
```

Добавить `Enum` в импорт из `sqlalchemy` в первой строке импортов файла и
убрать `String` оттуда **нельзя** — он ещё используется колонками `currency`,
`external_id`, `source`, `dedup_key`.

В `backend/app/positions/engine.py:166-172` убрать обходной комментарий и
вернуть `is`:

```python
        if entry.quantity == 0:
            if entry.op_type is OperationType.REDEMPTION:
                _close_whole_position(lots, touched, realized, entry)
            continue
```

- [ ] **Step 4: Написать миграцию**

Создать `backend/alembic/versions/0015_operation_type_enum.py`:

```python
"""тип операции — нативный enum вместо строки

Revision ID: 0015
Revises: 0014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Порядок значений тот же, что в app/models/transaction.py: SQLAlchemy сверяет
# состав типа, а не порядок, но расхождение в списке ловится
# test_full_chain_upgrades_matches_models_and_downgrades.
OPERATION_TYPES = (
    'BUY', 'SELL', 'DIVIDEND', 'COUPON', 'FEE', 'TAX', 'DEPOSIT', 'WITHDRAWAL',
    'REDEMPTION', 'AMORTIZATION', 'VARIATION_MARGIN', 'OTHER',
    'TRANSFER_IN', 'TRANSFER_OUT', 'CONVERSION_OUT', 'CONVERSION_IN', 'ADJUSTMENT',
)


def upgrade() -> None:
    operation_type = sa.Enum(*OPERATION_TYPES, name='operation_type')
    operation_type.create(op.get_bind())
    # USING обязателен: PostgreSQL не приводит varchar к enum неявно. Значения
    # в живой базе проверены — все семнадцать входят в тип, посторонних строк
    # в transaction.op_type нет.
    op.execute(
        'ALTER TABLE transaction ALTER COLUMN op_type '
        'TYPE operation_type USING op_type::operation_type'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE transaction ALTER COLUMN op_type '
        'TYPE VARCHAR(24) USING op_type::text'
    )
    sa.Enum(name='operation_type').drop(op.get_bind())
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_operation_type_enum.py tests/test_migrations.py tests/test_positions_engine.py -v`
Expected: PASS. `test_full_chain_upgrades_matches_models_and_downgrades`
проверит, что модель и миграция совпали.

- [ ] **Step 6: Прогнать весь набор**

Run: `cd backend && uv run pytest`
Expected: PASS, 349 тестов плюс два новых. Если падает что-то, сравнивающее
`op_type` со строкой, — это и есть цель задачи; такие сравнения заменить на
сравнение с членом `OperationType`.

- [ ] **Step 7: Применить миграцию к рабочей базе**

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade 0014 -> 0015`.

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models/transaction.py backend/app/positions/engine.py \
        backend/alembic/versions/0015_operation_type_enum.py \
        backend/tests/test_operation_type_enum.py
git commit -m "refactor: перевести op_type на нативный enum и завести типы фазы 2b"
```

---

### Task 2: Переводы бумаг

Закрывает расхождение по РусАгро без участия владельца.

**Files:**
- Modify: `backend/app/connectors/tbank/mapper.py:13-34`
- Modify: `backend/app/positions/engine.py:9-10` (множества), `:153-219` (свёртка)
- Create: `backend/tests/test_transfers.py`

**Interfaces:**
- Consumes: `OperationType.TRANSFER_IN`, `TRANSFER_OUT` из Task 1.
- Produces: `OpenLot.cost_known: bool` (по умолчанию `True`),
  `PositionState.cost_basis_known: bool`.

- [ ] **Step 1: Проверить написание типа операции на живом ответе**

Ввод бумаг в базе есть (`OPERATION_TYPE_INPUT_SECURITIES`), вывода нет —
написание надо подтвердить, иначе операция молча уйдёт в `OTHER`.

Run:
```bash
cd backend && uv run python -c "
from app.config import settings
from app.connectors.tbank.client import TinkoffClient
c = TinkoffClient(settings.tbank_token)
import json
print(json.dumps(sorted({o['type'] for a in c.get_accounts() for o in c.get_operations(a['id'], '2020-01-01T00:00:00Z')}), indent=1))
"
```
Записать полученный список в комментарий к `TYPE_MAP`. Если
`OPERATION_TYPE_OUTPUT_SECURITIES` в нём нет — маппинг всё равно добавить (тип
описан в документации T-Invest API), но пометить комментарием, что на живых
данных владельца он не встречался.

- [ ] **Step 2: Написать падающий тест**

Создать `backend/tests/test_transfers.py`:

```python
"""Ввод и вывод бумаг: количество двигают, себестоимости не несут.

Живой случай, ради которого это делается: 19.12.2024 на счёт «Инвестиционный»
пришли 351 бумага РусАгро операцией OPERATION_TYPE_INPUT_SECURITIES. Она
попадала в OperationType.OTHER, движок её не считал движением количества, и
сверка показывала 209 против 560 у брокера.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.tbank.mapper import map_operation
from app.models import OperationType
from app.positions.engine import LedgerEntry, fold


def _entry(op_type: OperationType, quantity: str, price: str = "0",
           day: int = 1) -> LedgerEntry:
    return LedgerEntry(
        op_type=op_type,
        executed_at=datetime(2026, 1, day, tzinfo=timezone.utc),
        instrument_id=1,
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal("0"),
        fee=Decimal("0"),
    )


def test_input_securities_maps_to_transfer_in():
    operation = {
        "id": "1", "state": "OPERATION_STATE_EXECUTED",
        "type": "OPERATION_TYPE_INPUT_SECURITIES",
        "date": "2024-12-19T10:00:00Z", "quantityDone": "351",
        "payment": {"currency": "rub", "units": "0", "nano": 0},
    }

    result = map_operation(operation, None)

    assert result.op_type is OperationType.TRANSFER_IN
    assert result.quantity == Decimal("351")


def test_transfer_in_increases_quantity_with_unknown_cost():
    result = fold([_entry(OperationType.TRANSFER_IN, "351")])

    position = result.positions[1]
    assert position.quantity == Decimal("351")
    assert position.cost_basis_known is False


def test_transfer_in_alongside_purchase_marks_whole_position_unknown():
    result = fold([
        _entry(OperationType.BUY, "209", price="100", day=1),
        _entry(OperationType.TRANSFER_IN, "351", day=2),
    ])

    position = result.positions[1]
    assert position.quantity == Decimal("560")
    assert position.cost_basis_known is False


def test_transfer_out_reduces_quantity_without_realized_sale():
    result = fold([
        _entry(OperationType.BUY, "100", price="50", day=1),
        _entry(OperationType.TRANSFER_OUT, "40", day=2),
    ])

    assert result.positions[1].quantity == Decimal("60")
    assert result.realized == []
    # Себестоимость оставшихся не поехала: вывод не трогает цену партии.
    assert result.positions[1].average_price == Decimal("50")


def test_purchase_only_position_keeps_cost_known():
    result = fold([_entry(OperationType.BUY, "10", price="7")])

    assert result.positions[1].cost_basis_known is True
```

- [ ] **Step 3: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_transfers.py -v`
Expected: FAIL — `TRANSFER_IN` не в `TYPE_MAP`, у `PositionState` нет
`cost_basis_known`.

- [ ] **Step 4: Дописать маппинг**

В `backend/app/connectors/tbank/mapper.py` в `TYPE_MAP` после
`"OPERATION_TYPE_BOND_AMORTIZATION"`:

```python
    # Перевод бумаг: приходят и уходят количеством, себестоимости брокер при
    # этом не сообщает. Живой случай — 351 бумага РусАгро 19.12.2024, которая
    # уходила в OTHER и не двигала позицию: сверка показывала 209 против 560.
    "OPERATION_TYPE_INPUT_SECURITIES": OperationType.TRANSFER_IN,
    "OPERATION_TYPE_OUTPUT_SECURITIES": OperationType.TRANSFER_OUT,
```

- [ ] **Step 5: Научить движок переводам**

В `backend/app/positions/engine.py` заменить множества в начале файла:

```python
INCREASING = {OperationType.BUY, OperationType.TRANSFER_IN}
DECREASING = {OperationType.SELL, OperationType.REDEMPTION, OperationType.TRANSFER_OUT}

# Операции, которые двигают количество, но не создают закрытой сделки: перевод
# бумаги наружу — не продажа, выручки у него нет. Считать его продажей значило
# бы выдумать финансовый результат и испортить налоговую базу.
WITHOUT_REALIZED = {OperationType.TRANSFER_OUT}

# Операции, приносящие количество без себестоимости: брокер её при переводе не
# сообщает, а выдумывать нельзя.
WITHOUT_COST = {OperationType.TRANSFER_IN}
```

Добавить поле в `OpenLot` (после `quantity_left`):

```python
    # Известна ли себестоимость партии. Ложь у партии, пришедшей переводом:
    # цена там ноль не потому, что бумага досталась даром, а потому, что
    # брокер себестоимости не прислал.
    cost_known: bool = True
```

Добавить поле в `PositionState` (после `average_price`):

```python
    # Истина, когда себестоимость известна по всем партиям. Ложь — средняя цена
    # и доходность по позиции не показываются вовсе: усреднение с нулём даёт
    # правдоподобное, но неверное число, которое владелец примет за настоящее.
    cost_basis_known: bool = True
```

В цикле `fold`, там где открывается новая партия (`if remaining > 0:`),
передать признак:

```python
        if remaining > 0:
            open_lots.append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=unit_price,
                    quantity_left=q(direction * remaining),
                    cost_known=entry.op_type not in WITHOUT_COST,
                )
            )
```

В цикле закрытия встречных партий пропустить создание `RealizedSale` для
операций без финансового результата — обернуть `realized.append(...)`:

```python
            if entry.op_type not in WITHOUT_REALIZED:
                realized.append(
                    RealizedSale(
                        instrument_id=entry.instrument_id,
                        sold_at=entry.executed_at,
                        quantity=taken,
                        proceeds=money(taken * proceeds),
                        cost=money(taken * cost),
                        opened_at=lot.opened_at,
                    )
                )
```

В сборке результата заполнить признак:

```python
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
```

- [ ] **Step 6: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_transfers.py tests/test_positions_engine.py tests/test_tbank_mapper.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/connectors/tbank/mapper.py backend/app/positions/engine.py \
        backend/tests/test_transfers.py
git commit -m "feat: учитывать ввод и вывод бумаг как движение количества"
```

---

### Task 3: Признак неизвестной себестоимости до экрана

Движок уже помечает позицию; теперь признак доезжает до таблицы позиций, и
средняя с доходностью перестают врать.

**Files:**
- Modify: `backend/app/models/position.py`
- Modify: `backend/app/positions/service.py:26-49`
- Modify: `backend/app/analytics/service.py:39-78` (`PositionRow`), `:154-212`
- Modify: `backend/app/api/schemas.py:44-88`
- Create: `backend/alembic/versions/0017_position_cost_basis_known.py`
- Modify: `frontend/src/api/client.ts:34-63`
- Modify: `frontend/src/components/PositionsTable.tsx:136-141`
- Modify: `backend/tests/test_transfers.py` (дописать)

Номер миграции `0017` намеренно: `0016` занимает таблица решений из Task 4,
которая пишется раньше по номеру, но позже по порядку задач. Если Task 4 ещё не
сделан, `down_revision` временно указывает на `'0015'` — поправить на `'0016'`
при слиянии задач в ветку. Чтобы этого избежать, **делать Task 4 до Task 3**
допустимо: они независимы.

**Interfaces:**
- Consumes: `PositionState.cost_basis_known` из Task 2.
- Produces: `Position.cost_basis_known: bool`,
  `PositionRow.cost_basis_known: bool`, `PositionOut.average_price: Decimal | None`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_transfers.py`:

```python
def test_position_row_hides_average_and_profit_when_cost_unknown(session):
    """Позиция, куда бумаги пришли переводом, не показывает ни среднюю, ни
    доходность: себестоимости у неё нет, а ноль в этом месте читается как
    «досталось даром» и завышает доходность до бесконечности."""
    from datetime import date

    from app.analytics.service import position_rows
    from app.models import Account, Instrument, Position, Price

    account = Account(broker="tbank", kind="broker", external_id="acc-2",
                      name="Инвестиционный", currency="RUB")
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            kind="share", currency="RUB", issuer="РусАгро")
    session.add_all([account, instrument])
    session.flush()

    session.add(Position(account_id=account.id, instrument_id=instrument.id,
                         quantity=Decimal("560"), average_price=Decimal("0"),
                         cost_basis_known=False))
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 8, 10),
                      close=Decimal("200"), currency="RUB", source="moex"))
    session.flush()

    row = next(r for r in position_rows(session) if r.isin == "RU000A0JQUZ6")

    assert row.cost_basis_known is False
    assert row.average_price is None
    assert row.profit is None
    assert row.profit_percent is None
    # Стоимость при этом известна: цена есть, неизвестна только себестоимость.
    assert row.market_value == Decimal("112000.0000")
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_transfers.py::test_position_row_hides_average_and_profit_when_cost_unknown -v`
Expected: FAIL — `TypeError: 'cost_basis_known' is an invalid keyword argument for Position`.

- [ ] **Step 3: Добавить колонку и миграцию**

В `backend/app/models/position.py` дописать после `average_price`:

```python
    # Известна ли себестоимость всех партий позиции. Ложь у позиции, куда
    # бумаги пришли переводом: брокер себестоимости при переводе не сообщает.
    # По такой позиции не показываются ни средняя цена, ни доходность.
    cost_basis_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Добавить `Boolean` в импорт из `sqlalchemy` в этом файле.

Создать `backend/alembic/versions/0017_position_cost_basis_known.py`:

```python
"""признак известной себестоимости у позиции

Revision ID: 0017
Revises: 0016

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # По умолчанию известна: до появления переводов все позиции собирались
    # только из сделок, у которых цена есть всегда. Пересборка позиций после
    # синхронизации проставит признак заново по журналу.
    op.add_column('position', sa.Column('cost_basis_known', sa.Boolean(), nullable=False,
                                        server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('position', 'cost_basis_known')
```

- [ ] **Step 4: Протащить признак через пересборку и аналитику**

В `backend/app/positions/service.py` в создании `Position` добавить поле:

```python
            Position(
                account_id=account.id,
                instrument_id=instrument_id,
                quantity=state.quantity,
                average_price=state.average_price,
                cost_basis_known=state.cost_basis_known,
            )
```

В `backend/app/analytics/service.py` в `PositionRow` заменить объявление
средней цены и дописать признак:

```python
    # None — себестоимость неизвестна: бумаги пришли переводом, брокер цены не
    # сообщил. Это не ноль и не «бесплатно»: показывать тут число нечестно.
    average_price: Decimal | None
    # Ложь — по позиции нет ни средней, ни доходности. Причина отличается от
    # «нет котировки»: там неизвестна текущая цена, здесь — цена покупки.
    cost_basis_known: bool
```

В `position_rows` заменить блок расчёта доходности:

```python
        if not position.cost_basis_known:
            # Себестоимости нет вовсе — считать не из чего. Отдельная ветка до
            # проверки котировки: причина умолчания другая, и на экране она
            # называется своими словами.
            profit = None
            percent = None
        elif valued.value is None or price_currency != reference_currency:
```

и в сборке `PositionRow`:

```python
                average_price=position.average_price if position.cost_basis_known else None,
                cost_basis_known=position.cost_basis_known,
```

- [ ] **Step 5: Обновить контракт API**

В `backend/app/api/schemas.py` в `PositionOut` заменить строку
`average_price: Decimal` на:

```python
    # None — себестоимость неизвестна (бумаги пришли переводом). Сериализуется
    # как null и на экране даёт прочерк, а не ноль.
    average_price: Decimal | None
    cost_basis_known: bool
```

`serialize_money` уже перечисляет `average_price` и уже умеет `None` — менять
его не нужно.

- [ ] **Step 6: Обновить фронтенд**

В `frontend/src/api/client.ts` в `PositionRow`:

```typescript
  // null = себестоимость неизвестна: бумаги пришли переводом, брокер цены
  // покупки не сообщил. Это не ноль — на экране прочерк.
  average_price: string | null;
  cost_basis_known: boolean;
```

В `frontend/src/components/PositionsTable.tsx` заменить ячейку средней цены:

```tsx
              {/* Средняя подписывается своей валютой, а не валютой котировки:
                  у замещающей облигации журнал знает рубли, а MOEX котирует её
                  в долларах, и рублёвое число под знаком доллара завышало
                  цифру в восемьдесят раз. Пустая средняя (бумаги пришли
                  переводом) даёт прочерк с подсказкой — formatMoney уже умеет
                  null, но молчаливый прочерк не объясняет причину. */}
              <td title={row.cost_basis_known ? undefined
                  : "Себестоимость неизвестна: бумаги пришли переводом"}>
                {formatMoney(row.average_price, row.average_price_currency)}
              </td>
```

- [ ] **Step 7: Прогнать тесты и сборку**

Run: `cd backend && uv run pytest tests/test_transfers.py tests/test_analytics.py tests/test_api.py tests/test_migrations.py -v`
Expected: PASS.

Run: `cd frontend && pnpm build`
Expected: сборка без ошибок типов.

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models/position.py backend/app/positions/service.py \
        backend/app/analytics/service.py backend/app/api/schemas.py \
        backend/alembic/versions/0017_position_cost_basis_known.py \
        backend/tests/test_transfers.py \
        frontend/src/api/client.ts frontend/src/components/PositionsTable.tsx
git commit -m "feat: не показывать среднюю и доходность при неизвестной себестоимости"
```

---

### Task 4: Таблица решений владельца

**Files:**
- Create: `backend/app/models/ledger_decision.py`
- Create: `backend/alembic/versions/0016_ledger_decision.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_decisions_service.py` (только модельная часть)

**Interfaces:**
- Produces: `LedgerDecision` с полями `id`, `account_id`, `kind`, `status`,
  `from_instrument_id`, `from_quantity`, `to_instrument_id`, `to_quantity`,
  `cost_basis`, `effective_at`, `note`, `proposed`, `reverts_id`, `created_at`.
  Константы `DecisionKind.CONVERSION | ADJUSTMENT | ACCEPTED_AS_IS`,
  `DecisionStatus.CONFIRMED | REJECTED | REVERTED`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_decisions_service.py`:

```python
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
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_decisions_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'LedgerDecision'`.

- [ ] **Step 3: Написать модель**

Создать `backend/app/models/ledger_decision.py`:

```python
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DecisionKind(StrEnum):
    # Корпоративное действие: одна бумага превратилась в другую.
    CONVERSION = "CONVERSION"
    # Ручная поправка количества, когда пары нет и владелец знает причину.
    ADJUSTMENT = "ADJUSTMENT"
    # Расхождение остаётся, но объяснено и больше не требует внимания.
    ACCEPTED_AS_IS = "ACCEPTED_AS_IS"


class DecisionStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    # Гипотеза отклонена владельцем. Записей журнала не порождает; нужна
    # только чтобы не предлагать её снова после каждой синхронизации.
    REJECTED = "REJECTED"
    # Решение отменено более поздним (см. reverts_id у отменяющего).
    REVERTED = "REVERTED"


class LedgerDecision(Base):
    """Решение владельца по расхождению журнала со снимком брокера.

    Хранятся только принятые решения. Гипотезы конвертации в базу не пишутся —
    они пересчитываются из таблицы reconciliation при каждом запросе
    (app/decisions/suggestions.py). Отклонённая гипотеза оставляет здесь строку
    со статусом REJECTED: это единственный способ не предлагать её заново после
    каждой синхронизации.

    Подтверждённое решение порождает записи в журнале операций с
    source='manual' и payload.decision_id, указывающим сюда. Отмена решения
    ничего не удаляет: журнал append-only, поэтому создаётся новое решение с
    reverts_id, порождающее зеркальные записи.
    """

    __tablename__ = "ledger_decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    kind: Mapped[DecisionKind] = mapped_column(
        Enum(DecisionKind, name="decision_kind", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
    from_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    from_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    to_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    to_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # Себестоимость, если владелец её знает: у перевода извне брокер её не
    # сообщает, но владелец мог посмотреть отчёт прежнего брокера.
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    # Дата самого события, а не дата решения: конвертация случилась когда-то в
    # прошлом, и порождённые записи должны встать в журнал на своё место.
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Пояснение обязательно у любого вида решения. Через год «почему тут 1012»
    # не восстановит никто, а решение продолжит влиять на налоговую базу.
    note: Mapped[str] = mapped_column(Text, nullable=False)
    # На чём система построила гипотезу: чтобы решение можно было перечитать и
    # понять, что видел владелец в момент подтверждения.
    proposed: Mapped[dict] = mapped_column(JSONB, default=dict)
    reverts_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_decision.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

В `backend/app/models/__init__.py` добавить импорт и запись в `__all__`:

```python
from app.models.ledger_decision import DecisionKind, DecisionStatus, LedgerDecision
```

В `__all__` вставить `"DecisionKind"`, `"DecisionStatus"`, `"LedgerDecision"`
по алфавиту (после `"DailySnapshot"` и перед `"FxRate"`).

- [ ] **Step 4: Написать миграцию**

Создать `backend/alembic/versions/0016_ledger_decision.py`:

```python
"""решения владельца по расхождениям журнала с брокером

Revision ID: 0016
Revises: 0015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ledger_decision',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Enum('CONVERSION', 'ADJUSTMENT', 'ACCEPTED_AS_IS',
                                  name='decision_kind'), nullable=False),
        sa.Column('status', sa.Enum('CONFIRMED', 'REJECTED', 'REVERTED',
                                    name='decision_status'), nullable=False),
        sa.Column('from_instrument_id', sa.Integer(), nullable=True),
        sa.Column('from_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('to_instrument_id', sa.Integer(), nullable=True),
        sa.Column('to_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('cost_basis', sa.Numeric(20, 4), nullable=True),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('proposed', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reverts_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['from_instrument_id'], ['instrument.id']),
        sa.ForeignKeyConstraint(['to_instrument_id'], ['instrument.id']),
        sa.ForeignKeyConstraint(['reverts_id'], ['ledger_decision.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ledger_decision_account_id'), 'ledger_decision',
                    ['account_id'])


def downgrade() -> None:
    # Откат уносит решения владельца, а вместе с ними — объяснение записям
    # журнала, которые они породили. Сами записи остаются (журнал append-only,
    # DELETE по нему запрещён триггером), но станут безотцовщиной: понять,
    # откуда взялась конвертация на 1012 бумаг, будет уже не из чего.
    # Отказываемся, как это делает 0011 при конфликте ключа.
    orphans = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM transaction WHERE source = 'manual'"
    )).scalar_one()
    if orphans:
        raise RuntimeError(
            f"Откат миграции 0016 невозможен: в журнале {orphans} записей с "
            "source='manual', порождённых решениями владельца. Журнал "
            "append-only, удалить их нельзя, а без таблицы решений они "
            "останутся без объяснения. Отмените решения через "
            "POST /api/decisions/{id}/revert, либо снимите ограничение "
            "осознанно, отредактировав миграцию."
        )

    op.drop_index(op.f('ix_ledger_decision_account_id'), table_name='ledger_decision')
    op.drop_table('ledger_decision')
    sa.Enum(name='decision_status').drop(op.get_bind())
    sa.Enum(name='decision_kind').drop(op.get_bind())
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_decisions_service.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 6: Написать тест на отказ отката**

Дописать в `backend/tests/test_migrations.py`:

```python
def test_0016_downgrade_refuses_when_manual_entries_exist(migrations_engine):
    """Записи, порождённые решениями владельца, переживают удаление таблицы
    решений (журнал append-only, DELETE запрещён триггером) и остаются без
    объяснения. Откат обязан отказаться понятным сообщением, а не молча
    оставить безотцовщину."""
    with migrations_engine.connect() as connection:
        config = _alembic_config(connection)

        command.upgrade(config, "0016")
        connection.commit()

        connection.execute(text(
            "INSERT INTO account (broker, kind, external_id, name, currency) "
            "VALUES ('tbank', 'broker', 'acc-1', 'Инвестиционный', 'RUB')"
        ))
        connection.execute(text("""
            INSERT INTO transaction (account_id, op_type, executed_at, quantity,
                                     price, amount, currency, fee, source, dedup_key, payload)
            SELECT id, 'CONVERSION_IN', TIMESTAMPTZ '2026-03-01 00:00:00+00', 79,
                   0, 0, 'RUB', 0, 'manual', 'manual-1', '{}'::jsonb
            FROM account WHERE external_id = 'acc-1'
        """))
        connection.commit()

        with pytest.raises(RuntimeError, match="Откат миграции 0016 невозможен"):
            command.downgrade(config, "base")

        connection.rollback()

        # Триггер append-only запрещает DELETE по журналу, поэтому чистим
        # схему целиком, а не строку: база в фикстуре общая для модуля.
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.commit()
```

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 7: Применить миграции к рабочей базе**

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade 0015 -> 0016`, затем `0016 -> 0017`, если Task 3 уже
сделан.

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models/ledger_decision.py backend/app/models/__init__.py \
        backend/alembic/versions/0016_ledger_decision.py \
        backend/tests/test_decisions_service.py backend/tests/test_migrations.py
git commit -m "feat: таблица решений владельца по расхождениям"
```

---

### Task 5: Заведение бумаги-получателя из снимка брокера

Без этого конвертацию некуда зачислять: у `HK0000051877` и `HK0000123577` нет
записи в `instrument`.

**Files:**
- Modify: `backend/app/connectors/base.py:21-31`
- Modify: `backend/app/connectors/tbank/connector.py:185-210`
- Modify: `backend/app/sync/holdings.py:10-63`
- Create: `backend/tests/test_holdings_instruments.py`

**Interfaces:**
- Consumes: `BrokerInstrument` из `app/connectors/base.py` (уже есть),
  `apply_reference`, `secid_from_ticker` из `app/instruments/service.py`.
- Produces: `BrokerPosition.reference: BrokerInstrument | None`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_holdings_instruments.py`:

```python
"""Бумага, которой нет в справочнике, заводится из снимка брокера.

Живой случай: HK0000051877 (79 штук) и HK0000123577 (92 штуки) лежат у брокера,
но в instrument их нет — в журнале по ним нет ни одной операции, а справочник
заполняется из операций. В расхождениях они показаны безымянными, и
конвертации их не во что зачислять.

Заводить по ISIN «на глазок» нельзя: одному ISIN в справочнике брокера
соответствует запись на каждый режим торгов, с разными флагами и валютой. В
фазе 2a обе наивные стратегии дали ошибки на миллионы. Здесь этой проблемы нет
по построению: коннектор уже разрешил инструмент по FIGI позиции, остаётся
донести результат до записи снимка.
"""

from decimal import Decimal

from sqlalchemy import select

from app.connectors.base import BrokerInstrument, BrokerPosition
from app.models import Account, BrokerHolding, Instrument
from app.sync.holdings import store_holdings


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_unknown_isin_gets_an_instrument_from_the_snapshot(session):
    account = _account(session)

    store_holdings(session, account, [BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("79"),
        reference=BrokerInstrument(
            isin="HK0000051877", ticker="3690", kind="share",
            name="Meituan Class B", currency="HKD",
            buy_available=False, sell_available=False,
        ),
    )])

    instrument = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalar_one()
    assert instrument.kind == "share"
    assert instrument.currency == "HKD"
    assert instrument.issuer == "Meituan Class B"
    assert instrument.trading_restricted is True

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.instrument_id == instrument.id


def test_second_snapshot_does_not_duplicate_and_refreshes_reference(session):
    account = _account(session)
    position = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("79"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Class B",
                                   currency="HKD", buy_available=False,
                                   sell_available=False),
    )
    store_holdings(session, account, [position])

    store_holdings(session, account, [BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("0"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Class B",
                                   currency="HKD", buy_available=True,
                                   sell_available=True),
    )])

    instruments = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalars().all()
    assert len(instruments) == 1
    # Разблокировка — такое же сообщение справочника, как и блокировка.
    assert instruments[0].trading_restricted is False


def test_position_without_reference_still_stores_holding(session):
    """Брокер, который справочных сведений не даёт, не должен ронять снимок:
    строка обязана сохраниться, просто без связи с инструментом."""
    account = _account(session)

    store_holdings(session, account, [BrokerPosition(
        isin="XX0000000001", ticker=None, quantity=Decimal("5"),
        blocked=Decimal("0"),
    )])

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.isin == "XX0000000001"
    assert holding.instrument_id is None
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_holdings_instruments.py -v`
Expected: FAIL — `TypeError: BrokerPosition.__init__() got an unexpected keyword argument 'reference'`.

- [ ] **Step 3: Расширить `BrokerPosition`**

В `backend/app/connectors/base.py` дописать в `BrokerPosition` после `blocked`:

```python
    # Справочные сведения о бумаге, уже разрешённые коннектором по FIGI этой
    # позиции. Нужны для бумаги, которой нет в нашем справочнике: она попала к
    # брокеру помимо журнала (конвертация, перевод), и завести её больше не из
    # чего. Разрешение по FIGI обязательно: одному ISIN в справочнике брокера
    # соответствует запись на каждый режим торгов, с разными флагами и валютой,
    # и выбор «на глазок» в фазе 2a дал ошибки на миллионы.
    # None — брокер справочных сведений не даёт.
    reference: "BrokerInstrument | None" = None
```

`BrokerInstrument` объявлен ниже по файлу, поэтому аннотация строкой. Если
`from __future__ import annotations` в файле уже есть — кавычки не нужны;
проверить первую строку файла.

- [ ] **Step 4: Донести справочник до позиции в коннекторе**

В `backend/app/connectors/tbank/connector.py` в `fetch_positions` заменить
создание `BrokerPosition`:

```python
            positions.append(BrokerPosition(
                isin=instrument.isin, ticker=ticker, quantity=qty,
                blocked=blocked_by_figi.get(figi, quantity("0")),
                # Тот же BrokerInstrument, что уже разрешён по FIGI выше:
                # у бумаги, которой нет в нашем справочнике, это единственный
                # источник вида, валюты и названия.
                reference=instrument,
            ))
```

- [ ] **Step 5: Заводить инструмент при записи снимка**

В `backend/app/sync/holdings.py` заменить импорты и блок разрешения
идентификаторов:

```python
from app.instruments import kinds
from app.instruments.service import apply_reference, secid_from_ticker
from app.models import Account, BrokerHolding, Instrument
```

При слиянии двух записей одного ISIN сохранять справочные сведения — в блоке
`merged[item.isin] = BrokerPosition(...)` дописать:

```python
                reference=existing.reference or item.reference,
```

Заменить блок `instrument_ids = {...}` на:

```python
    instruments = {
        instrument.isin: instrument
        for instrument in session.execute(
            select(Instrument).where(Instrument.isin.in_(merged.keys()))
        ).scalars()
    }

    for item in merged.values():
        instrument = instruments.get(item.isin)
        if instrument is None and item.reference is not None:
            # Бумага есть у брокера, но не в нашем справочнике: она попала на
            # счёт помимо журнала — конвертацией или переводом. Так лежат
            # HK0000051877 и HK0000123577, обе заблокированы целиком, и обе
            # безымянны в расхождениях. Заводим из справочных сведений,
            # разрешённых коннектором по FIGI позиции.
            instrument = Instrument(
                isin=item.isin,
                ticker=item.reference.ticker or item.ticker,
                secid=secid_from_ticker(item.reference.ticker or item.ticker),
                kind=item.reference.kind or kinds.OTHER,
                currency=(item.reference.currency or "RUB").upper(),
                issuer=item.reference.name,
                trading_restricted=_restricted_from(item.reference),
            )
            session.add(instrument)
            session.flush()
            instruments[item.isin] = instrument
        elif instrument is not None and item.reference is not None:
            # Уже известную бумагу справочник тоже освежает: разблокировка —
            # такое же сообщение брокера, как и блокировка.
            apply_reference(
                instrument,
                item.reference.kind,
                item.reference.name,
                (item.reference.currency or "").upper() or None,
                _restricted_from(item.reference),
            )

        session.add(BrokerHolding(
            account_id=account.id,
            instrument_id=instrument.id if instrument is not None else None,
            isin=item.isin,
            quantity=item.quantity,
            blocked=item.blocked,
        ))
```

Дописать в конец файла:

```python
def _restricted_from(reference) -> bool | None:
    """Ограничена ли бумага в обороте по справочным сведениям снимка.

    Правило то же, что в app/instruments/service.py: ограничением считается
    недоступность обеих операций сразу. Один флаг ничего не решает — выпуск,
    закрытый для покупки, но открытый для продажи, распоряжению поддаётся.
    Хотя бы один флаг отсутствует — сведений нет, возвращаем None.
    """
    buy, sell = reference.buy_available, reference.sell_available
    if not isinstance(buy, bool) or not isinstance(sell, bool):
        return None
    return not buy and not sell
```

При создании нового инструмента `trading_restricted` — колонка NOT NULL, а
`_restricted_from` может вернуть `None`; в конструкторе выше это надо привести:
заменить `trading_restricted=_restricted_from(item.reference)` на
`trading_restricted=bool(_restricted_from(item.reference))`.

- [ ] **Step 6: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_holdings_instruments.py tests/test_broker_holding.py tests/test_tbank_connector.py tests/test_sync_service.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/connectors/base.py backend/app/connectors/tbank/connector.py \
        backend/app/sync/holdings.py backend/tests/test_holdings_instruments.py
git commit -m "feat: заводить бумагу из снимка брокера, если её нет в справочнике"
```

---

### Task 6: Перенос партий при конвертации

**Files:**
- Modify: `backend/app/positions/engine.py`
- Modify: `backend/app/positions/service.py:8-23`
- Create: `backend/tests/test_conversion.py`

**Interfaces:**
- Consumes: `OperationType.CONVERSION_OUT`, `CONVERSION_IN` из Task 1;
  `OpenLot.cost_known`, `PositionState.cost_basis_known` из Task 2.
- Produces: `LedgerEntry.link_id: int | None`; исключение
  `ConversionError` из `app.positions.engine`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_conversion.py`:

```python
"""Конвертация переносит открытые партии, не теряя дат открытия.

Дата важна не для красоты: трёхлетняя льгота по НДФЛ считается от неё, и
свернуть партии в одну на дату события значит сжечь льготу. Суммарная
себестоимость при переносе сохраняется, а цена пересчитывается на новое
количество.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import OperationType
from app.positions.engine import ConversionError, LedgerEntry, fold

OLD, NEW = 1, 2
WHEN = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _buy(instrument_id: int, quantity: str, price: str, day: int) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.BUY,
        executed_at=datetime(2024, 1, day, tzinfo=timezone.utc),
        instrument_id=instrument_id, quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal("0"), fee=Decimal("0"),
    )


def _out(quantity: str, link_id: int = 7) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
        instrument_id=OLD, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id,
    )


def _in(quantity: str, link_id: int = 7) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_IN, executed_at=WHEN,
        instrument_id=NEW, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id,
    )


def test_one_to_one_conversion_keeps_lots_and_dates():
    """Живой случай: 79 iShares HK0000310034 → 79 HK0000051877."""
    result = fold([
        _buy(OLD, "40", "100", day=10),
        _buy(OLD, "39", "150", day=20),
        _out("79"), _in("79"),
    ])

    assert OLD not in result.positions or result.positions[OLD].quantity == 0
    new = result.positions[NEW]
    assert new.quantity == Decimal("79")
    assert len(new.lots) == 2
    # Даты открытия обеих партий переехали как есть.
    assert [lot.opened_at.day for lot in new.lots] == [10, 20]
    # Цены при один-к-одному не изменились.
    assert [lot.price for lot in new.lots] == [Decimal("100"), Decimal("150")]
    # Конвертация не создаёт закрытой сделки: финансового результата нет.
    assert result.realized == []


def test_conversion_preserves_total_cost_when_quantity_changes():
    """40 бумаг по 1000 превращаются в 1012 — суммарная себестоимость та же."""
    result = fold([_buy(OLD, "40", "1000", day=5), _out("40"), _in("1012")])

    new = result.positions[NEW]
    assert new.quantity == Decimal("1012")
    total_cost = sum(lot.quantity_left * lot.price for lot in new.lots)
    assert total_cost == Decimal("40000")
    assert new.lots[0].opened_at.day == 5


def test_partial_conversion_leaves_the_rest_in_place():
    result = fold([_buy(OLD, "100", "10", day=1), _out("40"), _in("40")])

    assert result.positions[OLD].quantity == Decimal("60")
    assert result.positions[NEW].quantity == Decimal("40")


def test_conversion_in_without_out_is_an_error():
    """Пустой карман — порча данных. Молча открыть партию с нулевой ценой
    значит подарить владельцу выдуманную доходность в сотни процентов."""
    with pytest.raises(ConversionError, match="CONVERSION_IN"):
        fold([_in("79")])


def test_conversion_out_beyond_available_quantity_is_an_error():
    with pytest.raises(ConversionError, match="больше, чем открыто"):
        fold([_buy(OLD, "10", "100", day=1), _out("79"), _in("79")])


def test_unknown_cost_survives_the_conversion():
    result = fold([
        LedgerEntry(op_type=OperationType.TRANSFER_IN,
                    executed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    instrument_id=OLD, quantity=Decimal("50"),
                    price=Decimal("0"), amount=Decimal("0"), fee=Decimal("0")),
        _out("50"), _in("50"),
    ])

    assert result.positions[NEW].cost_basis_known is False


def test_two_conversions_at_the_same_instant_do_not_mix():
    """Два решения на одну дату различаются по link_id: карманы не общие."""
    result = fold([
        _buy(OLD, "10", "100", day=1),
        _buy(3, "20", "5", day=2),
        _out("10", link_id=1), _in("10", link_id=1),
        LedgerEntry(op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
                    instrument_id=3, quantity=Decimal("20"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0"), link_id=2),
        LedgerEntry(op_type=OperationType.CONVERSION_IN, executed_at=WHEN,
                    instrument_id=4, quantity=Decimal("20"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0"), link_id=2),
    ])

    assert result.positions[NEW].lots[0].price == Decimal("100")
    assert result.positions[4].lots[0].price == Decimal("5")
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_conversion.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConversionError'`.

- [ ] **Step 3: Реализовать перенос партий**

В `backend/app/positions/engine.py` дописать после множеств:

```python
# Стороны конвертации. В INCREASING/DECREASING они не входят: их обработка
# отдельная — количество не открывает и не закрывает партии по цене операции,
# а переносит уже существующие партии из одной бумаги в другую.
CONVERSION = {OperationType.CONVERSION_OUT, OperationType.CONVERSION_IN}


class ConversionError(RuntimeError):
    """Стороны конвертации не сошлись. Это порча данных, а не редкий случай:
    молча открыть партию с нулевой ценой значит подарить владельцу выдуманную
    доходность и неверную налоговую базу."""
```

Дописать поле в `LedgerEntry` (после `fee`):

```python
    # Идентификатор решения владельца, связывающий две стороны конвертации
    # (payload.decision_id порождённых записей). None у всего остального.
    link_id: int | None = None
```

Заменить `sort_key` в `fold`:

```python
    # Порядок внутри одного мгновения. Покупка раньше продажи — чтобы не
    # возникало мнимого разворота позиции. CONVERSION_OUT строго раньше
    # CONVERSION_IN: иначе карман пуст и себестоимость теряется. IN идёт
    # последним, потому что снятые партии должны быть уже в кармане.
    def sort_key(entry):
        if entry.op_type in INCREASING:
            priority = 0
        elif entry.op_type is OperationType.CONVERSION_OUT:
            priority = 2
        elif entry.op_type is OperationType.CONVERSION_IN:
            priority = 3
        else:
            priority = 1
        return (entry.executed_at, priority)
```

Завести карман перед циклом, рядом с `lots`:

```python
    # Партии, снятые CONVERSION_OUT и ждущие своего CONVERSION_IN. Ключ —
    # link_id решения: два разных корпоративных действия одной датой не должны
    # черпать из общего кармана.
    pockets: dict[int, list[OpenLot]] = {}
```

Вставить обработку конвертации в цикле сразу после проверки
`if entry.instrument_id is None: continue`:

```python
        if entry.op_type in CONVERSION:
            _apply_conversion(lots, pockets, touched, entry)
            continue
```

Дописать функцию переноса рядом с `_close_whole_position`:

```python
def _apply_conversion(
    lots: dict[int, list[OpenLot]],
    pockets: dict[int, list[OpenLot]],
    touched: set[int],
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
    for lot in taken_lots:
        # Доля партии в новом количестве та же, что была в старом; цена
        # меняется обратно пропорционально, поэтому себестоимость партии
        # (количество × цена) остаётся прежней.
        share = q(lot.quantity_left * new_quantity / old_quantity)
        open_lots.append(OpenLot(
            instrument_id=entry.instrument_id,
            opened_at=lot.opened_at,
            price=money(lot.quantity_left * lot.price / share) if share else money("0"),
            quantity_left=share,
            cost_known=lot.cost_known,
        ))
    touched.add(entry.instrument_id)
```

После цикла по записям, перед сборкой `positions`, проверить, что карманы
пусты:

```python
    if pockets:
        raise ConversionError(
            f"Партии, снятые конвертациями {sorted(pockets)}, остались "
            "невостребованными: у них нет парного CONVERSION_IN. Бумаги "
            "исчезли бы из портфеля бесследно."
        )
```

- [ ] **Step 4: Научить движок ручной корректировке**

`ADJUSTMENT` порождается и решением владельца (Task 7), и изменённой операцией
брокера (Task 9). В `INCREASING`/`DECREASING` его положить нельзя: направление у
него задаётся **знаком количества**, а не типом — в отличие от покупки и
продажи, где знак всегда один и тот же.

В `backend/app/positions/engine.py` дописать в множество операций без
реализованного результата:

```python
WITHOUT_REALIZED = {OperationType.TRANSFER_OUT, OperationType.ADJUSTMENT}
```

В цикле `fold`, сразу после ветки конвертации, вставить:

```python
        if entry.op_type is OperationType.ADJUSTMENT:
            # Направление по знаку количества: поправка бывает в обе стороны, и
            # тип операции у них общий. Нулевая поправка (брокер изменил только
            # сумму) количество не трогает вовсе.
            if entry.quantity == 0:
                continue
            direction = 1 if entry.quantity > 0 else -1
        elif entry.op_type in INCREASING:
            direction = 1
        elif entry.op_type in DECREASING:
            direction = -1
        else:
            continue
```

— то есть заменить существующую цепочку `if/elif/else` определения
`direction`, поставив ветку `ADJUSTMENT` первой.

Ниже, где считается `remaining`, взять модуль количества: у отрицательной
поправки `entry.quantity` меньше нуля, а `remaining` в цикле FIFO обязан быть
положительным.

```python
        remaining = q(abs(entry.quantity))
```

Себестоимость положительной поправки берётся из цены записи: `record_decision`
кладёт туда `cost_basis / to_quantity`, а при неизвестной себестоимости — ноль.
Ноль в цене поправки означает ровно «неизвестно», поэтому дописать
`ADJUSTMENT` в `WITHOUT_COST` **нельзя** — иначе поправка с указанной
владельцем себестоимостью тоже помечалась бы неизвестной. Признак ставится по
цене:

```python
        if remaining > 0:
            open_lots.append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=unit_price,
                    quantity_left=q(direction * remaining),
                    cost_known=(
                        unit_price != 0
                        if entry.op_type is OperationType.ADJUSTMENT
                        else entry.op_type not in WITHOUT_COST
                    ),
                )
            )
```

Дописать в `backend/tests/test_conversion.py`:

```python
def test_adjustment_adds_quantity_with_unknown_cost():
    entry = LedgerEntry(
        op_type=OperationType.ADJUSTMENT, executed_at=WHEN, instrument_id=OLD,
        quantity=Decimal("1012"), price=Decimal("0"), amount=Decimal("0"),
        fee=Decimal("0"),
    )

    result = fold([entry])

    assert result.positions[OLD].quantity == Decimal("1012")
    assert result.positions[OLD].cost_basis_known is False
    assert result.realized == []


def test_adjustment_with_price_keeps_cost_known():
    entry = LedgerEntry(
        op_type=OperationType.ADJUSTMENT, executed_at=WHEN, instrument_id=OLD,
        quantity=Decimal("10"), price=Decimal("250"), amount=Decimal("0"),
        fee=Decimal("0"),
    )

    result = fold([entry])

    assert result.positions[OLD].cost_basis_known is True
    assert result.positions[OLD].average_price == Decimal("250")


def test_negative_adjustment_closes_lots_without_realized_sale():
    result = fold([
        _buy(OLD, "10", "100", day=1),
        LedgerEntry(op_type=OperationType.ADJUSTMENT, executed_at=WHEN,
                    instrument_id=OLD, quantity=Decimal("-2"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0")),
    ])

    assert result.positions[OLD].quantity == Decimal("8")
    assert result.realized == []
```

- [ ] **Step 5: Прочитать `link_id` из журнала**

В `backend/app/positions/service.py` в `_entries` дописать поле:

```python
        LedgerEntry(
            op_type=tx.op_type,
            executed_at=tx.executed_at,
            instrument_id=tx.instrument_id,
            quantity=tx.quantity,
            price=tx.price,
            amount=tx.amount,
            fee=tx.fee,
            # Идентификатор решения владельца: связывает две стороны
            # конвертации. Лежит в payload, потому что колонка ради доли
            # процента записей журнала не окупается.
            link_id=(tx.payload or {}).get("decision_id"),
        )
```

- [ ] **Step 6: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_conversion.py tests/test_positions_engine.py tests/test_positions_service.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/positions/engine.py backend/app/positions/service.py \
        backend/tests/test_conversion.py
git commit -m "feat: переносить партии при конвертации и учитывать ручную поправку"
```

---

### Task 7: Запись и отмена решения

**Files:**
- Create: `backend/app/decisions/__init__.py`
- Create: `backend/app/decisions/service.py`
- Modify: `backend/app/sync/reconcile.py`
- Modify: `backend/tests/test_decisions_service.py` (дописать)

**Interfaces:**
- Consumes: `LedgerDecision`, `DecisionKind`, `DecisionStatus` из Task 4;
  движок конвертации из Task 6.
- Produces:
  - `record_decision(session, decision: LedgerDecision) -> LedgerDecision`
  - `revert_decision(session, decision_id: int, note: str) -> LedgerDecision`
  - `rebuild_after_decision(session, account: Account) -> None`
  - `reconcile_from_snapshot(session, account) -> list[Reconciliation]` в
    `app/sync/reconcile.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_decisions_service.py`:

```python
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
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_decisions_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.decisions'`.

- [ ] **Step 3: Сверка из сохранённого снимка**

В `backend/app/sync/reconcile.py` дописать после `reconcile_account`:

```python
def reconcile_from_snapshot(session: Session, account: Account) -> list[Reconciliation]:
    """Пересчитывает сверку по уже сохранённому снимку брокера.

    Нужна после решения владельца: подтверждение конвертации меняет позиции, и
    расхождения обязаны пересчитаться сразу. Ходить за этим к брокеру незачем —
    снимок лежит в broker_holding с прошлой синхронизации, а частота запросов у
    T-Invest API ограничена.
    """
    holdings = session.execute(
        select(BrokerHolding).where(BrokerHolding.account_id == account.id)
    ).scalars().all()
    return reconcile_account(session, account, [
        BrokerPosition(isin=holding.isin, ticker=None,
                       quantity=holding.quantity, blocked=holding.blocked)
        for holding in holdings
    ])
```

Добавить `BrokerHolding` в импорт моделей в этом файле.

- [ ] **Step 4: Написать службу решений**

Создать `backend/app/decisions/__init__.py` пустым файлом.

Создать `backend/app/decisions/service.py`:

```python
"""Решения владельца по расхождениям журнала со снимком брокера.

Решение хранится в ledger_decision и **порождает** записи журнала — движок
позиций по-прежнему читает ровно один вход. Отмена ничего не удаляет: журнал
append-only, поэтому создаётся зеркальное решение с reverts_id.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    LedgerDecision,
    OperationType,
    Transaction,
)
from app.models.ledger_decision import DecisionKind, DecisionStatus
from app.money import money, quantity as q
from app.positions.service import rebuild_positions
from app.sync.reconcile import reconcile_from_snapshot

SOURCE = "manual"


class DecisionError(ValueError):
    """Решение не описывает того, что обещает его вид."""


def _validate(decision: LedgerDecision) -> None:
    if not (decision.note or "").strip():
        raise DecisionError("Пояснение обязательно: через год причину решения не восстановит никто.")

    has_from = decision.from_instrument_id is not None and decision.from_quantity is not None
    has_to = decision.to_instrument_id is not None and decision.to_quantity is not None

    if decision.kind is DecisionKind.CONVERSION and not (has_from and has_to):
        raise DecisionError(
            "Конвертация описывается обеими сторонами: из какой бумаги и в какую, "
            "с количествами."
        )
    if decision.kind is DecisionKind.ADJUSTMENT and has_from == has_to:
        raise DecisionError(
            "Корректировка описывает ровно одну сторону: либо списание, либо зачисление."
        )
    if decision.kind is DecisionKind.ACCEPTED_AS_IS and (has_from or has_to):
        raise DecisionError(
            "«Принято как есть» ничего не двигает — бумаги и количества у такого "
            "решения быть не должно."
        )


def _dedup_key(decision_id: int, leg: str) -> str:
    return hashlib.sha256(f"{SOURCE}|{decision_id}|{leg}".encode()).hexdigest()


def _entry(
    decision: LedgerDecision, leg: str, op_type: OperationType,
    instrument_id: int, quantity, price,
) -> Transaction:
    return Transaction(
        account_id=decision.account_id,
        instrument_id=instrument_id,
        op_type=op_type,
        executed_at=decision.effective_at,
        quantity=q(quantity),
        price=money(price),
        amount=money("0"),
        currency="RUB",
        fee=money("0"),
        external_id=f"decision:{decision.id}:{leg}",
        source=SOURCE,
        dedup_key=_dedup_key(decision.id, leg),
        # decision_id связывает две стороны конвертации: движок достаёт его в
        # LedgerEntry.link_id (app/positions/service.py).
        payload={"decision_id": decision.id},
    )


def _generate_entries(session: Session, decision: LedgerDecision) -> None:
    """Записи журнала, порождённые подтверждённым решением.

    Отклонённое решение и «принято как есть» не порождают ничего: первое —
    потому что владелец сказал «нет», второе — потому что расхождение
    остаётся, оно лишь объяснено.
    """
    if decision.status is not DecisionStatus.CONFIRMED:
        return

    if decision.kind is DecisionKind.CONVERSION:
        session.add(_entry(decision, "out", OperationType.CONVERSION_OUT,
                           decision.from_instrument_id, decision.from_quantity, "0"))
        session.add(_entry(decision, "in", OperationType.CONVERSION_IN,
                           decision.to_instrument_id, decision.to_quantity, "0"))
    elif decision.kind is DecisionKind.ADJUSTMENT:
        if decision.to_instrument_id is not None:
            # Себестоимость известна — цена на бумагу; нет — ноль, и партия
            # пометится неизвестной (WITHOUT_COST в движке этого не сделает,
            # поэтому цена ноль здесь означает ровно «неизвестно»).
            price = (money(decision.cost_basis / decision.to_quantity)
                     if decision.cost_basis is not None and decision.to_quantity
                     else money("0"))
            session.add(_entry(decision, "in", OperationType.ADJUSTMENT,
                               decision.to_instrument_id, decision.to_quantity, price))
        else:
            session.add(_entry(decision, "out", OperationType.ADJUSTMENT,
                               decision.from_instrument_id, -decision.from_quantity, "0"))

    session.flush()


def rebuild_after_decision(session: Session, account: Account) -> None:
    """Пересобирает позиции и сверку счёта после изменения журнала."""
    rebuild_positions(session, account)
    reconcile_from_snapshot(session, account)


def record_decision(session: Session, decision: LedgerDecision) -> LedgerDecision:
    _validate(decision)
    session.add(decision)
    session.flush()

    _generate_entries(session, decision)
    rebuild_after_decision(session, session.get(Account, decision.account_id))
    return decision


def revert_decision(session: Session, decision_id: int, note: str) -> LedgerDecision:
    """Отменяет решение зеркальным.

    Ни решение, ни порождённые им записи не удаляются: журнал append-only, и
    правка задним числом стёрла бы след того, что владелец однажды решил иначе.
    """
    original = session.get(LedgerDecision, decision_id)
    if original is None:
        raise DecisionError(f"Решение {decision_id} не найдено.")
    if original.status is not DecisionStatus.CONFIRMED:
        raise DecisionError(
            f"Отменить можно только подтверждённое решение, а это — "
            f"{original.status.value}."
        )

    mirror = LedgerDecision(
        account_id=original.account_id,
        kind=original.kind,
        status=DecisionStatus.CONFIRMED,
        # Стороны меняются местами: то, что было зачислено, списывается.
        from_instrument_id=original.to_instrument_id,
        from_quantity=original.to_quantity,
        to_instrument_id=original.from_instrument_id,
        to_quantity=original.from_quantity,
        cost_basis=original.cost_basis,
        effective_at=original.effective_at,
        note=note,
        proposed={"reverts": original.id},
        reverts_id=original.id,
    )
    _validate(mirror)
    session.add(mirror)
    session.flush()

    _generate_entries(session, mirror)
    original.status = DecisionStatus.REVERTED
    session.flush()

    rebuild_after_decision(session, session.get(Account, original.account_id))
    return mirror


def decisions_for(session: Session, account_id: int | None = None) -> list[LedgerDecision]:
    statement = select(LedgerDecision).order_by(LedgerDecision.created_at.desc())
    if account_id is not None:
        statement = statement.where(LedgerDecision.account_id == account_id)
    return list(session.execute(statement).scalars())
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_decisions_service.py tests/test_reconcile.py -v`
Expected: PASS.

Если `test_revert_returns_positions_to_the_previous_state` падает на переносе
партий — проверить, что зеркальное решение подставляет `from`/`to` наоборот и
что движок конвертации из Task 6 не путает карманы: у отмены свой `link_id`
(идентификатор зеркального решения).

- [ ] **Step 6: Коммит**

```bash
git add backend/app/decisions/ backend/app/sync/reconcile.py \
        backend/tests/test_decisions_service.py
git commit -m "feat: записывать и отменять решения владельца по расхождениям"
```

---

### Task 8: Гипотезы конвертации

**Files:**
- Create: `backend/app/decisions/suggestions.py`
- Create: `backend/tests/test_suggestions.py`

**Interfaces:**
- Consumes: `Reconciliation`, `BrokerHolding`, `LedgerDecision` из моделей.
- Produces: `Suggestion` (dataclass: `from_isin`, `from_quantity`, `to_isin`,
  `to_quantity`, `blocked_fully`, `ambiguous`) и
  `suggestions_for_account(session, account_id) -> dict[str, list[Suggestion]]`,
  где ключ — ISIN строки расхождения, к которой относится гипотеза.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_suggestions.py`:

```python
"""Гипотезы конвертации: пара «исчезло / появилось ровно столько же».

Величины сравниваются точно. Подгонять близкие числа нельзя: в фазе 2a
«правдоподобный» выбор записи справочника дал ошибки на миллионы, и здесь та же
цена ошибки — неверная налоговая база.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.decisions.suggestions import suggestions_for_account
from app.models import (
    Account, BrokerHolding, Instrument, LedgerDecision, Reconciliation,
)
from app.models.ledger_decision import DecisionKind, DecisionStatus


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _finding(session, account, isin, ledger, broker, status, instrument_id=None):
    session.add(Reconciliation(
        account_id=account.id, instrument_id=instrument_id, isin=isin,
        ledger_quantity=Decimal(ledger), broker_quantity=Decimal(broker),
        status=status,
    ))
    session.flush()


def test_equal_quantities_produce_a_pair(session):
    """Живая пара: 79 iShares HK0000310034 → 79 HK0000051877."""
    account = _account(session)
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker")
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger")

    result = suggestions_for_account(session, account.id)

    assert list(result) == ["HK0000310034", "HK0000051877"]
    suggestion = result["HK0000310034"][0]
    assert suggestion.from_isin == "HK0000310034"
    assert suggestion.to_isin == "HK0000051877"
    assert suggestion.from_quantity == Decimal("79")
    assert suggestion.to_quantity == Decimal("79")
    assert suggestion.ambiguous is False


def test_full_block_at_broker_is_reported(session):
    account = _account(session)
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker")
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger")
    session.add(BrokerHolding(account_id=account.id, instrument_id=None,
                              isin="HK0000051877", quantity=Decimal("79"),
                              blocked=Decimal("79")))
    session.flush()

    suggestion = suggestions_for_account(session, account.id)["HK0000310034"][0]

    assert suggestion.blocked_fully is True


def test_mismatched_quantities_produce_nothing(session):
    """Икс 5 вырос на 45, а излишек ГДР — 5. Пары нет, и выдумывать её нельзя."""
    account = _account(session)
    _finding(session, account, "US98387E2054", "45", "40", "quantity_mismatch")
    _finding(session, account, "RU000A108X38", "96", "141", "quantity_mismatch")

    assert suggestions_for_account(session, account.id) == {}


def test_negative_ledger_quantity_is_not_a_candidate(session):
    """Kyndryl −2 и NVIDIA −3 — следы шортов, конвертировать нечего."""
    account = _account(session)
    _finding(session, account, "US50155Q1004", "-2", "0", "missing_at_broker")
    _finding(session, account, "XX0000000002", "0", "2", "missing_in_ledger")

    assert suggestions_for_account(session, account.id) == {}


def test_two_candidates_with_equal_quantity_are_both_offered_as_ambiguous(session):
    account = _account(session)
    _finding(session, account, "AA0000000001", "10", "0", "missing_at_broker")
    _finding(session, account, "BB0000000001", "0", "10", "missing_in_ledger")
    _finding(session, account, "CC0000000001", "0", "10", "missing_in_ledger")

    offered = suggestions_for_account(session, account.id)["AA0000000001"]

    assert {s.to_isin for s in offered} == {"BB0000000001", "CC0000000001"}
    assert all(s.ambiguous for s in offered)


def test_rejected_pair_is_not_offered_again(session):
    account = _account(session)
    old = Instrument(isin="HK0000310034", ticker="3010", secid="3010",
                     kind="share", currency="HKD")
    new = Instrument(isin="HK0000051877", ticker="3690", secid="3690",
                     kind="share", currency="HKD")
    session.add_all([old, new])
    session.flush()
    _finding(session, account, "HK0000310034", "79", "0", "missing_at_broker", old.id)
    _finding(session, account, "HK0000051877", "0", "79", "missing_in_ledger", new.id)

    session.add(LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.REJECTED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Не связаны", proposed={},
    ))
    session.flush()

    assert suggestions_for_account(session, account.id) == {}
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_suggestions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.decisions.suggestions'`.

- [ ] **Step 3: Написать построение гипотез**

Создать `backend/app/decisions/suggestions.py`:

```python
"""Гипотезы корпоративных действий из расхождений сверки.

Источника сведений о корпоративных действиях у T-Invest API нет. Единственное,
на что можно опереться, — арифметика: из журнала пропало ровно столько же,
сколько появилось у брокера. Величины сравниваются **точно**; подгонять близкие
числа нельзя, цена ошибки — неверная налоговая база.

Гипотезы нигде не хранятся: они пересчитываются при каждом запросе. В базе
остаётся только решение владельца, и отклонённое глушит повторный показ.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrokerHolding, Instrument, LedgerDecision, Reconciliation
from app.models.ledger_decision import DecisionKind, DecisionStatus


@dataclass(frozen=True)
class Suggestion:
    from_isin: str
    from_quantity: Decimal
    to_isin: str
    to_quantity: Decimal
    # Бумага-получатель заблокирована у брокера целиком. Конвертации часто
    # оседают именно так — у живой пары это верно с обеих сторон. Признак
    # усиливающий: сам по себе гипотезу не создаёт, но показывается владельцу.
    blocked_fully: bool
    # Кандидатов с такой же величиной больше одного. Выбирать за владельца
    # нельзя: в фазе 2a «правдоподобный» выбор стоил ошибок на миллионы.
    ambiguous: bool


def _rejected_pairs(session: Session, account_id: int) -> set[tuple[str, str]]:
    """Пары ISIN, по которым владелец уже сказал «нет»."""
    rows = session.execute(
        select(Instrument.isin, LedgerDecision.to_instrument_id)
        .join(LedgerDecision, LedgerDecision.from_instrument_id == Instrument.id)
        .where(
            LedgerDecision.account_id == account_id,
            LedgerDecision.kind == DecisionKind.CONVERSION,
            LedgerDecision.status == DecisionStatus.REJECTED,
        )
    ).all()
    if not rows:
        return set()

    to_isin = {
        instrument_id: isin
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(
                Instrument.id.in_({row[1] for row in rows})
            )
        ).all()
    }
    return {(from_isin, to_isin[to_id]) for from_isin, to_id in rows if to_id in to_isin}


def _fully_blocked(session: Session, account_id: int) -> set[str]:
    return {
        isin
        for isin, quantity, blocked in session.execute(
            select(BrokerHolding.isin, BrokerHolding.quantity, BrokerHolding.blocked)
            .where(BrokerHolding.account_id == account_id)
        ).all()
        if quantity > 0 and quantity == blocked
    }


def suggestions_for_account(session: Session, account_id: int) -> dict[str, list[Suggestion]]:
    """Гипотезы по счёту, сгруппированные по ISIN строки расхождения.

    Одна гипотеза попадает в словарь дважды — под ISIN обеих сторон: владелец
    может открыть разбор с любой из двух строк, и видеть он должен одно и то же.
    """
    findings = session.execute(
        select(Reconciliation).where(Reconciliation.account_id == account_id)
    ).scalars().all()

    # Излишек в журнале — кандидат на списание. Отрицательный остаток журнала
    # в кандидаты не берётся: это след шорта, а не бумага, которой можно
    # конвертироваться.
    surplus = [
        (f.isin, f.ledger_quantity - f.broker_quantity)
        for f in findings
        if f.ledger_quantity > f.broker_quantity and f.ledger_quantity > 0
    ]
    shortage = [
        (f.isin, f.broker_quantity - f.ledger_quantity)
        for f in findings
        if f.broker_quantity > f.ledger_quantity
    ]

    rejected = _rejected_pairs(session, account_id)
    blocked = _fully_blocked(session, account_id)

    result: dict[str, list[Suggestion]] = {}
    for from_isin, from_quantity in surplus:
        matches = [
            (to_isin, to_quantity)
            for to_isin, to_quantity in shortage
            if to_quantity == from_quantity and (from_isin, to_isin) not in rejected
        ]
        if not matches:
            continue

        ambiguous = len(matches) > 1
        for to_isin, to_quantity in matches:
            suggestion = Suggestion(
                from_isin=from_isin, from_quantity=from_quantity,
                to_isin=to_isin, to_quantity=to_quantity,
                blocked_fully=to_isin in blocked,
                ambiguous=ambiguous,
            )
            result.setdefault(from_isin, []).append(suggestion)
            result.setdefault(to_isin, []).append(suggestion)

    return result
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_suggestions.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/decisions/suggestions.py backend/tests/test_suggestions.py
git commit -m "feat: предлагать гипотезу конвертации по равным количествам"
```

---

### Task 9: Корректирующая запись при изменённой операции брокера

**Files:**
- Modify: `backend/app/ledger/service.py`
- Create: `backend/tests/test_corrections.py`

**Interfaces:**
- Consumes: `OperationType.ADJUSTMENT` из Task 1.
- Produces: `AppendResult.corrected: int` — счётчик корректирующих записей.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_corrections.py`:

```python
"""Операция, изменённая брокером задним числом, даёт корректирующую запись.

До этой правки конфликт по (account_id, source, external_id) считался дублем и
молча пропускался — верно, когда содержание совпало, и неверно, когда брокер
переписал операцию. Журнал append-only, поэтому ответ — новая запись на
разницу, а не правка старой.

Частый случай доисполняющейся заявки закрыт отдельно, окном
STILL_FILLING_WINDOW в коннекторе, так что этот путь должен срабатывать редко.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.ledger.schemas import RawOperation
from app.ledger.service import append_operations
from app.models import Account, OperationType, Transaction


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _operation(quantity: str, amount: str, price: str = "100") -> RawOperation:
    return RawOperation(
        external_id="op-1", op_type="BUY",
        executed_at=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(amount), currency="RUB",
        fee=Decimal("0"), payload={},
    )


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
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_corrections.py -v`
Expected: FAIL — `AttributeError: 'AppendResult' object has no attribute 'corrected'`.

- [ ] **Step 3: Различить дубль и изменённую операцию**

В `backend/app/ledger/service.py` расширить результат:

```python
@dataclass(frozen=True)
class AppendResult:
    inserted: int
    skipped: int
    # Операции, которые брокер переписал задним числом: на разницу записана
    # корректирующая запись. Должно быть редкостью — частый случай
    # доисполняющейся заявки закрыт окном STILL_FILLING_WINDOW в коннекторе.
    # Если счётчик стабильно ненулевой, значит обход перестал работать.
    corrected: int = 0
```

Дописать поиск изменившейся операции и построение корректирующей записи:

```python
def _find_changed(
    session: Session, account: Account, source: str, op: RawOperation
) -> tuple[Transaction, Decimal, Decimal] | None:
    """Уже записанная операция с тем же внешним идентификатором, содержание
    которой разошлось с присланным, вместе с уже записанными итогами.

    Разошлось — значит брокер переписал операцию задним числом. Совпало — это
    обычный дубль пересекающегося окна синхронизации, и говорить о нём нечего.

    Итоги возвращаются отсюда, а не пересчитываются вызывающим: они уже посчитаны
    здесь, и второй такой же запрос к базе на каждую операцию батча был бы
    заметен на первой полной синхронизации счёта.
    """
    if op.external_id is None:
        return None

    existing = session.execute(
        select(Transaction).where(
            Transaction.account_id == account.id,
            Transaction.source == source,
            Transaction.external_id == op.external_id,
        ).order_by(Transaction.id)
    ).scalars().all()
    if not existing:
        return None

    # Корректирующие записи уже учтены: сравниваем с суммой всего, что по этой
    # операции записано, иначе одна и та же правка порождала бы корректировку
    # при каждой синхронизации.
    recorded_quantity = sum((tx.quantity for tx in existing), Decimal("0"))
    recorded_amount = sum((tx.amount for tx in existing), Decimal("0"))

    if recorded_quantity == op.quantity and recorded_amount == op.amount:
        return None
    return existing[0], recorded_quantity, recorded_amount


def _correction_for(
    account: Account, source: str, op: RawOperation, original: Transaction,
    recorded_quantity: Decimal, recorded_amount: Decimal,
) -> Transaction:
    """Корректирующая запись на разницу между присланным и записанным.

    Одна запись на изменившуюся операцию, а не по записи на каждое поле:
    свёртка обязана увидеть изменение целиком, иначе цена уедет отдельно от
    количества.
    """
    return Transaction(
        account_id=account.id,
        instrument_id=original.instrument_id,
        op_type=OperationType.ADJUSTMENT,
        executed_at=op.executed_at,
        quantity=op.quantity - recorded_quantity,
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
            "corrects_transaction_id": original.id,
            "corrects_external_id": original.external_id,
        },
    )
```

Импортировать `hashlib`, `Decimal`, `OperationType` и `logging` в начале файла;
завести `logger = logging.getLogger(__name__)`.

В `append_operations`, в цикле отбора, заменить ветку пропуска:

```python
    to_insert: list[tuple[RawOperation, str]] = []
    corrections: list[Transaction] = []
    skipped = 0
    seen_in_batch: set[str] = set()

    for op, key in zip(operations, keys):
        if key in known or key in seen_in_batch:
            skipped += 1
            continue
        changed = _find_changed(session, account, source, op)
        if changed is not None:
            original, recorded_quantity, recorded_amount = changed
            corrections.append(_correction_for(
                account, source, op, original, recorded_quantity, recorded_amount
            ))
            logger.warning(
                "Брокер изменил операцию %s на счёте %s: было количество %s на %s, "
                "стало %s на %s. Записана корректирующая запись.",
                op.external_id, account.external_id, recorded_quantity,
                recorded_amount, op.quantity, op.amount,
            )
            skipped += 1
            continue
        seen_in_batch.add(key)
        to_insert.append((op, key))
```

Перед обоими `return AppendResult(...)` добавить вставку корректировок и
счётчик. Заменить ранний выход:

```python
    if not to_insert and not corrections:
        return AppendResult(inserted=0, skipped=skipped)

    if corrections:
        session.add_all(corrections)
        session.flush()

    if not to_insert:
        return AppendResult(inserted=0, skipped=skipped, corrected=len(corrections))
```

и оба финальных возврата дополнить `corrected=len(corrections)`.

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_corrections.py tests/test_ledger_service.py tests/test_sync_service.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/ledger/service.py backend/tests/test_corrections.py
git commit -m "feat: писать корректирующую запись, когда брокер изменил операцию"
```

---

### Task 10: REST-контур решений

**Files:**
- Create: `backend/app/api/routes_decisions.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes_portfolio.py:100-113`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py` (дописать)

**Interfaces:**
- Consumes: `record_decision`, `revert_decision`, `decisions_for` из Task 7;
  `suggestions_for_account` из Task 8.
- Produces: `SuggestionOut`, `DecisionIn`, `DecisionOut` в
  `app/api/schemas.py`; эндпоинты `GET /api/decisions`, `POST /api/decisions`,
  `POST /api/decisions/{id}/revert`; поле `suggestions` в `ReconciliationOut`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_api.py`:

```python
def test_reconciliation_row_carries_its_suggestion(client, session):
    """Гипотеза едет вместе со строкой расхождения: интерфейс не должен
    сопоставлять два списка на своей стороне."""
    from decimal import Decimal

    from app.models import Account, Reconciliation

    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    session.add_all([
        Reconciliation(account_id=account.id, isin="HK0000310034",
                       ledger_quantity=Decimal("79"), broker_quantity=Decimal("0"),
                       status="missing_at_broker"),
        Reconciliation(account_id=account.id, isin="HK0000051877",
                       ledger_quantity=Decimal("0"), broker_quantity=Decimal("79"),
                       status="missing_in_ledger"),
    ])
    session.commit()

    rows = client.get("/api/reconciliations").json()

    by_isin = {row["isin"]: row for row in rows}
    suggestion = by_isin["HK0000310034"]["suggestions"][0]
    assert suggestion["to_isin"] == "HK0000051877"
    assert suggestion["to_quantity"] == "79.00000000"
    assert suggestion["ambiguous"] is False


def test_post_decision_records_it_and_returns_the_result(client, session):
    from decimal import Decimal

    from app.models import Account, Instrument

    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    old = Instrument(isin="HK0000310034", ticker="3010", secid="3010",
                     kind="share", currency="HKD")
    new = Instrument(isin="HK0000051877", ticker="3690", secid="3690",
                     kind="share", currency="HKD")
    session.add_all([account, old, new])
    session.commit()

    response = client.post("/api/decisions", json={
        "account": "Инвестиционный",
        "kind": "CONVERSION",
        "status": "CONFIRMED",
        "from_isin": "HK0000310034",
        "from_quantity": "79",
        "to_isin": "HK0000051877",
        "to_quantity": "79",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "Конвертация гонконгского ETF",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "CONVERSION"
    assert body["note"] == "Конвертация гонконгского ETF"

    listed = client.get("/api/decisions").json()
    assert len(listed) == 1


def test_post_decision_without_note_is_rejected(client, session):
    from app.models import Account

    session.add(Account(broker="tbank", kind="broker", external_id="acc-1",
                        name="Инвестиционный", currency="RUB"))
    session.commit()

    response = client.post("/api/decisions", json={
        "account": "Инвестиционный",
        "kind": "ACCEPTED_AS_IS",
        "status": "CONFIRMED",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "   ",
    })

    assert response.status_code == 400
    assert "Пояснение обязательно" in response.json()["detail"]
```

Фикстура `client` уже есть в `tests/test_api.py` — использовать её как есть, не
заводя вторую.

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_api.py -k "suggestion or decision" -v`
Expected: FAIL — `KeyError: 'suggestions'` и `404` на `/api/decisions`.

- [ ] **Step 3: Дописать схемы**

В `backend/app/api/schemas.py` добавить:

```python
class SuggestionOut(BaseModel):
    """Гипотеза корпоративного действия, предложенная системой.

    Едет вместе со строкой расхождения, а не отдельным списком: сопоставлять
    их на стороне интерфейса значило бы повторить там правило подбора пары.
    """

    from_isin: str
    from_quantity: Decimal
    to_isin: str
    to_quantity: Decimal
    # Бумага-получатель заблокирована у брокера целиком — усиливающий признак.
    blocked_fully: bool
    # Кандидатов с такой же величиной несколько: выбирает владелец.
    ambiguous: bool

    @field_serializer("from_quantity", "to_quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"


class DecisionIn(BaseModel):
    # Подпись счёта — та же, что показана в строке расхождения: интерфейс
    # идентификаторов счетов не видит.
    account: str
    kind: str
    status: str
    from_isin: str | None = None
    from_quantity: Decimal | None = None
    to_isin: str | None = None
    to_quantity: Decimal | None = None
    cost_basis: Decimal | None = None
    effective_at: datetime
    note: str


class DecisionOut(BaseModel):
    id: int
    account: str
    kind: str
    status: str
    from_isin: str | None
    from_quantity: Decimal | None
    to_isin: str | None
    to_quantity: Decimal | None
    effective_at: datetime
    note: str
    reverts_id: int | None

    @field_serializer("from_quantity", "to_quantity")
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.8f}"


class RevertIn(BaseModel):
    note: str
```

Добавить `datetime` в импорты этого файла, если его там ещё нет.

В `ReconciliationOut` дописать поле:

```python
    # Гипотезы конвертации по этой строке. Пусто — пары не нашлось, и
    # расхождение закрывается ручной корректировкой.
    suggestions: list[SuggestionOut] = []
```

- [ ] **Step 4: Отдать гипотезы вместе с расхождениями**

В `backend/app/api/routes_portfolio.py` заменить `get_reconciliations`:

```python
@router.get("/reconciliations", response_model=list[ReconciliationOut])
def get_reconciliations(session: Session = Depends(get_session)) -> list[ReconciliationOut]:
    rows = session.execute(select(Reconciliation).order_by(Reconciliation.isin)).scalars().all()
    # Гипотезы считаются по счёту целиком: пара ищется среди расхождений
    # одного счёта, поэтому кэшируем результат на счёт, а не запрашиваем его
    # для каждой строки.
    by_account: dict[int, dict[str, list]] = {}
    for account_id in {row.account_id for row in rows}:
        by_account[account_id] = suggestions_for_account(session, account_id)

    return [
        ReconciliationOut(
            isin=row.isin, status=row.status,
            ledger_quantity=row.ledger_quantity, broker_quantity=row.broker_quantity,
            account=account_label_by_id(session, row.account_id),
            suggestions=[
                SuggestionOut(**suggestion.__dict__)
                for suggestion in by_account[row.account_id].get(row.isin, [])
            ],
        )
        for row in rows
    ]
```

Дописать импорты `suggestions_for_account` и `SuggestionOut`.

- [ ] **Step 5: Написать роутер решений**

Создать `backend/app/api/routes_decisions.py`:

```python
"""REST-контур решений владельца по расхождениям.

Счёт и бумаги приходят подписями и ISIN, а не идентификаторами: интерфейс видит
именно их, и заставлять его знать внутренние ключи незачем.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.labels import account_label
from app.api.schemas import DecisionIn, DecisionOut, RevertIn
from app.db import get_session
from app.decisions.service import DecisionError, decisions_for, record_decision, revert_decision
from app.models import Account, Instrument, LedgerDecision
from app.models.ledger_decision import DecisionKind, DecisionStatus

router = APIRouter(prefix="/api", tags=["decisions"])


def _account_by_label(session: Session, label: str) -> Account:
    for account in session.execute(select(Account)).scalars():
        if account_label(account) == label:
            return account
    raise HTTPException(status_code=404, detail=f"Счёт «{label}» не найден")


def _instrument_id(session: Session, isin: str | None) -> int | None:
    if isin is None:
        return None
    instrument = session.execute(
        select(Instrument).where(Instrument.isin == isin)
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Бумага {isin} не найдена в справочнике. Она попадёт туда после "
                "ближайшей синхронизации — снимок брокера заводит бумаги, "
                "которых нет в журнале."
            ),
        )
    return instrument.id


def _isin(session: Session, instrument_id: int | None) -> str | None:
    if instrument_id is None:
        return None
    return session.get(Instrument, instrument_id).isin


def _to_out(session: Session, decision: LedgerDecision) -> DecisionOut:
    return DecisionOut(
        id=decision.id,
        account=account_label(session.get(Account, decision.account_id)),
        kind=decision.kind.value,
        status=decision.status.value,
        from_isin=_isin(session, decision.from_instrument_id),
        from_quantity=decision.from_quantity,
        to_isin=_isin(session, decision.to_instrument_id),
        to_quantity=decision.to_quantity,
        effective_at=decision.effective_at,
        note=decision.note,
        reverts_id=decision.reverts_id,
    )


@router.get("/decisions", response_model=list[DecisionOut])
def list_decisions(session: Session = Depends(get_session)) -> list[DecisionOut]:
    return [_to_out(session, decision) for decision in decisions_for(session)]


@router.post("/decisions", response_model=DecisionOut)
def create_decision(payload: DecisionIn, session: Session = Depends(get_session)) -> DecisionOut:
    account = _account_by_label(session, payload.account)
    try:
        decision = record_decision(session, LedgerDecision(
            account_id=account.id,
            kind=DecisionKind(payload.kind),
            status=DecisionStatus(payload.status),
            from_instrument_id=_instrument_id(session, payload.from_isin),
            from_quantity=payload.from_quantity,
            to_instrument_id=_instrument_id(session, payload.to_isin),
            to_quantity=payload.to_quantity,
            cost_basis=payload.cost_basis,
            effective_at=payload.effective_at,
            note=payload.note,
            proposed={},
        ))
    except DecisionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        # Неизвестный kind или status: DecisionKind(...) поднимает ValueError.
        raise HTTPException(status_code=400, detail=f"Неизвестное значение: {error}") from error

    session.commit()
    return _to_out(session, decision)


@router.post("/decisions/{decision_id}/revert", response_model=DecisionOut)
def revert(decision_id: int, payload: RevertIn,
           session: Session = Depends(get_session)) -> DecisionOut:
    try:
        mirror = revert_decision(session, decision_id, note=payload.note)
    except DecisionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    session.commit()
    return _to_out(session, mirror)
```

В `backend/app/main.py` подключить роутер рядом с остальными:

```python
from app.api import routes_decisions
...
app.include_router(routes_decisions.router)
```

- [ ] **Step 6: Прогнать тесты**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest`
Expected: PASS целиком.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/api/routes_decisions.py backend/app/api/schemas.py \
        backend/app/api/routes_portfolio.py backend/app/main.py \
        backend/tests/test_api.py
git commit -m "feat: REST-контур решений и гипотезы в строке расхождения"
```

---

### Task 11: Панель разбора расхождения

**Files:**
- Create: `frontend/src/components/DecisionPanel.tsx`
- Create: `frontend/src/components/DecisionPanel.test.tsx`
- Modify: `frontend/src/components/ReconciliationBanner.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/package.json`, `frontend/vite.config.ts`

**Interfaces:**
- Consumes: `GET /api/reconciliations` с полем `suggestions`,
  `POST /api/decisions` из Task 10.
- Produces: компонент `DecisionPanel` с пропсами
  `{ row: ReconciliationRow; onDone: () => void }`.

- [ ] **Step 1: Завести окружение компонентных тестов**

Компонентных тестов в проекте нет — только `format.test.ts` и
`coverage.test.ts` на чистые функции.

Run:
```bash
cd frontend && pnpm add -D @testing-library/react @testing-library/user-event \
                          @testing-library/jest-dom jsdom
```

В `frontend/vite.config.ts` в блок `test` дописать:

```typescript
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
```

Создать `frontend/src/setupTests.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Написать падающий тест**

Создать `frontend/src/components/DecisionPanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DecisionPanel } from "./DecisionPanel";
import type { ReconciliationRow } from "../api/client";

const WITH_SUGGESTION: ReconciliationRow = {
  isin: "HK0000310034",
  status: "missing_at_broker",
  ledger_quantity: "79.00000000",
  broker_quantity: "0.00000000",
  account: "Инвестиционный",
  suggestions: [{
    from_isin: "HK0000310034",
    from_quantity: "79.00000000",
    to_isin: "HK0000051877",
    to_quantity: "79.00000000",
    blocked_fully: true,
    ambiguous: false,
  }],
};

const WITHOUT_SUGGESTION: ReconciliationRow = {
  ...WITH_SUGGESTION,
  isin: "US50155Q1004",
  ledger_quantity: "-2.00000000",
  suggestions: [],
};

function renderPanel(row: ReconciliationRow) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecisionPanel row={row} onDone={() => {}} />
    </QueryClientProvider>,
  );
}

describe("DecisionPanel", () => {
  it("предзаполняет форму гипотезой и называет усиливающий признак", () => {
    renderPanel(WITH_SUGGESTION);

    expect(screen.getByDisplayValue("HK0000051877")).toBeInTheDocument();
    expect(screen.getByText(/заблокирован/i)).toBeInTheDocument();
  });

  it("без гипотезы предлагает выбрать действие, а не молчит", () => {
    renderPanel(WITHOUT_SUGGESTION);

    expect(screen.getByLabelText(/что произошло/i)).toBeInTheDocument();
  });

  it("не отправляет решение без пояснения", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderPanel(WITH_SUGGESTION);

    await userEvent.click(screen.getByRole("button", { name: /подтвердить/i }));

    expect(screen.getByText(/пояснение обязательно/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Запустить тест и убедиться, что он падает**

Run: `cd frontend && pnpm vitest run src/components/DecisionPanel.test.tsx`
Expected: FAIL — модуль `./DecisionPanel` не найден.

- [ ] **Step 4: Дописать типы и вызовы в клиенте**

В `frontend/src/api/client.ts` добавить:

```typescript
export interface Suggestion {
  from_isin: string;
  from_quantity: string;
  to_isin: string;
  to_quantity: string;
  // Бумага-получатель заблокирована у брокера целиком: конвертации часто
  // оседают именно так. Признак усиливающий, сам по себе гипотезу не создаёт.
  blocked_fully: boolean;
  // Кандидатов с такой же величиной несколько — выбирает владелец.
  ambiguous: boolean;
}

export interface DecisionInput {
  account: string;
  kind: "CONVERSION" | "ADJUSTMENT" | "ACCEPTED_AS_IS";
  status: "CONFIRMED" | "REJECTED";
  from_isin?: string | null;
  from_quantity?: string | null;
  to_isin?: string | null;
  to_quantity?: string | null;
  cost_basis?: string | null;
  effective_at: string;
  note: string;
}

export interface Decision {
  id: number;
  account: string;
  kind: string;
  status: string;
  from_isin: string | null;
  from_quantity: string | null;
  to_isin: string | null;
  to_quantity: string | null;
  effective_at: string;
  note: string;
  reverts_id: number | null;
}
```

В `ReconciliationRow` дописать `suggestions: Suggestion[];`.

В объект `api` добавить:

```typescript
  decisions: () => request<Decision[]>("/decisions"),
  createDecision: (body: DecisionInput) =>
    request<Decision>("/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
```

- [ ] **Step 5: Написать панель**

Создать `frontend/src/components/DecisionPanel.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DecisionInput, type ReconciliationRow } from "../api/client";
import { formatQuantity } from "../api/format";

const KINDS = [
  { value: "CONVERSION", label: "Конвертация: одна бумага стала другой" },
  { value: "ADJUSTMENT", label: "Поправить количество вручную" },
  { value: "ACCEPTED_AS_IS", label: "Принять как есть, расхождение объяснено" },
] as const;

type Kind = (typeof KINDS)[number]["value"];

// Дата события по умолчанию — сегодня. Конвертация случилась когда-то раньше,
// и владелец обычно знает когда; поле редактируемое именно поэтому.
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function DecisionPanel({ row, onDone }: {
  row: ReconciliationRow;
  onDone: () => void;
}) {
  const suggestion = row.suggestions[0] ?? null;
  const queryClient = useQueryClient();

  const [kind, setKind] = useState<Kind>(suggestion ? "CONVERSION" : "ADJUSTMENT");
  const [fromIsin, setFromIsin] = useState(suggestion?.from_isin ?? row.isin ?? "");
  const [fromQuantity, setFromQuantity] = useState(suggestion?.from_quantity ?? "");
  const [toIsin, setToIsin] = useState(suggestion?.to_isin ?? "");
  const [toQuantity, setToQuantity] = useState(suggestion?.to_quantity ?? "");
  const [effectiveAt, setEffectiveAt] = useState(today());
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (body: DecisionInput) => api.createDecision(body),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onDone();
    },
  });

  function confirm(status: "CONFIRMED" | "REJECTED") {
    if (note.trim() === "") {
      // Проверяем до запроса: бэкенд то же самое отвергнет, но владелец
      // узнает об этом только после круга по сети.
      setValidation("Пояснение обязательно — через год причину не восстановит никто.");
      return;
    }
    setValidation(null);
    submit.mutate({
      account: row.account,
      kind,
      status,
      from_isin: kind === "ACCEPTED_AS_IS" ? null : fromIsin || null,
      from_quantity: kind === "ACCEPTED_AS_IS" ? null : fromQuantity || null,
      to_isin: kind === "CONVERSION" || kind === "ADJUSTMENT" ? toIsin || null : null,
      to_quantity: kind === "CONVERSION" || kind === "ADJUSTMENT" ? toQuantity || null : null,
      effective_at: `${effectiveAt}T00:00:00Z`,
      note,
    });
  }

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--line)", borderRadius: 6 }}>
      {suggestion && (
        <div style={{ fontSize: 12.5, marginBottom: 8 }}>
          Похоже на конвертацию: {formatQuantity(suggestion.from_quantity)} шт.{" "}
          {suggestion.from_isin} → {formatQuantity(suggestion.to_quantity)} шт.{" "}
          {suggestion.to_isin}
          {suggestion.blocked_fully && (
            <div style={{ color: "var(--amber)", fontSize: 11.5 }}>
              Бумага-получатель заблокирована у брокера целиком — частый след
              корпоративного действия.
            </div>
          )}
          {suggestion.ambiguous && (
            <div style={{ color: "var(--amber)", fontSize: 11.5 }}>
              Подходящих бумаг несколько: выбор за вами, система не угадывает.
            </div>
          )}
        </div>
      )}

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Что произошло
        <select value={kind} onChange={(event) => setKind(event.target.value as Kind)}
                style={{ display: "block", marginTop: 3, width: "100%" }}>
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>

      {kind !== "ACCEPTED_AS_IS" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
          {kind === "CONVERSION" && (
            <>
              <label style={{ fontSize: 12 }}>
                Из какой бумаги
                <input value={fromIsin} onChange={(e) => setFromIsin(e.target.value)}
                       style={{ display: "block", width: "100%" }} />
              </label>
              <label style={{ fontSize: 12 }}>
                Сколько списать
                <input value={fromQuantity} onChange={(e) => setFromQuantity(e.target.value)}
                       style={{ display: "block", width: "100%" }} />
              </label>
            </>
          )}
          <label style={{ fontSize: 12 }}>
            В какую бумагу
            <input value={toIsin} onChange={(e) => setToIsin(e.target.value)}
                   style={{ display: "block", width: "100%" }} />
          </label>
          <label style={{ fontSize: 12 }}>
            Сколько зачислить
            <input value={toQuantity} onChange={(e) => setToQuantity(e.target.value)}
                   style={{ display: "block", width: "100%" }} />
          </label>
        </div>
      )}

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Дата события
        <input type="date" value={effectiveAt}
               onChange={(event) => setEffectiveAt(event.target.value)}
               style={{ display: "block", marginTop: 3 }} />
      </label>

      <label style={{ display: "block", fontSize: 12, marginBottom: 6 }}>
        Пояснение
        <textarea value={note} onChange={(event) => setNote(event.target.value)}
                  rows={2} style={{ display: "block", marginTop: 3, width: "100%" }} />
      </label>

      {validation && (
        <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 6 }}>{validation}</div>
      )}
      {submit.isError && (
        <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 6 }}>
          {(submit.error as Error).message}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={() => confirm("CONFIRMED")}
                disabled={submit.isPending}>
          Подтвердить
        </button>
        {suggestion && (
          <button type="button" onClick={() => confirm("REJECTED")}
                  disabled={submit.isPending}>
            Это не конвертация
          </button>
        )}
        <button type="button" onClick={onDone} disabled={submit.isPending}>
          Отмена
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Встроить панель в баннер**

В `frontend/src/components/ReconciliationBanner.tsx` добавить импорты
`DecisionPanel` и завести состояние раскрытой строки внутри
`ReconciliationSummary`:

```tsx
  const [open, setOpen] = useState<string | null>(null);
```

Заменить тело строки списка:

```tsx
            <div key={`${row.account}-${row.isin}-${index}`} style={{ fontSize: 13, color: "var(--tx-2)", padding: "3px 0" }}>
              {row.account} · {row.isin}: {TEXT[row.status] ?? row.status} — в журнале {formatQuantity(row.ledger_quantity)},
              у брокера {formatQuantity(row.broker_quantity)}
              {" "}
              <button
                type="button"
                onClick={() => setOpen(open === `${row.account}-${row.isin}` ? null : `${row.account}-${row.isin}`)}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                         color: "var(--amber)", font: "inherit", textDecoration: "underline" }}
              >
                разобрать
              </button>
              {row.suggestions.length > 0 && (
                <span title="Система нашла подходящую пару" style={{ marginLeft: 4 }}>💡</span>
              )}
              {open === `${row.account}-${row.isin}` && (
                <DecisionPanel row={row} onDone={() => setOpen(null)} />
              )}
            </div>
```

- [ ] **Step 7: Показать уже принятые решения**

Разобранное расхождение исчезает из списка, и вместе с ним со страницы пропадает
всё, что владелец решил. Через месяц вопрос «а почему тут 1012 бумаг» останется
без ответа, хотя ответ записан.

Дописать в `frontend/src/components/ReconciliationBanner.tsx` под списком
расхождений, внутри `expanded`:

```tsx
          <DecisionLog />
```

и завести компонент в том же файле:

```tsx
// Решения не исчезают вместе с расхождением, которое они закрыли: пояснение
// владельца — единственный источник ответа на вопрос «откуда это количество».
function DecisionLog() {
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: api.decisions });

  if (!decisions.data || decisions.data.length === 0) return null;

  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginBottom: 4 }}>
        Уже разобрано: {decisions.data.length}
      </div>
      {decisions.data.map((decision) => (
        <div key={decision.id} style={{ fontSize: 12, color: "var(--tx-2)", padding: "2px 0" }}>
          {decision.account} · {decision.from_isin ?? "—"} → {decision.to_isin ?? "—"}
          {decision.status === "REVERTED" && " (отменено)"} — {decision.note}
        </div>
      ))}
    </div>
  );
}
```

Дописать импорты `useQuery` из `@tanstack/react-query` и `api` из `../api/client`.

Баннер сейчас возвращает `null`, когда расхождений нет (`if (rows.length === 0)
return null;`). Оставить как есть: журнал решений — часть разбора расхождений, а
не самостоятельный раздел, и показывать его на чистом экране незачем.

- [ ] **Step 8: Прогнать тесты и сборку**

Run: `cd frontend && pnpm vitest run`
Expected: PASS — 21 прежний тест плюс три новых.

Run: `cd frontend && pnpm build`
Expected: сборка без ошибок типов.

- [ ] **Step 9: Коммит**

```bash
git add frontend/src/components/DecisionPanel.tsx \
        frontend/src/components/DecisionPanel.test.tsx \
        frontend/src/components/ReconciliationBanner.tsx \
        frontend/src/api/client.ts frontend/src/setupTests.ts \
        frontend/vite.config.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat: панель разбора расхождения с гипотезой конвертации"
```

---

### Task 12: Разбор живых расхождений и закрытие фазы

Проверка на настоящих данных владельца — то, ради чего фаза делалась.

**Files:**
- Modify: `docs/roadmap.md`
- Create: `docs/handoff/2026-08-10-phase-2b-handoff.md`

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `cd backend && uv run pytest`
Expected: PASS.

Run: `cd frontend && pnpm vitest run && pnpm build`
Expected: PASS, сборка без ошибок.

- [ ] **Step 2: Применить миграции и синхронизироваться**

Run: `cd backend && uv run alembic upgrade head`

Синхронизация ходит в живой счёт — **спросить владельца перед запуском**.
После согласия:

Run: `curl -s -X POST http://localhost:8001/api/sync/tbank | python -m json.tool`
Expected: все счета `success`.

- [ ] **Step 3: Убедиться, что РусАгро исчезло само**

Run:
```bash
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select r.isin, coalesce(i.issuer, i.ticker, '—') as bumaga,
       r.ledger_quantity, r.broker_quantity, r.status
from reconciliation r left join instrument i on i.id = r.instrument_id
order by r.isin;"
```
Expected: строки `RU000A0JQUZ6` нет — `TRANSFER_IN` на 351 бумагу учтён.
Гонконгские бумаги больше не безымянны: снимок завёл им записи в справочнике.

Если РусАгро осталось — проверить, что операция от 19.12.2024 перечиталась:
дедупликация по `dedup_key` не тронет уже записанную строку с `op_type='OTHER'`,
и старую запись придётся перечитать полным прогоном истории. Полный прогон
запускается через `sync_broker(session, connector, since=<дата открытия счёта>)`
и тоже требует согласия владельца.

- [ ] **Step 4: Разобрать оставшиеся расхождения в интерфейсе**

Открыть `http://localhost:3000`, развернуть баннер расхождений и разобрать
каждое. Ожидаемые решения:

| Расхождение | Решение |
|---|---|
| `HK0000310034` 79 → `HK0000051877` 79 | конвертация по гипотезе |
| `HK0000123577` 92 | корректировка либо «принято как есть» — пары нет |
| ТКС Холдинг 40 → Т-Технологии +1012 | корректировка обеих сторон по отчёту брокера |
| Икс 5 +45, X5 ГДР −5 | корректировка по отчёту брокера |
| HeadHunter 9 | корректировка |
| Meituan +1 | корректировка |
| Kyndryl −2, NVIDIA −3 | корректировка: закрыть остаток шорта |

Пояснение у каждого решения обязательно и должно называть источник — отчёт
брокера, уведомление о корпоративном действии, собственная память владельца.

- [ ] **Step 5: Сверить итог с брокером**

Run: `cd backend && uv run python -m app.valuation_check`
Expected: разница с `totalAmountPortfolio` меньше 0,2 % — остаётся только то,
что фаза 2a объяснила курсовой разницей ЦБ против брокера и разной секундой
котировки.

Если разница больше — не подгонять решениями. Записать в хендофф, что именно не
сошлось, с цифрами.

- [ ] **Step 6: Обновить роадмеп**

В `docs/roadmap.md` в разделе `### 2b. Журнал без белых пятен`:

- заголовок → `### 2b. Журнал без белых пятен — завершена 10.08.2026`;
- убрать из «Что входит» пункт про достройку графика задним числом;
- добавить после 2b новый раздел:

```markdown
### 2c. История стоимости задним числом

**Зачем.** График стоимости начинается с даты запуска системы, а не с даты
открытия первого счёта. Журнал знает состав портфеля на любую дату в прошлом —
не хватает только цен и курсов.

**Что входит.**

- Достройка снимков по журналу и историческим котировкам. `MoexClient.close_history`
  написан и покрыт тестами, но нигде не подключён.
- Исторические курсы валют: капитал теперь валютный, а `fx_rate` заполняется
  только с текущего дня. Либо тянуть архив ЦБ, либо достраивать одну рублёвую
  часть и честно это помечать.
- Отдельные случаи: дни без торгов, инструменты, которых на MOEX нет,
  корпоративные действия внутри восстанавливаемого периода.

**Признак готовности.** График показывает историю с даты открытия первого
счёта. Даты, для которых оценка неполная, помечены на самом графике, а не
только в документации.
```

- [ ] **Step 7: Написать хендофф**

Создать `docs/handoff/2026-08-10-phase-2b-handoff.md` по образцу
`2026-08-10-phase-2a-handoff.md`: где мы, что фаза сделала, установленное
разведкой, ошибки фазы, попутный долг, что делать в 2c. Обязательно записать:

- фактические решения владельца по каждому расхождению с их пояснениями;
- итог `valuation_check` после разбора, с таблицей по счетам;
- подтверждённое написание `OPERATION_TYPE_OUTPUT_SECURITIES` (или факт, что на
  живых данных он не встретился);
- что осталось незакрытым из попутного долга фазы 2a.

- [ ] **Step 8: Коммит и Pull Request**

```bash
git add docs/roadmap.md docs/handoff/2026-08-10-phase-2b-handoff.md
git commit -m "docs: хендофф после фазы 2b и выделение фазы 2c"
git push -u origin feature/phase-2b
```

Тело PR собрать из фактических итогов и **показать владельцу до создания** —
это outward-facing артефакт. Обязательные разделы: что фаза сделала, таблица
расхождений «было / стало» с принятыми решениями, итог `valuation_check` по
счетам, что осталось незакрытым. Числа брать из прогонов шагов 3–5, а не из
этого плана: план писался до реализации и его ожидания могли не сбыться.

```bash
gh pr create --title "feat: фаза 2b — журнал без белых пятен" --body-file /tmp/pr-2b.md
```

---

## Порядок задач и зависимости

```
Task 1 (enum) ──┬── Task 2 (переводы) ── Task 3 (себестоимость на экран)
                │
                ├── Task 4 (таблица решений) ──┬── Task 7 (запись решений) ── Task 10 (API) ── Task 11 (панель)
                │                              │
                ├── Task 5 (бумага из снимка) ─┤
                │                              │
                ├── Task 6 (перенос партий) ───┘
                │
                └── Task 9 (корректировки)

Task 8 (гипотезы) зависит только от Task 4; Task 10 ждёт и Task 7, и Task 8.
Task 12 — последняя, после всех.
```

Task 3 и Task 4 независимы, но Task 3 создаёт миграцию `0017` с
`down_revision = '0016'`. Делать Task 4 раньше Task 3 удобнее: тогда номер
сойдётся сам.
