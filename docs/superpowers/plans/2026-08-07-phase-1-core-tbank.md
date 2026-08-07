# Джарвис, фаза 1: ядро и Т-Банк — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Владелец открывает `localhost:3000` и видит свой настоящий портфель Т-Банка: совокупную стоимость, структуру по классам активов, список позиций, график стоимости и явный список расхождений между журналом операций и данными брокера.

**Architecture:** Модульный монолит FastAPI. Источник истины — неизменяемый журнал операций (`transaction`); позиции, лоты FIFO и метрики вычисляются из него. Синхронизация с брокером не перезаписывает позиции, а сверяет расчёт со снимком брокера и показывает расхождения. Фронтенд — React SPA, обращается только к REST API бэкенда.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (синхронный), Alembic, PostgreSQL 16, `tinkoff-investments` (T-Invest API), httpx (MOEX ISS), pytest. Фронтенд: React 19, TypeScript, Vite, TanStack Query, Tailwind, Apache ECharts. Запуск — Docker Compose.

Синхронный SQLAlchemy выбран сознательно: пользователь один, нагрузки нет, а официальный SDK Т-Банка синхронный. Async добавил бы сложность тестов без выигрыша.

## Global Constraints

- Python 3.12+, менеджер зависимостей — `uv`. Node.js 20+, менеджер — `pnpm`.
- PostgreSQL 16. SQLite не используется даже в тестах: расхождение диалектов прячет ошибки.
- **Все денежные величины — `decimal.Decimal`, нигде не `float`.** Это касается цен, сумм, комиссий, количеств дробных паёв. В БД — `NUMERIC(20, 8)` для количеств, `NUMERIC(20, 4)` для денег.
- Все моменты времени хранятся в UTC (`TIMESTAMP WITH TIME ZONE`), отображаются в `Europe/Moscow`.
- Токен T-Invest API берётся из переменной окружения `TBANK_TOKEN`, запрашивается с правами **только на чтение**. Ни один метод SDK, изменяющий состояние счёта, в коде не вызывается.
- Журнал операций (`transaction`) — append-only. `UPDATE` и `DELETE` по этой таблице запрещены; исправления вносятся корректирующими операциями.
- Сообщения коммитов — Conventional Commits: `feat:`, `fix:`, `test:`, `chore:`, `docs:`.
- Язык интерфейса и сообщений об ошибках — русский. Код, имена таблиц и полей — английский.
- Секреты только в `.env`, который в `.gitignore`. В репозиторий коммитится `.env.example` с пустыми значениями.

## Файловая структура

```
backend/
  pyproject.toml
  alembic.ini
  alembic/versions/
  app/
    config.py              настройки из окружения
    db.py                  engine, SessionLocal, get_session
    money.py               Decimal-утилиты и конвертация типов SDK
    models/                SQLAlchemy-модели, по файлу на сущность
    ledger/
      schemas.py           RawOperation — нормализованная операция
      dedup.py             ключ дедупликации
      service.py           append_operations
    positions/
      engine.py            чистая функция: операции → позиции и лоты FIFO
      service.py           пересборка позиций в БД
    marketdata/
      moex.py              HTTP-клиент ISS
      service.py           обновление цен инструментов
    instruments/service.py поиск и создание инструментов по ISIN
    connectors/
      base.py              протокол BrokerConnector
      tbank/client.py      обёртка над SDK
      tbank/mapper.py      операции SDK → RawOperation
      tbank/connector.py   реализация протокола
    sync/
      service.py           оркестрация синхронизации
      reconcile.py         сверка журнала со снимком брокера
    snapshots/service.py   ежедневный снимок стоимости
    analytics/service.py   сводка капитала и аллокация
    api/                   роутеры, по файлу на ресурс
    main.py
  tests/
frontend/
  src/
    api/client.ts          типы и запросы к бэкенду
    components/            переиспользуемые элементы
    pages/PortfolioPage.tsx
    theme.css
docker-compose.yml
.env.example
README.md
```

Разделение по ответственности, а не по слоям: движок позиций лежит рядом со своим сервисом, маппер Т-Банка — рядом со своим клиентом. `positions/engine.py` — чистая функция без БД: это самая ответственная логика в фазе, и её нужно тестировать без инфраструктуры.

---

### Task 1: Каркас проекта и работающий контейнер

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `README.md`
- Create: `backend/pyproject.toml`, `backend/Dockerfile`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `app.config.Settings` с полями `database_url: str`, `tbank_token: str`, `moex_base_url: str`; фабрика `get_settings() -> Settings`. FastAPI-приложение `app.main.app`.

- [ ] **Step 1: Написать падающий тест**

`backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Создать `backend/pyproject.toml`**

```toml
[project]
name = "jarvis-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0.36",
    "psycopg[binary]>=3.2",
    "alembic>=1.14",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "httpx>=0.28",
    "tinkoff-investments>=0.2.0b110",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-cov>=6.0", "respx>=0.22"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.uv]
package = false
```

- [ ] **Step 4: Создать `backend/app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://jarvis:jarvis@localhost:5432/jarvis"
    tbank_token: str = ""
    moex_base_url: str = "https://iss.moex.com/iss"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Создать `backend/app/main.py` и пустой `backend/app/__init__.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Джарвис", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Запустить тест и убедиться, что он проходит**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 7: Создать `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: jarvis
      POSTGRES_PASSWORD: jarvis
      POSTGRES_DB: jarvis
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U jarvis"]
      interval: 5s
      retries: 10

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg://jarvis:jarvis@db:5432/jarvis
      TBANK_TOKEN: ${TBANK_TOKEN}
    ports: ["8000:8000"]
    depends_on:
      db: {condition: service_healthy}

volumes:
  pgdata:
```

- [ ] **Step 8: Создать `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 9: Создать `.env.example` и `README.md`**

`.env.example`:

```
TBANK_TOKEN=
DATABASE_URL=postgresql+psycopg://jarvis:jarvis@localhost:5432/jarvis
```

`README.md` — раздел «Запуск»: скопировать `.env.example` в `.env`, вписать токен T-Invest API с правами только на чтение, выполнить `docker compose up -d db`, затем `cd backend && uv run uvicorn app.main:app --reload`.

- [ ] **Step 10: Проверить, что база поднимается**

Run: `docker compose up -d db && docker compose ps`
Expected: сервис `db` в состоянии `healthy`

- [ ] **Step 11: Коммит**

```bash
git add docker-compose.yml .env.example README.md backend/
git commit -m "feat: каркас бэкенда, docker-compose и health-эндпоинт"
```

---

### Task 2: Работа с деньгами

**Files:**
- Create: `backend/app/money.py`
- Test: `backend/tests/test_money.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `money(value: str | int | Decimal) -> Decimal` — деньги, округление до 4 знаков
  - `quantity(value: str | int | Decimal) -> Decimal` — количество, 8 знаков
  - `quotation_to_decimal(units: int, nano: int) -> Decimal` — формат SDK Т-Банка

SDK Т-Банка отдаёт денежные величины парой `units` (целая часть) и `nano` (миллиардные доли). Прямое `units + nano / 1e9` даёт float и теряет копейки на больших суммах — поэтому отдельная функция.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_money.py`:

```python
from decimal import Decimal

import pytest

from app.money import money, quantity, quotation_to_decimal


def test_money_rounds_to_four_places():
    assert money("123.456789") == Decimal("123.4568")


def test_money_accepts_int():
    assert money(100) == Decimal("100.0000")


def test_money_rejects_float():
    with pytest.raises(TypeError):
        money(1.5)  # type: ignore[arg-type]


def test_quantity_keeps_eight_places():
    assert quantity("0.00000001") == Decimal("0.00000001")


def test_quotation_combines_units_and_nano():
    assert quotation_to_decimal(142, 500000000) == Decimal("142.5000")


def test_quotation_handles_negative_variation_margin():
    assert quotation_to_decimal(-3, -250000000) == Decimal("-3.2500")


def test_quotation_zero():
    assert quotation_to_decimal(0, 0) == Decimal("0.0000")
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_money.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.money'`

- [ ] **Step 3: Реализовать `backend/app/money.py`**

```python
from decimal import Decimal, ROUND_HALF_UP

MONEY_EXP = Decimal("0.0001")
QUANTITY_EXP = Decimal("0.00000001")
NANO = Decimal("1000000000")


def _to_decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float недопустим для денежных величин, используйте str или Decimal")
    return Decimal(value)


def money(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def quantity(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(QUANTITY_EXP, rounding=ROUND_HALF_UP)


def quotation_to_decimal(units: int, nano: int) -> Decimal:
    return money(Decimal(units) + Decimal(nano) / NANO)
```

`isinstance(value, float)` проверяется до `isinstance(value, int)` не нужно: `bool` — подкласс `int`, а `float` отдельным типом, поэтому порядок здесь безопасен.

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_money.py -v`
Expected: PASS, 7 тестов

- [ ] **Step 5: Коммит**

```bash
git add backend/app/money.py backend/tests/test_money.py
git commit -m "feat: Decimal-утилиты для денег и конвертация формата T-Invest"
```

---

### Task 3: Модели БД и первая миграция

**Files:**
- Create: `backend/app/db.py`, `backend/app/models/__init__.py`, `backend/app/models/base.py`, `backend/app/models/instrument.py`, `backend/app/models/account.py`, `backend/app/models/transaction.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.get_settings`
- Produces:
  - `app.db.engine`, `app.db.SessionLocal`, `app.db.get_session()` — генератор для Depends
  - `app.models.Base` — декларативная база
  - `Instrument(id, isin, ticker, secid, kind, currency, issuer, sector, asset_class, maturity_date, face_value)`
  - `Account(id, broker, kind, external_id, name, currency, opened_at)`
  - `Transaction(id, account_id, instrument_id, op_type, executed_at, quantity, price, amount, currency, fee, external_id, source, payload, created_at)`
  - `OperationType` — строковый enum: `BUY`, `SELL`, `DIVIDEND`, `COUPON`, `FEE`, `TAX`, `DEPOSIT`, `WITHDRAWAL`, `REDEMPTION`, `AMORTIZATION`, `VARIATION_MARGIN`, `OTHER`
  - фикстура `session` в conftest

- [ ] **Step 1: Написать падающий тест**

`backend/tests/test_models.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.models import Account, Instrument, OperationType, Transaction


def test_transaction_persists_decimal_precision(session):
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB", issuer="Сбербанк")
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add_all([instrument, account])
    session.flush()

    tx = Transaction(
        account_id=account.id,
        instrument_id=instrument.id,
        op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        quantity=Decimal("35.00000000"),
        price=Decimal("142.5000"),
        amount=Decimal("-4987.5000"),
        currency="RUB",
        fee=Decimal("1.4963"),
        external_id="op-777",
        source="tbank",
        payload={"raw": "value"},
    )
    session.add(tx)
    session.commit()

    stored = session.get(Transaction, tx.id)
    assert stored.price == Decimal("142.5000")
    assert stored.fee == Decimal("1.4963")
    assert stored.payload == {"raw": "value"}


def test_external_id_unique_per_source(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-2",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()

    def make(external_id: str) -> Transaction:
        return Transaction(
            account_id=account.id, instrument_id=None, op_type=OperationType.DEPOSIT,
            executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000.0000"),
            currency="RUB", fee=Decimal("0"), external_id=external_id,
            source="tbank", payload={},
        )

    session.add(make("dup-1"))
    session.commit()

    import pytest
    from sqlalchemy.exc import IntegrityError

    session.add(make("dup-1"))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_models.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Создать `backend/app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 4: Создать `backend/app/models/instrument.py`**

```python
from datetime import date

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Instrument(Base):
    __tablename__ = "instrument"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    secid: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    issuer: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(64))
    asset_class: Mapped[str | None] = mapped_column(String(32))
    maturity_date: Mapped[date | None] = mapped_column(Date)
    face_value: Mapped[object | None] = mapped_column(Numeric(20, 4))
```

`kind` принимает значения `share`, `bond`, `etf`, `currency`, `futures`, `metal`. `asset_class` заполняется для фондов и задаёт класс актива при подсчёте аллокации: `equity`, `bonds`, `money_market`, `gold`, `mixed`.

- [ ] **Step 5: Создать `backend/app/models/account.py`**

```python
from datetime import date

