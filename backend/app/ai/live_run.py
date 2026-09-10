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

# codex exec — headless: approval_policy у него всегда "never" (спросить
# некого), а по умолчанию Codex требует подтверждения на любой новый MCP-
# инструмент. Без этой пометки каждый вызов падает с "MCP tool call requires
# approval, but approval policy is never" ещё до того, как инструмент
# прочитает хоть что-то. Все девять инструментов сервера — только читающие
# (см. instructions в app/ai/mcp.py), доверить им авто-подтверждение безопасно.
_TOOL_NAMES = (
    "portfolio_overview", "positions", "returns", "value_history", "ledger",
    "instrument_prices", "allocation", "data_quality", "find_instrument",
)
_APPROVE_TOOLS = [
    arg
    for name in _TOOL_NAMES
    for arg in ("-c", f'mcp_servers.jarvis.tools.{name}.approval_mode="approve"')
]

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
             "-C", str(REPO_ROOT), *_APPROVE_TOOLS, "-o", str(answer), question],
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
