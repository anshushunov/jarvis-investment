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