from sqlalchemy import Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("broker", "external_id", name="uq_account_broker_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    broker: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    opened_at: Mapped[date | None] = mapped_column(Date)
```

`kind` — `brokerage` или `iis`.

- [ ] **Step 6: Создать `backend/app/models/transaction.py`**

```python
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OperationType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    COUPON = "COUPON"
    FEE = "FEE"
    TAX = "TAX"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    REDEMPTION = "REDEMPTION"
    AMORTIZATION = "AMORTIZATION"
    VARIATION_MARGIN = "VARIATION_MARGIN"
    OTHER = "OTHER"


class Transaction(Base):
    __tablename__ = "transaction"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_transaction_source_external"),
        Index("ix_transaction_account_executed", "account_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    op_type: Mapped[OperationType] = mapped_column(String(24))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    external_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Знак `amount` — со стороны счёта: покупка отрицательна, продажа и дивиденд положительны. Это позволяет считать денежные потоки суммированием без разбора типа операции.

- [ ] **Step 7: Создать `backend/app/models/__init__.py`**

```python
from app.models.account import Account
from app.models.base import Base
from app.models.instrument import Instrument
from app.models.transaction import OperationType, Transaction

__all__ = ["Account", "Base", "Instrument", "OperationType", "Transaction"]
```

- [ ] **Step 8: Создать `backend/app/db.py`**

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
```

- [ ] **Step 9: Создать `backend/tests/conftest.py`**

```python
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base

ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql+psycopg://jarvis:jarvis@localhost:5432/postgres")
TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://jarvis:jarvis@localhost:5432/jarvis_test")


@pytest.fixture(scope="session")
def test_engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS jarvis_test"))
        conn.execute(text("CREATE DATABASE jarvis_test"))
    admin.dispose()

    engine = create_engine(TEST_URL)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False)
    db = factory()
    yield db
    db.close()
    transaction.rollback()
    connection.close()
```

Каждый тест идёт во внешней транзакции с откатом — база остаётся чистой без пересоздания схемы между тестами.

- [ ] **Step 10: Запустить тесты и убедиться, что они проходят**

Run: `docker compose up -d db && cd backend && uv run pytest tests/test_models.py -v`
Expected: PASS, 2 теста

- [ ] **Step 11: Инициализировать Alembic и создать первую миграцию**

Run:
```bash
cd backend
uv run alembic init alembic
```

В `alembic/env.py` заменить блок настройки на:

```python
from app.config import get_settings
from app.models import Base

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

Затем:
```bash
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```

- [ ] **Step 12: Проверить, что миграция применилась**

Run: `docker compose exec db psql -U jarvis -d jarvis -c "\dt"`
Expected: таблицы `account`, `instrument`, `transaction`, `alembic_version`

- [ ] **Step 13: Коммит**

```bash
git add backend/app/db.py backend/app/models backend/alembic backend/alembic.ini backend/tests
git commit -m "feat: модели инструментов, счетов и журнала операций с миграцией"
```

---

### Task 4: Нормализованная операция и дедупликация

**Files:**
- Create: `backend/app/ledger/__init__.py`, `backend/app/ledger/schemas.py`, `backend/app/ledger/dedup.py`
- Test: `backend/tests/test_dedup.py`

**Interfaces:**
- Consumes: `app.models.OperationType`, `app.money`
- Produces:
  - `RawOperation` — pydantic-модель с полями `external_id: str | None`, `op_type: OperationType`, `executed_at: datetime`, `isin: str | None`, `ticker: str | None`, `quantity: Decimal`, `price: Decimal`, `amount: Decimal`, `currency: str`, `fee: Decimal`, `payload: dict`
  - `natural_key(source: str, account_external_id: str, op: RawOperation) -> str` — sha256-хэш от нормализованных полей

Дедупликация нужна двум сценариям: повторный вызов API (там есть `external_id`) и повторная загрузка пересекающегося отчёта во второй фазе (там его нет). Ключ считается сейчас, чтобы вторая фаза не переделывала журнал.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_dedup.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import OperationType


def make_op(**overrides) -> RawOperation:
    defaults = dict(
        external_id=None,
        op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        isin="RU0009029540",
        ticker="SBER",
        quantity=Decimal("35"),
        price=Decimal("142.5"),
        amount=Decimal("-4987.5"),
        currency="RUB",
        fee=Decimal("1.4963"),
        payload={},
    )
    return RawOperation(**{**defaults, **overrides})


def test_same_operation_gives_same_key():
    assert natural_key("tbank", "acc-1", make_op()) == natural_key("tbank", "acc-1", make_op())


def test_payload_does_not_affect_key():
    assert natural_key("tbank", "acc-1", make_op(payload={"a": 1})) == natural_key(
        "tbank", "acc-1", make_op(payload={"b": 2})
    )


def test_different_quantity_gives_different_key():
    assert natural_key("tbank", "acc-1", make_op()) != natural_key(
        "tbank", "acc-1", make_op(quantity=Decimal("36"))
    )


def test_different_account_gives_different_key():
    assert natural_key("tbank", "acc-1", make_op()) != natural_key("tbank", "acc-2", make_op())


def test_trailing_zeros_in_decimal_do_not_change_key():
    assert natural_key("tbank", "acc-1", make_op(quantity=Decimal("35"))) == natural_key(
        "tbank", "acc-1", make_op(quantity=Decimal("35.00"))
    )
```

Последний тест защищает от неприятного случая: брокер отдаёт `35`, отчёт — `35.00`, и без нормализации одна и та же сделка задвоится.

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_dedup.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.ledger'`

- [ ] **Step 3: Создать `backend/app/ledger/schemas.py` и пустой `backend/app/ledger/__init__.py`**

```python
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models import OperationType


class RawOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_id: str | None
    op_type: OperationType
    executed_at: datetime
    isin: str | None
    ticker: str | None
    quantity: Decimal
    price: Decimal
    amount: Decimal
    currency: str
    fee: Decimal
    payload: dict
```

- [ ] **Step 4: Создать `backend/app/ledger/dedup.py`**

```python
import hashlib
from decimal import Decimal

from app.ledger.schemas import RawOperation


def _norm(value: Decimal) -> str:
    normalized = value.normalize()
    return f"{normalized:f}"


def natural_key(source: str, account_external_id: str, op: RawOperation) -> str:
    parts = [
        source,
        account_external_id,
        op.op_type.value,
        op.executed_at.astimezone(tz=None).isoformat(),
        op.isin or "",
        _norm(op.quantity),
        _norm(op.price),
        _norm(op.amount),
        op.currency,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
```

`Decimal.normalize()` убирает незначащие нули, `f"{...:f}"` не даёт экспоненциальной записи, в которую `normalize()` превращает крупные круглые числа.

- [ ] **Step 5: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_dedup.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 6: Коммит**

```bash
git add backend/app/ledger backend/tests/test_dedup.py
git commit -m "feat: нормализованная операция и ключ дедупликации журнала"
```

---

### Task 5: Запись в журнал с идемпотентностью

**Files:**
- Create: `backend/app/ledger/service.py`
- Modify: `backend/app/models/transaction.py` — добавить колонку `dedup_key`
- Create: `backend/alembic/versions/0002_dedup_key.py`
- Test: `backend/tests/test_ledger_service.py`

**Interfaces:**
- Consumes: `RawOperation`, `natural_key`, `Transaction`, `Account`, `app.instruments.service.resolve_instrument`
- Produces: `append_operations(session, account, source, operations: list[RawOperation]) -> AppendResult`, где `AppendResult` — dataclass с полями `inserted: int`, `skipped: int`

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_ledger_service.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.ledger.schemas import RawOperation
from app.ledger.service import append_operations
from app.models import Account, OperationType, Transaction


def make_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def buy_op(external_id: str | None = "op-1") -> RawOperation:
    return RawOperation(
        external_id=external_id, op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
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
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_ledger_service.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.ledger.service'`

- [ ] **Step 3: Добавить `dedup_key` в модель транзакции**

В `backend/app/models/transaction.py` добавить в `__table_args__` ограничение и в класс — колонку:

```python
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_transaction_source_external"),
        UniqueConstraint("dedup_key", name="uq_transaction_dedup_key"),
        Index("ix_transaction_account_executed", "account_id", "executed_at"),
    )
```

```python
    dedup_key: Mapped[str] = mapped_column(String(64), index=True)
```

И связь для удобства тестов:

```python
    from sqlalchemy.orm import relationship
    instrument = relationship("Instrument", lazy="joined")
```

- [ ] **Step 4: Создать `backend/app/instruments/service.py` и пустой `backend/app/instruments/__init__.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.schemas import RawOperation
from app.models import Instrument

KIND_BY_PREFIX = {"share": "share", "bond": "bond", "etf": "etf", "currency": "currency"}


def resolve_instrument(session: Session, op: RawOperation) -> Instrument | None:
    if op.isin is None:
        return None

    existing = session.execute(
        select(Instrument).where(Instrument.isin == op.isin)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    instrument = Instrument(
        isin=op.isin,
        ticker=op.ticker,
        secid=op.ticker,
        kind=str(op.payload.get("instrument_kind", "share")),
        currency=op.currency,
        issuer=op.payload.get("issuer"),
    )
    session.add(instrument)
    session.flush()
    return instrument
```

- [ ] **Step 5: Создать `backend/app/ledger/service.py`**

```python
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.instruments.service import resolve_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import Account, Transaction


@dataclass(frozen=True)
class AppendResult:
    inserted: int
    skipped: int


def append_operations(
    session: Session, account: Account, source: str, operations: list[RawOperation]
) -> AppendResult:
    if not operations:
        return AppendResult(inserted=0, skipped=0)

    keys = {op: natural_key(source, account.external_id, op) for op in operations}
    known = set(
        session.execute(
            select(Transaction.dedup_key).where(Transaction.dedup_key.in_(keys.values()))
        ).scalars()
    )

    inserted = 0
    skipped = 0
    seen_in_batch: set[str] = set()

    for op in operations:
        key = keys[op]
        if key in known or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)

        instrument = resolve_instrument(session, op)
        session.add(
            Transaction(
                account_id=account.id,
                instrument_id=instrument.id if instrument else None,
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
        )
        inserted += 1

    session.flush()
    return AppendResult(inserted=inserted, skipped=skipped)
```

`seen_in_batch` закрывает случай, когда одна и та же операция пришла дважды внутри одной пачки — брокер такое отдаёт при пересечении страниц пагинации.

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_ledger_service.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 7: Создать миграцию**

Run:
```bash
cd backend && uv run alembic revision --autogenerate -m "dedup key" && uv run alembic upgrade head
```

- [ ] **Step 8: Коммит**

```bash
git add backend/app/ledger backend/app/instruments backend/app/models backend/alembic/versions backend/tests/test_ledger_service.py
git commit -m "feat: идемпотентная запись операций в журнал"
```

---

### Task 6: Движок позиций и лотов FIFO

**Files:**
- Create: `backend/app/positions/__init__.py`, `backend/app/positions/engine.py`
- Test: `backend/tests/test_positions_engine.py`

**Interfaces:**
- Consumes: `OperationType`, `app.money.quantity`
- Produces:
  - `LedgerEntry` — dataclass: `op_type: OperationType`, `executed_at: datetime`, `instrument_id: int | None`, `quantity: Decimal`, `price: Decimal`, `amount: Decimal`, `fee: Decimal`
  - `OpenLot` — dataclass: `instrument_id: int`, `opened_at: datetime`, `price: Decimal`, `quantity_left: Decimal`
  - `RealizedSale` — dataclass: `instrument_id: int`, `sold_at: datetime`, `quantity: Decimal`, `proceeds: Decimal`, `cost: Decimal`, `opened_at: datetime`
  - `PositionState` — dataclass: `instrument_id: int`, `quantity: Decimal`, `average_price: Decimal`, `lots: list[OpenLot]`
  - `FoldResult` — dataclass: `positions: dict[int, PositionState]`, `realized: list[RealizedSale]`, `cash: dict[str, Decimal]`
  - `fold(entries: list[LedgerEntry], currency: str = "RUB") -> FoldResult`

Это самая ответственная функция фазы: ошибка здесь не падает, а тихо показывает неверную среднюю цену и неверный налог. Поэтому она чистая — без БД, без сети, только данные на входе и выходе.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_positions_engine.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.positions.engine import LedgerEntry, fold
from app.models import OperationType

D = Decimal


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 10, 0, tzinfo=timezone.utc)


def entry(op_type, day, qty="0", price="0", amount="0", fee="0", instrument_id=1):
    return LedgerEntry(
        op_type=op_type, executed_at=at(day), instrument_id=instrument_id,
        quantity=D(qty), price=D(price), amount=D(amount), fee=D(fee),
    )


def test_single_buy_creates_position():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000")])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("100.0000")


def test_average_price_is_weighted():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="30", price="200", amount="-6000"),
    ])
    assert result.positions[1].average_price == D("175.0000")


def test_partial_sale_consumes_oldest_lot_first():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
    ])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("200.0000")

    sale = result.realized[0]
    assert sale.cost == D("1000.0000")
    assert sale.proceeds == D("3000.0000")
    assert sale.opened_at == at(1)


def test_sale_splitting_a_lot_leaves_remainder():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="4", price="150", amount="600"),
    ])
    position = result.positions[1]
    assert position.quantity == D("6")
    assert position.lots[0].quantity_left == D("6")
    assert result.realized[0].cost == D("400.0000")


def test_full_exit_leaves_zero_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="10", price="120", amount="1200"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.positions[1].lots == []


def test_dividend_does_not_change_quantity_but_changes_cash():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.DIVIDEND, 5, amount="340.50"),
    ])
    assert result.positions[1].quantity == D("10")
    assert result.cash["RUB"] == D("-659.5000")


def test_redemption_closes_bond_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="1000", amount="-10000"),
        entry(OperationType.REDEMPTION, 9, qty="10", price="1000", amount="10000"),
    ])
    assert result.positions[1].quantity == D("0")


