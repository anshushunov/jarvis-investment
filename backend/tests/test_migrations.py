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

    engine = create_engine(MIGRATIONS_URL)
    try:
        yield engine
    finally:
        # База удаляется за собой, а не остаётся висеть в кластере до
        # следующего прогона. Пересоздание на входе остаётся: оно защищает от
        # прерванного прогона, после которого teardown не отработал.
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATIONS_DB}"))
        admin.dispose()


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


def test_0011_deletes_only_stale_moex_ruble_prices_of_foreign_instruments(migrations_engine):
    """DELETE в 0011 необратимо трогает настоящие строки владельца — его
    поведение закрепляется отдельно от сверки моделей, потому что
    `test_full_chain_upgrades_matches_models_and_downgrades` гоняет цепочку на
    пустой базе и DELETE там всегда no-op. Засеваем схему на версии 0010 (ещё
    без колонки currency, как было до миграции), прогоняем настоящую 0011 и
    проверяем, кто из пяти комбинаций выжил:
    - рублёвый инструмент + moex — выживает (обычная биржевая цена);
    - нерублёвый (HKD) + moex — удаляется (никогда не использовалась при
      оценке, после пересчёта по курсам занизила бы позицию);
    - нерублёвый в нижнем регистре (hkd) + moex — тоже удаляется: DELETE
      сравнивает через upper(), регистр валюты не должен на это влиять;
    - рублёвый в нижнем регистре (rub) + moex — тоже выживает: без upper()
      строка 'rub' не равна 'RUB' и удалилась бы ошибочно — это и есть
      случай, ради которого регистронезависимость нужна, а не только
      декларативная неделикатность для не-рубля;
    - нерублёвый + источник не moex (manual) — выживает: правило только про
      биржевые рублёвые цены, не про валюту инструмента вообще.
    """
    with migrations_engine.connect() as connection:
        config = _alembic_config(connection)

        # Останавливаемся на 0010: у price ещё нет колонки currency, ровно та
        # схема, в которой реальные строки дожили до этой миграции.
        command.upgrade(config, "0010")
        connection.commit()

        connection.execute(text("""
            INSERT INTO instrument (isin, ticker, secid, kind, currency) VALUES
                ('RU0000000001', 'SBER', 'SBER', 'share', 'RUB'),
                ('KYG875721634', '700',  '700',  'share', 'HKD'),
                ('KYG875721635', '9866', '9866', 'share', 'hkd'),
                ('KYG875721636', '941',  '941',  'share', 'HKD'),
                ('RU0000000002', 'GAZP', 'GAZP', 'share', 'rub')
        """))
        connection.execute(text("""
            INSERT INTO price (instrument_id, on_date, close, source)
            SELECT id, DATE '2026-08-09', 300, 'moex' FROM instrument WHERE isin = 'RU0000000001'
            UNION ALL
            SELECT id, DATE '2026-08-09', 300, 'moex' FROM instrument WHERE isin = 'KYG875721634'
            UNION ALL
            SELECT id, DATE '2026-08-09', 300, 'moex' FROM instrument WHERE isin = 'KYG875721635'
            UNION ALL
            SELECT id, DATE '2026-08-09', 300, 'manual' FROM instrument WHERE isin = 'KYG875721636'
            UNION ALL
            SELECT id, DATE '2026-08-09', 300, 'moex' FROM instrument WHERE isin = 'RU0000000002'
        """))
        connection.commit()

        command.upgrade(config, "0011")
        connection.commit()

        survivors = connection.execute(text(
            """
            SELECT i.isin, p.source FROM price p
            JOIN instrument i ON i.id = p.instrument_id
            ORDER BY i.isin
            """
        )).all()

        assert survivors == [
            ("KYG875721636", "manual"),
            ("RU0000000001", "moex"),
            ("RU0000000002", "moex"),
        ]

        # Откат к пустой схеме: база в этом фикстуре общая для всех тестов
        # модуля, следующий тест должен получить её чистой.
        command.downgrade(config, "base")
        connection.commit()


def test_0011_downgrade_refuses_when_two_sources_share_a_date(migrations_engine):
    """Ровно то, что 0011 разрешила (две цены на одну дату из разных
    источников), не переживает откат к двухколоночному ключу
    (instrument_id, on_date). Без явной проверки create_unique_constraint
    упал бы голым UniqueViolation от драйвера; с ней — понятным RuntimeError
    на русском, по образцу 0008."""
    with migrations_engine.connect() as connection:
        config = _alembic_config(connection)

        command.upgrade(config, "0011")
        connection.commit()

        connection.execute(text(
            "INSERT INTO instrument (isin, ticker, secid, kind, currency) "
            "VALUES ('RU0000000003', 'LKOH', 'LKOH', 'share', 'RUB')"
        ))
        connection.execute(text("""
            INSERT INTO price (instrument_id, on_date, close, currency, source)
            SELECT id, DATE '2026-08-09', 300, 'RUB', 'moex' FROM instrument WHERE isin = 'RU0000000003'
            UNION ALL
            SELECT id, DATE '2026-08-09', 305, 'RUB', 'tbank' FROM instrument WHERE isin = 'RU0000000003'
        """))
        connection.commit()

        with pytest.raises(RuntimeError, match="Откат миграции 0011 невозможен"):
            command.downgrade(config, "base")

        # Проверка успевает отработать до первой DDL-команды, поэтому упавшая
        # транзакция не оставляет соединение в невалидном состоянии — но откат
        # транзакции всё равно нужен явно, соединение общее для всего модуля.
        connection.rollback()

        # Конфликт устранён руками — ровно то, что просит сделать сообщение
        # об ошибке, — и штатный откат проходит.
        connection.execute(text(
            "DELETE FROM price WHERE source = 'tbank'"
        ))
        connection.commit()
        command.downgrade(config, "base")
        connection.commit()


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
