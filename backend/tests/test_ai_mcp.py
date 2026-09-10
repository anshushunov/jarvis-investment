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