def test_deposit_only_affects_cash():
    result = fold([entry(OperationType.DEPOSIT, 1, amount="50000", instrument_id=None)])
    assert result.positions == {}
    assert result.cash["RUB"] == D("50000.0000")


def test_fee_reduces_cash():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000", fee="5")])
    assert result.cash["RUB"] == D("-1005.0000")


def test_selling_more_than_owned_does_not_go_negative():
    result = fold([
        entry(OperationType.BUY, 1, qty="5", price="100", amount="-500"),
        entry(OperationType.SELL, 2, qty="8", price="150", amount="1200"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.realized[0].quantity == D("5")


def test_operations_are_sorted_by_time_regardless_of_input_order():
    unsorted_entries = [
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
    ]
    result = fold(unsorted_entries)
    assert result.realized[0].cost == D("1000.0000")
```

Последний тест важен: брокер отдаёт операции в обратном хронологическом порядке, и FIFO по неотсортированному входу даст неверную налоговую базу.

Тест про продажу большего количества, чем есть, фиксирует поведение при неполной истории: журнал начат позднее первой покупки. Позиция не уходит в минус, реализация считается по тому, что известно, а расхождение поймает сверка (задача 11).

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_positions_engine.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.positions'`

- [ ] **Step 3: Реализовать `backend/app/positions/engine.py` и пустой `backend/app/positions/__init__.py`**

```python
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models import OperationType
from app.money import money, quantity as q

INCREASING = {OperationType.BUY}
DECREASING = {OperationType.SELL, OperationType.REDEMPTION}


@dataclass(frozen=True)
class LedgerEntry:
    op_type: OperationType
    executed_at: datetime
    instrument_id: int | None
    quantity: Decimal
    price: Decimal
    amount: Decimal
    fee: Decimal


@dataclass
class OpenLot:
    instrument_id: int
    opened_at: datetime
    price: Decimal
    quantity_left: Decimal


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


@dataclass(frozen=True)
class FoldResult:
    positions: dict[int, PositionState]
    realized: list[RealizedSale]
    cash: dict[str, Decimal]


def _average(lots: list[OpenLot]) -> Decimal:
    total_qty = sum((lot.quantity_left for lot in lots), Decimal("0"))
    if total_qty == 0:
        return money("0")
    total_cost = sum((lot.quantity_left * lot.price for lot in lots), Decimal("0"))
    return money(total_cost / total_qty)


def fold(entries: list[LedgerEntry], currency: str = "RUB") -> FoldResult:
    lots: dict[int, list[OpenLot]] = defaultdict(list)
    realized: list[RealizedSale] = []
    cash: dict[str, Decimal] = defaultdict(lambda: money("0"))

    for entry in sorted(entries, key=lambda e: e.executed_at):
        cash[currency] = money(cash[currency] + entry.amount - entry.fee)

        if entry.instrument_id is None:
            continue

        if entry.op_type in INCREASING:
            lots[entry.instrument_id].append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=money(entry.price),
                    quantity_left=q(entry.quantity),
                )
            )
        elif entry.op_type in DECREASING:
            remaining = q(entry.quantity)
            unit_proceeds = money(entry.price)
            open_lots = lots[entry.instrument_id]

            while remaining > 0 and open_lots:
                lot = open_lots[0]
                taken = min(lot.quantity_left, remaining)
                realized.append(
                    RealizedSale(
                        instrument_id=entry.instrument_id,
                        sold_at=entry.executed_at,
                        quantity=taken,
                        proceeds=money(taken * unit_proceeds),
                        cost=money(taken * lot.price),
                        opened_at=lot.opened_at,
                    )
                )
                lot.quantity_left = q(lot.quantity_left - taken)
                remaining = q(remaining - taken)
                if lot.quantity_left == 0:
                    open_lots.pop(0)

    positions = {
        instrument_id: PositionState(
            instrument_id=instrument_id,
            quantity=q(sum((lot.quantity_left for lot in open_lots), Decimal("0"))),
            average_price=_average(open_lots),
            lots=open_lots,
        )
        for instrument_id, open_lots in lots.items()
    }
    return FoldResult(positions=positions, realized=realized, cash=dict(cash))
```

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_positions_engine.py -v`
Expected: PASS, 11 тестов

- [ ] **Step 5: Коммит**

```bash
git add backend/app/positions backend/tests/test_positions_engine.py
git commit -m "feat: движок свёртки журнала в позиции и лоты FIFO"
```

---

### Task 7: Клиент MOEX ISS

**Files:**
- Create: `backend/app/marketdata/__init__.py`, `backend/app/marketdata/moex.py`
- Test: `backend/tests/test_moex.py`

**Interfaces:**
- Consumes: `app.config.get_settings`, `app.money.money`
- Produces:
  - `MoexClient(base_url: str | None = None)`
  - `MoexClient.last_price(secid: str, market: str = "shares") -> Decimal | None`
  - `MoexClient.close_history(secid: str, start: date, end: date, market: str = "shares") -> list[tuple[date, Decimal]]`

ISS отдаёт данные блоками `{"columns": [...], "data": [[...]]}` — позиции колонок не гарантированы, поэтому индексы всегда ищутся по имени, а не задаются числом.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_moex.py`:

```python
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.moex import MoexClient

BASE = "https://iss.moex.com/iss"


@respx.mock
def test_last_price_reads_column_by_name():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json={
            "marketdata": {
                "columns": ["SECID", "BOARDID", "LAST", "VALTODAY"],
                "data": [["SBER", "SMAL", None, 0], ["SBER", "TQBR", 314.28, 1000]],
            }
        })
    )
    assert MoexClient(BASE).last_price("SBER") == Decimal("314.2800")


@respx.mock
def test_last_price_returns_none_when_no_trades():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/XXXX.json").mock(
        return_value=httpx.Response(200, json={
            "marketdata": {"columns": ["SECID", "LAST"], "data": [["XXXX", None]]}
        })
    )
    assert MoexClient(BASE).last_price("XXXX") is None


@respx.mock
def test_last_price_returns_none_on_empty_data():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/NOPE.json").mock(
        return_value=httpx.Response(200, json={"marketdata": {"columns": ["SECID", "LAST"], "data": []}})
    )
    assert MoexClient(BASE).last_price("NOPE") is None


@respx.mock
def test_close_history_parses_rows():
    respx.get(f"{BASE}/history/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(200, json={
            "history": {
                "columns": ["TRADEDATE", "SECID", "CLOSE"],
                "data": [["2026-03-10", "SBER", 310.5], ["2026-03-11", "SBER", 314.28]],
            }
        })
    )
    rows = MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11))
    assert rows == [(date(2026, 3, 10), Decimal("310.5000")), (date(2026, 3, 11), Decimal("314.2800"))]


@respx.mock
def test_http_error_raises():
    respx.get(f"{BASE}/engines/stock/markets/shares/securities/SBER.json").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(httpx.HTTPStatusError):
        MoexClient(BASE).last_price("SBER")
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_moex.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.marketdata'`

- [ ] **Step 3: Реализовать `backend/app/marketdata/moex.py` и пустой `backend/app/marketdata/__init__.py`**

```python
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money


def _rows(block: dict) -> list[dict]:
    columns = block["columns"]
    return [dict(zip(columns, row)) for row in block["data"]]


class MoexClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        response = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def last_price(self, secid: str, market: str = "shares") -> Decimal | None:
        payload = self._get(
            f"/engines/stock/markets/{market}/securities/{secid}.json",
            params={"iss.meta": "off", "iss.only": "marketdata"},
        )
        for row in _rows(payload["marketdata"]):
            if row.get("LAST") is not None:
                return money(str(row["LAST"]))
        return None

    def close_history(
        self, secid: str, start: date, end: date, market: str = "shares"
    ) -> list[tuple[date, Decimal]]:
        payload = self._get(
            f"/history/engines/stock/markets/{market}/securities/{secid}.json",
            params={
                "iss.meta": "off",
                "iss.only": "history",
                "history.columns": "TRADEDATE,SECID,CLOSE",
                "from": start.isoformat(),
                "till": end.isoformat(),
            },
        )
        result: list[tuple[date, Decimal]] = []
        for row in _rows(payload["history"]):
            if row.get("CLOSE") is None:
                continue
            traded = datetime.strptime(row["TRADEDATE"], "%Y-%m-%d").date()
            result.append((traded, money(str(row["CLOSE"]))))
        return result
```

`money(str(...))` вместо `money(...)`: ISS отдаёт числа как JSON float, и прямая передача упёрлась бы в запрет float из задачи 2. Строковая обёртка сохраняет десятичное представление.

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_moex.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 5: Проверить на живом ISS**

Run: `cd backend && uv run python -c "from app.marketdata.moex import MoexClient; print(MoexClient().last_price('SBER'))"`
Expected: печатается Decimal с текущей ценой (в выходные — `None`, это нормально)

- [ ] **Step 6: Коммит**

```bash
git add backend/app/marketdata backend/tests/test_moex.py
git commit -m "feat: клиент MOEX ISS для цен и истории котировок"
```

---

### Task 8: Хранение цен и обновление котировок

**Files:**
- Create: `backend/app/models/price.py`, `backend/app/marketdata/service.py`
- Modify: `backend/app/models/__init__.py` — экспорт `Price`
- Create: `backend/alembic/versions/0003_price.py`
- Test: `backend/tests/test_marketdata_service.py`

**Interfaces:**
- Consumes: `MoexClient`, `Instrument`
- Produces:
  - `Price(id, instrument_id, on_date, close, source)` с уникальностью `(instrument_id, on_date)`
  - `refresh_last_prices(session, client: MoexClient, on_date: date) -> int` — возвращает число обновлённых инструментов
  - `latest_prices(session) -> dict[int, Decimal]` — последняя известная цена по каждому инструменту

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_marketdata_service.py`:

```python
from datetime import date
from decimal import Decimal

from app.marketdata.service import latest_prices, refresh_last_prices
from app.models import Instrument, Price


class FakeMoex:
    def __init__(self, prices: dict[str, Decimal | None]) -> None:
        self.prices = prices
        self.calls: list[str] = []

    def last_price(self, secid: str, market: str = "shares") -> Decimal | None:
        self.calls.append(secid)
        return self.prices.get(secid)


def add_instrument(session, secid: str) -> Instrument:
    instrument = Instrument(isin=f"RU{secid:0>10}", ticker=secid, secid=secid,
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_writes_price_for_each_instrument(session):
    add_instrument(session, "SBER")
    add_instrument(session, "GAZP")
    client = FakeMoex({"SBER": Decimal("314.28"), "GAZP": Decimal("128.10")})

    updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 2
    assert sorted(client.calls) == ["GAZP", "SBER"]


def test_missing_price_is_skipped_without_error(session):
    add_instrument(session, "SBER")
    add_instrument(session, "DEAD")
    client = FakeMoex({"SBER": Decimal("314.28"), "DEAD": None})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 1


def test_second_run_same_day_updates_instead_of_duplicating(session):
    add_instrument(session, "SBER")
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("300")}), date(2026, 3, 12))
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("314.28")}), date(2026, 3, 12))

    rows = session.query(Price).all()
    assert len(rows) == 1
    assert rows[0].close == Decimal("314.2800")


def test_latest_prices_takes_most_recent_date(session):
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 10), close=Decimal("300"), source="moex"),
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 12), close=Decimal("314.28"), source="moex"),
    ])
    session.flush()

    assert latest_prices(session) == {instrument.id: Decimal("314.2800")}


def test_instrument_without_secid_is_not_requested(session):
    instrument = Instrument(isin="RU000MANUAL1", ticker=None, secid=None,
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    client = FakeMoex({})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 0
    assert client.calls == []
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_marketdata_service.py -v`
Expected: FAIL с `ImportError: cannot import name 'Price'`

- [ ] **Step 3: Создать `backend/app/models/price.py`**

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Price(Base):
    __tablename__ = "price"
    __table_args__ = (UniqueConstraint("instrument_id", "on_date", name="uq_price_instrument_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    source: Mapped[str] = mapped_column(String(16), default="moex")
```

- [ ] **Step 4: Добавить `Price` в `backend/app/models/__init__.py`**

```python
from app.models.price import Price
```

и в `__all__`.

- [ ] **Step 5: Создать `backend/app/marketdata/service.py`**

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Instrument, Price

MARKET_BY_KIND = {"share": "shares", "etf": "shares", "bond": "bonds", "currency": "selt"}


def refresh_last_prices(session: Session, client, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(Instrument.secid.is_not(None))
    ).scalars().all()

    updated = 0
    for instrument in instruments:
        market = MARKET_BY_KIND.get(instrument.kind, "shares")
        price = client.last_price(instrument.secid, market=market)
        if price is None:
            continue

        statement = insert(Price).values(
            instrument_id=instrument.id, on_date=on_date, close=price, source="moex"
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date], set_={"close": price}
        )
        session.execute(statement)
        updated += 1

    session.flush()
    return updated


