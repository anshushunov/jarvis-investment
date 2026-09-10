# Фаза 5a «Реестр инструментов и MCP-сервер» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать модели доступ к данным портфеля инструментами: девять читающих
инструментов в реестре, stdio-фасад MCP поверх него для Codex CLI и целевые
доли с расчётом выравнивания пополнением.

**Architecture:** три слоя, новая логика только в среднем. `app/ai/tools/*.py` —
чистые функции над сессией SQLAlchemy, зовущие существующие сервисы;
`app/ai/registry.py` — единственное место, где инструмент описан для модели;
`app/ai/mcp.py` — фасад без логики. Новый расчёт — целевые доли и выравнивание —
живёт в `app/allocation/`, рядом с остальным расчётным слоем. Единственное
экранное изменение — раздел «Целевые доли» в «Настройках».

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, Pydantic v2, Alembic,
pytest, PostgreSQL 16, пакет `mcp` 2.x (официальный Python SDK) · React 19,
TypeScript, TanStack Query, Tailwind 3.4, vitest, Testing Library · Codex CLI
0.147 на машине владельца.

## Global Constraints

- **Дизайн фазы:** [`docs/superpowers/specs/2026-09-06-phase-5a-tool-registry-design.md`](../specs/2026-09-06-phase-5a-tool-registry-design.md).
  Расхождение с ним — дефект реализации, а не улучшение.
- **Все деньги — `Decimal`, никогда `float`.** Наружу суммы отдаются строками:
  API — `f"{value:.4f}"`, инструменты ассистента — `"846124.16"` (две копейки,
  `app/ai/serialize.py`). Доли и ставки — дробью `"0.6000"`.
- **Округление денег — через `app.money.money()`**, а не `round()`.
- **Инструменты только читают и в сеть не ходят.** Каждая транзакция MCP-сервера
  открыта как `READ ONLY` (`postgresql_readonly=True`), запись отбивает база.
- **Логи сервера — только в stderr.** В stdio-транспорте stdout занят протоколом.
- **Отказ — это ответ.** Инструмент никогда не роняет сервер: `ToolRefusal` с
  русским текстом превращается в `{"error": "…"}`, любое другое исключение —
  трейсбек в stderr и `{"error": …}` без цифр.
- **Пакет `mcp` на PyPI — версии 2.x:** `from mcp.server.mcpserver import
  MCPServer`, инструмент регистрируется `server.add_tool(fn, name=…,
  description=…)`, схема входа выводится из сигнатуры функции
  (`Annotated[тип, Field(description=…)]`), тестовый клиент — `from mcp import
  Client` (асинхронный контекст-менеджер). Класса `FastMCP` в 2.x нет.
- **Схема входа инструмента: у каждого аргумента есть `Field(description=…)`.**
  Закрепляется тестом фасада.
- **Проверки, зависящие от типа операции, поднимают данные из базы** (правило
  фазы 2b, `tests/test_operation_type_enum.py`).
- **Инлайновых стилей во фронте быть не может.** `cd frontend && pnpm check:styles
  --strict` обязана оставаться зелёной; экран собирается из примитивов фазы 3
  (`Card`, `Field`, `Table`, `Button`, `Badge`). Не хватило примитива — остановиться
  и сказать вслух.
- **База перед тестами должна быть поднята:** `docker compose up -d db` (Rancher
  Desktop). Тесты бэкенда ходят в Postgres на 5433; без него они падают на
  первой же фикстуре `session`. Порты: база 5433, бэкенд 8001, фронт 3000.
  `uv` лежит в `C:\Users\User\.local\bin` и в PATH может отсутствовать.
- **Команды:** бэкенд — `cd backend && uv run pytest` (651 тест до фазы), фронт —
  `cd frontend && pnpm exec vitest run` (123 теста до фазы), типы — `cd frontend
  && pnpm run build`.
- **`run_tool` не валидирует типы аргументов** — это делает MCP-фасад по схеме. В
  тестах инструментов передавать `date(...)`, а не строки дат.
- **Коммиты** — по-русски, в стиле истории проекта: `feat: …`, `test: …`,
  `docs: …`. Авторство LLM не указывается.

## Карта файлов

| Файл | Ответственность |
|---|---|
| `backend/app/allocation/__init__.py` | пустой, пакет |
| `backend/app/allocation/rebalance.py` | чистая арифметика выравнивания: `X = max(v_i/t_i) − V`, дефициты |
| `backend/app/allocation/service.py` | целевые доли: хранение, проверка набора, отчёт факт/цель |
| `backend/app/models/target_allocation.py` | таблица `target_allocation` |
| `backend/alembic/versions/0020_target_allocation.py` | миграция |
| `backend/app/analytics/service.py` | `PositionRow` узнаёт `instrument_id` и `asset_class`; константа `ASSET_CLASSES` (дополняется) |
| `backend/app/api/routes_allocation.py` | `GET`/`PUT /api/allocation/targets` |
| `backend/app/api/schemas.py`, `backend/app/main.py` | схемы и роутер (дополняются) |
| `backend/app/returns/metrics.py`, `service.py` | период `custom` с явными границами, `PeriodError` (дополняются) |
| `backend/app/instruments/search.py` | поиск бумаги по строке |
| `backend/app/ai/__init__.py` | пустой, пакет |
| `backend/app/ai/errors.py` | `ToolRefusal` |
| `backend/app/ai/serialize.py` | форма ответа: деньги строками, даты, ссылки на бумагу и счёт, прореживание рядов |
| `backend/app/ai/tools/__init__.py` | пустой, пакет |
| `backend/app/ai/tools/overview.py` | `portfolio_overview` |
| `backend/app/ai/tools/positions.py` | `positions` |
| `backend/app/ai/tools/instruments.py` | `find_instrument` |
| `backend/app/ai/tools/returns.py` | `returns` |
| `backend/app/ai/tools/history.py` | `value_history`, `instrument_prices` |
| `backend/app/ai/tools/ledger.py` | `ledger` |
| `backend/app/ai/tools/quality.py` | `data_quality` |
| `backend/app/ai/tools/allocation.py` | `allocation` |
| `backend/app/ai/registry.py` | `ToolSpec`, список `TOOLS`, `INSTRUCTIONS`, `run_tool` |
| `backend/app/ai/mcp.py` | stdio-фасад: сессии `READ ONLY`, логи в stderr, `python -m app.ai.mcp` |
| `backend/app/ai/live_run.py` | шесть живых вопросов через `codex exec`, запись в `docs/handoff/` |
| `frontend/src/api/client.ts` | типы и вызовы целевых долей (дополняется) |
| `frontend/src/components/TargetAllocationForm.tsx` | форма целей: строки, сумма, остаток «не задано» |
| `frontend/src/components/TargetAllocationCard.tsx` | карточка с запросами и сохранением |
| `frontend/src/pages/SettingsPage.tsx` | подключение карточки (дополняется) |
| `README.md`, `docs/roadmap.md`, `docs/handoff/…` | регистрация в Codex, статус фазы, хендофф и запись живого прогона |

`app/ai/errors.py` в дизайне отдельным файлом не назван. Он выделен потому, что
`ToolRefusal` нужен и инструментам, и реестру, а реестр импортирует инструменты:
исключение внутри реестра замкнуло бы импорт по кругу.

---

### Задача 1: арифметика выравнивания

**Files:**
- Create: `backend/app/allocation/__init__.py`
- Create: `backend/app/allocation/rebalance.py`
- Test: `backend/tests/test_allocation_rebalance.py`

**Interfaces:**
- Consumes: `app.money.money`
- Produces: `Group(key: str, target: Decimal, value: Decimal)`;
  `Rebalance(total_value, minimal_contribution, contribution, deficits:
  dict[str, Decimal], unfixable: dict[str, Decimal], not_closed: list[str],
  short_by: Decimal)`; `minimal_contribution(groups) -> Decimal`;
  `rebalance(groups: list[Group], contribution: Decimal | None = None) -> Rebalance`.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_allocation_rebalance.py`:

```python
from decimal import Decimal

import pytest

from app.allocation.rebalance import Group, minimal_contribution, rebalance


def groups(*items):
    return [Group(key=key, target=Decimal(target), value=Decimal(value))
            for key, target, value in items]


def test_minimal_contribution_leaves_no_surplus():
    """Акции 60 при цели 50 %, облигации 40 при цели 50 %: докинуть 20 в
    облигации — и обе группы ровно на цели, ни одна не выше."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")))
    assert result.minimal_contribution == Decimal("20.0000")
    assert result.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("20.0000")}
    assert result.not_closed == []
    assert result.short_by == Decimal("0")


def test_sum_of_deficits_equals_minimal_contribution_on_uneven_numbers():
    """Тождество дизайна (раздел 4.4): Σ max(0, t_i·(V+X) − v_i) = X при
    минимальном X. Числа нарочно не делятся нацело — проверяется тождество, а
    не совпадение чисел."""
    items = groups(("equity", "0.6", "70"), ("bonds", "0.4", "30"))
    result = rebalance(items)
    assert abs(sum(result.deficits.values()) - result.minimal_contribution) <= Decimal("0.0001")
    assert result.minimal_contribution == minimal_contribution(items)


def test_zero_target_group_is_unfixable_and_named_with_its_value():
    """Группа с целью «ноль», в которой что-то лежит, пополнением не
    выправляется никогда: v_i / t_i не определено. Она названа отдельно, с
    суммой, которую пришлось бы продать."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "30"),
                              ("derivatives", "0", "10")))
    assert result.minimal_contribution == Decimal("20.0000")
    assert result.unfixable == {"derivatives": Decimal("10.0000")}
    # Дефициты закрывают и то, что лежит в невыправляемой группе: 30 = 20 + 10.
    assert sum(result.deficits.values()) == Decimal("30.0000")


def test_contribution_below_minimal_names_groups_left_above_target():
    """Своя сумма меньше минимальной: расчёт так и говорит и называет группы,
    чей перекос этой суммой не закрывается. Молча распределить меньшее и сделать
    вид, что доли выровнены, он не имеет права."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")), Decimal("5"))
    assert result.short_by == Decimal("15.0000")
    assert result.not_closed == ["equity"]
    assert result.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("12.5000")}


def test_contribution_above_minimal_is_spread_by_deficits():
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")), Decimal("50"))
    assert result.deficits == {"equity": Decimal("15.0000"), "bonds": Decimal("35.0000")}
    assert sum(result.deficits.values()) == result.contribution
    assert result.not_closed == []
    assert result.short_by == Decimal("0")


def test_empty_portfolio_needs_nothing_but_spreads_a_given_sum_by_targets():
    empty = groups(("equity", "0.7", "0"), ("bonds", "0.3", "0"))
    assert rebalance(empty).minimal_contribution == Decimal("0.0000")
    assert rebalance(empty, Decimal("100")).deficits == {
        "equity": Decimal("70.0000"), "bonds": Decimal("30.0000"),
    }


def test_negative_contribution_is_refused():
    with pytest.raises(ValueError, match="отрицательной"):
        rebalance(groups(("equity", "1", "10")), Decimal("-1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_allocation_rebalance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.allocation'`

- [ ] **Step 3: Write minimal implementation**

Создать пустой `backend/app/allocation/__init__.py` и
`backend/app/allocation/rebalance.py`:

```python
"""Выравнивание долей пополнением — чистая арифметика (дизайн 5a, раздел 4.4).

Ни базы, ни целей как сущностей: на входе группы с целевой долей и фактом, на
выходе — сколько докинуть и куда. Модуль зовёт инструмент `allocation` (фаза
5a), позовут экран 4d и панель чата 5b, поэтому он лежит рядом с остальным
расчётным слоем, а не внутри инструмента.

Обозначения: V — стоимость портфеля, v_i — стоимость группы, t_i — её цель,
Σt_i = 1 (группа «не задано» входит в список с остатком цели). Пополнение
тратится только на покупки — продаж расчёт не предлагает.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.money import money


@dataclass(frozen=True)
class Group:
    key: str
    # Целевая доля от всего портфеля, от 0 до 1. Ноль — законная цель: «этого
    # в портфеле быть не должно».
    target: Decimal
    # Факт в рублях. У группы, которую оценить нечем, сюда приходит ноль, а
    # оговорка живёт у вызывающего — он знает, чего именно не хватило.
    value: Decimal


@dataclass(frozen=True)
class Rebalance:
    total_value: Decimal
    # Минимальная сумма, после которой ни одна группа не превышает цель:
    # X = max_i(v_i / t_i) − V.
    minimal_contribution: Decimal
    # Сумма, по которой посчитана раскладка: минимальная либо переданная.
    contribution: Decimal
    # Раскладка пополнения по группам: дефицит каждой при V + X.
    deficits: dict[str, Decimal]
    # Группы с целью «ноль», в которых что-то лежит: пополнением не
    # выправляются никогда и названы вместе с суммой, которую пришлось бы
    # продать.
    unfixable: dict[str, Decimal]
    # Группы, чей перекос переданной суммой не закрывается (она меньше
    # минимальной). Пусто, когда суммы достаточно.
    not_closed: list[str]
    # На сколько переданная сумма меньше минимальной. Ноль — достаточна.
    short_by: Decimal


def minimal_contribution(groups: list[Group]) -> Decimal:
    """X = max_i(v_i / t_i) − V, не меньше нуля.

    При таком X у группы с наибольшим перекосом факт ровно равен цели, у
    остальных — ниже, и сумма дефицитов равна X: это тождество, и проверяется
    оно тестом, а не совпадением чисел. Группы с целью ноль в максимум не
    входят: v_i / 0 не определено, такая группа выправляется только продажей
    (см. Rebalance.unfixable).
    """
    total = sum((group.value for group in groups), Decimal("0"))
    needed = max((group.value / group.target for group in groups if group.target > 0),
                 default=Decimal("0"))
    return money(max(Decimal("0"), needed - total))


def deficits_at(groups: list[Group], contribution: Decimal) -> dict[str, Decimal]:
    """Сколько не хватает каждой группе до цели после пополнения на `contribution`."""
    total = sum((group.value for group in groups), Decimal("0")) + contribution
    return {
        group.key: money(max(Decimal("0"), group.target * total - group.value))
        for group in groups if group.target > 0
    }


