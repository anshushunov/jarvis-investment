import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base

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