def latest_prices(session: Session) -> dict[int, Decimal]:
    ranked = select(
        Price.instrument_id,
        Price.close,
        func.row_number().over(
            partition_by=Price.instrument_id, order_by=Price.on_date.desc()
        ).label("rn"),
    ).subquery()

    rows = session.execute(
        select(ranked.c.instrument_id, ranked.c.close).where(ranked.c.rn == 1)
    ).all()
    return {instrument_id: close for instrument_id, close in rows}
```

Импорт в начале файла: `from sqlalchemy import func, select`. Оконная функция `row_number()` берёт последнюю по дате цену каждого инструмента одним запросом, без цикла по инструментам.

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_marketdata_service.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 7: Создать миграцию**

Run: `cd backend && uv run alembic revision --autogenerate -m "price table" && uv run alembic upgrade head`

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models backend/app/marketdata backend/alembic/versions backend/tests/test_marketdata_service.py
git commit -m "feat: хранение котировок и обновление цен с MOEX"
```

---

### Task 9: Коннектор Т-Банка

**Files:**
- Create: `backend/app/connectors/__init__.py`, `backend/app/connectors/base.py`, `backend/app/connectors/tbank/__init__.py`, `backend/app/connectors/tbank/mapper.py`, `backend/app/connectors/tbank/connector.py`
- Test: `backend/tests/test_tbank_mapper.py`

**Interfaces:**
- Consumes: `RawOperation`, `OperationType`, `quotation_to_decimal`
- Produces:
  - `BrokerAccount` — dataclass: `external_id: str`, `name: str`, `kind: str`
  - `BrokerPosition` — dataclass: `isin: str`, `ticker: str | None`, `quantity: Decimal`
  - `BrokerConnector` — Protocol с методами `fetch_accounts() -> list[BrokerAccount]`, `fetch_operations(account_external_id: str, since: datetime) -> list[RawOperation]`, `fetch_positions(account_external_id: str) -> list[BrokerPosition]`
  - `map_operation(sdk_operation) -> RawOperation | None`
  - `TBankConnector(token: str)` — реализация протокола

Маппер отделён от клиента намеренно: сетевую часть тестировать дорого, а соответствие типов операций — именно то, что ломается при изменении API. Тесты работают на простых объектах-заглушках с теми же полями, что у SDK.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_tbank_mapper.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.tbank.mapper import map_operation
from app.models import OperationType


@dataclass
class Q:
    units: int
    nano: int


@dataclass
class M:
    units: int
    nano: int
    currency: str = "rub"


@dataclass
class SdkOperation:
    id: str
    operation_type: str
    date: datetime
    instrument_uid: str = ""
    figi: str = ""
    quantity: int = 0
    price: Q = None
    payment: M = None
    currency: str = "rub"
    state: str = "OPERATION_STATE_EXECUTED"


def op(**overrides) -> SdkOperation:
    defaults = dict(
        id="op-1",
        operation_type="OPERATION_TYPE_BUY",
        date=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        quantity=35,
        price=Q(142, 500000000),
        payment=M(-4987, -500000000),
    )
    return SdkOperation(**{**defaults, **overrides})


def test_buy_maps_to_buy_with_positive_quantity():
    result = map_operation(op(), isin="RU0009029540", ticker="SBER")
    assert result.op_type == OperationType.BUY
    assert result.quantity == Decimal("35")
    assert result.price == Decimal("142.5000")
    assert result.amount == Decimal("-4987.5000")
    assert result.external_id == "op-1"


def test_sell_maps_to_sell():
    result = map_operation(
        op(operation_type="OPERATION_TYPE_SELL", payment=M(4987, 500000000)),
        isin="RU0009029540", ticker="SBER",
    )
    assert result.op_type == OperationType.SELL
    assert result.amount == Decimal("4987.5000")


def test_dividend_has_no_quantity():
    result = map_operation(
        op(operation_type="OPERATION_TYPE_DIVIDEND", quantity=0, price=Q(0, 0), payment=M(340, 500000000)),
        isin="RU0009029540", ticker="SBER",
    )
    assert result.op_type == OperationType.DIVIDEND
    assert result.quantity == Decimal("0")
    assert result.amount == Decimal("340.5000")


def test_coupon_maps_to_coupon():
    result = map_operation(op(operation_type="OPERATION_TYPE_COUPON", payment=M(41, 320000000)),
                           isin="RU000A101234", ticker="OFZ")
    assert result.op_type == OperationType.COUPON


def test_broker_fee_maps_to_fee():
    result = map_operation(op(operation_type="OPERATION_TYPE_BROKER_FEE", payment=M(-1, -496300000)),
                           isin=None, ticker=None)
    assert result.op_type == OperationType.FEE
    assert result.isin is None


def test_input_maps_to_deposit():
    result = map_operation(op(operation_type="OPERATION_TYPE_INPUT", payment=M(100000, 0)),
                           isin=None, ticker=None)
    assert result.op_type == OperationType.DEPOSIT


def test_unknown_type_maps_to_other_and_keeps_payload():
    result = map_operation(op(operation_type="OPERATION_TYPE_SOMETHING_NEW"), isin=None, ticker=None)
    assert result.op_type == OperationType.OTHER
    assert result.payload["operation_type"] == "OPERATION_TYPE_SOMETHING_NEW"


def test_unexecuted_operation_is_skipped():
    assert map_operation(op(state="OPERATION_STATE_CANCELED"), isin=None, ticker=None) is None
```

Тест про неизвестный тип операции существенен: T-Invest API добавляет типы, и падение синхронизации из-за незнакомой строки хуже, чем запись с типом `OTHER`, которую видно в журнале.

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_tbank_mapper.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.connectors'`

- [ ] **Step 3: Создать `backend/app/connectors/base.py` и пустой `backend/app/connectors/__init__.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.ledger.schemas import RawOperation


@dataclass(frozen=True)
class BrokerAccount:
    external_id: str
    name: str
    kind: str


@dataclass(frozen=True)
class BrokerPosition:
    isin: str
    ticker: str | None
    quantity: Decimal


class BrokerConnector(Protocol):
    source: str

    def fetch_accounts(self) -> list[BrokerAccount]: ...

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]: ...

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]: ...
```

- [ ] **Step 4: Создать `backend/app/connectors/tbank/mapper.py` и пустой `backend/app/connectors/tbank/__init__.py`**

```python
from decimal import Decimal

from app.ledger.schemas import RawOperation
from app.models import OperationType
from app.money import money, quantity, quotation_to_decimal

TYPE_MAP = {
    "OPERATION_TYPE_BUY": OperationType.BUY,
    "OPERATION_TYPE_BUY_CARD": OperationType.BUY,
    "OPERATION_TYPE_SELL": OperationType.SELL,
    "OPERATION_TYPE_DIVIDEND": OperationType.DIVIDEND,
    "OPERATION_TYPE_COUPON": OperationType.COUPON,
    "OPERATION_TYPE_BROKER_FEE": OperationType.FEE,
    "OPERATION_TYPE_SERVICE_FEE": OperationType.FEE,
    "OPERATION_TYPE_TAX": OperationType.TAX,
    "OPERATION_TYPE_DIVIDEND_TAX": OperationType.TAX,
    "OPERATION_TYPE_INPUT": OperationType.DEPOSIT,
    "OPERATION_TYPE_OUTPUT": OperationType.WITHDRAWAL,
    "OPERATION_TYPE_BOND_REPAYMENT": OperationType.REDEMPTION,
    "OPERATION_TYPE_BOND_REPAYMENT_FULL": OperationType.REDEMPTION,
    "OPERATION_TYPE_BOND_AMORTIZATION": OperationType.AMORTIZATION,
    "OPERATION_TYPE_MARGIN_FEE": OperationType.FEE,
}

EXECUTED = "OPERATION_STATE_EXECUTED"


def _as_str(value) -> str:
    return value if isinstance(value, str) else getattr(value, "name", str(value))


def map_operation(sdk_operation, isin: str | None, ticker: str | None) -> RawOperation | None:
    if _as_str(sdk_operation.state) != EXECUTED:
        return None

    raw_type = _as_str(sdk_operation.operation_type)
    op_type = TYPE_MAP.get(raw_type, OperationType.OTHER)

    price = sdk_operation.price
    payment = sdk_operation.payment

    return RawOperation(
        external_id=str(sdk_operation.id),
        op_type=op_type,
        executed_at=sdk_operation.date,
        isin=isin,
        ticker=ticker,
        quantity=quantity(Decimal(sdk_operation.quantity or 0)),
        price=quotation_to_decimal(price.units, price.nano) if price else money("0"),
        amount=quotation_to_decimal(payment.units, payment.nano) if payment else money("0"),
        currency=(getattr(payment, "currency", None) or sdk_operation.currency or "rub").upper(),
        fee=money("0"),
        payload={"operation_type": raw_type, "figi": sdk_operation.figi},
    )
```

Комиссия не вычитается из `fee` сделки: T-Invest API отдаёт брокерскую комиссию отдельной операцией `OPERATION_TYPE_BROKER_FEE`, и учитывать её дважды нельзя. Поэтому `fee` у сделок нулевая, а комиссии живут в журнале как самостоятельные записи.

- [ ] **Step 5: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_tbank_mapper.py -v`
Expected: PASS, 8 тестов

- [ ] **Step 6: Создать `backend/app/connectors/tbank/connector.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal

from tinkoff.invest import Client
from tinkoff.invest.constants import INVEST_GRPC_API

from app.connectors.base import BrokerAccount, BrokerPosition
from app.connectors.tbank.mapper import map_operation
from app.ledger.schemas import RawOperation
from app.money import quantity, quotation_to_decimal

ACCOUNT_KIND = {"ACCOUNT_TYPE_TINKOFF_IIS": "iis"}


def _as_str(value) -> str:
    return value if isinstance(value, str) else getattr(value, "name", str(value))


class TBankConnector:
    source = "tbank"

    def __init__(self, token: str) -> None:
        self.token = token

    def fetch_accounts(self) -> list[BrokerAccount]:
        with Client(self.token, target=INVEST_GRPC_API) as client:
            response = client.users.get_accounts()
            return [
                BrokerAccount(
                    external_id=account.id,
                    name=account.name or "Счёт",
                    kind=ACCOUNT_KIND.get(_as_str(account.type), "brokerage"),
                )
                for account in response.accounts
            ]

    def fetch_operations(self, account_external_id: str, since: datetime) -> list[RawOperation]:
        with Client(self.token, target=INVEST_GRPC_API) as client:
            response = client.operations.get_operations(
                account_id=account_external_id,
                from_=since,
                to=datetime.now(tz=timezone.utc),
            )
            instruments = self._instrument_index(client, response.operations)

            mapped: list[RawOperation] = []
            for operation in response.operations:
                isin, ticker = instruments.get(operation.figi, (None, None))
                result = map_operation(operation, isin=isin, ticker=ticker)
                if result is not None:
                    mapped.append(result)
            return mapped

    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]:
        with Client(self.token, target=INVEST_GRPC_API) as client:
            portfolio = client.operations.get_portfolio(account_id=account_external_id)
            positions: list[BrokerPosition] = []
            for item in portfolio.positions:
                instrument = client.instruments.find_instrument(query=item.figi)
                found = instrument.instruments[0] if instrument.instruments else None
                if found is None or not found.isin:
                    continue
                positions.append(
                    BrokerPosition(
                        isin=found.isin,
                        ticker=found.ticker,
                        quantity=quantity(quotation_to_decimal(
                            item.quantity.units, item.quantity.nano
                        )),
                    )
                )
            return positions

    @staticmethod
    def _instrument_index(client, operations) -> dict[str, tuple[str | None, str | None]]:
        index: dict[str, tuple[str | None, str | None]] = {}
        for figi in {op.figi for op in operations if op.figi}:
            found = client.instruments.find_instrument(query=figi)
            if found.instruments:
                instrument = found.instruments[0]
                index[figi] = (instrument.isin or None, instrument.ticker or None)
        return index
