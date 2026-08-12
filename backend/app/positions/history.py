"""Состав портфеля на прошлую дату.

Свёртка журнала — существующая (`app/positions/engine.py:fold`), а не своя:
FIFO, закрытые сделки, конвертации и отмены решений владельца считаются одним
кодом и сегодня, и год назад. Второй реализации свёртки в проекте быть не
должно — она разойдётся с первой на первом же корпоративном действии.
"""

from datetime import date

from app.positions.engine import LedgerEntry, PositionState, fold
from app.timeutils import moscow_day_end


def holdings_at(entries: list[LedgerEntry], on_date: date) -> dict[int, PositionState]:
    """Открытые позиции на конец дня: инструмент → состояние.

    Позиция с нулевым количеством не возвращается вовсе: к этой дате её нет, и
    это не то же самое, что «есть, но неоценена». Иначе каждая закрытая за
    шесть лет бумага портила бы покрытие снимка.

    Записи фильтруются по московскому концу суток — тому же поясу, в котором
    живёт календарная дата снимка.
    """
    cutoff = moscow_day_end(on_date)
    result = fold([entry for entry in entries if entry.executed_at < cutoff])
    return {
        instrument_id: state
        for instrument_id, state in result.positions.items()
        if state.quantity != 0
    }