def rebalance(groups: list[Group], contribution: Decimal | None = None) -> Rebalance:
    if contribution is not None and contribution < 0:
        raise ValueError("Сумма пополнения не может быть отрицательной: продаж расчёт не предлагает")

    total = money(sum((group.value for group in groups), Decimal("0")))
    minimal = minimal_contribution(groups)
    applied = minimal if contribution is None else money(contribution)
    deficits = deficits_at(groups, applied)

    unfixable = {group.key: money(group.value) for group in groups
                 if group.target == 0 and group.value > 0}
    short = applied < minimal
    not_closed = [group.key for group in groups
                  if short and group.target > 0 and group.target * (total + applied) < group.value]

    return Rebalance(
        total_value=total, minimal_contribution=minimal, contribution=applied,
        deficits=deficits, unfixable=unfixable, not_closed=not_closed,
        short_by=money(minimal - applied) if short else Decimal("0"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_allocation_rebalance.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/allocation backend/tests/test_allocation_rebalance.py
git commit -m "feat: арифметика выравнивания долей пополнением"
```

---

### Задача 2: таблица целевых долей и миграция

**Files:**
- Create: `backend/app/models/target_allocation.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0020_target_allocation.py`
- Modify: `backend/tests/test_migrations.py:84-85`
- Test: `backend/tests/test_allocation_targets.py`

**Interfaces:**
- Produces: модель `TargetAllocation(id, asset_class: str | None,
  instrument_id: int | None, share: Decimal, updated_at)`. Ровно один из двух
  ключей заполнен — проверяет база.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_allocation_targets.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import TargetAllocation


def test_database_refuses_target_without_exactly_one_key(session):
    """Цель без ключа — не цель; цель с двумя ключами считала бы один рубль
    дважды. Оба случая отбивает база, а не только сервис."""
    session.add(TargetAllocation(asset_class=None, instrument_id=None, share=Decimal("0.5")))
    with pytest.raises(IntegrityError, match="ck_target_allocation_one_key"):
        session.flush()


def test_database_refuses_two_targets_on_one_class(session):
    session.add_all([
        TargetAllocation(asset_class="equity", share=Decimal("0.5")),
        TargetAllocation(asset_class="equity", share=Decimal("0.3")),
    ])
    with pytest.raises(IntegrityError, match="uq_target_allocation_asset_class"):
        session.flush()
```

В `backend/tests/test_migrations.py` дополнить множество таблиц в
`test_full_chain_upgrades_matches_models_and_downgrades`:

```python
        assert {"account", "instrument", "transaction", "price", "position",
                "reconciliation", "sync_run", "daily_snapshot",
                "target_allocation"} <= tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_allocation_targets.py tests/test_migrations.py -v`
Expected: FAIL — `ImportError: cannot import name 'TargetAllocation'`; тест
цепочки миграций — `AssertionError` на множестве таблиц.

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/models/target_allocation.py`:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TargetAllocation(Base):
    """Целевая доля — первая настройка, живущая в базе (дизайн 5a, раздел 4.4).

    Строка задаёт долю от всего портфеля либо на класс активов, либо на бумагу:
    ровно один из двух ключей заполнен, и это проверяет сама база. Смешивать
    внутри ветки нельзя (цель на Сбер при цели на акции считала бы один рубль
    дважды) — это правило про пару строк, а не про одну, и живёт оно в
    app/allocation/service.py.
    """

    __tablename__ = "target_allocation"
    __table_args__ = (
        # Уникальность каждого ключа по отдельности. NULL в уникальном
        # ограничении Postgres с NULL не конфликтует, поэтому две цели на класс
        # (у обеих instrument_id пуст) сравниваются только по asset_class, и
        # наоборот. Составной ключ из двух колонок не сработал бы: пары
        # (NULL, 5) и (NULL, 5) он счёл бы разными.
        UniqueConstraint("asset_class", name="uq_target_allocation_asset_class"),
        UniqueConstraint("instrument_id", name="uq_target_allocation_instrument"),
        CheckConstraint("(asset_class IS NULL) <> (instrument_id IS NULL)",
                        name="ck_target_allocation_one_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str | None] = mapped_column(String(32))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    # Доля от 0 до 1 с точностью до сотой процента: 0.6000 — это 60 %.
    share: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

В `backend/app/models/__init__.py` добавить импорт
`from app.models.target_allocation import TargetAllocation` и строку
`"TargetAllocation",` в `__all__` (по алфавиту, после `"SyncRun"`).

Создать `backend/alembic/versions/0020_target_allocation.py`:

```python
"""целевые доли портфеля

Revision ID: 0020
Revises: 0019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'target_allocation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_class', sa.String(32), nullable=True),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('share', sa.Numeric(7, 4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_class', name='uq_target_allocation_asset_class'),
        sa.UniqueConstraint('instrument_id', name='uq_target_allocation_instrument'),
        sa.CheckConstraint('(asset_class IS NULL) <> (instrument_id IS NULL)',
                           name='ck_target_allocation_one_key'),
    )


def downgrade() -> None:
    # Откат уносит цели владельца — их немного и они восстанавливаются с
    # экрана за минуту, в отличие от записей журнала (ср. 0016). Отказ здесь
    # был бы лишним.
    op.drop_table('target_allocation')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_allocation_targets.py tests/test_migrations.py -v`
Expected: PASS. Если `test_full_chain_upgrades_matches_models_and_downgrades`
жалуется на расхождение моделей и миграций — сверить типы колонок буквально
(`String(32)`, `Numeric(7, 4)`, `nullable`), а не подгонять миграцию под тест.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/target_allocation.py backend/app/models/__init__.py backend/alembic/versions/0020_target_allocation.py backend/tests/test_allocation_targets.py backend/tests/test_migrations.py
git commit -m "feat: таблица целевых долей target_allocation"
```

---

### Задача 3: служба целевых долей и отчёт факт/цель

**Files:**
- Modify: `backend/app/analytics/service.py:38-83` (`PositionRow`), `:181-251`
  (`position_rows`), после `cash_asset_class` — константа `ASSET_CLASSES`
- Modify: `backend/app/api/schemas.py:44-91` (`PositionOut`)
- Modify: `frontend/src/api/client.ts:34-66` (`PositionRow`)
- Create: `backend/app/allocation/service.py`
- Test: `backend/tests/test_analytics.py` (дополнить), `backend/tests/test_allocation_service.py`

**Interfaces:**
- Consumes: `rebalance`, `Group` из задачи 1; `TargetAllocation` из задачи 2;
  `portfolio_overview`, `position_rows`, `asset_class_of`.
- Produces: `PositionRow.instrument_id: int`, `PositionRow.asset_class: str`;
  `ASSET_CLASSES: frozenset[str]`; `AllocationError(ValueError)`;
  `TargetInput(share, asset_class=None, isin=None)`; `list_targets(session)`;
  `replace_targets(session, targets: list[TargetInput]) -> list[TargetAllocation]`;
  `AllocationRow(kind, key, title, target, value, actual, deviation_points,
  deviation_rub)`; `AllocationReport(total_value, as_of, rows, rebalance,
  valued_positions, positions_total, unpriced, notes)`;
  `allocation_report(session, contribution: Decimal | None = None)`;
  `UNASSIGNED_KEY = "unassigned"`.

Задача двухчастная и намеренно не разрезана: факт по бумаге для отчёта берётся
из `position_rows`, а у строки позиции до сих пор нет ни идентификатора бумаги,
ни класса. Первый шаг даёт их, второй на них строится.

- [ ] **Step 1: Write the failing tests**

Дописать в конец `backend/tests/test_analytics.py`:

```python
def test_position_rows_carry_instrument_id_and_asset_class(session):
    """Идентификатор — для реестра инструментов ассистента (тикеры не уникальны),
    класс — той же функцией, что считает разбивку капитала: целевые доли
    сравниваются с фактом по одним и тем же ключам."""
    seed(session)
    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["SBER"].asset_class == "equity"
    assert rows["OFZ"].asset_class == "bonds"
    assert rows["TMOS"].asset_class == "equity"
    assert all(isinstance(row.instrument_id, int) for row in rows.values())
```

Создать `backend/tests/test_allocation_service.py`:

```python
from decimal import Decimal

import pytest

from app.allocation.service import (
    UNASSIGNED_KEY,
    AllocationError,
    TargetInput,
    allocation_report,
    list_targets,
    replace_targets,
)
from tests.test_analytics import add_account, add_priced_position


def two_class_portfolio(session):
    """Акции 60 000 ₽ и облигации 40 000 ₽ — перекос, который видно глазами."""
    account = add_account(session)
    add_priced_position(session, account, "RU0009029540", Decimal("100"), Decimal("600"))
    add_priced_position(session, account, "RU000A101234", Decimal("40"), Decimal("1000"), kind="bond")
    return account


def test_targets_are_replaced_as_a_whole(session):
    replace_targets(session, [TargetInput(share=Decimal("0.6"), asset_class="equity")])
    stored = replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="bonds")])
    assert [(row.asset_class, row.share) for row in stored] == [("bonds", Decimal("0.5000"))]
    assert [row.asset_class for row in list_targets(session)] == ["bonds"]


def test_sum_over_one_is_refused(session):
    with pytest.raises(AllocationError, match="превышает 100"):
        replace_targets(session, [TargetInput(share=Decimal("0.7"), asset_class="equity"),
                                  TargetInput(share=Decimal("0.4"), asset_class="bonds")])


def test_unknown_class_is_refused(session):
    with pytest.raises(AllocationError, match="Неизвестный класс"):
        replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equities")])


def test_instrument_inside_targeted_class_is_refused(session):
    """Одно пространство целей: если у акций цель 60 %, у Сбера собственной
    цели быть не может — один рубль посчитался бы дважды."""
    two_class_portfolio(session)
    with pytest.raises(AllocationError, match="уже задана цель"):
        replace_targets(session, [TargetInput(share=Decimal("0.6"), asset_class="equity"),
                                  TargetInput(share=Decimal("0.1"), isin="RU0009029540")])


def test_instrument_target_resolves_by_isin(session):
    two_class_portfolio(session)
    stored = replace_targets(session, [TargetInput(share=Decimal("0.1"), isin="RU0009029540")])
    assert stored[0].instrument_id is not None
    assert stored[0].asset_class is None


def test_unknown_isin_is_refused(session):
    with pytest.raises(AllocationError, match="не найдена"):
        replace_targets(session, [TargetInput(share=Decimal("0.1"), isin="XX0000000000")])


def test_report_measures_deviation_and_minimal_contribution(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity"),
                              TargetInput(share=Decimal("0.5"), asset_class="bonds")])
    report = allocation_report(session)
    rows = {row.key: row for row in report.rows}
    assert report.total_value == Decimal("100000.0000")
    assert rows["equity"].actual == Decimal("0.6000")
    assert rows["equity"].deviation_points == Decimal("10.00")
    assert rows["equity"].deviation_rub == Decimal("10000.0000")
    assert UNASSIGNED_KEY not in rows
    assert report.rebalance.minimal_contribution == Decimal("20000.0000")
    assert report.rebalance.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("20000.0000")}
    # Тождество дизайна: сумма дефицитов равна минимальному пополнению.
    assert sum(report.rebalance.deficits.values()) == report.rebalance.minimal_contribution


def test_unassigned_group_takes_the_rest(session):
    """Сумма целей не обязана быть сотней: остаток — группа «не задано» с
    фактом, равным всему, что не покрыто целями."""
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity")])
    rows = {row.key: row for row in allocation_report(session).rows}
    assert rows[UNASSIGNED_KEY].target == Decimal("0.5000")
    assert rows[UNASSIGNED_KEY].value == Decimal("40000.0000")


def test_value_outside_full_targets_is_unfixable_by_contribution(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("1"), asset_class="equity")])
    report = allocation_report(session)
    assert report.rebalance.unfixable == {UNASSIGNED_KEY: Decimal("40000.0000")}


def test_instrument_target_is_measured_by_its_position(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), isin="RU000A101234")])
    rows = {row.key: row for row in allocation_report(session).rows}
    assert rows["RU000A101234"].value == Decimal("40000.0000")
    assert rows["RU000A101234"].actual == Decimal("0.4000")


def test_report_without_targets_says_so(session):
    two_class_portfolio(session)
    report = allocation_report(session)
    assert report.rows[0].key == UNASSIGNED_KEY
    assert report.rows[0].target == Decimal("1.0000")
    assert any("не заданы" in note for note in report.notes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_analytics.py::test_position_rows_carry_instrument_id_and_asset_class tests/test_allocation_service.py -v`
Expected: FAIL — `AttributeError: 'PositionRow' object has no attribute 'asset_class'`
и `ModuleNotFoundError: No module named 'app.allocation.service'`

- [ ] **Step 3: Write minimal implementation**

В `backend/app/analytics/service.py`:

1. В `PositionRow` после поля `name` добавить:

```python
    # Идентификатор бумаги. Нужен реестру инструментов ассистента (фаза 5a):
    # модель называет бумагу этим ключом в ledger и instrument_prices, а тикер
    # ключом быть не может — у 252 бумаг живого портфеля тикеры не уникальны.
    instrument_id: int
    # Класс актива — той же функцией, что считает разбивку капитала
    # (asset_class_of): целевые доли по классу сравниваются с фактом по тем же
    # ключам, и второй расстановки классов рядом быть не должно.
    asset_class: str
```

2. В `position_rows` при сборке `PositionRow(...)` после `name=...` добавить
   `instrument_id=instrument.id,` и `asset_class=asset_class_of(instrument),`.

3. После функции `cash_asset_class` добавить:

```python
# Все классы активов, которые оценка способна назначить: по виду инструмента
# (CLASS_BY_KIND), фонду («mixed» по умолчанию — Instrument.asset_class код
# сегодня не заполняет, «money_market» зарезервирован под фонды денежного
# рынка), денежным остаткам и металлам. Целевая доля задаётся только на класс
# из этого списка: опечатка «equities» заводила бы группу с нулевым фактом и
# честным на вид дефицитом.
ASSET_CLASSES = (
    frozenset(CLASS_BY_KIND.values())
    | frozenset(METAL_CURRENCIES.values())
    | frozenset({CASH_CLASS, "mixed", "money_market", "other"})
)
```

В `backend/app/api/schemas.py`, `PositionOut` — после поля `name` добавить (у
схемы `extra="forbid"`, без этого обработчик позиций упадёт на новых полях):

```python
    # Идентификатор бумаги и её класс — те же, что видит ассистент (фаза 5a).
    # Экрану они пока не нужны, но контракт один на обоих потребителей.
    instrument_id: int
    asset_class: str
```

В `frontend/src/api/client.ts`, интерфейс `PositionRow` — после `name`:

```ts
  // Идентификатор бумаги и класс актива: те же ключи, которыми оперирует
  // ассистент. Экран «Активы» их не показывает, но контракт с бэкендом один.
  instrument_id: number;
  asset_class: string;
```

Создать `backend/app/allocation/service.py`:

```python
"""Целевые доли: хранение, проверка набора и сравнение с фактом (дизайн 5a,
раздел 4.4).

Факт берётся из тех же расчётов, что и цифры на экране: класс — из разбивки
`portfolio_overview`, бумага — суммой `position_rows` по счетам. Второго
расчёта стоимости здесь нет.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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
        share = target.share.quantize(SHARE_EXP)
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
    actual = (value / total).quantize(SHARE_EXP) if total else None
    return AllocationRow(
        kind=kind, key=key, title=title, target=target, value=money(value), actual=actual,
        deviation_points=(((actual - target) * 100).quantize(Decimal("0.01"))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_analytics.py tests/test_allocation_service.py tests/test_api.py -v`
Expected: PASS. `test_api.py` прогоняется затем, что `PositionOut` со строгой
схемой получил два новых поля — обработчик позиций обязан их отдавать.

- [ ] **Step 5: Проверить типы фронта**

Run: `cd frontend && pnpm run build`
Expected: сборка без ошибок (в тестах фронта фикстуры `PositionRow` появятся в
задаче 5, там же они получат новые поля).

- [ ] **Step 6: Commit**

```bash
git add backend/app/analytics/service.py backend/app/api/schemas.py backend/app/allocation/service.py backend/tests/test_analytics.py backend/tests/test_allocation_service.py frontend/src/api/client.ts
git commit -m "feat: целевые доли — проверка набора и отчёт факт против цели"
```

---

### Задача 4: роуты целевых долей

**Files:**
- Create: `backend/app/api/routes_allocation.py`
- Modify: `backend/app/api/schemas.py` (дописать в конец)
- Modify: `backend/app/main.py:6,27-30`
- Test: `backend/tests/test_allocation_api.py`

**Interfaces:**
- Consumes: `replace_targets`, `list_targets`, `TargetInput`, `AllocationError`
  из задачи 3.
- Produces: `GET /api/allocation/targets` → `list[TargetOut]`;
  `PUT /api/allocation/targets` с телом `list[TargetIn]` — замена набора
  целиком, 400 с русским `detail` при противоречии. `TargetOut(asset_class,
  isin, ticker, name, share: "0.6000", updated_at)`.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_allocation_api.py`:

```python
from decimal import Decimal

from tests.test_analytics import add_account, add_priced_position


def test_put_then_get_targets(client, session):
    account = add_account(session)
    add_priced_position(session, account, "RU0009029540", Decimal("10"), Decimal("100"))
    session.commit()

    response = client.put("/api/allocation/targets", json=[
        {"asset_class": "bonds", "share": "0.4"},
        {"isin": "RU0009029540", "share": "0.1"},
    ])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0]["asset_class"] == "bonds"
    assert body[0]["isin"] is None
    # Доля — строкой и дробью, как все ставки проекта.
    assert body[0]["share"] == "0.4000"
    assert body[1]["isin"] == "RU0009029540"
    assert body[1]["name"] == "RU0009029540"
    assert client.get("/api/allocation/targets").json() == body


def test_contradictory_targets_are_refused_with_a_reason(client):
    response = client.put("/api/allocation/targets", json=[
        {"asset_class": "equity", "share": "0.7"},
        {"asset_class": "bonds", "share": "0.4"},
    ])
    assert response.status_code == 400
    assert "превышает 100" in response.json()["detail"]


def test_refused_set_leaves_previous_targets_intact(client):
    first = client.put("/api/allocation/targets", json=[{"asset_class": "equity", "share": "0.5"}])
    assert first.status_code == 200
    client.put("/api/allocation/targets", json=[{"asset_class": "equities", "share": "0.5"}])
    assert [row["asset_class"] for row in client.get("/api/allocation/targets").json()] == ["equity"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_allocation_api.py -v`
Expected: FAIL — 404 или 405, обработчика нет

- [ ] **Step 3: Write minimal implementation**

Дописать в конец `backend/app/api/schemas.py`:

```python
class TargetIn(BaseModel):
    # Ровно один из двух ключей: класс активов или ISIN бумаги. Что именно не
    # так с набором, объясняет бэкенд (AllocationError → 400).
    asset_class: str | None = None
    isin: str | None = None
    # Доля от 0 до 1 строкой, как все дроби проекта: "0.6" — это 60 %.
    share: Decimal


class TargetOut(BaseModel):
    asset_class: str | None
    isin: str | None
    ticker: str | None
    name: str | None
    share: Decimal
    updated_at: datetime

    @field_serializer("share")
    def serialize_share(self, value: Decimal) -> str:
        return f"{value:.4f}"
```

Создать `backend/app/api/routes_allocation.py`:

```python
"""Целевые доли: чтение и запись набора целиком.

Отклонения от целей на экраны фаза не выводит (дизайн 5a, раздел 9) — их
считает инструмент `allocation` ассистента поверх app/allocation/service.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.allocation.service import AllocationError, TargetInput, list_targets, replace_targets
from app.api.schemas import TargetIn, TargetOut
from app.db import get_session
from app.models import Instrument, TargetAllocation

router = APIRouter(prefix="/api/allocation", tags=["allocation"])


def _to_out(session: Session, rows: list[TargetAllocation]) -> list[TargetOut]:
    # Бумаги подгружаются одним запросом на весь список, как в соседних
    # обработчиках, а не по одной на строку.
    instruments = {
        instrument.id: instrument
        for instrument in session.execute(select(Instrument).where(Instrument.id.in_(
            {row.instrument_id for row in rows if row.instrument_id is not None}
        ))).scalars()
    }
    result = []
    for row in rows:
        instrument = instruments.get(row.instrument_id) if row.instrument_id is not None else None
        result.append(TargetOut(
            asset_class=row.asset_class,
            isin=instrument.isin if instrument else None,
            ticker=instrument.ticker if instrument else None,
            name=(instrument.issuer or instrument.ticker or instrument.isin) if instrument else None,
            share=row.share,
            updated_at=row.updated_at,
        ))
    return result


@router.get("/targets", response_model=list[TargetOut])
def get_targets(session: Session = Depends(get_session)) -> list[TargetOut]:
    return _to_out(session, list_targets(session))


@router.put("/targets", response_model=list[TargetOut])
def put_targets(payload: list[TargetIn], session: Session = Depends(get_session)) -> list[TargetOut]:
    try:
        rows = replace_targets(session, [
            TargetInput(share=item.share, asset_class=item.asset_class, isin=item.isin)
            for item in payload
        ])
    except AllocationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    session.commit()
    return _to_out(session, rows)
```

В `backend/app/main.py`: в импорт добавить `routes_allocation`
(`from app.api import routes_allocation, routes_analytics, …`) и после
`app.include_router(routes_analytics.router)` — `app.include_router(routes_allocation.router)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_allocation_api.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_allocation.py backend/app/api/schemas.py backend/app/main.py backend/tests/test_allocation_api.py
git commit -m "feat: роуты целевых долей GET/PUT /api/allocation/targets"
```

---

### Задача 5: раздел «Целевые доли» в «Настройках»

**Files:**
- Modify: `frontend/src/api/client.ts` (типы и два вызова)
- Create: `frontend/src/components/TargetAllocationForm.tsx`
- Create: `frontend/src/components/TargetAllocationCard.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Test: `frontend/src/components/TargetAllocationForm.test.tsx`

**Interfaces:**
- Consumes: `GET`/`PUT /api/allocation/targets` из задачи 4; `PositionRow`
  (с `instrument_id`, `asset_class` из задачи 3); примитивы `Card`, `CardTitle`,
  `StateMessage`, `Field`, `FieldLabel`, `Table`, `Th`, `Td`, `Button`;
  `ASSET_CLASS_TITLES` из `api/format.ts`.
- Produces: типы `AllocationTarget`, `AllocationTargetInput`;
  `api.allocationTargets()`, `api.saveAllocationTargets(body)`; компонент
  `TargetAllocationForm({ targets, positions, onSave, saving, error })` с
  экспортами `percentToShare`, `shareToPercent`, `rowsFromTargets`;
  `TargetAllocationCard` с запросами.

- [ ] **Step 1: Write the failing test**

Создать `frontend/src/components/TargetAllocationForm.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AllocationTarget, PositionRow } from "../api/client";
import { percentToShare, shareToPercent, TargetAllocationForm } from "./TargetAllocationForm";

const targets: AllocationTarget[] = [
  { asset_class: "equity", isin: null, ticker: null, name: null, share: "0.6000",
    updated_at: "2026-09-09T10:00:00Z" },
  { asset_class: null, isin: "RU000A101234", ticker: "OFZ", name: "ОФЗ 26238", share: "0.1000",
    updated_at: "2026-09-09T10:00:00Z" },
];

// Форма фикстуры — из фактического контракта (backend/app/api/schemas.py, PositionOut).
const position = (over: Partial<PositionRow>): PositionRow => ({
  isin: "RU0009029540", ticker: "SBER", name: "Сбербанк", broker: "tbank",
  account: "Инвестиционный (1)", instrument_id: 1, asset_class: "equity", currency: "RUB",
  quantity: "10.00000000", average_price: "100.0000", cost_basis_known: true,
  average_price_currency: "RUB", last_price: "150.0000", market_value: "1500.0000",
  profit: "500.0000", profit_percent: "50.0000", value_base: "1500.0000", price_source: "moex",
  blocked: "0.00000000", restricted: false, ...over,
});

const positions = [
  position({}),
  position({ isin: "RU000A101234", ticker: "OFZ", name: "ОФЗ 26238", instrument_id: 2, asset_class: "bonds" }),
];

function renderForm(over: Partial<Parameters<typeof TargetAllocationForm>[0]> = {}) {
  const onSave = vi.fn();
  render(
    <TargetAllocationForm targets={targets} positions={positions} onSave={onSave}
                          saving={false} error={null} {...over} />,
  );
  return onSave;
}

describe("TargetAllocationForm", () => {
  it("переводит долю в проценты и обратно без потери сотых", () => {
    expect(shareToPercent("0.6000")).toBe("60");
    expect(percentToShare("12,5")).toBe("0.1250");
  });

  it("показывает цели процентами и считает остаток «не задано»", () => {
    renderForm();
    expect(screen.getByLabelText("Доля Акции")).toHaveValue("60");
    expect(screen.getByText(/Итого 70 % · не задано 30 %/)).toBeInTheDocument();
  });

  it("не даёт сохранить сумму больше ста", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.clear(screen.getByLabelText("Доля Акции"));
    await user.type(screen.getByLabelText("Доля Акции"), "95");
    expect(screen.getByText(/больше 100 %, сохранить нельзя/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });

  it("добавляет цель на класс и отправляет доли дробями", async () => {
    const user = userEvent.setup();
    const onSave = renderForm();
    await user.selectOptions(screen.getByLabelText("Класс"), "bonds");
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    await user.type(screen.getByLabelText("Доля Облигации"), "20");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith([
      { asset_class: "equity", isin: null, share: "0.6000" },
      { asset_class: null, isin: "RU000A101234", share: "0.1000" },
      { asset_class: "bonds", isin: null, share: "0.2000" },
    ]);
  });

  it("предлагает в бумаги только открытые позиции, ещё не названные целью", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.selectOptions(screen.getByLabelText("Добавить цель"), "instrument");
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("Сбербанк");
    expect(options).not.toContain("ОФЗ 26238");
  });

  it("показывает отказ бэкенда словами", () => {
    renderForm({ error: "У класса «equity» уже задана цель" });
    expect(screen.getByRole("alert")).toHaveTextContent("уже задана цель");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/TargetAllocationForm.test.tsx`
Expected: FAIL — `Failed to resolve import "./TargetAllocationForm"`

- [ ] **Step 3: Write minimal implementation**

В `frontend/src/api/client.ts` перед `describeError` добавить:

```ts
export interface AllocationTarget {
  // Ровно один из двух ключей заполнен: класс активов или ISIN бумаги.
  asset_class: string | null;
  isin: string | null;
  ticker: string | null;
  name: string | null;
  // Доля от всего портфеля дробью: "0.6000" — это 60 %.
  share: string;
  updated_at: string;
}

export interface AllocationTargetInput {
  asset_class: string | null;
  isin: string | null;
  share: string;
}
```

В объект `api` добавить:

```ts
  allocationTargets: () => request<AllocationTarget[]>("/allocation/targets"),
  // Набор целей заменяется целиком: бэкенд проверяет его как одно целое
  // (сумма не больше ста, бумага не внутри класса с целью) и либо принимает
  // весь, либо отвергает весь с русским объяснением.
  saveAllocationTargets: (body: AllocationTargetInput[]) =>
    request<AllocationTarget[]>("/allocation/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
```

Создать `frontend/src/components/TargetAllocationForm.tsx`:

```tsx
import { useState } from "react";

import type { AllocationTarget, AllocationTargetInput, PositionRow } from "../api/client";
import { ASSET_CLASS_TITLES } from "../api/format";
import { Button } from "../ui/Button";
import { Field, FieldLabel } from "../ui/Field";
import { Table, Td, Th } from "../ui/Table";

// Тот же класс, что у выпадающих списков панели решений (DecisionPanel.tsx):
// select — не Field, но выглядеть обязан так же.
const CONTROL =
  "block w-full rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx outline-none focus:border-blue";

// Классы, на которые можно задать цель. «Деньги и металлы» — ключ разреза
// доходности, а не класс аллокации, и в цели не годится.
const TARGETABLE_CLASSES = Object.keys(ASSET_CLASS_TITLES).filter((key) => key !== "cash_and_metals");

type Kind = "asset_class" | "instrument";

export interface TargetRow {
  id: string;
  kind: Kind;
  key: string;      // класс или ISIN
  title: string;
  percent: string;  // как набрано владельцем: "60", "12,5"
}

// Проценты — единственная величина модуля, которой разрешён Number: та же
// оговорка, что у formatPercent в api/format.ts. Это доля, а не деньги.
export function percentToShare(percent: string): string {
  return (Number.parseFloat(percent.replace(",", ".")) / 100).toFixed(4);
}

export function shareToPercent(share: string): string {
  // Через целые сотые процента: 0.07 * 100 в двоичной арифметике — это
  // 7.000000000000001, а в поле ввода владелец ждёт «7».
  return String(Math.round(Number.parseFloat(share) * 10000) / 100);
}

export function sumPercent(rows: TargetRow[]): number {
  return rows.reduce(
    (total, row) => total + (Number.parseFloat(row.percent.replace(",", ".")) || 0), 0);
}

export function rowsFromTargets(targets: AllocationTarget[]): TargetRow[] {
  return targets.map((target, index) =>
    target.asset_class !== null
      ? { id: `class-${index}`, kind: "asset_class", key: target.asset_class,
          title: ASSET_CLASS_TITLES[target.asset_class] ?? target.asset_class,
          percent: shareToPercent(target.share) }
      : { id: `isin-${index}`, kind: "instrument", key: target.isin ?? "",
          title: target.name ?? target.isin ?? "—", percent: shareToPercent(target.share) },
  );
}

function plainPercent(value: number): string {
  return `${String(Math.round(value * 100) / 100).replace(".", ",")} %`;
}

export function TargetAllocationForm({ targets, positions, onSave, saving, error }: {
  targets: AllocationTarget[];
  positions: PositionRow[];
  onSave: (body: AllocationTargetInput[]) => void;
  saving: boolean;
  error: string | null;
}) {
  const [rows, setRows] = useState<TargetRow[]>(() => rowsFromTargets(targets));
  const [kind, setKind] = useState<Kind>("asset_class");
  const [key, setKey] = useState("");

  const used = new Set(rows.map((row) => row.key));
  const classOptions = TARGETABLE_CLASSES.filter((klass) => !used.has(klass));
  // Бумаги — из открытых позиций: цель на бумагу, которой в портфеле нет,
  // сравнивать не с чем. Одна бумага на нескольких счетах — один пункт.
  const held = new Map<string, string>();
  for (const row of positions) {
    if (row.isin !== null && !used.has(row.isin) && !held.has(row.isin)) held.set(row.isin, row.name);
  }

  const total = sumPercent(rows);
  const overLimit = total > 100;

  function addRow() {
    if (key === "") return;
    const title = kind === "asset_class" ? (ASSET_CLASS_TITLES[key] ?? key) : (held.get(key) ?? key);
    setRows([...rows, { id: `${kind}-${key}`, kind, key, title, percent: "" }]);
    setKey("");
  }

  function save() {
    onSave(rows.map((row) => ({
      asset_class: row.kind === "asset_class" ? row.key : null,
      isin: row.kind === "instrument" ? row.key : null,
      share: percentToShare(row.percent),
    })));
  }

  return (
    <div>
      {rows.length === 0 ? (
        <div className="text-sm text-muted">
          Целей пока нет: без них ассистент не скажет, что подрезать, а что нарастить.
        </div>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Цель</Th>
              <Th numeric>Доля, %</Th>
              <Th>{""}</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <Td>
                  {row.title}
                  <span className="ml-1.5 text-xs text-muted">
                    {row.kind === "asset_class" ? "класс" : "бумага"}
                  </span>
                </Td>
                <Td numeric>
                  <Field aria-label={`Доля ${row.title}`} className="w-20 text-right" inputMode="decimal"
                         value={row.percent}
                         onChange={(event) => setRows(rows.map((item) =>
                           item.id === row.id ? { ...item, percent: event.target.value } : item))} />
                </Td>
                <Td>
                  <Button variant="ghost" onClick={() => setRows(rows.filter((item) => item.id !== row.id))}>
                    Убрать
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <div className={`mt-2 text-sm tabular-nums ${overLimit ? "text-red" : "text-muted"}`}>
        Итого {plainPercent(total)} · не задано {plainPercent(Math.max(0, 100 - total))}
        {overLimit && " — сумма целей больше 100 %, сохранить нельзя"}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <FieldLabel htmlFor="target-kind">Добавить цель</FieldLabel>
          <select id="target-kind" className={CONTROL} value={kind}
                  onChange={(event) => { setKind(event.target.value as Kind); setKey(""); }}>
            <option value="asset_class">на класс активов</option>
            <option value="instrument">на бумагу</option>
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="target-key">{kind === "asset_class" ? "Класс" : "Бумага"}</FieldLabel>
          <select id="target-key" className={CONTROL} value={key}
                  onChange={(event) => setKey(event.target.value)}>
            <option value="">—</option>
            {kind === "asset_class"
              ? classOptions.map((klass) => (
                  <option key={klass} value={klass}>{ASSET_CLASS_TITLES[klass]}</option>
                ))
              : [...held.entries()].map(([isin, name]) => (
                  <option key={isin} value={isin}>{name}</option>
                ))}
          </select>
        </div>
        <Button variant="ghost" onClick={addRow} disabled={key === ""}>Добавить</Button>
        <Button onClick={save} disabled={overLimit || saving}>
          {saving ? "Сохраняю…" : "Сохранить"}
        </Button>
      </div>

      {error !== null && <div role="alert" className="mt-2 text-sm text-red">{error}</div>}
    </div>
  );
}
```

Создать `frontend/src/components/TargetAllocationCard.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type AllocationTargetInput } from "../api/client";
import { Card, CardTitle } from "../ui/Card";
import { StateMessage } from "../ui/CardState";
import { TargetAllocationForm } from "./TargetAllocationForm";

export function TargetAllocationCard() {
  const queryClient = useQueryClient();
  const targets = useQuery({ queryKey: ["allocation-targets"], queryFn: api.allocationTargets });
  // Тот же ключ, что у экрана «Активы»: один запрос на оба экрана.
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const save = useMutation({
    mutationFn: (body: AllocationTargetInput[]) => api.saveAllocationTargets(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["allocation-targets"] }),
  });

  return (
    <Card>
      <CardTitle>Целевые доли</CardTitle>
      <div className="mb-3 text-xs text-muted">
        Доля от всего портфеля на класс активов или на бумагу. Сумма не обязана быть сотней:
        остаток — группа «не задано». Ассистент сравнивает с целями факт и считает, сколько докинуть.
      </div>
      {targets.isPending || positions.isPending ? (
        <StateMessage kind="loading">Загрузка…</StateMessage>
      ) : targets.isError || positions.isError ? (
        <StateMessage kind="error">{((targets.error ?? positions.error) as Error).message}</StateMessage>
      ) : (
        // key сбрасывает форму после сохранения: строки перечитываются из ответа.
        <TargetAllocationForm
          key={targets.dataUpdatedAt}
          targets={targets.data}
          positions={positions.data}
          onSave={(body) => save.mutate(body)}
          saving={save.isPending}
          error={save.isError ? (save.error as Error).message : null}
        />
      )}
    </Card>
  );
}
```

В `frontend/src/pages/SettingsPage.tsx` обернуть карточку анимаций и добавить
новую:

```tsx
import { TargetAllocationCard } from "../components/TargetAllocationCard";
…
  return (
    <div className="grid gap-3.5">
      <Card>
        …(содержимое карточки анимаций без изменений)…
      </Card>
      <TargetAllocationCard />
    </div>
  );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run`
Expected: PASS, 123 прежних + 6 новых

- [ ] **Step 5: Проверить типы и стили**

Run: `cd frontend && pnpm run build && pnpm check:styles --strict`
Expected: сборка без ошибок, ноль инлайн-стилей и hex-литералов

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/TargetAllocationForm.tsx frontend/src/components/TargetAllocationForm.test.tsx frontend/src/components/TargetAllocationCard.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: раздел «Целевые доли» в настройках"
```

---

### Задача 6: произвольные границы периода доходности

**Files:**
- Modify: `backend/app/returns/metrics.py:18-20,69-89`
- Modify: `backend/app/returns/service.py:39-57,142-174`
- Test: `backend/tests/test_returns_service.py` (дополнить)

**Interfaces:**
- Consumes: `period_bounds`, `returns_report`, `snapshot_account_values`,
  `MONEY_CLASSES`.
- Produces: `PERIOD_CUSTOM = "custom"`; `PeriodError(ValueError)`;
  `period_bounds(period_key, today, first_day, since=None, until=None)`;
  `returns_report(session, period_key, today=None, …, since=None, until=None)`;
  `closing_snapshot(session, until) -> DailySnapshot | None`. Оба имени
  экспортируются из `app.returns.service`.

Вопрос «сколько я заработал в 2024 году» тремя ключами не задать (дизайн,
раздел 5). Период, закончившийся в прошлом, не может кончаться сегодняшней
оценкой: его конец — последний снимок не позже границы.

- [ ] **Step 1: Write the failing test**

Дописать в `backend/tests/test_returns_service.py` (в импорт из
`app.returns.service` добавить `PERIOD_CUSTOM`, `PeriodError`; добавить
`import pytest`):

```python
def test_custom_period_in_the_past_ends_at_its_closing_snapshot(session, account):
    """«Сколько я заработал в 2024 году»: конец периода — снимок на 31.12.2024,
    а не сегодняшняя оценка. Позиций в базе нет нарочно: сегодняшний обзор дал
    бы ноль, и прибыль вышла бы −100 000 вместо +20 000."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 1, 10), amount="100000")
    add_snapshot(session, date(2024, 1, 10), "100000", by_account={str(account.id): "100000"})
    add_snapshot(session, date(2024, 12, 31), "120000", by_account={str(account.id): "120000"})
    add_snapshot(session, date(2026, 8, 13), "130000", by_account={str(account.id): "130000"})

    report = returns_report(session, PERIOD_CUSTOM, today=date(2026, 8, 13),
                            since=date(2024, 1, 1), until=date(2024, 12, 31))
    assert report.period.since == date(2024, 1, 1)
    assert report.period.until == date(2024, 12, 31)
    assert report.portfolio.profit == Decimal("20000.0000")
    assert report.portfolio.value == Decimal("120000.0000")
    assert report.by_account[0].metric.value == Decimal("120000.0000")


def test_custom_period_without_a_closing_snapshot_is_refused(session, account):
    add_snapshot(session, date(2026, 8, 13), "130000")
    with pytest.raises(PeriodError, match="нет ни одного снимка"):
        returns_report(session, PERIOD_CUSTOM, today=date(2026, 8, 13),
                       since=date(2020, 1, 1), until=date(2020, 12, 31))


def test_custom_period_bounds_are_checked():
    today = date(2026, 8, 13)
    with pytest.raises(PeriodError, match="позже конца"):
        period_bounds(PERIOD_CUSTOM, today, None, since=date(2025, 1, 1), until=date(2024, 1, 1))
    with pytest.raises(PeriodError, match="хотя бы началом"):
        period_bounds(PERIOD_CUSTOM, today, None)
    with pytest.raises(PeriodError, match="в будущем"):
        period_bounds(PERIOD_CUSTOM, today, None, since=date(2026, 1, 1), until=date(2027, 1, 1))
    short = period_bounds(PERIOD_CUSTOM, today, None, since=date(2026, 5, 1))
    assert short.until == today
    assert short.annualized is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'PERIOD_CUSTOM'`

- [ ] **Step 3: Write minimal implementation**

В `backend/app/returns/metrics.py` после `PERIOD_YTD = "ytd"` добавить:

```python
# Произвольные границы (фаза 5a): вопрос «сколько я заработал в 2024 году»
# тремя ключами не задать. Даты несёт вызов, а не ключ.
PERIOD_CUSTOM = "custom"


class PeriodError(ValueError):
    """Период задан противоречиво или считать за него нечего. Текст — для
    владельца, по-русски: инструмент ассистента отдаёт его как есть."""
```

Заменить `period_bounds` целиком:

```python
def period_bounds(period_key: str, today: date, first_day: date | None,
                  since: date | None = None, until: date | None = None) -> Period:
    """Границы периода и признак «показывать в годовых».

    Порог аннуализации — годовая база XIRR (`app.returns.xirr.DAYS_IN_YEAR`),
    общая с ним и с `twr.annualize`: две константы «365» в двух модулях
    расходятся ровно тогда, когда одну из них поправят, а `over_period` и
    `annualize` обязаны остаться обратными друг другу.

    Период короче года аннуализировать нельзя: ставка врёт кратно — два
    процента за полтора месяца превращаются в двадцать семь годовых, — и такой
    период показывается за период (дизайн, раздел 4.3).

    Произвольный период задаётся началом, конец по умолчанию — сегодня. Конец
    в будущем отвергается: снимков за него нет и быть не может.
    """
    end = today
    if period_key == PERIOD_CUSTOM:
        if since is None:
            raise PeriodError("Произвольный период задаётся хотя бы началом (since)")
        end = until or today
        if since > end:
            raise PeriodError(f"Начало периода {since} позже конца {end}")
        if end > today:
            raise PeriodError(f"Конец периода {end} в будущем: снимков за него нет")
    elif period_key == PERIOD_12M:
        since = today - timedelta(days=int(DAYS_IN_YEAR))
    elif period_key == PERIOD_YTD:
        since = date(today.year, 1, 1)
    else:
        since = first_day

    length = (end - since).days if since is not None else 0
    return Period(key=period_key, since=since, until=end, annualized=length >= DAYS_IN_YEAR)
```

В `backend/app/returns/service.py`:

1. В импорт из `app.returns.metrics` добавить `PERIOD_CUSTOM,` и `PeriodError,`
   (оба под тем же `# noqa: F401` — часть публичного лица пакета). В импорт из
   `app.returns.breakdown` добавить `MONEY_CLASSES,`.
2. После `opening_snapshot` добавить:

```python
def closing_snapshot(session: Session, until: date) -> DailySnapshot | None:
    """Последний снимок не позже конца периода — его конечная стоимость.

    Нужен только периоду, закончившемуся в прошлом: сегодняшний период
    заканчивается живой оценкой (`portfolio_overview`), и второй источник для
    него не нужен. Разбивка по классам берётся из снимка как есть, а
    стоимость денежного периметра — суммой денежных классов из неё же: иного
    источника у прошлой даты нет (см. MONEY_CLASSES в breakdown.py).
    """
    return session.execute(
        select(DailySnapshot).where(DailySnapshot.on_date <= until)
        .order_by(DailySnapshot.on_date.desc()).limit(1)
    ).scalars().first()
```

3. В `returns_report` добавить параметры `since: date | None = None, until:
   date | None = None` последними и переписать начало тела так (докстринг
   дополнить абзацем про произвольный период):

```python
    today = today or moscow_today()
    period = period_bounds(period_key, today, _first_snapshot_day(session), since, until)

    if period.until < today:
        # Период кончился в прошлом: его конец — снимок, а не сегодняшняя
        # оценка. Переданные значения не перетираются, по той же причине, что
        # и ниже у обзора.
        closing = closing_snapshot(session, period.until)
        if closing is None:
            raise PeriodError(f"На {period.until} нет ни одного снимка стоимости: "
                              "считать конец периода не из чего")
        by_class_closing = {key: Decimal(str(value))
                            for key, value in (closing.by_asset_class or {}).items()}
        value_now = closing.total_value if value_now is None else value_now
        by_account_now = (snapshot_account_values(closing) if by_account_now is None
                          else by_account_now)
        by_class_now = by_class_closing if by_class_now is None else by_class_now
        cash_now = (sum((by_class_closing.get(klass, Decimal("0")) for klass in MONEY_CLASSES),
                        Decimal("0")) if cash_now is None else cash_now)

    if (value_now is None or by_account_now is None or by_class_now is None
            or cash_now is None):
        …(блок с overview без изменений)…

    book = RateBook.load(session)
    …(дальше без изменений; строка `period = period_bounds(...)` из старого места удаляется)…
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_service.py tests/test_returns_api.py tests/test_returns_check.py -v`
Expected: PASS — три новых теста и все прежние: у трёх старых ключей поведение
не изменилось.

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/metrics.py backend/app/returns/service.py backend/tests/test_returns_service.py
git commit -m "feat: произвольные границы периода доходности"
```

---

### Задача 7: каркас реестра и инструмент `portfolio_overview`

**Files:**
- Create: `backend/app/ai/__init__.py`, `backend/app/ai/tools/__init__.py` (пустые)
- Create: `backend/app/ai/errors.py`
- Create: `backend/app/ai/serialize.py`
- Create: `backend/app/ai/registry.py`
- Create: `backend/app/ai/tools/overview.py`
- Test: `backend/tests/test_ai_serialize.py`, `backend/tests/test_ai_overview.py`

**Interfaces:**
- Consumes: `portfolio_overview` (`app.analytics.service`), `all_balances`,
  `account_label`, `SyncRun`.
- Produces: `ToolRefusal(Exception)`; `serialize.amount/rate/percent/price/qty/
  day/moment/instrument_name/instrument_ref/account_ref/auto_granularity/thin`;
  `ToolSpec(name, description, handler)`; `TOOLS: list[ToolSpec]`;
  `INSTRUCTIONS: str`; `INTERNAL_ERROR: str`; `tool_by_name(name)`;
  `run_tool(session, name, arguments) -> dict`; обработчик
  `overview.portfolio_overview(session) -> dict`.

Список `TOOLS` в реестре с самого начала пишется в порядке таблицы дизайна
(раздел 4.2): `portfolio_overview`, `positions`, `returns`, `value_history`,
`ledger`, `instrument_prices`, `allocation`, `data_quality`, `find_instrument`.
Задачи 8–11 вставляют свои записи на свои места, а не в конец.

- [ ] **Step 1: Write the failing tests**

Создать `backend/tests/test_ai_serialize.py`:

```python
from datetime import date
from decimal import Decimal

from app.ai import serialize as s


def test_money_is_a_string_with_kopecks_and_none_stays_none():
    assert s.amount(Decimal("846124.1600")) == "846124.16"
    assert s.amount(Decimal("-0.005")) == "-0.01"
    assert s.amount(None) is None


def test_quantity_drops_trailing_zeros_without_exponent():
    assert s.qty(Decimal("100.00000000")) == "100"
    assert s.qty(Decimal("0.50000000")) == "0.5"


def test_rate_is_a_fraction_with_four_digits():
    assert s.rate(Decimal("0.03311")) == "0.0331"


def test_auto_granularity_by_window_length():
    assert s.auto_granularity(30) == "day"
    assert s.auto_granularity(400) == "week"
    assert s.auto_granularity(2220) == "month"


def test_thin_keeps_last_point_of_each_bucket_and_the_last_point():
    days = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 3), date(2026, 2, 4)]
    assert s.thin(days, lambda d: d, "month") == [date(2026, 1, 5), date(2026, 2, 4)]
    # ISO-неделя: 1–4 января 2026 — одна неделя, 5 января — следующая; 3 и 4
    # февраля — одна неделя, из неё остаётся последняя точка.
    assert s.thin(days, lambda d: d, "week") == [
        date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 4),
    ]
    assert s.thin(days, lambda d: d, "day") == days
```

Создать `backend/tests/test_ai_overview.py`:

```python
import logging
from datetime import datetime, timezone

from app.ai.errors import ToolRefusal
from app.ai.registry import INTERNAL_ERROR, ToolSpec, run_tool
from app.models import SyncRun
from tests.test_analytics import seed


def test_overview_answers_with_money_as_strings(session):
    seed(session)
    result = run_tool(session, "portfolio_overview", {})
    assert result["total_value_rub"] == "7350.00"
    assert result["by_account"][0]["title"] == "Брокерский (acc-1)"
    assert result["by_account"][0]["value_rub"] == "7350.00"
    assert result["coverage"] == {
        "positions_total": 3, "valued_positions": 3, "unpriced": [], "currencies_without_rate": [],
    }
    assert result["as_of"] is not None
    assert result["last_sync"] is None


def test_overview_reports_the_last_finished_sync(session):
    seed(session)
    session.add(SyncRun(broker="tbank", status="success", inserted=12,
                        finished_at=datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)))
    session.flush()
    result = run_tool(session, "portfolio_overview", {})
    assert result["last_sync"]["status"] == "success"
    assert result["last_sync"]["finished_at"].startswith("2026-09-08")


def test_refusal_becomes_an_answer(session, monkeypatch):
    def refusing(session):
        raise ToolRefusal("Нет такого счёта")
    monkeypatch.setattr("app.ai.registry.TOOLS", [ToolSpec("fake", "тест", refusing)])
    assert run_tool(session, "fake", {}) == {"error": "Нет такого счёта"}


def test_unexpected_failure_is_logged_and_answered_without_numbers(session, monkeypatch, caplog):
    def broken(session):
        raise RuntimeError("boom")
    monkeypatch.setattr("app.ai.registry.TOOLS", [ToolSpec("fake", "тест", broken)])
    with caplog.at_level(logging.ERROR, logger="app.ai.registry"):
        result = run_tool(session, "fake", {})
    assert result == {"error": INTERNAL_ERROR.format(name="fake")}
    assert "boom" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_ai_serialize.py tests/test_ai_overview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai'`

- [ ] **Step 3: Write minimal implementation**

Создать пустые `backend/app/ai/__init__.py` и `backend/app/ai/tools/__init__.py`.

Создать `backend/app/ai/errors.py`:

```python
class ToolRefusal(Exception):
    """Отказ — это ответ (дизайн 5a, раздел 4.1).

    Нет цены, пустой период, неизвестный идентификатор: инструмент объясняет
    по-русски, сервер живёт дальше, а модель получает текст, а не трейсбек.
    Живёт отдельно от реестра: реестр импортирует инструменты, а инструменты
    поднимают это исключение — внутри реестра оно замкнуло бы импорт по кругу.
    """
```

Создать `backend/app/ai/serialize.py`:

```python
"""Форма ответа инструментов (дизайн 5a, раздел 4.1): деньги строками, даты
ISO, имена — те же, что на экране.

Одно место на весь реестр: девять инструментов отдают суммы одинаково, и
второе правило форматирования рядом разъехалось бы с первым при первой правке.
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import TypeVar

from app.accounts.labels import account_label
from app.models import Account, Instrument
from app.money import money

T = TypeVar("T")

# Шаги ряда. «auto» подбирает шаг по длине окна: полный ряд за шесть лет —
# 2220 точек, столько в ответе не нужно никому, а месячный шаг за две недели
# оставил бы одну точку.
GRANULARITIES = ("auto", "day", "week", "month")
DAY_LIMIT = 120
WEEK_LIMIT = 730


def amount(value: Decimal | None) -> str | None:
    """Сумма денег строкой с копейками: "846124.16". None остаётся None —
    величина, которой нет, нулём не заполняется."""
    return None if value is None else f"{money(value):.2f}"


def rate(value: Decimal | None) -> str | None:
    """Доля строкой: "0.0331" — это 3,31 %."""
    return None if value is None else f"{value:.4f}"


def percent(value: Decimal | None) -> str | None:
    """Проценты строкой с двумя знаками: "50.00"."""
    return None if value is None else f"{value:.2f}"


def price(value: Decimal | None) -> str | None:
    """Цена — с четырьмя знаками: у облигаций и гонконгских бумаг копеек мало."""
    return None if value is None else f"{value:.4f}"


def qty(value: Decimal | None) -> str | None:
    """Количество без хвостовых нулей: "100", "0.5". Через format(…, "f"), а не
    str(): normalize() у сотни даёт "1E+2"."""
    return None if value is None else format(value.normalize(), "f")


def day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def instrument_name(instrument: Instrument) -> str:
    """То же имя, каким бумага подписана на экране: эмитент, иначе тикер, иначе ISIN."""
    return instrument.issuer or instrument.ticker or instrument.isin or "—"


def instrument_ref(instrument: Instrument) -> dict:
    return {"instrument_id": instrument.id, "name": instrument_name(instrument),
            "ticker": instrument.ticker, "isin": instrument.isin}


def account_ref(account: Account) -> dict:
    return {"account_id": account.id, "title": account_label(account), "broker": account.broker}


def auto_granularity(days: int) -> str:
    if days <= DAY_LIMIT:
        return "day"
    return "week" if days <= WEEK_LIMIT else "month"


def thin(points: list[T], pick_date: Callable[[T], date], granularity: str) -> list[T]:
    """Прореживает ряд: последняя точка каждой недели или месяца. Последняя
    точка ряда остаётся всегда — ответ «как двигалась стоимость» без
    сегодняшней точки неполон."""
    if granularity == "day" or not points:
        return list(points)
    if granularity == "week":
        def bucket(value: date):
            return value.isocalendar()[:2]
    else:
        def bucket(value: date):
            return (value.year, value.month)
    kept: list[T] = []
    for index, current in enumerate(points):
        following = points[index + 1] if index + 1 < len(points) else None
        if following is None or bucket(pick_date(current)) != bucket(pick_date(following)):
            kept.append(current)
    return kept
```

Создать `backend/app/ai/tools/overview.py`:

```python
"""Инструмент portfolio_overview: сколько всего, по счетам, деньги, что
недоступно, на какую дату, когда синхронизировано."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import all_balances
from app.ai import serialize as s
from app.analytics.service import portfolio_overview as overview_of
from app.models import Account, SyncRun


def last_sync(session: Session) -> dict | None:
    """Последний завершившийся прогон синхронизации любого счёта. Успешный и
    неуспешный различаются статусом — модель обязана видеть оба."""
    run = session.execute(
        select(SyncRun).where(SyncRun.finished_at.is_not(None))
        .order_by(SyncRun.finished_at.desc()).limit(1)
    ).scalars().first()
    if run is None:
        return None
    return {"finished_at": s.moment(run.finished_at), "status": run.status,
            "inserted": run.inserted, "mismatches": run.mismatches, "error": run.error}


def portfolio_overview(session: Session) -> dict:
    overview = overview_of(session)
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    cash_rows = all_balances(session)

    by_account = []
    for account_id, value in overview.by_account.items():
        account = accounts.get(account_id)
        if account is None:
            continue
        by_account.append({
            **s.account_ref(account),
            "value_rub": s.amount(value),
            "cash": [{"currency": row.currency, "amount": s.amount(row.amount),
                      "blocked": s.amount(row.blocked)}
                     for row in cash_rows if row.account_id == account_id],
        })

    cash_by_currency: dict[str, Decimal] = {}
    for row in cash_rows:
        cash_by_currency[row.currency] = cash_by_currency.get(row.currency, Decimal("0")) + row.amount

    total = overview.total_value
    return {
        "as_of": s.day(overview.as_of),
        "fx_as_of": s.day(overview.fx_as_of),
        "total_value_rub": s.amount(total),
        "securities_value_rub": s.amount(overview.securities_value),
        "cash_value_rub": s.amount(overview.cash_value),
        "restricted_value_rub": s.amount(overview.restricted_value),
        "by_account": by_account,
        "by_asset_class": [
            {"asset_class": klass, "value_rub": s.amount(value),
             "share": s.rate(value / total) if total else None}
            for klass, value in overview.by_asset_class.items()
        ],
        "cash_by_currency": [{"currency": currency, "amount": s.amount(value)}
                             for currency, value in sorted(cash_by_currency.items())],
        "coverage": {
            "positions_total": overview.positions_total,
            "valued_positions": overview.valued_positions,
            "unpriced": overview.unpriced,
            "currencies_without_rate": overview.currencies_without_rate,
        },
        "last_sync": last_sync(session),
        "note": ("Суммы в рублях по курсам на fx_as_of; неоценённые позиции в итог не входят "
                 "и названы в coverage.unpriced. restricted_value_rub входит в итог, а не "
                 "вычитается из него."),
    }
```

Создать `backend/app/ai/registry.py`:

```python
"""Реестр инструментов ассистента — единственное место, где инструмент описан
для модели: имя, назначение, обработчик (дизайн 5a, раздел 4).

Схему входа даёт сигнатура обработчика (`Annotated[тип, Field(description=…)]`
у каждого аргумента); транслирует её наружу `app/ai/mcp.py`, который логики не
содержит. Обработчик — чистая функция `(session, **вход) -> dict` над сессией
SQLAlchemy: в сеть не ходит, ничего не пишет, всё возвращаемое сериализуемо в
JSON без потерь (деньги — строками, app/ai/serialize.py).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.ai.errors import ToolRefusal
from app.ai.tools import overview

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


INTERNAL_ERROR = ("Инструмент {name} не смог ответить: внутренняя ошибка. Подробности — в "
                  "журнале сервера (stderr). Числа по этому вопросу оценивать приблизительно нельзя.")

# Инструкция сервера (дизайн, раздел 4.1). Отдаётся клиенту вместе со списком
# инструментов. Это инструкция, а не гарантия — см. раздел 8 дизайна.
INSTRUCTIONS = """Ты — ассистент владельца инвестиционного портфеля «Джарвис». Отвечай по-русски.

Правила работы с числами:
1. Любая цифра по портфелю — стоимость, доля, прибыль, доходность, количество — берётся только из инструментов этого сервера. Не считай их по памяти и не пересчитывай приближённо: если инструмент чего-то не вернул, так и скажи — «инструмент этого не даёт», а не оценивай.
2. Внешние сведения (котировки с рынка, новости, ставки, макро) — только с названным источником и датой, отдельным блоком ответа, не смешивая с портфельными числами.
3. Суммы, состав портфеля и названия счетов в поисковые запросы не подставляй.
4. Каждый ответ инструмента несёт дату (as_of) и покрытие (coverage): цитируй их, когда называешь итог. Пустое поле с причиной рядом — это «не посчитано», а не ноль.
5. Прежде чем обращаться к бумаге по имени, найди её идентификатор через find_instrument: тикеры не уникальны.
6. Инструменты только читают. Действий — синхронизации, сделок, правок журнала — сервер не выполняет, и предлагать их от своего имени не должен.
7. Спрашивают, можно ли доверять доходности, — вызови data_quality и назови границы честности сам, без наводящих вопросов: сколько дней измерил TWR, какие бумаги без цен, какие расхождения с брокером не разобраны.
"""

# Порядок — таблица дизайна (раздел 4.2). Записи добавляются на свои места.
TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="portfolio_overview",
        description=("Сколько всего денег в портфеле и из чего это складывается: итог в рублях, "
                     "по счетам (с идентификаторами счетов для других инструментов), деньги по "
                     "валютам, недоступное к распоряжению, дата оценки, покрытие оценкой и "
                     "последняя синхронизация. Начинать с него."),
        handler=overview.portfolio_overview,
    ),
]


def tool_by_name(name: str) -> ToolSpec:
    for spec in TOOLS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def run_tool(session: Session, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Вызывает инструмент и превращает любой сбой в ответ.

    ToolRefusal — объяснение владельцу как есть. Всё остальное — трейсбек в
    журнал (stderr) и честное «не смог ответить» без единой цифры: в
    stdio-транспорте это единственный способ не уронить сессию и не соврать.
    """
    spec = tool_by_name(name)
    try:
        return spec.handler(session, **arguments)
    except ToolRefusal as refusal:
        return {"error": str(refusal)}
    except Exception:
        logger.exception("Инструмент %s упал на входе %r", name, arguments)
        return {"error": INTERNAL_ERROR.format(name=name)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_ai_serialize.py tests/test_ai_overview.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai backend/tests/test_ai_serialize.py backend/tests/test_ai_overview.py
git commit -m "feat: реестр инструментов ассистента и portfolio_overview"
```

---

### Задача 8: `find_instrument` и `positions`

**Files:**
- Create: `backend/app/instruments/search.py`
- Create: `backend/app/ai/tools/instruments.py`
- Create: `backend/app/ai/tools/positions.py`
- Modify: `backend/app/ai/registry.py` (импорт и две записи в `TOOLS`)
- Test: `backend/tests/test_ai_positions.py`

**Interfaces:**
- Consumes: `position_rows`, `portfolio_overview`, `ASSET_CLASSES`,
  `asset_class_of`; `serialize`, `ToolRefusal`.
- Produces: `search_instruments(session, query, limit=10) -> list[Candidate]`,
  `Candidate(instrument, held: bool, exact: bool)`; обработчики
  `instruments.find_instrument(session, query, limit=10)` и
  `positions.positions(session, account_id=None, asset_class=None,
  unpriced_only=False)`.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_ai_positions.py`:

```python
from decimal import Decimal

from app.ai.registry import run_tool
from app.models import Instrument
from tests.test_analytics import add_account, add_priced_position, seed


def test_positions_are_sorted_by_value_with_shares_of_the_whole(session):
    seed(session)
    result = run_tool(session, "positions", {})
    assert [row["name"] for row in result["rows"]] == ["OFZ", "Сбербанк", "TMOS"]
    assert result["rows"][0]["value_rub"] == "5050.00"
    assert result["rows"][0]["share"] == "0.6871"
    assert result["rows"][0]["account"]["title"] == "Брокерский (acc-1)"
    assert result["total_value_rub"] == "7350.00"
    assert isinstance(result["rows"][0]["instrument_id"], int)


def test_positions_filter_by_class_and_refuse_unknown_class(session):
    seed(session)
    bonds = run_tool(session, "positions", {"asset_class": "bonds"})
    assert [row["name"] for row in bonds["rows"]] == ["OFZ"]
    assert "Класса «equities» нет" in run_tool(session, "positions", {"asset_class": "equities"})["error"]


def test_unknown_account_is_refused_with_the_list_of_known(session):
    seed(session)
    error = run_tool(session, "positions", {"account_id": 999})["error"]
    assert "Счёта 999 нет" in error
    assert "Брокерский (acc-1)" in error


def test_unpriced_only_names_the_reason(session):
    account = add_account(session)
    add_priced_position(session, account, "RU000A0JQUZ6", Decimal("5"), price=None)
    add_priced_position(session, account, "RU0009029540", Decimal("1"), Decimal("100"))
    result = run_tool(session, "positions", {"unpriced_only": True})
    assert [row["isin"] for row in result["rows"]] == ["RU000A0JQUZ6"]
    assert result["rows"][0]["value_rub"] is None
    assert "котировки нет" in result["rows"][0]["profit_reason"]


def test_find_instrument_ranks_exact_ticker_first_and_flags_held(session):
    """Два инструмента под одним тикером T — AT&T и Т-Технологии (попутный
    долг роадмепа): оба возвращаются, различить их даёт название и валюта."""
    seed(session)
    session.add_all([
        Instrument(isin="US00206R1023", ticker="T", secid="T", kind="share", currency="USD",
                   issuer="AT&T"),
        Instrument(isin="RU000A107UL4", ticker="T", secid="T", kind="share", currency="RUB",
                   issuer="Т-Технологии"),
    ])
    session.flush()
    result = run_tool(session, "find_instrument", {"query": "T"})
    names = [candidate["name"] for candidate in result["candidates"]]
    assert names[:2] == ["AT&T", "Т-Технологии"]
    assert "разные бумаги" in result["note"]

    sber = run_tool(session, "find_instrument", {"query": "сбер"})["candidates"][0]
    assert sber["ticker"] == "SBER"
    assert sber["held"] is True
    assert sber["asset_class"] == "equity"


def test_find_instrument_with_nothing_found_says_so(session):
    result = run_tool(session, "find_instrument", {"query": "несуществующее"})
    assert result["candidates"] == []
    assert "Ничего не найдено" in result["note"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_positions.py -v`
Expected: FAIL — `KeyError: 'positions'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/instruments/search.py`:

```python
"""Поиск бумаги по строке — для ассистента и для всех, кому нужно превратить
«Озон» в идентификатор.

Живёт в справочнике, а не в инструменте: правило «что считать совпадением»
одно на проект, и панель чата фазы 5b позовёт его напрямую.
"""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Instrument, Position

# Кандидатов читается больше, чем отдаётся: ранжирование — в Python, и точное
# совпадение тикера обязано попасть в ответ даже при сотне частичных.
FETCH_LIMIT = 50


@dataclass(frozen=True)
class Candidate:
    instrument: Instrument
    # Есть ли открытая позиция по бумаге хотя бы на одном счёте.
    held: bool
    # Точное совпадение тикера, ISIN или биржевого кода — такие идут первыми.
    exact: bool


def search_instruments(session: Session, query: str, limit: int = 10) -> list[Candidate]:
    text = query.strip()
    if not text:
        return []
    pattern = f"%{text}%"
    rows = session.execute(
        select(Instrument).where(or_(
            Instrument.ticker.ilike(pattern), Instrument.secid.ilike(pattern),
            Instrument.isin.ilike(pattern), Instrument.issuer.ilike(pattern),
        )).limit(FETCH_LIMIT)
    ).scalars().all()
    held = set(session.execute(
        select(Position.instrument_id).where(Position.quantity != 0)
    ).scalars())

    upper = text.upper()
    candidates = [
        Candidate(
            instrument=row, held=row.id in held,
            exact=upper in {(row.ticker or "").upper(), (row.isin or "").upper(),
                            (row.secid or "").upper()},
        )
        for row in rows
    ]
    # Точные раньше частичных, открытые раньше проданных, дальше по имени.
    # Порядок задан здесь, а не у читателя: у выдачи несколько потребителей.
    candidates.sort(key=lambda candidate: (
        not candidate.exact, not candidate.held,
        (candidate.instrument.issuer or candidate.instrument.ticker or "").lower(),
    ))
    return candidates[:limit]
```

Создать `backend/app/ai/tools/instruments.py`:

```python
"""Инструмент find_instrument: превратить «Озон» в идентификатор.

Нужен не для удобства: без него модель начнёт угадывать тикеры и однажды
спутает T (AT&T) с T (Т-Технологии).
"""

from typing import Annotated

from pydantic import Field
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.analytics.service import asset_class_of
from app.instruments.search import search_instruments

NOTE_EMPTY = "Ничего не найдено: проверь написание или спроси по ISIN."
NOTE_MANY = ("Несколько кандидатов — это разные бумаги, даже с одним тикером (T — и AT&T, и "
             "Т-Технологии): выбирай по названию, валюте и признаку held.")


def find_instrument(
    session: Session,
    query: Annotated[str, Field(description=(
        "Тикер, ISIN, биржевой код или часть названия эмитента: «OZON», «Озон», «RU000A101234»"))],
    limit: Annotated[int, Field(ge=1, le=25, description="Сколько кандидатов вернуть")] = 10,
) -> dict:
    candidates = search_instruments(session, query, limit)
    return {
        "query": query,
        "candidates": [
            {**s.instrument_ref(candidate.instrument),
             "kind": candidate.instrument.kind, "currency": candidate.instrument.currency,
             "asset_class": asset_class_of(candidate.instrument),
             "held": candidate.held, "exact_match": candidate.exact}
            for candidate in candidates
        ],
        "note": NOTE_EMPTY if not candidates else NOTE_MANY if len(candidates) > 1 else None,
    }
```

Создать `backend/app/ai/tools/positions.py`:

```python
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
    if not row.cost_basis_known:
        return REASON_NO_COST_BASIS
    if row.market_value is None:
        return REASON_NO_PRICE
    if row.value_base is None:
        return REASON_NO_RATE
    if row.profit is None:
        return REASON_CURRENCY_MISMATCH
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
        "note": ("share — доля от всего портфеля (total_value_rub), включая деньги. profit — "
                 "нереализованная прибыль к средней цене, в валюте бумаги; null с причиной в "
                 "profit_reason. Цена с price_source=tbank — оценка брокера, не биржи."),
    }
```

В `backend/app/ai/registry.py`: импорт заменить на
`from app.ai.tools import instruments, overview, positions`; в `TOOLS` после
`portfolio_overview` вставить запись `positions`, а `find_instrument` — в конец:

```python
    ToolSpec(
        name="positions",
        description=("Открытые позиции: бумага, счёт, класс, количество, средняя цена против "
                     "текущей, стоимость в рублях, доля портфеля, прибыль либо причина её "
                     "отсутствия. Фильтры по счёту, классу и «только неоценённые»."),
        handler=positions.positions,
    ),
    …
    ToolSpec(
        name="find_instrument",
        description=("Найти бумагу по тикеру, ISIN или названию и получить её instrument_id для "
                     "ledger и instrument_prices. Тикеры не уникальны — всегда искать здесь, а "
                     "не угадывать."),
        handler=instruments.find_instrument,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_positions.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/instruments/search.py backend/app/ai/tools/instruments.py backend/app/ai/tools/positions.py backend/app/ai/registry.py backend/tests/test_ai_positions.py
git commit -m "feat: инструменты positions и find_instrument"
```

---

### Задача 9: `returns`, `value_history`, `instrument_prices`

**Files:**
- Create: `backend/app/ai/tools/returns.py`
- Create: `backend/app/ai/tools/history.py`
- Modify: `backend/app/ai/registry.py` (импорт и три записи в `TOOLS`)
- Test: `backend/tests/test_ai_returns.py`, `backend/tests/test_ai_history.py`

**Interfaces:**
- Consumes: `returns_report`, `PERIOD_*`, `REASON_*`, `PeriodError` (задача 6);
  `incomplete_days`; `prices` через `Price`, `SOURCE_PRIORITY`, `PRICE_MAX_AGE`;
  `serialize.thin/auto_granularity`.
- Produces: обработчики `returns.returns(session, period="all", since=None,
  until=None, breakdown="asset_classes", instruments_limit=30)`,
  `history.value_history(session, since=None, until=None, granularity="auto")`,
  `history.instrument_prices(session, instrument_id, since=None, until=None,
  granularity="auto")`.

- [ ] **Step 1: Write the failing tests**

Создать `backend/tests/test_ai_returns.py`:

```python
from datetime import date

from app.ai.registry import run_tool
from app.models import OperationType
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_snapshot


def test_returns_shape_and_all_breakdowns(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 1, 10), amount="100000")
    add_snapshot(session, date(2024, 1, 10), "100000")
    result = run_tool(session, "returns", {"period": "all", "breakdown": "all"})
    assert result["period"]["from"] == "2024-01-10"
    assert isinstance(result["portfolio"]["profit_rub"], str)
    assert result["twr_coverage"]["days_total"] == 1
    assert "by_account" in result
    assert "by_asset_class" in result
    assert "by_instrument" in result
    assert result["unattributed"]["profit_rub"] == "0.00"


def test_returns_default_breakdown_is_by_asset_class_only(session, account):
    add_snapshot(session, date(2024, 1, 10), "100000")
    result = run_tool(session, "returns", {})
    assert "by_asset_class" in result
    assert "by_account" not in result
    assert "by_instrument" not in result


def test_returns_without_history_is_a_refusal(session):
    assert "снимков" in run_tool(session, "returns", {})["error"]


def test_returns_custom_period_needs_bounds_and_refuses_gently(session, account):
    add_snapshot(session, date(2024, 1, 10), "100000")
    assert "custom" in run_tool(session, "returns", {"period": "all", "since": date(2024, 1, 1)})["error"]
    assert "хотя бы началом" in run_tool(session, "returns", {"period": "custom"})["error"]


def test_instruments_breakdown_is_limited_and_says_so(session, account):
    for number in range(3):
        instrument = add_instrument(session, isin=f"RU00000000{number:02d}", ticker=f"T{number}")
        add_tx(session, account_id=account.id, op_type=OperationType.BUY, day=date(2024, 1, 11),
               amount="-1000", quantity="1", price="1000", instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 10), "3000")
    result = run_tool(session, "returns", {"breakdown": "instruments", "instruments_limit": 2})
    assert len(result["by_instrument"]) == 2
    assert result["by_instrument_total"] == 3
    assert result["by_instrument_truncated"] is True
    # Причина названа словами, а не кодом.
    assert result["by_instrument"][0]["reason"] == "нет цены на конец периода"
```

Создать `backend/tests/test_ai_history.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from app.ai.registry import run_tool
from app.models import Price
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_price, add_snapshot


def test_value_history_thins_long_series_and_counts_incomplete_days(session):
    start = date(2024, 1, 1)
    for offset in range(400):
        add_snapshot(session, start + timedelta(days=offset), str(100000 + offset),
                     valued=1 if offset % 2 else 0)
    result = run_tool(session, "value_history", {})
    assert result["granularity"] == "week"
    assert result["points_total"] == 400
    assert result["points_returned"] < 70
    assert result["points"][-1]["date"] == (start + timedelta(days=399)).isoformat()
    assert result["points"][-1]["complete"] is True
    assert result["days_incomplete"] == 200


def test_value_history_window_and_refusal(session):
    add_snapshot(session, date(2026, 1, 1), "1")
    result = run_tool(session, "value_history", {"since": date(2026, 1, 1), "until": date(2026, 1, 31)})
    assert result["points_total"] == 1
    assert result["granularity"] == "day"
    assert result["points"][0]["value_rub"] == "1.00"
    empty = run_tool(session, "value_history", {"since": date(2025, 1, 1), "until": date(2025, 1, 31)})
    assert "нет" in empty["error"]


def test_instrument_prices_names_gaps_and_prefers_exchange_price(session):
    instrument = add_instrument(session)
    add_price(session, instrument.id, date(2026, 1, 1), "100")
    add_price(session, instrument.id, date(2026, 1, 2), "101")
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 1, 2), close=Decimal("999"),
                      currency="RUB", source="tbank"))
    add_price(session, instrument.id, date(2026, 1, 22), "105")
    result = run_tool(session, "instrument_prices", {"instrument_id": instrument.id})
    assert [point["close"] for point in result["points"]] == ["100.0000", "101.0000", "105.0000"]
    assert result["gaps"] == [{"from": "2026-01-02", "to": "2026-01-22", "days": 20}]
    assert result["instrument"]["ticker"] == "AGRO"