```

- [ ] **Step 7: Проверить коннектор на живом API**

Run: `cd backend && uv run python -c "from app.config import get_settings; from app.connectors.tbank.connector import TBankConnector; print(TBankConnector(get_settings().tbank_token).fetch_accounts())"`
Expected: список счетов с реальными идентификаторами

Если метод отсутствует или переименован, поправить `connector.py` под текущее SDK — маппер и остальной код от этого не зависят.

- [ ] **Step 8: Коммит**

```bash
git add backend/app/connectors backend/tests/test_tbank_mapper.py
git commit -m "feat: коннектор Т-Банка и маппер операций T-Invest API"
```

---

### Task 10: Материализация позиций

**Files:**
- Create: `backend/app/models/position.py`, `backend/app/positions/service.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0004_position.py`
- Test: `backend/tests/test_positions_service.py`

**Interfaces:**
- Consumes: `fold`, `LedgerEntry`, `Transaction`, `Account`
- Produces:
  - `Position(id, account_id, instrument_id, quantity, average_price, updated_at)` с уникальностью `(account_id, instrument_id)`
  - `rebuild_positions(session, account: Account) -> int` — число позиций после пересборки

Позиции пересобираются целиком, а не инкрементально: журнал append-only и обычно содержит тысячи записей, полный пересчёт занимает миллисекунды, а инкрементальное обновление — источник рассинхронизации.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_positions_service.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.models import Account, Instrument, OperationType, Position, Transaction
from app.positions.service import rebuild_positions


def setup_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def add_tx(session, account, instrument, op_type, day, qty, price, amount):
    session.add(Transaction(
        account_id=account.id,
        instrument_id=instrument.id if instrument else None,
        op_type=op_type,
        executed_at=datetime(2026, 3, day, tzinfo=timezone.utc),
        quantity=Decimal(qty), price=Decimal(price), amount=Decimal(amount),
        currency="RUB", fee=Decimal("0"), external_id=f"tx-{day}-{op_type}",
        source="tbank", payload={}, dedup_key=f"key-{day}-{op_type}",
    ))
    session.flush()


def add_instrument(session) -> Instrument:
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_creates_position_from_journal(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")

    assert rebuild_positions(session, account) == 1

    position = session.query(Position).one()
    assert position.quantity == Decimal("10.00000000")
    assert position.average_price == Decimal("100.0000")


def test_rebuild_is_idempotent(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")

    rebuild_positions(session, account)
    rebuild_positions(session, account)

    assert session.query(Position).count() == 1


def test_closed_position_is_removed(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")
    rebuild_positions(session, account)

    add_tx(session, account, instrument, OperationType.SELL, 2, "10", "120", "1200")
    assert rebuild_positions(session, account) == 0
    assert session.query(Position).count() == 0


def test_cash_operations_do_not_create_positions(session):
    account = setup_account(session)
    add_tx(session, account, None, OperationType.DEPOSIT, 1, "0", "0", "50000")

    assert rebuild_positions(session, account) == 0
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_positions_service.py -v`
Expected: FAIL с `ImportError: cannot import name 'Position'`

- [ ] **Step 3: Создать `backend/app/models/position.py`**

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Position(Base):
    __tablename__ = "position"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_position_account_instrument"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    average_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Экспортировать `Position` в `backend/app/models/__init__.py`**

- [ ] **Step 5: Создать `backend/app/positions/service.py`**

```python
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Account, Position, Transaction
from app.positions.engine import LedgerEntry, fold


def _entries(session: Session, account: Account) -> list[LedgerEntry]:
    transactions = session.execute(
        select(Transaction).where(Transaction.account_id == account.id)
    ).scalars().all()
    return [
        LedgerEntry(
            op_type=tx.op_type,
            executed_at=tx.executed_at,
            instrument_id=tx.instrument_id,
            quantity=tx.quantity,
            price=tx.price,
            amount=tx.amount,
            fee=tx.fee,
        )
        for tx in transactions
    ]


def rebuild_positions(session: Session, account: Account) -> int:
    result = fold(_entries(session, account), currency=account.currency)

    session.execute(delete(Position).where(Position.account_id == account.id))

    kept = 0
    for instrument_id, state in result.positions.items():
        if state.quantity == 0:
            continue
        session.add(
            Position(
                account_id=account.id,
                instrument_id=instrument_id,
                quantity=state.quantity,
                average_price=state.average_price,
            )
        )
        kept += 1

    session.flush()
    return kept
```

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_positions_service.py -v`
Expected: PASS, 4 теста

- [ ] **Step 7: Создать миграцию**

Run: `cd backend && uv run alembic revision --autogenerate -m "position table" && uv run alembic upgrade head`

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models backend/app/positions/service.py backend/alembic/versions backend/tests/test_positions_service.py
git commit -m "feat: материализация позиций из журнала операций"
```

---

### Task 11: Сверка с брокером

**Files:**
- Create: `backend/app/models/reconciliation.py`, `backend/app/sync/__init__.py`, `backend/app/sync/reconcile.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0005_reconciliation.py`
- Test: `backend/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `BrokerPosition`, `Position`, `Instrument`, `Account`
- Produces:
  - `Reconciliation(id, account_id, instrument_id, isin, ledger_quantity, broker_quantity, status, checked_at, note)`
  - `reconcile_account(session, account, broker_positions: list[BrokerPosition]) -> list[Reconciliation]` — возвращает только расхождения; совпадения не сохраняются

Ключевое поведение: расхождение фиксируется, но позиция **не** правится. Тест на это обязателен — именно эту защиту проще всего случайно сломать при рефакторинге.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_reconcile.py`:

```python
from decimal import Decimal

from app.connectors.base import BrokerPosition
from app.models import Account, Instrument, Position, Reconciliation
from app.sync.reconcile import reconcile_account


def setup(session) -> tuple[Account, Instrument]:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB")
    session.add_all([account, instrument])
    session.flush()
    return account, instrument


def add_position(session, account, instrument, qty: str) -> Position:
    position = Position(account_id=account.id, instrument_id=instrument.id,
                        quantity=Decimal(qty), average_price=Decimal("100"))
    session.add(position)
    session.flush()
    return position


def test_matching_quantities_produce_no_records(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("35"))
    ])

    assert result == []
    assert session.query(Reconciliation).count() == 0


def test_quantity_mismatch_is_recorded(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))
    ])

    assert len(result) == 1
    assert result[0].ledger_quantity == Decimal("35.00000000")
    assert result[0].broker_quantity == Decimal("40.00000000")
    assert result[0].status == "quantity_mismatch"


def test_mismatch_does_not_modify_position(session):
    account, instrument = setup(session)
    position = add_position(session, account, instrument, "35")

    reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))
    ])

    session.refresh(position)
    assert position.quantity == Decimal("35.00000000")


def test_position_missing_in_ledger_is_recorded(session):
    account, _ = setup(session)

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU000A101234", ticker="OFZ", quantity=Decimal("10"))
    ])

    assert result[0].status == "missing_in_ledger"
    assert result[0].ledger_quantity == Decimal("0")
    assert result[0].isin == "RU000A101234"


def test_position_missing_at_broker_is_recorded(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [])

    assert result[0].status == "missing_at_broker"
    assert result[0].broker_quantity == Decimal("0")


def test_rerun_replaces_previous_results(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")
    broker = [BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))]

    reconcile_account(session, account, broker)
    reconcile_account(session, account, broker)

    assert session.query(Reconciliation).count() == 1


def test_tiny_difference_below_threshold_is_ignored(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("35.000000001"))
    ])

    assert result == []
```

Последний тест — защита от ложных срабатываний на округлении дробных паёв фондов.

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_reconcile.py -v`
Expected: FAIL с `ImportError: cannot import name 'Reconciliation'`

- [ ] **Step 3: Создать `backend/app/models/reconciliation.py`**

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Reconciliation(Base):
    __tablename__ = "reconciliation"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    isin: Mapped[str | None] = mapped_column(String(12))
    ledger_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    broker_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
```

`status` принимает значения `quantity_mismatch`, `missing_in_ledger`, `missing_at_broker`.

- [ ] **Step 4: Экспортировать `Reconciliation` в `backend/app/models/__init__.py`**

- [ ] **Step 5: Создать `backend/app/sync/reconcile.py` и пустой `backend/app/sync/__init__.py`**

```python
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.models import Account, Instrument, Position, Reconciliation

TOLERANCE = Decimal("0.000001")


def reconcile_account(
    session: Session, account: Account, broker_positions: list[BrokerPosition]
) -> list[Reconciliation]:
    session.execute(delete(Reconciliation).where(Reconciliation.account_id == account.id))

    rows = session.execute(
        select(Position, Instrument)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .where(Position.account_id == account.id)
    ).all()

    ledger: dict[str, tuple[Position, Instrument]] = {
        instrument.isin: (position, instrument)
        for position, instrument in rows
        if instrument.isin
    }
    broker: dict[str, BrokerPosition] = {item.isin: item for item in broker_positions}

    findings: list[Reconciliation] = []

    for isin in sorted(ledger.keys() | broker.keys()):
        position_pair = ledger.get(isin)
        broker_position = broker.get(isin)

        ledger_qty = position_pair[0].quantity if position_pair else Decimal("0")
        broker_qty = broker_position.quantity if broker_position else Decimal("0")

        if abs(ledger_qty - broker_qty) <= TOLERANCE:
            continue

        if position_pair is None:
            status = "missing_in_ledger"
        elif broker_position is None:
            status = "missing_at_broker"
        else:
            status = "quantity_mismatch"

        finding = Reconciliation(
            account_id=account.id,
            instrument_id=position_pair[1].id if position_pair else None,
            isin=isin,
            ledger_quantity=ledger_qty,
            broker_quantity=broker_qty,
            status=status,
        )
        session.add(finding)
        findings.append(finding)

    session.flush()
    return findings
```

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_reconcile.py -v`
Expected: PASS, 7 тестов

- [ ] **Step 7: Создать миграцию**

Run: `cd backend && uv run alembic revision --autogenerate -m "reconciliation table" && uv run alembic upgrade head`

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models backend/app/sync backend/alembic/versions backend/tests/test_reconcile.py
git commit -m "feat: сверка расчётных позиций со снимком брокера"
```

---

### Task 12: Оркестрация синхронизации

**Files:**
- Create: `backend/app/models/sync_run.py`, `backend/app/sync/service.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0006_sync_run.py`
- Test: `backend/tests/test_sync_service.py`

**Interfaces:**
- Consumes: `BrokerConnector`, `append_operations`, `rebuild_positions`, `reconcile_account`
- Produces:
  - `SyncRun(id, broker, account_id, started_at, finished_at, status, inserted, skipped, mismatches, error)`
  - `sync_broker(session, connector: BrokerConnector, since: datetime) -> list[SyncRun]`

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_sync_service.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import BrokerAccount, BrokerPosition
from app.ledger.schemas import RawOperation
from app.models import Account, OperationType, Position, SyncRun
from app.sync.service import sync_broker

SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeConnector:
    source = "tbank"

    def __init__(self, operations=None, positions=None, fail_on_positions=False):
        self.operations = operations or []
        self.positions = positions or []
        self.fail_on_positions = fail_on_positions

    def fetch_accounts(self):
        return [BrokerAccount(external_id="acc-1", name="Брокерский", kind="brokerage")]

    def fetch_operations(self, account_external_id, since):
        return self.operations

    def fetch_positions(self, account_external_id):
        if self.fail_on_positions:
            raise RuntimeError("брокер недоступен")
        return self.positions


def buy() -> RawOperation:
    return RawOperation(
        external_id="op-1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal("35"),
        price=Decimal("142.5"), amount=Decimal("-4987.5"), currency="RUB",
        fee=Decimal("0"), payload={},
    )


def test_creates_account_on_first_sync(session):
    sync_broker(session, FakeConnector(), SINCE)
    account = session.query(Account).one()
    assert account.external_id == "acc-1"
    assert account.broker == "tbank"


def test_second_sync_reuses_account(session):
    sync_broker(session, FakeConnector(), SINCE)
    sync_broker(session, FakeConnector(), SINCE)
    assert session.query(Account).count() == 1


def test_operations_land_in_journal_and_positions(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()],
                                              positions=[BrokerPosition("RU0009029540", "SBER", Decimal("35"))]), SINCE)
    assert runs[0].inserted == 1
    assert runs[0].mismatches == 0
    assert session.query(Position).one().quantity == Decimal("35.00000000")


def test_mismatch_is_counted(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()],
                                              positions=[BrokerPosition("RU0009029540", "SBER", Decimal("40"))]), SINCE)
    assert runs[0].mismatches == 1
    assert runs[0].status == "success"


def test_connector_failure_is_recorded_not_raised(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()], fail_on_positions=True), SINCE)
    assert runs[0].status == "failed"
    assert "недоступен" in runs[0].error


def test_failed_sync_keeps_already_written_operations(session):
    sync_broker(session, FakeConnector(operations=[buy()], fail_on_positions=True), SINCE)
    from app.models import Transaction
    assert session.query(Transaction).count() == 1


def test_run_records_are_persisted(session):
    sync_broker(session, FakeConnector(), SINCE)
    assert session.query(SyncRun).count() == 1
```

Тест про сохранение операций при падении сверки фиксирует главное свойство: отказ на последнем шаге не должен отменять успешно загруженные данные.

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_sync_service.py -v`
Expected: FAIL с `ImportError: cannot import name 'SyncRun'`

