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
from app.ai.tools import history, instruments, ledger, overview, positions, returns

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
    ToolSpec(
        name="positions",
        description=("Открытые позиции: бумага, счёт, класс, количество, средняя цена против "
                     "текущей, стоимость в рублях, доля портфеля, прибыль либо причина её "
                     "отсутствия. Фильтры по счёту, классу и «только неоценённые»."),
        handler=positions.positions,
    ),
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
    ToolSpec(
        name="ledger",
        description=("Журнал операций: что происходило по бумаге, счёту, типу операции и датам. "
                     "Страница строк плюс агрегаты по всей выборке (количество, суммы по типам и "
                     "валютам, диапазон дат) и признак усечения."),
        handler=ledger.ledger,
    ),
    ToolSpec(
        name="instrument_prices",
        description=("Как двигалась цена одной бумаги: ряд котировок с источником и валютой и "
                     "перечень дыр в ряду. Нужен instrument_id из find_instrument."),
        handler=history.instrument_prices,
    ),
    ToolSpec(
        name="find_instrument",
        description=("Найти бумагу по тикеру, ISIN или названию и получить её instrument_id для "
                     "ledger и instrument_prices. Тикеры не уникальны — всегда искать здесь, а "
                     "не угадывать."),
        handler=instruments.find_instrument,
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
    try:
        spec = tool_by_name(name)
    except KeyError:
        known_names = ", ".join(spec.name for spec in TOOLS)
        return {"error": f"Инструмента «{name}» нет. Известные: {known_names}"}
    try:
        return spec.handler(session, **arguments)
    except ToolRefusal as refusal:
        return {"error": str(refusal)}
    except Exception:
        logger.exception("Инструмент %s упал на входе %r", name, arguments)
        return {"error": INTERNAL_ERROR.format(name=name)}