def test_instrument_prices_refuses_unknown_instrument(session):
    assert "find_instrument" in run_tool(session, "instrument_prices", {"instrument_id": 12345})["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_ai_returns.py tests/test_ai_history.py -v`
Expected: FAIL — `KeyError: 'returns'`, `KeyError: 'value_history'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/ai/tools/returns.py`:

```python
"""Инструмент returns: XIRR, TWR с измеренной долей периода, прибыль, разрезы."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.models import Account
from app.returns.metrics import Metric, PeriodError
from app.returns.service import (
    PERIOD_CUSTOM,
    REASON_CASH,
    REASON_EMPTY_PERIOD,
    REASON_NO_FLOWS,
    REASON_NO_FULL_DAYS,
    REASON_NO_HISTORY,
    REASON_NO_SOLUTION,
    REASON_SERIES_GAPS,
    returns_report,
)

# Причины — словами, теми же, что на экране «Аналитика». Четыре последних —
# ключи разложения прибыли (app/returns/fx_split.py) — записаны литералами,
# как во фронте: это контракт строки разреза, а не внутренняя константа.
REASON_TEXTS = {
    REASON_NO_FLOWS: "пополнений и изъятий за период не было — доходность вложений посчитать не из чего",
    REASON_NO_SOLUTION: "потоки есть, но уравнение ставки решения не имеет: недостаточно данных",
    REASON_NO_HISTORY: "истории стоимости за период нет",
    REASON_NO_FULL_DAYS: "ни одного дня с полной оценкой — TWR измерить не на чем, не хватает цен",
    REASON_SERIES_GAPS: "в ряду стоимостей дыры — цепочка TWR рвётся",
    REASON_CASH: "у денег доходности нет: проценты приходят отдельными записями",
    REASON_EMPTY_PERIOD: "период нулевой длины — ещё не прошло ни дня",
    "no_price": "нет цены на конец периода",
    "no_rate": "нет курса валюты",
    "no_cost_basis": "бумага пришла переводом, себестоимость неизвестна",
    "currency_mismatch": "расчёты и котировка в разных валютах",
}

Breakdown = Literal["none", "accounts", "asset_classes", "instruments", "all"]


def _reason(code: str | None) -> str | None:
    return None if code is None else REASON_TEXTS.get(code, code)


def _metric(metric: Metric) -> dict:
    return {
        "xirr": s.rate(metric.xirr), "twr": s.rate(metric.twr),
        "profit_rub": s.amount(metric.profit), "invested_rub": s.amount(metric.invested),
        "value_rub": s.amount(metric.value), "twr_measured_days": metric.chain_days,
        "reason": _reason(metric.reason),
    }


def returns(
    session: Session,
    period: Annotated[Literal["all", "12m", "ytd", "custom"], Field(
        description="Период: всё время, 12 месяцев, с начала года или custom с границами since/until")] = "all",
    since: Annotated[date | None, Field(
        description="Начало произвольного периода, ГГГГ-ММ-ДД (только при period=custom)")] = None,
    until: Annotated[date | None, Field(
        description="Конец произвольного периода; по умолчанию сегодня (только при period=custom)")] = None,
    breakdown: Annotated[Breakdown, Field(
        description="Какие разрезы вернуть: accounts, asset_classes, instruments, all или none")] = "asset_classes",
    instruments_limit: Annotated[int, Field(ge=1, le=300, description=(
        "Сколько строк разреза по бумагам вернуть; порядок: открытые раньше закрытых, "
        "по стоимости и модулю прибыли"))] = 30,
) -> dict:
    if period != PERIOD_CUSTOM and (since is not None or until is not None):
        raise ToolRefusal("Границы since/until действуют только при period=custom")
    try:
        report = returns_report(session, period, since=since, until=until)
    except PeriodError as error:
        raise ToolRefusal(str(error)) from error

    bounds = report.period
    if bounds.since is None:
        raise ToolRefusal("Истории стоимости нет: снимков в базе ещё нет, доходность считать не из чего")

    coverage = report.coverage
    result: dict = {
        "period": {
            "key": bounds.key, "from": s.day(bounds.since), "to": s.day(bounds.until),
            "annualized": bounds.annualized,
            "note": None if bounds.annualized else "период короче года: ставки за период, не в годовых",
        },
        "portfolio": _metric(report.portfolio),
        "twr_coverage": {
            "measured_days": coverage.chain_days, "days_total": coverage.days_total,
            "days_fully_valued": coverage.days_valued, "chain_breaks": coverage.chain_breaks,
            "note": ("TWR измерен только на днях с полной оценкой; годовая ставка приведена по "
                     "measured_days, а не по длине периода. XIRR от дыр в ценах не зависит."),
        },
        "coverage": {
            "positions_total": coverage.positions_total, "positions_valued": coverage.positions_valued,
            "unpriced": coverage.unpriced, "currencies_without_rate": coverage.currencies_without_rate,
        },
        "unattributed": {
            "profit_rub": s.amount(report.unattributed.profit),
            "fees_rub": s.amount(report.unattributed.fees),
            "taxes_rub": s.amount(report.unattributed.taxes),
            "other_rub": s.amount(report.unattributed.other),
            "note": "комиссии, налоги и возвраты без привязки к бумаге — строка «Прочее»",
        },
    }

    if breakdown in ("accounts", "all"):
        accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
        result["by_account"] = [
            {**s.account_ref(accounts[row.account_id]), **_metric(row.metric)}
            for row in report.by_account if row.account_id in accounts
        ]
    if breakdown in ("asset_classes", "all"):
        result["by_asset_class"] = [
            {"asset_class": row.asset_class, **_metric(row.metric)} for row in report.by_asset_class
        ]
    if breakdown in ("instruments", "all"):
        rows = report.by_instrument
        result["by_instrument"] = [
            {"instrument_id": row.instrument_id, "name": row.name, "ticker": row.ticker,
             "xirr": s.rate(row.xirr), "profit_rub": s.amount(row.profit),
             "value_rub": s.amount(row.value), "closed": row.closed,
             "unrealized_rub": s.amount(row.unrealized),
             "price_part_rub": s.amount(row.price_part), "fx_part_rub": s.amount(row.fx_part),
             "reason": _reason(row.reason)}
            for row in rows[:instruments_limit]
        ]
        result["by_instrument_total"] = len(rows)
        result["by_instrument_truncated"] = len(rows) > instruments_limit
        result["instruments_without_profit"] = [row.name for row in rows if row.profit is None]
    return result
```

Создать `backend/app/ai/tools/history.py`:

```python
"""Инструменты value_history и instrument_prices: как двигалась стоимость и
цена, с пометкой дней неполной оценки и дыр в ряду."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.marketdata.service import PRICE_MAX_AGE, SOURCE_PRIORITY
from app.models import DailySnapshot, Instrument, Price
from app.returns.metrics import incomplete_days

Granularity = Literal["auto", "day", "week", "month"]
_UNKNOWN_PRIORITY = 99


def _granularity(requested: str, first: date, last: date) -> str:
    return s.auto_granularity((last - first).days) if requested == "auto" else requested


def value_history(
    session: Session,
    since: Annotated[date | None, Field(description="С даты, ГГГГ-ММ-ДД; по умолчанию с первой точки")] = None,
    until: Annotated[date | None, Field(description="По дату; по умолчанию до последней")] = None,
    granularity: Annotated[Granularity, Field(description=(
        "Шаг ряда: auto подбирает по длине окна — день до 120 дней, неделя до двух лет, дальше месяц"))] = "auto",
) -> dict:
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    query = select(DailySnapshot).order_by(DailySnapshot.on_date)
    if since is not None:
        query = query.where(DailySnapshot.on_date >= since)
    if until is not None:
        query = query.where(DailySnapshot.on_date <= until)
    rows = list(session.execute(query).scalars().all())
    if not rows:
        raise ToolRefusal("Снимков стоимости за это окно нет")

    used = _granularity(granularity, rows[0].on_date, rows[-1].on_date)
    kept = s.thin(rows, lambda row: row.on_date, used)
    # Правило «какой день полный» — одно на проект (app/returns/metrics.py):
    # неизвестное покрытие считается неполным там же, где рвётся цепочка TWR.
    incomplete = incomplete_days(rows)
    return {
        "from": s.day(rows[0].on_date), "to": s.day(rows[-1].on_date),
        "granularity": used, "points_total": len(rows), "points_returned": len(kept),
        "days_incomplete": len(incomplete),
        "points": [
            {"date": s.day(row.on_date), "value_rub": s.amount(row.total_value),
             "source": row.source, "complete": row.on_date not in incomplete,
             "unpriced": list(row.unpriced or [])}
            for row in kept
        ],
        "note": ("complete=false — в этот день часть позиций без цены, стоимость занижена (у "
                 "снимков без посчитанного покрытия — тоже false). Прореженный ряд оставляет "
                 "последнюю точку каждого шага; source=backfill — точка достроена задним числом."),
    }


def instrument_prices(
    session: Session,
    instrument_id: Annotated[int, Field(description="Идентификатор бумаги из find_instrument или positions")],
    since: Annotated[date | None, Field(description="С даты, ГГГГ-ММ-ДД")] = None,
    until: Annotated[date | None, Field(description="По дату")] = None,
    granularity: Annotated[Granularity, Field(description="Шаг ряда, как у value_history")] = "auto",
) -> dict:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise ToolRefusal(f"Бумаги с идентификатором {instrument_id} нет — найди её через find_instrument")
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    query = select(Price).where(Price.instrument_id == instrument_id).order_by(Price.on_date)
    if since is not None:
        query = query.where(Price.on_date >= since)
    if until is not None:
        query = query.where(Price.on_date <= until)

    # Одна цена на дату: при двух источниках приоритет тот же, что у оценки
    # (биржа, затем независимый источник, затем брокер).
    best: dict[date, Price] = {}
    for row in session.execute(query).scalars():
        current = best.get(row.on_date)
        if (current is None or SOURCE_PRIORITY.get(row.source, _UNKNOWN_PRIORITY)
                < SOURCE_PRIORITY.get(current.source, _UNKNOWN_PRIORITY)):
            best[row.on_date] = row
    series = [best[on_date] for on_date in sorted(best)]
    if not series:
        raise ToolRefusal(f"Котировок по {s.instrument_name(instrument)} за это окно нет")

    gaps = [
        {"from": s.day(earlier.on_date), "to": s.day(later.on_date),
         "days": (later.on_date - earlier.on_date).days}
        for earlier, later in zip(series, series[1:])
        if later.on_date - earlier.on_date > PRICE_MAX_AGE
    ]
    used = _granularity(granularity, series[0].on_date, series[-1].on_date)
    kept = s.thin(series, lambda row: row.on_date, used)
    return {
        "instrument": s.instrument_ref(instrument),
        "from": s.day(series[0].on_date), "to": s.day(series[-1].on_date),
        "granularity": used, "points_total": len(series), "points_returned": len(kept),
        "points": [{"date": s.day(row.on_date), "close": s.price(row.close),
                    "currency": row.currency, "source": row.source} for row in kept],
        "gaps": gaps,
        "note": (f"Дыра — разрыв больше {PRICE_MAX_AGE.days} дней между соседними котировками: в "
                 "такие дни бумага не оценивалась. Цена облигации — в деньгах за бумагу, не в "
                 "процентах номинала."),
    }
```

В `backend/app/ai/registry.py`: импорт — `from app.ai.tools import history,
instruments, overview, positions, returns`; в `TOOLS` после `positions`
вставить три записи в порядке дизайна:

```python
    ToolSpec(
        name="returns",
        description=("Доходность за период: XIRR, TWR с числом измеренных дней и разрывов, "
                     "прибыль, вложено, стоимость, разрезы по счетам, классам и бумагам, строка "
                     "«Прочее». Периоды all, 12m, ytd или custom с since/until."),
        handler=returns.returns,
    ),
    ToolSpec(
        name="value_history",
        description=("Как двигалась стоимость портфеля по дням: ряд снимков в окне дат с "
                     "пометкой дней неполной оценки и бумаг без цены в каждый из них."),
        handler=history.value_history,
    ),
```

и после `ledger` (задача 10 добавит его; до неё — сразу после `value_history`):

```python
    ToolSpec(
        name="instrument_prices",
        description=("Как двигалась цена одной бумаги: ряд котировок с источником и валютой и "
                     "перечень дыр в ряду. Нужен instrument_id из find_instrument."),
        handler=history.instrument_prices,
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_ai_returns.py tests/test_ai_history.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/tools/returns.py backend/app/ai/tools/history.py backend/app/ai/registry.py backend/tests/test_ai_returns.py backend/tests/test_ai_history.py
git commit -m "feat: инструменты returns, value_history и instrument_prices"
```

---

### Задача 10: `ledger`

**Files:**
- Create: `backend/app/ai/tools/ledger.py`
- Modify: `backend/app/ai/registry.py` (импорт и запись между `value_history` и `instrument_prices`)
- Test: `backend/tests/test_ai_ledger.py`

**Interfaces:**
- Consumes: `Transaction`, `OperationType`, `moscow_date`, `moscow_day_end`,
  `MOSCOW_TZ`; `serialize`, `ToolRefusal`.
- Produces: обработчик `ledger.ledger(session, instrument_id=None,
  account_id=None, op_types=None, since=None, until=None, limit=100,
  offset=0)`: строки самые новые первыми, агрегаты по всей выборке, признак
  усечения.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_ai_ledger.py`:

```python
from datetime import date, timezone

from app.ai.registry import run_tool
from app.models import OperationType
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument


def test_ledger_aggregates_whole_selection_but_pages_rows(session, account):
    """Журнал — двенадцать тысяч операций: страница — сотня, а итог считается
    по всей выборке. Без агрегатов модель посчитала бы итог по первой странице
    и не заметила бы подмены."""
    instrument = add_instrument(session)
    for day_no in (1, 2, 3):
        add_tx(session, account_id=account.id, op_type=OperationType.BUY,
               day=date(2024, 3, day_no), amount="-1000", quantity="1", price="1000",
               instrument_id=instrument.id, fee="-5")
    add_tx(session, account_id=account.id, op_type=OperationType.DIVIDEND,
           day=date(2024, 4, 1), amount="300", instrument_id=instrument.id)

    result = run_tool(session, "ledger", {"instrument_id": instrument.id, "limit": 2})
    assert result["total"] == 4
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["rows"][0]["date"] == "2024-04-01"
    assert result["rows"][0]["instrument"]["ticker"] == "AGRO"
    assert {(row["op_type"], row["count"], row["amount"]) for row in result["sums"]} == {
        ("BUY", 3, "-3000.00"), ("DIVIDEND", 1, "300.00"),
    }
    assert result["date_range"] == {"from": "2024-03-01", "to": "2024-04-01"}


def test_ledger_day_bounds_are_moscow_days(session, account):
    """21:00 UTC 1 марта — это уже полночь 2 марта по Москве: календарная дата
    операции обязана совпадать с той, в которой живут снимки."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100", at_hour=21, tz=timezone.utc)
    assert run_tool(session, "ledger", {"since": date(2024, 3, 2), "until": date(2024, 3, 2)})["total"] == 1
    assert run_tool(session, "ledger", {"until": date(2024, 3, 1)})["total"] == 0


def test_ledger_refuses_unknown_op_type_listing_known(session):
    error = run_tool(session, "ledger", {"op_types": ["PURCHASE"]})["error"]
    assert "PURCHASE" in error
    assert "BUY" in error


def test_ledger_filters_by_op_type_case_insensitively(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100")
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 3, 1), amount="-1")
    assert run_tool(session, "ledger", {"op_types": ["deposit"]})["total"] == 1


def test_ledger_refuses_unknown_instrument_and_account(session):
    assert "find_instrument" in run_tool(session, "ledger", {"instrument_id": 999})["error"]
    assert "Счёта 999 нет" in run_tool(session, "ledger", {"account_id": 999})["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_ledger.py -v`
Expected: FAIL — `KeyError: 'ledger'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/ai/tools/ledger.py`:

```python
"""Инструмент ledger: что происходило — операции плюс агрегаты по всей выборке.

Журнал — двенадцать тысяч операций. Страница ограничена, агрегаты считаются по
всей выборке, и признак усечения едет в ответе: без него модель посчитала бы
итог по первой сотне и не заметила бы подмены (дизайн, раздел 4.1).
"""

from datetime import date, datetime, time
from typing import Annotated

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.models import Account, Instrument, OperationType, Transaction
from app.timeutils import MOSCOW_TZ, moscow_date, moscow_day_end

MAX_LIMIT = 500
OP_TYPES_HELP = ", ".join(member.value for member in OperationType)


def ledger(
    session: Session,
    instrument_id: Annotated[int | None, Field(
        description="Только операции по этой бумаге (идентификатор из find_instrument)")] = None,
    account_id: Annotated[int | None, Field(
        description="Только этот счёт (account_id из portfolio_overview)")] = None,
    op_types: Annotated[list[str] | None, Field(
        description=f"Только эти типы операций: {OP_TYPES_HELP}")] = None,
    since: Annotated[date | None, Field(description="С даты по Москве, ГГГГ-ММ-ДД")] = None,
    until: Annotated[date | None, Field(description="По дату по Москве включительно")] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT, description=(
        "Сколько строк вернуть; агрегаты sums и date_range считаются по всей выборке"))] = 100,
    offset: Annotated[int, Field(ge=0, description="Смещение для следующей страницы")] = 0,
) -> dict:
    types: list[OperationType] = []
    for raw in op_types or []:
        try:
            types.append(OperationType(raw.upper()))
        except ValueError:
            raise ToolRefusal(f"Типа операции «{raw}» нет. Известные: {OP_TYPES_HELP}") from None
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    if instrument_id is not None and session.get(Instrument, instrument_id) is None:
        raise ToolRefusal(f"Бумаги с идентификатором {instrument_id} нет — найди её через find_instrument")
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    if account_id is not None and account_id not in accounts:
        known = ", ".join(f"{account.id} — {s.account_ref(account)['title']}"
                          for account in accounts.values())
        raise ToolRefusal(f"Счёта {account_id} нет. Известные счета: {known or 'ни одного'}")

    conditions = []
    if instrument_id is not None:
        conditions.append(Transaction.instrument_id == instrument_id)
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if types:
        conditions.append(Transaction.op_type.in_(types))
    if since is not None:
        # Границы дня — московские, как у снимков и графика (app/timeutils.py).
        conditions.append(Transaction.executed_at >= datetime.combine(since, time.min, tzinfo=MOSCOW_TZ))
    if until is not None:
        conditions.append(Transaction.executed_at < moscow_day_end(until))

    total, first, last = session.execute(
        select(func.count(Transaction.id), func.min(Transaction.executed_at),
               func.max(Transaction.executed_at)).where(*conditions)
    ).one()
    sums = session.execute(
        select(Transaction.op_type, Transaction.currency, func.count(Transaction.id),
               func.sum(Transaction.amount), func.sum(Transaction.fee))
        .where(*conditions)
        .group_by(Transaction.op_type, Transaction.currency)
        .order_by(Transaction.op_type, Transaction.currency)
    ).all()
    rows = session.execute(
        select(Transaction).where(*conditions)
        .order_by(Transaction.executed_at.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    ).scalars().all()

    return {
        "filter": {"instrument_id": instrument_id, "account_id": account_id,
                   "op_types": [member.value for member in types] or None,
                   "since": s.day(since), "until": s.day(until)},
        "total": total, "offset": offset, "limit": limit, "returned": len(rows),
        "truncated": offset + len(rows) < total,
        "date_range": {"from": s.day(moscow_date(first)) if first else None,
                       "to": s.day(moscow_date(last)) if last else None},
        "sums": [
            {"op_type": getattr(op_type, "value", op_type), "currency": currency, "count": count,
             "amount": s.amount(amount), "fee": s.amount(fee)}
            for op_type, currency, count, amount, fee in sums
        ],
        "rows": [
            {"id": row.id, "date": s.day(moscow_date(row.executed_at)),
             "executed_at": s.moment(row.executed_at),
             "account": s.account_ref(accounts[row.account_id]) if row.account_id in accounts else None,
             "op_type": row.op_type.value,
             "instrument": s.instrument_ref(row.instrument) if row.instrument is not None else None,
             "quantity": s.qty(row.quantity), "price": s.price(row.price),
             "amount": s.amount(row.amount), "currency": row.currency, "fee": s.amount(row.fee),
             "source": row.source}
            for row in rows
        ],
        "note": ("Знак amount — с точки зрения счёта: покупка и комиссия отрицательны, продажа и "
                 "выплаты положительны. Строки — самые новые первыми; sums и date_range посчитаны "
                 "по всей выборке, а не по странице. source=manual — запись, порождённая решением "
                 "владельца по расхождению."),
    }
```

В `backend/app/ai/registry.py`: добавить `ledger` в импорт из `app.ai.tools`;
в `TOOLS` между `value_history` и `instrument_prices` вставить:

```python
    ToolSpec(
        name="ledger",
        description=("Журнал операций: что происходило по бумаге, счёту, типу операции и датам. "
                     "Страница строк плюс агрегаты по всей выборке (количество, суммы по типам и "
                     "валютам, диапазон дат) и признак усечения."),
        handler=ledger.ledger,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_ledger.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/tools/ledger.py backend/app/ai/registry.py backend/tests/test_ai_ledger.py
git commit -m "feat: инструмент ledger с агрегатами по всей выборке"
```

---

### Задача 11: `data_quality` и `allocation`

**Files:**
- Create: `backend/app/ai/tools/quality.py`
- Create: `backend/app/ai/tools/allocation.py`
- Modify: `backend/app/ai/registry.py` (импорт и две записи между `instrument_prices` и `find_instrument`)
- Test: `backend/tests/test_ai_quality.py`, `backend/tests/test_ai_allocation.py`

**Interfaces:**
- Consumes: `Reconciliation`, `BrokerHolding`, `CashBalance`, `SyncRun`,
  `DailySnapshot`, `incomplete_days`, `portfolio_overview`;
  `allocation_report` (задача 3).
- Produces: обработчики `quality.data_quality(session)` и
  `allocation.allocation(session, contribution_rub: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

Создать `backend/tests/test_ai_quality.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.ai.registry import run_tool
from app.models import DailySnapshot, Instrument, Reconciliation, SyncRun
from tests.test_analytics import seed


def test_data_quality_names_reconciliations_unpriced_days_and_sync(session):
    account = seed(session)
    sber = session.execute(select(Instrument).where(Instrument.ticker == "SBER")).scalar_one()
    session.add(Reconciliation(account_id=account.id, instrument_id=sber.id, isin=sber.isin,
                               ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
                               status="quantity_mismatch"))
    for day in (date(2026, 1, 1), date(2026, 1, 2)):
        session.add(DailySnapshot(on_date=day, total_value=Decimal("1"), source="backfill",
                                  positions_total=2, valued_positions=1, unpriced=["HeadHunter"]))
    session.add_all([
        SyncRun(broker="tbank", account_id=account.id, status="failed", error="сеть",
                started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc)),
        SyncRun(broker="tbank", account_id=account.id, status="success", inserted=3,
                started_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
                finished_at=datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc)),
    ])
    session.flush()

    result = run_tool(session, "data_quality", {})
    mismatch = result["reconciliation"]["unresolved"][0]
    assert mismatch["account"]["title"] == "Брокерский (acc-1)"
    assert mismatch["name"] == "Сбербанк"
    assert mismatch["status"] == "quantity_mismatch"
    assert mismatch["ledger_quantity"] == "10"
    assert mismatch["broker_quantity"] == "12"
    assert result["history"]["instruments_without_price"] == [{"name": "HeadHunter", "days": 2}]
    assert result["history"]["days_fully_valued"] == 0
    assert result["history"]["share_fully_valued"] == "0.0000"
    assert result["sync"]["last_runs"] == [{
        **result["sync"]["last_runs"][0], "status": "success", "inserted": 3,
    }]
    assert "valuation_check" in result["broker_total_check"]


def test_data_quality_on_empty_database_answers_without_numbers_made_up(session):
    result = run_tool(session, "data_quality", {})
    assert result["reconciliation"]["count"] == 0
    assert result["history"]["snapshots"] == 0
    assert result["history"]["share_fully_valued"] is None
```

Создать `backend/tests/test_ai_allocation.py`:

```python
from decimal import Decimal

from app.ai.registry import run_tool
from app.allocation.service import TargetInput, replace_targets
from tests.test_allocation_service import two_class_portfolio


def half_and_half(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity"),
                              TargetInput(share=Decimal("0.5"), asset_class="bonds")])


def test_allocation_reports_gap_and_minimal_contribution(session):
    half_and_half(session)
    result = run_tool(session, "allocation", {})
    rows = {row["key"]: row for row in result["targets"]}
    assert rows["equity"]["actual_share"] == "0.6000"
    assert rows["equity"]["deviation_points"] == "10.00"
    assert rows["equity"]["deviation_rub"] == "10000.00"
    assert result["rebalance"]["minimal_contribution_rub"] == "20000.00"
    assert result["rebalance"]["buy_by_group"] == {"equity": "0.00", "bonds": "20000.00"}
    assert result["rebalance"]["contribution_is_custom"] is False
    assert any("лотность" in note for note in result["notes"])


def test_allocation_with_custom_sum_below_minimal_says_so(session):
    half_and_half(session)
    result = run_tool(session, "allocation", {"contribution_rub": "5 000"})
    assert result["rebalance"]["contribution_is_custom"] is True
    assert result["rebalance"]["short_by_rub"] == "15000.00"
    assert result["rebalance"]["not_closed_by_contribution"] == ["equity"]


def test_allocation_without_targets_points_to_settings(session):
    two_class_portfolio(session)
    result = run_tool(session, "allocation", {})
    assert result["targets"][0]["key"] == "unassigned"
    assert any("не заданы" in note for note in result["notes"])


def test_allocation_refuses_unreadable_or_negative_sum(session):
    assert "не читается" in run_tool(session, "allocation", {"contribution_rub": "много"})["error"]
    assert "отрицательной" in run_tool(session, "allocation", {"contribution_rub": "-1"})["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_ai_quality.py tests/test_ai_allocation.py -v`
Expected: FAIL — `KeyError: 'data_quality'`, `KeyError: 'allocation'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/ai/tools/quality.py`:

```python
"""Инструмент data_quality: границы честности — расхождения с брокером, бумаги
без цен, блокировки, свежесть данных.

Это то, что не даёт назвать TWR −25,26 % без оговорки: число измеренных дней,
шесть бумаг без котировок и неразобранные расхождения из таблицы reconciliation.
"""

from collections import Counter
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.analytics.service import portfolio_overview
from app.models import (
    Account,
    BrokerHolding,
    CashBalance,
    DailySnapshot,
    Instrument,
    Reconciliation,
    SyncRun,
)
from app.returns.metrics import incomplete_days

# Денежного итога брокера (totalAmountPortfolio) в базе нет: его знает только
# живой запрос, и инструмент честно называет прогон, которым сверка снимается.
VALUATION_CHECK_NOTE = (
    "Денежной сверки с итогом брокера (totalAmountPortfolio) здесь нет: его знает только "
    "живой запрос к API, и снимает её прогон `cd backend && uv run python -m app.valuation_check`."
)


def data_quality(session: Session) -> dict:
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    instruments = {row.id: row for row in session.execute(select(Instrument)).scalars()}
    overview = portfolio_overview(session)

    def account_of(account_id: int | None) -> dict | None:
        return s.account_ref(accounts[account_id]) if account_id in accounts else None

    def name_of(instrument_id: int | None) -> str | None:
        return s.instrument_name(instruments[instrument_id]) if instrument_id in instruments else None

    reconciliations = [
        {"account": account_of(row.account_id), "isin": row.isin, "name": name_of(row.instrument_id),
         "ledger_quantity": s.qty(row.ledger_quantity), "broker_quantity": s.qty(row.broker_quantity),
         "status": row.status, "checked_at": s.moment(row.checked_at)}
        for row in session.execute(
            select(Reconciliation).order_by(Reconciliation.account_id, Reconciliation.isin)
        ).scalars()
    ]

    snapshots = list(session.execute(select(DailySnapshot).order_by(DailySnapshot.on_date)).scalars())
    incomplete = incomplete_days(snapshots)
    without_price = Counter(name for row in snapshots for name in (row.unpriced or []))
    full_days = len(snapshots) - len(incomplete)

    blocked_holdings = [
        {"account": account_of(row.account_id), "isin": row.isin, "name": name_of(row.instrument_id),
         "quantity": s.qty(row.quantity), "blocked": s.qty(row.blocked)}
        for row in session.execute(select(BrokerHolding).where(BrokerHolding.blocked != 0)).scalars()
    ]
    blocked_cash = [
        {"account": account_of(row.account_id), "currency": row.currency,
         "amount": s.amount(row.amount), "blocked": s.amount(row.blocked)}
        for row in session.execute(select(CashBalance).where(CashBalance.blocked != 0)).scalars()
    ]

    # Последний прогон синхронизации каждого счёта — в порядке запуска, поэтому
    # последний по счёту перетирает предыдущие.
    latest: dict[int | None, SyncRun] = {}
    for run in session.execute(select(SyncRun).order_by(SyncRun.started_at, SyncRun.id)).scalars():
        latest[run.account_id] = run
    last_runs = [
        {"account": account_of(run.account_id), "status": run.status,
         "started_at": s.moment(run.started_at), "finished_at": s.moment(run.finished_at),
         "inserted": run.inserted, "mismatches": run.mismatches, "corrected": run.corrected,
         "error": run.error}
        for run in latest.values()
    ]

    last = snapshots[-1] if snapshots else None
    return {
        "reconciliation": {
            "unresolved": reconciliations, "count": len(reconciliations),
            "note": ("Расхождения количеств журнала с брокером; разбираются решениями владельца на "
                     "экране «Сделки и расхождения», не инструментами."),
        },
        "valuation": {
            "positions_total": overview.positions_total, "valued_positions": overview.valued_positions,
            "unpriced_today": overview.unpriced,
            "currencies_without_rate": overview.currencies_without_rate,
            "restricted_value_rub": s.amount(overview.restricted_value),
            "as_of": s.day(overview.as_of), "fx_as_of": s.day(overview.fx_as_of),
        },
        "history": {
            "snapshots": len(snapshots), "days_fully_valued": full_days,
            "share_fully_valued": (s.rate(Decimal(full_days) / len(snapshots)) if snapshots else None),
            "first_date": s.day(snapshots[0].on_date) if snapshots else None,
            "last_date": s.day(last.on_date) if last else None,
            "last_source": last.source if last else None,
            "instruments_without_price": [{"name": name, "days": days}
                                          for name, days in without_price.most_common()],
            "note": ("Дни с неполной оценкой рвут цепочку TWR: доходность по времени измерена только "
                     "на полных днях (см. returns.twr_coverage). XIRR от этого не зависит."),
        },
        "blocked": {"holdings": blocked_holdings, "cash": blocked_cash},
        "sync": {"last_runs": last_runs},
        "broker_total_check": VALUATION_CHECK_NOTE,
    }
```

Создать `backend/app/ai/tools/allocation.py`:

```python
"""Инструмент allocation: факт против целей, отклонения, сколько докинуть и
куда. Расчёт — в app/allocation/, здесь только форма ответа."""

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import Field
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.allocation.service import allocation_report


def allocation(
    session: Session,
    contribution_rub: Annotated[str | None, Field(description=(
        "Своя сумма пополнения в рублях строкой, например \"100000\". Без неё считается "
        "минимальная сумма, после которой ни одна группа не превышает цель"))] = None,
) -> dict:
    contribution = None
    if contribution_rub is not None:
        try:
            contribution = Decimal(contribution_rub.replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except InvalidOperation:
            raise ToolRefusal(f"Сумма пополнения «{contribution_rub}» не читается как число") from None
        if contribution < 0:
            raise ToolRefusal("Сумма пополнения не может быть отрицательной: продаж расчёт не предлагает")

    report = allocation_report(session, contribution)
    plan = report.rebalance
    return {
        "as_of": s.day(report.as_of),
        "total_value_rub": s.amount(report.total_value),
        "targets": [
            {"kind": row.kind, "key": row.key, "title": row.title,
             "target_share": s.rate(row.target), "actual_share": s.rate(row.actual),
             "value_rub": s.amount(row.value),
             "deviation_points": s.percent(row.deviation_points),
             "deviation_rub": s.amount(row.deviation_rub)}
            for row in report.rows
        ],
        "rebalance": {
            "minimal_contribution_rub": s.amount(plan.minimal_contribution),
            "contribution_rub": s.amount(plan.contribution),
            "contribution_is_custom": contribution is not None,
            "short_by_rub": s.amount(plan.short_by),
            "buy_by_group": {key: s.amount(value) for key, value in plan.deficits.items()},
            "not_closed_by_contribution": plan.not_closed,
            "unfixable_without_selling": {key: s.amount(value) for key, value in plan.unfixable.items()},
        },
        "coverage": {"positions_total": report.positions_total,
                     "valued_positions": report.valued_positions, "unpriced": report.unpriced},
        "notes": report.notes,
    }
```

В `backend/app/ai/registry.py`: импорт — `from app.ai.tools import allocation,
history, instruments, ledger, overview, positions, quality, returns`; между
`instrument_prices` и `find_instrument` вставить:

```python
    ToolSpec(
        name="allocation",
        description=("Факт против целевых долей: доля и отклонение каждой группы, «не задано», "
                     "минимальное пополнение, выравнивающее доли, раскладка по группам и группы, "
                     "которые пополнением не выправить. Своя сумма — contribution_rub."),
        handler=allocation.allocation,
    ),
    ToolSpec(
        name="data_quality",
        description=("Границы честности: неразобранные расхождения с брокером, доля дат с полной "
                     "оценкой, бумаги без котировок с числом дней, блокировки, последняя "
                     "синхронизация и последний снимок. Вызывать, когда спрашивают, можно ли "
                     "доверять цифрам."),
        handler=quality.data_quality,
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_ai_quality.py tests/test_ai_allocation.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/tools/quality.py backend/app/ai/tools/allocation.py backend/app/ai/registry.py backend/tests/test_ai_quality.py backend/tests/test_ai_allocation.py
git commit -m "feat: инструменты data_quality и allocation"
```

---

### Задача 12: MCP-фасад

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (через `uv add`)
- Create: `backend/app/ai/mcp.py`
- Modify: `README.md` (новый раздел перед «Сверка с брокером и расхождения»)
- Test: `backend/tests/test_ai_mcp.py`

**Interfaces:**
- Consumes: `registry.TOOLS`, `registry.INSTRUCTIONS`, `registry.run_tool`;
  `app.db.engine`; `MCPServer` из `mcp.server.mcpserver`.
- Produces: `read_only_sessions(engine=None) -> sessionmaker`;
  `configure_logging()`; `build_server(sessions) -> MCPServer`, где `sessions`
  — вызываемое, возвращающее контекст-менеджер сессии; `main()`;
  `python -m app.ai.mcp`.

- [ ] **Step 1: Добавить зависимость**

Run: `cd backend && uv add "mcp>=2.2,<3"`
Expected: `pyproject.toml` получает строку `"mcp>=2.2,<3",` в `dependencies`,
`uv.lock` обновляется. Проверить: `uv run python -c "from mcp.server.mcpserver import MCPServer; print('ok')"`.

- [ ] **Step 2: Write the failing test**

Создать `backend/tests/test_ai_mcp.py`:

```python
"""Фасад проверяется тонко (дизайн, раздел 7): список инструментов отдаётся,
схемы валидны, stdout чист от логов, попытка записи отбивается базой."""

import asyncio
import json
import logging
import os
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from app.ai import registry
from app.ai.mcp import build_server, configure_logging, read_only_sessions
from app.ai.registry import ToolSpec
from app.models import Account
from tests.conftest import TEST_URL
from tests.test_analytics import seed

# Порядок — таблица дизайна, раздел 4.2.
EXPECTED_TOOLS = ["portfolio_overview", "positions", "returns", "value_history", "ledger",
                  "instrument_prices", "allocation", "data_quality", "find_instrument"]


def run(coroutine):
    return asyncio.run(coroutine)


def test_registry_exposes_the_nine_tools_of_the_design():
    assert [spec.name for spec in registry.TOOLS] == EXPECTED_TOOLS


def test_schemas_hide_the_session_and_describe_every_argument(session):
    server = build_server(lambda: nullcontext(session))
    tools = run(server.list_tools())
    assert [tool.name for tool in tools] == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description, tool.name
        properties = tool.input_schema.get("properties", {})
        assert "session" not in properties, tool.name
        for name, prop in properties.items():
            assert prop.get("description"), f"{tool.name}.{name} без описания"


def test_instructions_separate_portfolio_numbers_from_the_web(session):
    server = build_server(lambda: nullcontext(session))
    assert "только из инструментов" in server.instructions
    assert "источником и датой" in server.instructions
    assert "поисковые запросы" in server.instructions


def test_call_returns_json_with_money_as_strings(session):
    seed(session)
    server = build_server(lambda: nullcontext(session))
    result = run(server.call_tool("portfolio_overview", {}))
    assert result.is_error is False
    body = json.loads(result.content[0].text)
    assert body["total_value_rub"] == "7350.00"


def test_refusal_is_an_answer_not_a_protocol_error(session):
    server = build_server(lambda: nullcontext(session))
    result = run(server.call_tool("positions", {"account_id": 999}))
    assert result.is_error is False
    assert "Счёта 999 нет" in json.loads(result.content[0].text)["error"]


def test_writes_are_rejected_by_the_database():
    """Чтение гарантируется базой, а не договорённостью. Свой движок, а не
    общий test_engine: флаг READ ONLY не должен пережить этот тест."""
    engine = create_engine(TEST_URL)
    try:
        sessions = read_only_sessions(engine)
        with sessions() as session:
            session.add(Account(broker="tbank", kind="broker", external_id="ro-1",
                                name="Проверка", currency="RUB"))
            with pytest.raises(DBAPIError, match="read-only"):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def test_nothing_is_written_to_stdout(session, capsys, monkeypatch):
    """В stdio-транспорте stdout занят протоколом: трейсбек упавшего
    инструмента обязан уйти в stderr, а stdout остаться пустым."""
    configure_logging()

    def broken(session):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.ai.registry.TOOLS", [ToolSpec("broken", "тест", broken)])
    server = build_server(lambda: nullcontext(session))
    result = run(server.call_tool("broken", {}))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "boom" in captured.err
    assert "внутренняя ошибка" in json.loads(result.content[0].text)["error"]
    # Обработчик смотрит в поток capsys, который закроется вместе с тестом;
    # оставить его на корневом логгере — значит сыпать «I/O on closed file» в
    # соседних тестах.
    logging.getLogger().handlers.clear()


def test_stdio_handshake_lists_tools_and_instructions():
    """Настоящий протокол через настоящий stdio: сервер поднимается отдельным
    процессом, как его поднимет Codex. Инициализация и список инструментов в
    базу не ходят, поэтому тест не зависит от данных."""
    backend = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.ai.mcp"],
                                   cwd=str(backend), env=dict(os.environ))

    async def talk():
        async with Client(params) as client:
            listed = await client.list_tools()
            return client.instructions, [tool.name for tool in listed.tools]

    instructions, names = run(talk())
    assert names == EXPECTED_TOOLS
    assert "только из инструментов" in instructions
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_mcp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.mcp'`

- [ ] **Step 4: Write minimal implementation**

Создать `backend/app/ai/mcp.py`:

```python
"""stdio-фасад реестра инструментов (дизайн 5a, раздел 4.3).

Логики здесь нет: реестр транслируется наружу как есть, и добавление
инструмента этот файл не трогает. Процесс живёт ровно столько, сколько сессия
клиента: Codex сам его запускает и гасит.

    cd backend && uv run python -m app.ai.mcp

Регистрация в Codex — одна команда, см. README, раздел «Ассистент».
"""

import inspect
import logging
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager

from mcp.server.mcpserver import MCPServer
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai import registry
from app.db import engine as default_engine

SERVER_NAME = "jarvis"

Sessions = Callable[[], AbstractContextManager[Session]]


def read_only_sessions(engine: Engine | None = None) -> sessionmaker:
    """Фабрика сессий, каждая транзакция которых открыта как READ ONLY.

    Чтение гарантируется базой, а не договорённостью: запись, просочившаяся в
    инструмент по недосмотру, упадёт на уровне Postgres, а не изменит журнал
    тихо. Флаг ставится драйвером при выдаче соединения (postgresql_readonly)
    и снимается при возврате в пул — сессии бэкенда его не наследуют.
    """
    bound = (engine or default_engine).execution_options(postgresql_readonly=True)
    return sessionmaker(bind=bound, expire_on_commit=False)


def configure_logging() -> None:
    """Логи — только в stderr. В stdio-транспорте stdout занят протоколом, и
    одна печать туда рвёт сессию невнятной ошибкой разбора."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _bind(spec: registry.ToolSpec, sessions: Sessions) -> Callable[..., dict]:
    """Обработчик реестра без параметра `session`: сессия открывается на вызов
    и закрывается за ним, а схему входа SDK выводит из оставшейся сигнатуры —
    подпись и аннотации подменяются вместе, SDK читает обе."""
    signature = inspect.signature(spec.handler)
    parameters = [p for p in signature.parameters.values() if p.name != "session"]

    def call(**arguments):
        with sessions() as session:
            return registry.run_tool(session, spec.name, arguments)

    call.__name__ = spec.name
    call.__doc__ = spec.description
    call.__signature__ = signature.replace(parameters=parameters)
    call.__annotations__ = {name: hint for name, hint in spec.handler.__annotations__.items()
                            if name != "session"}
    return call


def build_server(sessions: Sessions) -> MCPServer:
    server = MCPServer(name=SERVER_NAME, instructions=registry.INSTRUCTIONS)
    for spec in registry.TOOLS:
        server.add_tool(_bind(spec, sessions), name=spec.name, description=spec.description)
    return server


def main() -> None:
    configure_logging()
    build_server(read_only_sessions()).run("stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_mcp.py -v`
Expected: PASS, 8 tests. Если `test_writes_are_rejected_by_the_database`
падает не с «read-only», а с другой ошибкой — посмотреть текст: ожидается
`cannot execute INSERT in a read-only transaction` от Postgres. Если
`test_stdio_handshake…` висит — запустить `uv run python -m app.ai.mcp` руками и
посмотреть stderr: сервер обязан молча ждать stdin.

- [ ] **Step 6: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS, 651 прежних + все новые. Особенно смотреть, что после
`test_ai_mcp.py` соседние тесты не падают на «read-only transaction».

- [ ] **Step 7: Дописать README**

В `README.md` перед разделом «Сверка с брокером и расхождения» добавить:

```markdown
## Ассистент: MCP-сервер для Codex

Джарвис отдаёт данные портфеля модели инструментами, а не промптом:
`backend/app/ai/` — реестр из девяти читающих инструментов и stdio-фасад к нему
(протокол MCP). Клиент — Codex CLI на машине владельца; наружу не выставляется
ни один порт, серверу нужен только Postgres на 5433.

Регистрация в Codex — один раз:

    codex mcp add jarvis -- C:/Users/User/.local/bin/uv run --directory C:/jarvis-investment/backend python -m app.ai.mcp
    codex mcp list

Дальше `codex` (интерактивно) или `codex exec "…вопрос…"` из любого каталога:
сервер поднимается на время сессии и гаснет вместе с ней. Инструменты:
`portfolio_overview`, `positions`, `returns`, `value_history`, `ledger`,
`instrument_prices`, `allocation`, `data_quality`, `find_instrument`; описания —
в `backend/app/ai/registry.py`, там же инструкция сервера для модели.

Три гарантии, на которых держится честность ответов:

- **только чтение** — каждая транзакция сервера открыта как `READ ONLY`, запись
  отобьёт сама база;
- **деньги строками и с датой** — каждый ответ несёт `as_of` и покрытие, а
  величина, которой нет, остаётся `null` с причиной рядом;
- **в сеть инструменты не ходят** — только база; денежная сверка с итогом
  брокера остаётся за `app.valuation_check`.

Веб-поиск самой модели разрешён инструкцией сервера при условии, что внешние
числа отделены от портфельных. Запросы Codex в интернет Джарвису не видны;
отключается поиск целиком в конфигурации Codex.

Живые вопросы признака готовности фазы 5a прогоняются скриптом:

    cd backend && uv run python -m app.ai.live_run

Он задаёт шесть вопросов через `codex exec` и записывает ответы в
`docs/handoff/<дата>-phase-5a-live-run.md`; сверять их нужно с прогонами
`app.valuation_check` и `app.returns.check`.
```

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/ai/mcp.py backend/tests/test_ai_mcp.py README.md
git commit -m "feat: stdio-фасад MCP поверх реестра инструментов"
```

---

### Задача 13: регистрация в Codex и живой прогон

**Files:**
- Create: `backend/app/ai/live_run.py`
- Create: `docs/handoff/2026-09-09-phase-5a-live-run.md` (порождается прогоном, затем дополняется руками)
- Test: `backend/tests/test_ai_live_run.py`
- Вне репозитория: `~/.codex/config.toml` (через `codex mcp add`)

**Interfaces:**
- Consumes: сервер из задачи 12, `codex` в PATH.
- Produces: `QUESTIONS: list[str]` (шесть вопросов раздела 7 дизайна);
  `ask(question) -> str`; `render(pairs, today) -> str`;
  `main(ask_fn=ask, today=None) -> Path`; `python -m app.ai.live_run`.

Признак готовности фазы тестами не ловится (дизайн, раздел 7): поведение
модели — не деталь реализации. Скрипт делает прогон повторяемым и записывает
его в репозиторий, как все прогоны проекта; сверка ответов с
`app.valuation_check` и `app.returns.check` — глазами, и её итог дописывается в
тот же файл.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_ai_live_run.py`:

```python
from datetime import date

from app.ai import live_run


def test_live_run_records_questions_and_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(live_run, "HANDOFF_DIR", tmp_path)
    target = live_run.main(ask_fn=lambda question: f"ответ на «{question}»", today=date(2026, 9, 9))
    text = target.read_text(encoding="utf-8")
    assert target.name == "2026-09-09-phase-5a-live-run.md"
    assert len(live_run.QUESTIONS) == 6
    assert all(question in text for question in live_run.QUESTIONS)
    assert "## 6." in text
    assert "## Сверка" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai_live_run.py -v`
Expected: FAIL — `ImportError: cannot import name 'live_run'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/ai/live_run.py`:

```python
"""Живые вопросы признака готовности фазы 5a — через codex exec.

Не тест: ответы модели сверяются глазами с прогонами app.valuation_check и
app.returns.check, а запись прогона кладётся в репозиторий, как все прогоны
проекта. Сервер должен быть зарегистрирован в Codex (README, «Ассистент»).

    cd backend && uv run python -m app.ai.live_run
"""

import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.timeutils import moscow_today

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDOFF_DIR = REPO_ROOT / "docs" / "handoff"

# Порядок и формулировки — раздел 7 дизайна. Пятый вопрос нарочно без
# подсказки про дни и бумаги: границы честности модель обязана назвать сама.
# Шестой — про рынок: проверяется, что внешние числа пришли отдельным блоком с
# источником и датой, а портфельные с ними не смешаны.
QUESTIONS = [
    "Сколько у меня всего денег в портфеле и на каких счетах? Назови дату оценки и покрытие.",
    "Как я заработал за всё время и за последние 12 месяцев? Нужны XIRR, прибыль и разрезы по классам активов.",
    "Что тянет портфель вниз? Назови бумаги с настоящими цифрами убытка и отдельно те, по которым прибыль не посчитана.",
    "Насколько я отклонился от целевых долей и сколько нужно докинуть, чтобы выровнять?",
    "Можно ли доверять этой доходности?",
    "Что сейчас происходит с ключевой ставкой ЦБ и как это соотносится с моей долей облигаций?",
]


def ask(question: str) -> str:
    """Один вопрос — одна свежая сессия Codex: без памяти о предыдущих ответах,
    только чтение в песочнице, ответ — в файл, а не в перемешанный stdout."""
    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("codex не найден в PATH — установить Codex CLI или добавить его в PATH")
    with tempfile.TemporaryDirectory() as folder:
        answer = Path(folder) / "answer.md"
        subprocess.run(
            [codex, "exec", "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
             "-C", str(REPO_ROOT), "-o", str(answer), question],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return answer.read_text(encoding="utf-8")


def render(pairs: list[tuple[str, str]], today: date) -> str:
    lines = [
        f"# Фаза 5a: живые вопросы через Codex, {today.isoformat()}", "",
        "Ответы модели записаны как есть, без правок. Сверка с прогонами",
        "`app.valuation_check` и `app.returns.check` — в разделе «Сверка» ниже,",
        "он заполняется руками после прогона.", "",
    ]
    for number, (question, answer) in enumerate(pairs, start=1):
        lines += [f"## {number}. {question}", "", answer.strip(), ""]
    lines += ["## Сверка", "", "_заполнить после прогона_", ""]
    return "\n".join(lines)


def main(ask_fn=ask, today: date | None = None) -> Path:
    today = today or moscow_today()
    pairs = []
    for question in QUESTIONS:
        print(f"→ {question}", file=sys.stderr)
        pairs.append((question, ask_fn(question)))
    target = HANDOFF_DIR / f"{today.isoformat()}-phase-5a-live-run.md"
    target.write_text(render(pairs, today), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_ai_live_run.py -v`
Expected: PASS, 1 test

- [ ] **Step 5: Зарегистрировать сервер в Codex и проверить дымом**

```bash
codex mcp add jarvis -- C:/Users/User/.local/bin/uv run --directory C:/jarvis-investment/backend python -m app.ai.mcp
codex mcp list
```

Expected: в списке появилась строка `jarvis … enabled`. Затем дымовой вопрос
без данных (база должна быть поднята: `docker compose up -d db`):

```bash
codex exec -s read-only --ephemeral --skip-git-repo-check -C C:/jarvis-investment "Какие инструменты сервера jarvis тебе доступны? Перечисли их имена списком, ничего не вызывая."
```

Expected: в ответе девять имён инструментов. Если Codex сервера не видит —
`codex mcp get jarvis` и stderr сервера (`uv run python -m app.ai.mcp` руками,
Ctrl+C) покажут, что именно не поднялось; чаще всего — `uv` не в PATH у Codex,
и тогда команда регистрации обязана содержать полный путь, как выше.

- [ ] **Step 6: Прогнать живые вопросы**

Перед прогоном освежить данные и снять эталон:

```bash
cd backend && uv run python -c "from app.scheduler import job_refresh_fx; job_refresh_fx()"
cd backend && uv run python -m app.valuation_check > /tmp/valuation.txt
cd backend && uv run python -m app.returns.check > /tmp/returns.txt
cd backend && uv run python -m app.ai.live_run
```

Expected: файл `docs/handoff/2026-09-09-phase-5a-live-run.md` с шестью
ответами. Затем заполнить раздел «Сверка» руками, по пунктам дизайна (раздел 7):

1. итог и разбивка по счетам из ответа 1 против «наш» в `/tmp/valuation.txt` —
   до копейки;
2. XIRR, прибыль и разрезы из ответа 2 против `/tmp/returns.txt`;
3. в ответе 3 названы бумаги с убытком и отдельно те, где прибыль не посчитана
   (четыре редомицилированные из хендоффа 4a, если цены им так и не догружены);
4. арифметика ответа 4 воспроизводится по формуле `X = max(v_i/t_i) − V`
   (перед прогоном задать хотя бы две цели в «Настройках», иначе ответ обязан
   сказать «цели не заданы»);
5. ответ 5 сам называет измеренные дни TWR и бумаги без цен — без наводящего
   вопроса;
6. в ответе 6 внешние числа — отдельным блоком с источником и датой,
   портфельные с ними не смешаны.

Каждый пункт записать как «сходится» / «расходится: …». Пункт, который не
выполнился, — не повод переписать ответ: это находка о модели или о реестре,
и её место в хендоффе. **Если расходится пункт 1 или 2 — остановиться и
разобраться, это дефект инструмента, а не модели.**

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/live_run.py backend/tests/test_ai_live_run.py docs/handoff/2026-09-09-phase-5a-live-run.md
git commit -m "feat: живой прогон вопросов через codex exec и его запись"
```

---

### Задача 14: закрытие фазы

**Files:**
- Modify: `docs/roadmap.md` (раздел «Фаза 5», «Где мы сейчас», таблица статусов, пункт 4d)
- Create: `docs/handoff/2026-09-09-phase-5a-handoff.md`

- [ ] **Step 1: Прогнать всё и проверить признак готовности**

```bash
cd backend && uv run pytest
cd frontend && pnpm exec vitest run && pnpm run build && pnpm check:styles --strict
```

Expected: всё зелёное. Признак готовности выполнен, если в записи живого
прогона (задача 13) пункты 1 и 2 сходятся, а по 3–6 записан итог. Пункт с
расхождением по 3–6 фазу не блокирует, но обязан быть назван в хендоффе как
находка.

- [ ] **Step 2: Обновить роадмеп**

В `docs/roadmap.md`:

1. Раздел «Фаза 5. ИИ-чат» разбить на «5a. Реестр инструментов и MCP-сервер —
   завершена 2026-09-…» и «5b. Панель чата» по образцу фазы 4: у 5a — ссылки
   на дизайн и план, что появилось (пакеты `app/ai`, `app/allocation`, таблица
   `target_allocation`, раздел «Целевые доли»), итог живого прогона по шести
   пунктам с цифрами; у 5b — панель на `codex exec`, контекст экрана,
   стриминг, история, и фраза о том, что список недостающих инструментов
   берётся из живых вопросов.
2. В «4d. Бенчмарки и целевые доли» переименовать в «4d. Бенчмарки» и
   дописать: целевые доли и выравнивание пополнением сделаны фазой 5a, здесь
   остаётся экранная подача перекосов, бенчмарки и look-through.
3. В «Где мы сейчас» добавить абзац про ассистента: клиент Codex, девять
   инструментов, что показал живой прогон, чем ответы отличались от прогонов.
4. В таблице статусов: строка «5a. Реестр инструментов и MCP-сервер —
   завершена …, проверена живыми вопросами», строка «5b. Панель чата —
   запланирована».
5. В «Попутный долг» дописать пункты, найденные фазой (например: два
   `select(Account)` в каждом инструменте; `returns` считается секундами без
   кэша в короткоживущем процессе — лечится в 5b; словарь `REASON_TEXTS`
   дублирует `REASONS` фронта третьим экземпляром), с причиной, почему остались.

- [ ] **Step 3: Написать хендофф**

Создать `docs/handoff/2026-09-09-phase-5a-handoff.md` по образцу
[`2026-08-14-phase-4a-handoff.md`](../../handoff/2026-08-14-phase-4a-handoff.md):
«Где мы» (ветка, число коммитов, тесты бэкенда и фронта), «Что показал живой
прогон» (шесть пунктов с цифрами и вердиктами), «Решения, которые нельзя менять
молча» (только чтение и READ ONLY; деньги строками; отказ — ответ; одно
пространство целей; продаж расчёт не предлагает; инструкция — не гарантия),
«Долг, оставленный сознательно», «Окружение» (регистрация в Codex, `mcp` 2.x,
команда живого прогона), «Что дальше» (5b и что из живых вопросов показало
нехватку инструментов).

- [ ] **Step 4: Commit**

```bash
git add docs/roadmap.md docs/handoff/2026-09-09-phase-5a-handoff.md
git commit -m "docs: фаза 5a закрыта — роадмеп и хендофф"
```

---

## Самопроверка плана

Проверено после написания, против дизайна:

- **Раздел 4 (три слоя)** — задачи 7–12: инструменты в `app/ai/tools/`, реестр
  в `registry.py` единственным местом описания, фасад `mcp.py` без логики.
  Новый расчёт — в `app/allocation/` (задачи 1, 3), а не внутри инструмента.
- **Раздел 4.1 (форма ответа)** — `serialize.py` (задача 7): деньги строками,
  `as_of` и `coverage` у каждого инструмента, лимиты и агрегаты у `ledger`
  (задача 10) и усечение у `returns.by_instrument` (задача 9), отказ как ответ
  (`run_tool`), инструкция сервера (`INSTRUCTIONS`).
- **Раздел 4.2 (девять инструментов)** — задачи 7–11, порядок и имена
  закреплены тестом `test_registry_exposes_the_nine_tools_of_the_design`.
  `find_instrument` возвращает обе бумаги под тикером `T` (тест задачи 8).
  `data_quality` честно называет `valuation_check` (задача 11).
- **Раздел 4.3 (фасад)** — задача 12: stdio, `mcp` 2.x, `READ ONLY` базой,
  логи в stderr закреплены тестом, регистрация одной командой (задача 13).
- **Раздел 4.4 (целевые доли)** — задачи 1–5: одно пространство целей
  (проверка при сохранении), сумма не обязана быть сотней, группа «не задано»,
  формула минимального пополнения и тождество дефицитов (тесты задачи 1),
  группа с целью ноль, своя сумма меньше минимальной, оговорка про лотность.
- **Раздел 5 (контракт)** — поля каждого инструмента в задачах 7–11;
  произвольные границы периода — задача 6.
- **Раздел 6 (интерфейс)** — задача 5: раздел в «Настройках» из примитивов,
  живой подсчёт суммы и остатка, отказ при превышении ста (на клиенте) и при
  бумаге внутри класса (текст бэкенда).
- **Раздел 7 (признак готовности)** — тесты инструментов и фасада (задачи
  1–12), живой прогон через `codex exec` с записью в репозиторий (задача 13).
- **Раздел 8 (риски)** — инструкция сервера и пункт 6 живого прогона;
  задержка `returns` без кэша названа в долге (задача 14).

**Отступления от дизайна, внесённые планом осознанно:**

1. **Появился `app/ai/errors.py`** — дизайн называет три файла. Причина:
   `ToolRefusal` нужен инструментам, а реестр их импортирует; исключение внутри
   реестра замкнуло бы импорт по кругу.
2. **Цель на бумагу задаётся по ISIN, а бумаги в форме берутся из открытых
   позиций** — дизайн говорит «добавление цели по бумаге», не уточняя как.
   Отдельный роут поиска для экрана не заводится: цель на бумагу, которой в
   портфеле нет, сравнивать не с чем. Ассистенту поиск даёт `find_instrument`.
3. **`PositionRow` и `PositionOut` получили `instrument_id` и `asset_class`.**
   Без идентификатора ассистент не может связать позицию с `ledger`, без
   класса — сравнить факт с целью той же функцией, что считает разбивку.
4. **Своя сумма меньше минимальной раскладывается «как есть», без
   масштабирования:** дефициты посчитаны при `V + X`, их сумма больше `X`, и
   инструмент называет разницу (`short_by_rub`) и группы, оставшиеся выше цели.
   Дизайн требует именно этого: молча распределить меньшее нельзя.

Все четыре — уточнения, а не сокращения объёма. Если владелец с каким-то не
согласен, поправка стоит одной задачи.