- [ ] **Step 3: Создать `backend/app/models/sync_run.py`**

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker: Mapped[str] = mapped_column(String(16), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    mismatches: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Экспортировать `SyncRun` в `backend/app/models/__init__.py`**

- [ ] **Step 5: Создать `backend/app/sync/service.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerConnector
from app.ledger.service import append_operations
from app.models import Account, SyncRun
from app.positions.service import rebuild_positions
from app.sync.reconcile import reconcile_account


def _get_or_create_account(session: Session, broker: str, broker_account) -> Account:
    existing = session.execute(
        select(Account).where(Account.broker == broker, Account.external_id == broker_account.external_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    account = Account(
        broker=broker,
        kind=broker_account.kind,
        external_id=broker_account.external_id,
        name=broker_account.name,
        currency="RUB",
    )
    session.add(account)
    session.flush()
    return account


def sync_broker(session: Session, connector: BrokerConnector, since: datetime) -> list[SyncRun]:
    runs: list[SyncRun] = []

    for broker_account in connector.fetch_accounts():
        account = _get_or_create_account(session, connector.source, broker_account)
        run = SyncRun(broker=connector.source, account_id=account.id, status="running")
        session.add(run)
        session.flush()

        try:
            operations = connector.fetch_operations(account.external_id, since)
            result = append_operations(session, account, connector.source, operations)
            rebuild_positions(session, account)

            broker_positions = connector.fetch_positions(account.external_id)
            findings = reconcile_account(session, account, broker_positions)

            run.inserted = result.inserted
            run.skipped = result.skipped
            run.mismatches = len(findings)
            run.status = "success"
        except Exception as error:  # noqa: BLE001 — отказ источника не должен ронять синхронизацию
            run.status = "failed"
            run.error = str(error)

        run.finished_at = datetime.now(tz=timezone.utc)
        session.flush()
        runs.append(run)

    session.commit()
    return runs
```

Широкий `except` здесь осознан: цель — записать отказ и продолжить с остальными счетами, а не упасть целиком. Текст ошибки сохраняется в `run.error` и показывается в интерфейсе.

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_sync_service.py -v`
Expected: PASS, 7 тестов

- [ ] **Step 7: Создать миграцию**

Run: `cd backend && uv run alembic revision --autogenerate -m "sync run table" && uv run alembic upgrade head`

- [ ] **Step 8: Коммит**

```bash
git add backend/app/models backend/app/sync/service.py backend/alembic/versions backend/tests/test_sync_service.py
git commit -m "feat: оркестрация синхронизации с записью статусов запусков"
```

---

### Task 13: Снимки стоимости и сводка портфеля

**Files:**
- Create: `backend/app/models/snapshot.py`, `backend/app/snapshots/__init__.py`, `backend/app/snapshots/service.py`, `backend/app/analytics/__init__.py`, `backend/app/analytics/service.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0007_snapshot.py`
- Test: `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: `Position`, `Instrument`, `latest_prices`
- Produces:
  - `DailySnapshot(id, on_date, total_value, by_asset_class, by_account)` — разбивки в JSONB
  - `take_snapshot(session, on_date: date) -> DailySnapshot`
  - `portfolio_overview(session) -> Overview` — dataclass: `total_value: Decimal`, `positions_value: Decimal`, `by_asset_class: dict[str, Decimal]`, `by_account: dict[str, Decimal]`
  - `position_rows(session) -> list[PositionRow]` — dataclass: `isin`, `ticker`, `name`, `broker`, `quantity`, `average_price`, `last_price`, `market_value`, `profit`, `profit_percent`

Класс актива определяется так: для фонда берётся `asset_class`, для остальных — маппинг из `kind`. Это и есть look-through в том объёме, который заявлен в спеке.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_analytics.py`:

```python
from datetime import date
from decimal import Decimal

from app.analytics.service import portfolio_overview, position_rows
from app.models import Account, DailySnapshot, Instrument, Position, Price
from app.snapshots.service import take_snapshot


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    share = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                       kind="share", currency="RUB", issuer="Сбербанк")
    fund = Instrument(isin="RU000A0JXMB2", ticker="TMOS", secid="TMOS",
                      kind="etf", currency="RUB", asset_class="equity")
    bond = Instrument(isin="RU000A101234", ticker="OFZ", secid="OFZ",
                      kind="bond", currency="RUB")
    session.add_all([account, share, fund, bond])
    session.flush()

    session.add_all([
        Position(account_id=account.id, instrument_id=share.id,
                 quantity=Decimal("10"), average_price=Decimal("100")),
        Position(account_id=account.id, instrument_id=fund.id,
                 quantity=Decimal("100"), average_price=Decimal("7")),
        Position(account_id=account.id, instrument_id=bond.id,
                 quantity=Decimal("5"), average_price=Decimal("1000")),
    ])
    session.add_all([
        Price(instrument_id=share.id, on_date=date(2026, 3, 12), close=Decimal("150"), source="moex"),
        Price(instrument_id=fund.id, on_date=date(2026, 3, 12), close=Decimal("8"), source="moex"),
        Price(instrument_id=bond.id, on_date=date(2026, 3, 12), close=Decimal("1010"), source="moex"),
    ])
    session.flush()
    return account


def test_total_value_uses_last_prices(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.positions_value == Decimal("7350.0000")


def test_fund_is_counted_by_its_asset_class(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.by_asset_class["equity"] == Decimal("2300.0000")
    assert overview.by_asset_class["bonds"] == Decimal("5050.0000")
    assert "etf" not in overview.by_asset_class


def test_position_row_computes_profit(session):
    seed(session)
    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["SBER"].market_value == Decimal("1500.0000")
    assert rows["SBER"].profit == Decimal("500.0000")
    assert rows["SBER"].profit_percent == Decimal("50.0000")


def test_position_without_price_has_zero_market_value(session):
    account = seed(session)
    nameless = Instrument(isin="RU000NOPRICE", ticker="NONE", secid=None,
                          kind="share", currency="RUB")
    session.add(nameless)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=nameless.id,
                         quantity=Decimal("1"), average_price=Decimal("50")))
    session.flush()

    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["NONE"].last_price is None
    assert rows["NONE"].market_value == Decimal("0.0000")


def test_snapshot_stores_total_and_breakdown(session):
    seed(session)
    snapshot = take_snapshot(session, date(2026, 3, 12))
    assert snapshot.total_value == Decimal("7350.0000")
    assert snapshot.by_asset_class["equity"] == "2300.0000"


def test_snapshot_same_day_is_overwritten(session):
    seed(session)
    take_snapshot(session, date(2026, 3, 12))
    take_snapshot(session, date(2026, 3, 12))
    assert session.query(DailySnapshot).count() == 1
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_analytics.py -v`
Expected: FAIL с `ImportError: cannot import name 'DailySnapshot'`

- [ ] **Step 3: Создать `backend/app/models/snapshot.py`**

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    __table_args__ = (UniqueConstraint("on_date", name="uq_snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    by_asset_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    by_account: Mapped[dict] = mapped_column(JSONB, default=dict)
```

Разбивки хранятся строками (`"2300.0000"`), а не числами: JSON не имеет десятичного типа, и запись float вернула бы в систему ровно ту неточность, которую задача 2 запрещает.

- [ ] **Step 4: Экспортировать `DailySnapshot` в `backend/app/models/__init__.py`**

- [ ] **Step 5: Создать `backend/app/analytics/service.py` и пустой `backend/app/analytics/__init__.py`**

```python
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.marketdata.service import latest_prices
from app.models import Account, Instrument, Position
from app.money import money

CLASS_BY_KIND = {
    "share": "equity",
    "bond": "bonds",
    "currency": "cash",
    "metal": "gold",
    "futures": "derivatives",
}


@dataclass(frozen=True)
class PositionRow:
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal | None
    market_value: Decimal
    profit: Decimal
    profit_percent: Decimal


@dataclass(frozen=True)
class Overview:
    total_value: Decimal
    positions_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]


def asset_class_of(instrument: Instrument) -> str:
    if instrument.kind == "etf":
        return instrument.asset_class or "mixed"
    return CLASS_BY_KIND.get(instrument.kind, "other")


def _rows(session: Session):
    return session.execute(
        select(Position, Instrument, Account)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .join(Account, Position.account_id == Account.id)
    ).all()


def position_rows(session: Session) -> list[PositionRow]:
    prices = latest_prices(session)
    result: list[PositionRow] = []

    for position, instrument, account in _rows(session):
        last_price = prices.get(instrument.id)
        market_value = money(position.quantity * last_price) if last_price else money("0")
        cost = money(position.quantity * position.average_price)
        profit = money(market_value - cost) if last_price else money("0")
        percent = money(profit / cost * 100) if last_price and cost != 0 else money("0")

        result.append(
            PositionRow(
                isin=instrument.isin,
                ticker=instrument.ticker,
                name=instrument.issuer or instrument.ticker or instrument.isin or "—",
                broker=account.broker,
                quantity=position.quantity,
                average_price=position.average_price,
                last_price=last_price,
                market_value=market_value,
                profit=profit,
                profit_percent=percent,
            )
        )
    return result


def portfolio_overview(session: Session) -> Overview:
    prices = latest_prices(session)
    by_class: dict[str, Decimal] = {}
    by_account: dict[str, Decimal] = {}
    total = money("0")

    for position, instrument, account in _rows(session):
        last_price = prices.get(instrument.id)
        if last_price is None:
            continue
        value = money(position.quantity * last_price)
        total = money(total + value)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + value)
        by_account[account.name] = money(by_account.get(account.name, money("0")) + value)

    return Overview(
        total_value=total, positions_value=total, by_asset_class=by_class, by_account=by_account
    )
```

`total_value` и `positions_value` совпадают в первой фазе: денежные остатки появятся во второй вместе с депозитами и ручными активами. Поле разделено уже сейчас, чтобы фронтенд не переписывать.

- [ ] **Step 6: Создать `backend/app/snapshots/service.py` и пустой `backend/app/snapshots/__init__.py`**

```python
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.service import portfolio_overview
from app.models import DailySnapshot


def take_snapshot(session: Session, on_date: date) -> DailySnapshot:
    overview = portfolio_overview(session)

    values = {
        "on_date": on_date,
        "total_value": overview.total_value,
        "by_asset_class": {k: str(v) for k, v in overview.by_asset_class.items()},
        "by_account": {k: str(v) for k, v in overview.by_account.items()},
    }

    statement = insert(DailySnapshot).values(**values).on_conflict_do_update(
        index_elements=[DailySnapshot.on_date],
        set_={
            "total_value": values["total_value"],
            "by_asset_class": values["by_asset_class"],
            "by_account": values["by_account"],
        },
    )
    session.execute(statement)
    session.flush()

    return session.query(DailySnapshot).filter(DailySnapshot.on_date == on_date).one()
```

- [ ] **Step 7: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_analytics.py -v`
Expected: PASS, 6 тестов

- [ ] **Step 8: Создать миграцию**

Run: `cd backend && uv run alembic revision --autogenerate -m "daily snapshot" && uv run alembic upgrade head`

- [ ] **Step 9: Коммит**

```bash
git add backend/app/models backend/app/analytics backend/app/snapshots backend/alembic/versions backend/tests/test_analytics.py
git commit -m "feat: сводка портфеля, аллокация по классам и ежедневные снимки"
```

---

### Task 14: REST API

**Files:**
- Create: `backend/app/api/__init__.py`, `backend/app/api/schemas.py`, `backend/app/api/routes_portfolio.py`, `backend/app/api/routes_sync.py`
- Modify: `backend/app/main.py` — подключить роутеры
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `portfolio_overview`, `position_rows`, `sync_broker`, `TBankConnector`, `get_session`
- Produces: эндпоинты
  - `GET /api/portfolio/overview` → `{total_value, positions_value, by_asset_class, by_account, as_of}`
  - `GET /api/portfolio/positions` → список позиций
  - `GET /api/portfolio/history?days=90` → `[{date, total_value}]`
  - `GET /api/reconciliations` → список расхождений
  - `POST /api/sync/tbank` → `[{account, status, inserted, skipped, mismatches, error}]`

Денежные значения отдаются **строками**, а не числами: JSON-число в JavaScript — это float64, и 4987.5000 на фронте способно стать 4987.499999999999.

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/test_api.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import Account, DailySnapshot, Instrument, Position, Price, Reconciliation


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB", issuer="Сбербанк")
    session.add_all([account, instrument])
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=instrument.id,
                         quantity=Decimal("10"), average_price=Decimal("100")))
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 3, 12),
                      close=Decimal("150"), source="moex"))
    session.flush()
    return account, instrument


def test_overview_returns_strings_not_floats(client, session):
    seed(session)
    payload = client.get("/api/portfolio/overview").json()
    assert payload["positions_value"] == "1500.0000"
    assert isinstance(payload["by_asset_class"]["equity"], str)


def test_positions_endpoint_returns_row(client, session):
    seed(session)
    rows = client.get("/api/portfolio/positions").json()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "SBER"
    assert rows[0]["profit"] == "500.0000"


def test_history_returns_snapshots_in_date_order(client, session):
    session.add_all([
        DailySnapshot(on_date=date(2026, 3, 11), total_value=Decimal("7000"),
                      by_asset_class={}, by_account={}),
        DailySnapshot(on_date=date(2026, 3, 12), total_value=Decimal("7350"),
                      by_asset_class={}, by_account={}),
    ])
    session.flush()

    rows = client.get("/api/portfolio/history?days=90").json()
    assert [row["date"] for row in rows] == ["2026-03-11", "2026-03-12"]
    assert rows[1]["total_value"] == "7350.0000"


def test_reconciliations_endpoint_lists_findings(client, session):
    account, instrument = seed(session)
    session.add(Reconciliation(
        account_id=account.id, instrument_id=instrument.id, isin="RU0009029540",
        ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
        status="quantity_mismatch",
    ))
    session.flush()

    rows = client.get("/api/reconciliations").json()
    assert rows[0]["status"] == "quantity_mismatch"
    assert rows[0]["broker_quantity"] == "12.00000000"


def test_empty_portfolio_returns_zeroes(client, session):
    payload = client.get("/api/portfolio/overview").json()
    assert payload["total_value"] == "0.0000"
    assert payload["by_asset_class"] == {}
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Создать `backend/app/api/schemas.py` и пустой `backend/app/api/__init__.py`**

```python
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class OverviewOut(BaseModel):
    total_value: Decimal
    positions_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]

    @field_serializer("total_value", "positions_value")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_asset_class", "by_account")
    def serialize_mapping(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}


