"""Цепочка миграций целиком — вверх, сверка с моделями, вниз.

Тестовая схема остальных тестов собирается через `Base.metadata.create_all`,
то есть `alembic upgrade head` в тестах не исполняется никогда: восемь
миграций, одна из них необратимая, а сходимость моделей и миграций
проверялась глазами. Расхождение проходило весь набор тестов и падало бы
только при подъёме на чистом томе.

Прогон идёт на собственной пустой базе (`jarvis_migrations_test`) — ни рабочая
`jarvis`, ни основная тестовая `jarvis_test` не затрагиваются. База
пересоздаётся в начале, поэтому повторные запуски безопасны и не зависят от
того, чем закончился предыдущий.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import Base

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_URL", "postgresql+psycopg://jarvis:jarvis@localhost:5433/postgres"
)
MIGRATIONS_DB = "jarvis_migrations_test"
MIGRATIONS_URL = os.environ.get(
    "TEST_MIGRATIONS_URL",
    f"postgresql+psycopg://jarvis:jarvis@localhost:5433/{MIGRATIONS_DB}",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Служебная таблица самого alembic: в моделях её нет и быть не должно, из
# сверки исключается.
ALEMBIC_VERSION_TABLE = "alembic_version"


def _alembic_config(connection) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # Соединение к отдельной пустой базе передаётся явно — env.py в этом случае
    # не читает настройки приложения и в рабочую базу не ходит.
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def migrations_engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATIONS_DB}"))
        conn.execute(text(f"CREATE DATABASE {MIGRATIONS_DB}"))
    admin.dispose()

    engine = create_engine(MIGRATIONS_URL)
    yield engine
    engine.dispose()


def test_full_chain_upgrades_matches_models_and_downgrades(migrations_engine):
    with migrations_engine.connect() as connection:
        config = _alembic_config(connection)

        # 1. Вся цепочка вверх на чистой базе — ровно то, что произойдёт при
        #    подъёме на новом томе.
        command.upgrade(config, "head")
        connection.commit()

        tables = set(inspect(connection).get_table_names())
        assert ALEMBIC_VERSION_TABLE in tables
        # Схема действительно создана, а не просто «команда не упала».
        assert {"account", "instrument", "transaction", "price", "position",
                "reconciliation", "sync_run", "daily_snapshot"} <= tables

        # 2. Результат обязан совпасть с метаданными моделей: расхождение
        #    моделей и миграций не ловится ничем другим — тестовая схема
        #    строится из моделей и миграции не видит.
        migration_context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_name": lambda name, type_, parent_names: not (
                    type_ == "table" and name == ALEMBIC_VERSION_TABLE
                ),
            },
        )
        differences = compare_metadata(migration_context, Base.metadata)
        assert differences == [], f"модели и миграции разошлись: {differences}"

        # 3. Вся цепочка вниз. Необратимая 0008 откатывается на пустой базе
        #    штатно: запрещающая её пара «разные счета, общий external_id»
        #    появляется только вместе с данными.
        command.downgrade(config, "base")
        connection.commit()

        remaining = set(inspect(connection).get_table_names())
        assert remaining <= {ALEMBIC_VERSION_TABLE}


def test_append_only_trigger_is_created_by_the_migration_chain(migrations_engine):
    """DDL триггера продублирован в миграции 0001 и в app/models/transaction.py
    (тестовая схема миграцию не видит). Дубль в моделях проверен тестами
    журнала; здесь проверяется тот, что владеет схемой в проде."""
    with migrations_engine.connect() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "head")
        connection.commit()

        trigger = connection.execute(text(
            "SELECT tgname FROM pg_trigger WHERE tgname = 'transaction_append_only_trigger'"
        )).scalar_one_or_none()
        assert trigger == "transaction_append_only_trigger"

        command.downgrade(config, "base")
        connection.commit()

        # Функция и триггер снимаются откатом, а не остаются висеть в базе.
        left = connection.execute(text(
            "SELECT proname FROM pg_proc WHERE proname = 'transaction_append_only'"
        )).scalar_one_or_none()
        assert left is None
