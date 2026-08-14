import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import get_session
from app.ledger.schemas import RawOperation
from app.main import app
from app.models import Account, Base, OperationType

ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql+psycopg://jarvis:jarvis@localhost:5433/postgres")
TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://jarvis:jarvis@localhost:5433/jarvis_test")


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
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def client(session):
    """Клиент API поверх тестовой сессии.

    Живёт здесь, а не в tests/test_api.py: фикстура нужна и тестам доходности
    (tests/test_returns_api.py), и импортировать её из чужого файла тестов —
    значит тянуть за собой весь его модуль ради одной строки. Место фикстуры,
    у которой больше одного потребителя, — conftest.
    """
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def account(session) -> Account:
    """Общий счёт для тестов, которым нужен просто «какой-то валидный счёт»,
    а не конкретные значения его полей — заведён здесь, а не в каждом файле
    тестов по отдельности, чтобы не плодить копии одного и того же."""
    acc = Account(broker="tbank", kind="broker", external_id="acc-1",
                  name="Инвестиционный", currency="RUB")
    session.add(acc)
    session.flush()
    return acc


def raw_operation(*, external_id: str, quantity: str, amount: str,
                  op_type: OperationType = OperationType.BUY,
                  price: str = "100", isin: str = "RU000A0JQUZ6") -> RawOperation:
    """Фабрика сырой операции коннектора для тестов журнала: большинство полей
    сценарию безразличны, поэтому заданы значением по умолчанию, а значимые
    для конкретной проверки — именованными параметрами."""
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