class PositionOut(BaseModel):
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal | None
    market_value: Decimal
    profit: Decimal
    profit_percent: Decimal

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"

    @field_serializer("average_price", "last_price", "market_value", "profit", "profit_percent")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"


class HistoryPointOut(BaseModel):
    date: date
    total_value: Decimal

    @field_serializer("total_value")
    def serialize_total(self, value: Decimal) -> str:
        return f"{value:.4f}"


class ReconciliationOut(BaseModel):
    isin: str | None
    status: str
    ledger_quantity: Decimal
    broker_quantity: Decimal

    @field_serializer("ledger_quantity", "broker_quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"


class SyncRunOut(BaseModel):
    broker: str
    status: str
    inserted: int
    skipped: int
    mismatches: int
    error: str | None
```

- [ ] **Step 4: Создать `backend/app/api/routes_portfolio.py`**

```python
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import portfolio_overview, position_rows
from app.api.schemas import HistoryPointOut, OverviewOut, PositionOut, ReconciliationOut
from app.db import get_session
from app.models import DailySnapshot, Reconciliation

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio/overview", response_model=OverviewOut)
def get_overview(session: Session = Depends(get_session)) -> OverviewOut:
    overview = portfolio_overview(session)
    return OverviewOut(
        total_value=overview.total_value,
        positions_value=overview.positions_value,
        by_asset_class=overview.by_asset_class,
        by_account=overview.by_account,
    )


@router.get("/portfolio/positions", response_model=list[PositionOut])
def get_positions(session: Session = Depends(get_session)) -> list[PositionOut]:
    return [PositionOut(**row.__dict__) for row in position_rows(session)]


@router.get("/portfolio/history", response_model=list[HistoryPointOut])
def get_history(days: int = 90, session: Session = Depends(get_session)) -> list[HistoryPointOut]:
    since = date.today() - timedelta(days=days)
    rows = session.execute(
        select(DailySnapshot).where(DailySnapshot.on_date >= since).order_by(DailySnapshot.on_date)
    ).scalars().all()
    return [HistoryPointOut(date=row.on_date, total_value=row.total_value) for row in rows]


@router.get("/reconciliations", response_model=list[ReconciliationOut])
def get_reconciliations(session: Session = Depends(get_session)) -> list[ReconciliationOut]:
    rows = session.execute(select(Reconciliation).order_by(Reconciliation.isin)).scalars().all()
    return [
        ReconciliationOut(
            isin=row.isin, status=row.status,
            ledger_quantity=row.ledger_quantity, broker_quantity=row.broker_quantity,
        )
        for row in rows
    ]
```

- [ ] **Step 5: Создать `backend/app/api/routes_sync.py`**

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import SyncRunOut
from app.config import get_settings
from app.connectors.tbank.connector import TBankConnector
from app.db import get_session
from app.sync.service import sync_broker

router = APIRouter(prefix="/api/sync", tags=["sync"])

DEFAULT_HISTORY_DAYS = 365 * 5


@router.post("/tbank", response_model=list[SyncRunOut])
def sync_tbank(session: Session = Depends(get_session)) -> list[SyncRunOut]:
    token = get_settings().tbank_token
    if not token:
        raise HTTPException(status_code=400, detail="Не задан TBANK_TOKEN в .env")

    since = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    runs = sync_broker(session, TBankConnector(token), since)
    return [
        SyncRunOut(broker=run.broker, status=run.status, inserted=run.inserted,
                   skipped=run.skipped, mismatches=run.mismatches, error=run.error)
        for run in runs
    ]
```

- [ ] **Step 6: Подключить роутеры в `backend/app/main.py`**

Добавить после создания `app`:

```python
from app.api import routes_portfolio, routes_sync

app.include_router(routes_portfolio.router)
app.include_router(routes_sync.router)
```

- [ ] **Step 7: Запустить все тесты**

Run: `cd backend && uv run pytest -v`
Expected: PASS, все тесты (≈60)

- [ ] **Step 8: Проверить на живых данных**

Run:
```bash
cd backend && uv run uvicorn app.main:app --reload &
curl -X POST http://localhost:8000/api/sync/tbank
curl http://localhost:8000/api/portfolio/overview
```
Expected: синхронизация возвращает статус `success` с числом загруженных операций, обзор — ненулевую стоимость

- [ ] **Step 9: Коммит**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat: REST API портфеля, истории, расхождений и синхронизации"
```

---

### Task 15: Дашборд

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/theme.css`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/MoneyValue.tsx`, `frontend/src/components/SummaryCard.tsx`, `frontend/src/components/AllocationChart.tsx`, `frontend/src/components/ValueChart.tsx`, `frontend/src/components/PositionsTable.tsx`, `frontend/src/components/ReconciliationBanner.tsx`
- Create: `frontend/src/pages/PortfolioPage.tsx`
- Test: `frontend/src/api/format.test.ts`

**Interfaces:**
- Consumes: REST API из задачи 14.
- Produces: SPA на `localhost:3000`, страница «Портфель».

- [ ] **Step 1: Создать каркас фронтенда**

Run:
```bash
pnpm create vite frontend --template react-ts
cd frontend
pnpm add @tanstack/react-query echarts echarts-for-react
pnpm add -D tailwindcss postcss autoprefixer vitest
pnpm exec tailwindcss init -p
```

- [ ] **Step 2: Написать падающий тест форматирования**

`frontend/src/api/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { formatMoney, formatPercent, formatQuantity } from "./format";

describe("formatMoney", () => {
  it("группирует разряды неразрывными пробелами и добавляет рубль", () => {
    expect(formatMoney("4812300.0000")).toBe("4 812 300 ₽");
  });

  it("сохраняет копейки для мелких сумм", () => {
    expect(formatMoney("142.5000")).toBe("142,50 ₽");
  });

  it("не теряет точность на больших числах", () => {
    expect(formatMoney("123456789.1200")).toBe("123 456 789 ₽");
  });

  it("показывает прочерк вместо отсутствующего значения", () => {
    expect(formatMoney(null)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("добавляет знак для роста", () => {
    expect(formatPercent("50.0000")).toBe("+50,0%");
  });

  it("оставляет минус для падения", () => {
    expect(formatPercent("-3.2500")).toBe("−3,3%");
  });
});

describe("formatQuantity", () => {
  it("убирает незначащие нули", () => {
    expect(formatQuantity("35.00000000")).toBe("35");
  });

  it("сохраняет дробные паи", () => {
    expect(formatQuantity("0.50000000")).toBe("0,5");
  });
});
```

- [ ] **Step 3: Запустить тест и убедиться, что он падает**

Run: `cd frontend && pnpm vitest run`
Expected: FAIL с `Cannot find module './format'`

- [ ] **Step 4: Реализовать `frontend/src/api/format.ts`**

```ts
const NBSP = " ";

function group(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

export function formatMoney(raw: string | null | undefined): string {
  if (raw === null || raw === undefined) return "—";
  const [whole, fraction = ""] = raw.split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  const kopecks = fraction.slice(0, 2);
  const showKopecks = digits.length <= 4 && kopecks !== "00";
  const body = group(digits) + (showKopecks ? `,${kopecks}` : "");
  return `${negative ? "−" : ""}${body}${NBSP}₽`;
}

export function formatPercent(raw: string | null | undefined): string {
  if (raw === null || raw === undefined) return "—";
  const value = Number.parseFloat(raw);
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1).replace(".", ",")}%`;
}

export function formatQuantity(raw: string): string {
  const trimmed = raw.replace(/\.?0+$/, "");
  return trimmed.replace(".", ",");
}
```

Проценты — единственное место, где допустим `Number`: значение уже мало, а результат идёт только на экран. Суммы форматируются строковыми операциями и никогда не проходят через `Number`.

- [ ] **Step 5: Запустить тест и убедиться, что он проходит**

Run: `cd frontend && pnpm vitest run`
Expected: PASS, 9 тестов

- [ ] **Step 6: Создать `frontend/src/theme.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-0: #0a0e18;
  --bg-1: #0f1424;
  --card: rgba(255, 255, 255, 0.035);
  --line: rgba(130, 150, 200, 0.16);
  --tx: #e7ecf9;
  --tx-2: #9aa5c4;
  --blue: #7b9cff;
  --green: #4fd39a;
  --red: #f2749a;
  --amber: #e8b04b;
}

body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(1100px 620px at 12% -8%, rgba(90, 130, 255, 0.16), transparent 60%),
    linear-gradient(170deg, var(--bg-1) 0%, var(--bg-0) 55%);
  background-attachment: fixed;
  color: var(--tx);
  font-family: -apple-system, "Segoe UI", Inter, sans-serif;
  font-variant-numeric: tabular-nums;
}

.card {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--card);
  backdrop-filter: blur(8px);
  padding: 18px 20px;
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
```

- [ ] **Step 7: Создать `frontend/src/api/client.ts`**

```ts
const BASE = "http://localhost:8000/api";

export interface Overview {
  total_value: string;
  positions_value: string;
  by_asset_class: Record<string, string>;
  by_account: Record<string, string>;
}

export interface PositionRow {
  isin: string | null;
  ticker: string | null;
  name: string;
  broker: string;
  quantity: string;
  average_price: string;
  last_price: string | null;
  market_value: string;
  profit: string;
  profit_percent: string;
}

export interface HistoryPoint {
  date: string;
  total_value: string;
}

export interface ReconciliationRow {
  isin: string | null;
  status: string;
  ledger_quantity: string;
  broker_quantity: string;
}

export interface SyncRunResult {
  broker: string;
  status: string;
  inserted: number;
  skipped: number;
  mismatches: number;
  error: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(`Запрос ${path} завершился с кодом ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/portfolio/overview"),
  positions: () => request<PositionRow[]>("/portfolio/positions"),
  history: (days = 90) => request<HistoryPoint[]>(`/portfolio/history?days=${days}`),
  reconciliations: () => request<ReconciliationRow[]>("/reconciliations"),
  syncTbank: () => request<SyncRunResult[]>("/sync/tbank", { method: "POST" }),
};
```

- [ ] **Step 8: Создать компоненты**

`frontend/src/components/MoneyValue.tsx`:

```tsx
import { formatMoney, formatPercent } from "../api/format";

export function MoneyValue({ amount, className = "" }: { amount: string | null; className?: string }) {
  return <span className={className}>{formatMoney(amount)}</span>;
}

export function ChangeValue({ percent }: { percent: string }) {
  const value = Number.parseFloat(percent);
  const color = value > 0 ? "var(--green)" : value < 0 ? "var(--red)" : "var(--tx-2)";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  return (
    <span style={{ color }}>
      {arrow} {formatPercent(percent)}
    </span>
  );
}
```

Стрелка дублирует цвет намеренно: цвет как единственный носитель смысла нечитаем при дальтонизме.

`frontend/src/components/SummaryCard.tsx`:

```tsx
import { MoneyValue } from "./MoneyValue";
import type { Overview } from "../api/client";

export function SummaryCard({ overview, onSync, syncing }: {
  overview: Overview;
  onSync: () => void;
  syncing: boolean;
}) {
  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Совокупный капитал</div>
      <div style={{ fontSize: 34, fontWeight: 650, letterSpacing: "-0.025em", margin: "6px 0 14px" }}>
        <MoneyValue amount={overview.total_value} />
      </div>
      <button
        onClick={onSync}
        disabled={syncing}
        style={{
          border: "1px solid var(--line)", borderRadius: 9, padding: "7px 14px",
          background: "rgba(123,156,255,0.14)", color: "var(--blue)", cursor: "pointer",
        }}
      >
        {syncing ? "Синхронизация…" : "Обновить из Т-Банка"}
      </button>
    </div>
  );
}
```

`frontend/src/components/AllocationChart.tsx`:

```tsx
import ReactECharts from "echarts-for-react";

const LABELS: Record<string, string> = {
  equity: "Акции",
  bonds: "Облигации",
  money_market: "Денежный рынок",
  gold: "Золото",
  cash: "Валюта",
  derivatives: "Срочный рынок",
  mixed: "Смешанные",
  other: "Прочее",
};

export function AllocationChart({ data }: { data: Record<string, string> }) {
  const entries = Object.entries(data).map(([key, value]) => ({
    name: LABELS[key] ?? key,
    value: Number.parseFloat(value),
  }));

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 8 }}>Структура портфеля</div>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          tooltip: { trigger: "item", valueFormatter: (v: number) => `${v.toLocaleString("ru-RU")} ₽` },
          legend: { bottom: 0, textStyle: { color: "#9aa5c4" } },
          series: [{
            type: "pie",
            radius: ["52%", "78%"],
            itemStyle: { borderColor: "#0f1424", borderWidth: 2 },
            label: { show: false },
            data: entries,
          }],
        }}
      />
    </div>
  );
}
```

`frontend/src/components/ValueChart.tsx`:

```tsx
import ReactECharts from "echarts-for-react";
import type { HistoryPoint } from "../api/client";

export function ValueChart({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        График появится, когда накопится хотя бы два ежедневных снимка стоимости.
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 8 }}>Стоимость портфеля</div>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          grid: { left: 60, right: 16, top: 16, bottom: 32 },
          xAxis: { type: "category", data: points.map((p) => p.date),
                   axisLine: { lineStyle: { color: "#3a4763" } } },
          yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: "#1c2438" } },
                   axisLabel: { color: "#9aa5c4" } },
          tooltip: { trigger: "axis" },
          series: [{
            type: "line", smooth: true, showSymbol: false,
            lineStyle: { color: "#638cff", width: 2 },
            areaStyle: { color: "rgba(99,140,255,0.18)" },
            data: points.map((p) => Number.parseFloat(p.total_value)),
          }],
        }}
      />
    </div>
  );
}
```

`frontend/src/components/PositionsTable.tsx`:

```tsx
import { formatMoney, formatQuantity } from "../api/format";
import { ChangeValue } from "./MoneyValue";
import type { PositionRow } from "../api/client";

export function PositionsTable({ rows }: { rows: PositionRow[] }) {
  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 10 }}>Позиции</div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ color: "var(--tx-2)", textAlign: "right" }}>
            <th style={{ textAlign: "left", paddingBottom: 8 }}>Бумага</th>
            <th>Количество</th>
            <th>Средняя</th>
            <th>Текущая</th>
            <th>Стоимость</th>
            <th>Результат</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.isin}-${row.broker}`} style={{ borderTop: "1px solid var(--line)", textAlign: "right" }}>
              <td style={{ textAlign: "left", padding: "9px 0" }}>
                <div>{row.ticker ?? "—"}</div>
                <div style={{ color: "var(--tx-2)", fontSize: 11.5 }}>{row.name}</div>
              </td>
              <td>{formatQuantity(row.quantity)}</td>
              <td>{formatMoney(row.average_price)}</td>
              <td>{formatMoney(row.last_price)}</td>
              <td>{formatMoney(row.market_value)}</td>
              <td><ChangeValue percent={row.profit_percent} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`frontend/src/components/ReconciliationBanner.tsx`:

```tsx
import { formatQuantity } from "../api/format";
import type { ReconciliationRow } from "../api/client";

const TEXT: Record<string, string> = {
  quantity_mismatch: "количество не совпадает",
  missing_in_ledger: "есть у брокера, но нет в журнале",
  missing_at_broker: "есть в журнале, но нет у брокера",
};

export function ReconciliationBanner({ rows }: { rows: ReconciliationRow[] }) {
  if (rows.length === 0) return null;

  return (
    <div className="card" style={{ borderColor: "rgba(232,176,75,0.45)", background: "rgba(232,176,75,0.08)" }}>
      <div style={{ color: "var(--amber)", fontWeight: 600, marginBottom: 8 }}>
        Расхождения с данными брокера: {rows.length}
      </div>
      {rows.map((row) => (
        <div key={row.isin} style={{ fontSize: 13, color: "var(--tx-2)", padding: "3px 0" }}>
          {row.isin}: {TEXT[row.status] ?? row.status} — в журнале {formatQuantity(row.ledger_quantity)},
          у брокера {formatQuantity(row.broker_quantity)}
        </div>
      ))}
      <div style={{ fontSize: 12, color: "var(--tx-2)", marginTop: 8 }}>
        Позиции не исправлены автоматически: вероятно, не хватает истории операций за более ранний период.
      </div>
    </div>
  );
}
```

- [ ] **Step 9: Создать страницу и точку входа**

`frontend/src/pages/PortfolioPage.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { AllocationChart } from "../components/AllocationChart";
import { PositionsTable } from "../components/PositionsTable";
import { ReconciliationBanner } from "../components/ReconciliationBanner";
import { SummaryCard } from "../components/SummaryCard";
import { ValueChart } from "../components/ValueChart";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });
  const history = useQuery({ queryKey: ["history"], queryFn: () => api.history(90) });
  const reconciliations = useQuery({ queryKey: ["reconciliations"], queryFn: api.reconciliations });

  const sync = useMutation({
    mutationFn: api.syncTbank,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (overview.isLoading) return <div style={{ padding: 32 }}>Загрузка…</div>;
  if (overview.isError) return <div style={{ padding: 32 }}>Бэкенд недоступен. Запущен ли он на порту 8000?</div>;

  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px", display: "grid", gap: 14 }}>
      <h1 style={{ fontSize: 22, fontWeight: 640, margin: 0 }}>Портфель</h1>

      {reconciliations.data && <ReconciliationBanner rows={reconciliations.data} />}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <SummaryCard overview={overview.data!} onSync={() => sync.mutate()} syncing={sync.isPending} />
        <ValueChart points={history.data ?? []} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 14 }}>
        <AllocationChart data={overview.data!.by_asset_class} />
        <PositionsTable rows={positions.data ?? []} />
      </div>
    </div>
  );
}
```

`frontend/src/App.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PortfolioPage } from "./pages/PortfolioPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PortfolioPage />
    </QueryClientProvider>
  );
}
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 10: Настроить порт в `frontend/vite.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 3000 },
});
```

- [ ] **Step 11: Запустить и проверить вручную**

Run:
```bash
cd backend && uv run uvicorn app.main:app --reload &
cd frontend && pnpm dev
```

Открыть `http://localhost:3000`. Ожидаемо: страница «Портфель», нажатие «Обновить из Т-Банка» запускает синхронизацию, после неё видны совокупная стоимость, donut структуры, таблица позиций. График показывает подсказку про накопление снимков.

- [ ] **Step 12: Коммит**

```bash
git add frontend/
git commit -m "feat: дашборд портфеля с аллокацией, позициями и расхождениями"
```

---

### Task 16: Планировщик и сборка целиком

**Files:**
- Create: `backend/app/scheduler.py`, `frontend/Dockerfile`
- Modify: `backend/app/main.py` — запуск планировщика, `docker-compose.yml` — сервис фронтенда, `backend/pyproject.toml` — зависимость APScheduler, `README.md`
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `refresh_last_prices`, `take_snapshot`, `sync_broker`, `MoexClient`, `TBankConnector`
- Produces: `build_scheduler() -> BackgroundScheduler`, задачи `job_refresh_prices()`, `job_daily_snapshot()`, `job_sync_tbank()`

- [ ] **Step 1: Написать падающий тест**

`backend/tests/test_scheduler.py`:

```python
from app.scheduler import build_scheduler


def test_scheduler_registers_expected_jobs():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"refresh_prices", "daily_snapshot", "sync_tbank"}


def test_snapshot_runs_after_market_close():
    scheduler = build_scheduler()
    snapshot = scheduler.get_job("daily_snapshot")
    assert str(snapshot.trigger).startswith("cron")
    assert "hour='19'" in str(snapshot.trigger)
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_scheduler.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: Добавить зависимость**

В `backend/pyproject.toml` в `dependencies` добавить `"apscheduler>=3.11"`, затем `uv sync`.

- [ ] **Step 4: Создать `backend/app/scheduler.py`**

```python
import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.connectors.tbank.connector import TBankConnector
from app.db import SessionLocal
from app.marketdata.moex import MoexClient
from app.marketdata.service import refresh_last_prices
from app.snapshots.service import take_snapshot
from app.sync.service import sync_broker

logger = logging.getLogger(__name__)
MOSCOW = "Europe/Moscow"
HISTORY_DAYS = 365 * 5


def job_refresh_prices() -> None:
    with SessionLocal() as session:
        updated = refresh_last_prices(session, MoexClient(), date.today())
        session.commit()
        logger.info("Обновлено котировок: %s", updated)


def job_daily_snapshot() -> None:
    with SessionLocal() as session:
        refresh_last_prices(session, MoexClient(), date.today())
        snapshot = take_snapshot(session, date.today())
        session.commit()
        logger.info("Снимок за %s: %s", snapshot.on_date, snapshot.total_value)


def job_sync_tbank() -> None:
    token = get_settings().tbank_token
    if not token:
        logger.warning("TBANK_TOKEN не задан, синхронизация пропущена")
        return

    with SessionLocal() as session:
        since = datetime.now(tz=timezone.utc) - timedelta(days=HISTORY_DAYS)
        runs = sync_broker(session, TBankConnector(token), since)
        for run in runs:
            logger.info("Синхронизация %s: %s, новых %s, расхождений %s",
                        run.broker, run.status, run.inserted, run.mismatches)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=MOSCOW)
    scheduler.add_job(job_refresh_prices, CronTrigger(day_of_week="mon-fri", hour="10-18", minute="*/15"),
                      id="refresh_prices")
    scheduler.add_job(job_daily_snapshot, CronTrigger(hour="19", minute="30"), id="daily_snapshot")
    scheduler.add_job(job_sync_tbank, CronTrigger(hour="9,20", minute="0"), id="sync_tbank")
    return scheduler
```

- [ ] **Step 5: Запустить планировщик при старте приложения**

В `backend/app/main.py` добавить:

```python
from contextlib import asynccontextmanager

from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Джарвис", docs_url="/api/docs", lifespan=lifespan)
```

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_scheduler.py -v`
Expected: PASS, 2 теста

- [ ] **Step 7: Создать `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

- [ ] **Step 8: Добавить фронтенд и миграции в `docker-compose.yml`**

В сервис `backend` добавить применение миграций при старте:

```yaml
    command: >
      sh -c "uv run alembic upgrade head &&
             uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

И новый сервис:

```yaml
  frontend:
    build: ./frontend
    ports: ["3000:80"]
    depends_on: [backend]
```

- [ ] **Step 9: Запустить всё и проверить**

Run: `docker compose up --build -d && docker compose ps`
Expected: три сервиса в рабочем состоянии; `http://localhost:3000` открывает дашборд

- [ ] **Step 10: Дописать README**

Разделы: требования (Docker Desktop, Python 3.12+ с `uv`, Node 20+ с `pnpm`), получение токена T-Invest API **с правами только на чтение**, запуск через `docker compose up`, запуск для разработки, запуск тестов (`cd backend && uv run pytest`, `cd frontend && pnpm vitest run`), расписание фоновых задач, что делать при расхождениях в сверке.

- [ ] **Step 11: Прогнать все тесты**

Run: `cd backend && uv run pytest -v && cd ../frontend && pnpm vitest run`
Expected: PASS, все тесты

- [ ] **Step 12: Коммит**

```bash
git add backend/app/scheduler.py backend/app/main.py backend/pyproject.toml frontend/Dockerfile docker-compose.yml README.md backend/tests/test_scheduler.py
git commit -m "feat: планировщик фоновых задач и сборка всей системы в Docker"
```

---

## Самопроверка плана

**Покрытие спеки (раздел 13, фаза 1):**

| Требование спеки | Задача |
|---|---|
| Docker Compose | 1, 16 |
| База и миграции | 3 (и по одной миграции в 5, 8, 10, 11, 12, 13) |
| Журнал операций | 3, 4, 5 |
| Коннектор T-Invest API | 9 |
| Цены MOEX | 7, 8 |
| Свёртка в позиции и лоты FIFO | 6, 10 |
| Ежедневные снимки стоимости | 13, 16 |
| Сверка | 11, 12 |
| Дашборд: сводка, график, аллокация | 15 |
| Decimal вместо float | 2, плюс сериализация строками в 14 и форматирование в 15 |
| Токен только на чтение | Global Constraints, README в 16 |
| Журнал append-only | 3 (ограничения), 5 (только вставка) |

**Не входит в фазу 1 и намеренно отсутствует:** XIRR и TWR, календарь выплат, налоги, бенчмарки, look-through дальше классификации фондов, ИИ-чат, остальные брокеры, ручные активы, денежные остатки в сводке. Всё это — фазы 2–6.

**Согласованность имён между задачами:** `RawOperation` (4) используется в 5, 9, 12. `append_operations` → `AppendResult.inserted/skipped` (5) читается в 12. `fold` → `FoldResult.positions` (6) используется в 10. `latest_prices` (8) вызывается в 13. `BrokerPosition` (9) принимается в 11 и 12. `portfolio_overview` → `Overview` (13) отдаётся в 14 и потребляется как `Overview` в 15. `reconcile_account` возвращает `list[Reconciliation]`, чья длина пишется в `SyncRun.mismatches` (12).

**Известное расхождение, требующее проверки при исполнении:** имена методов SDK Т-Банка (`client.users.get_accounts`, `client.operations.get_operations`, `client.operations.get_portfolio`, `client.instruments.find_instrument`) взяты из текущей документации. Шаг 7 задачи 9 — живая проверка именно этого; при расхождении правится только `connector.py`, маппер и остальной код не затрагиваются.
