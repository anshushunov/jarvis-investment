"""Живые вопросы признака готовности фазы 5a — через codex exec.

Не тест: ответы модели сверяются глазами с прогонами app.valuation_check и
app.returns.check, а запись прогона кладётся в репозиторий, как все прогоны
проекта. Сервер должен быть зарегистрирован в Codex (README, «Ассистент»).

    cd backend && uv run python -m app.ai.live_run
"""

import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.ai import registry
from app.timeutils import moscow_today

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDOFF_DIR = REPO_ROOT / "docs" / "handoff"

# codex exec — headless: approval_policy у него всегда "never" (спросить
# некого), а по умолчанию Codex требует подтверждения на любой новый MCP-
# инструмент. Без этой пометки каждый вызов падает с "MCP tool call requires
# approval, but approval policy is never" ещё до того, как инструмент
# прочитает хоть что-то. Все инструменты сервера — только читающие (см.
# instructions в app/ai/mcp.py), доверить им авто-подтверждение безопасно.
# Список берётся из реестра, а не дублируется руками: девятый инструмент
# добавят в registry.TOOLS — он должен появиться и здесь без отдельной правки.
_APPROVE_TOOLS = [
    arg
    for spec in registry.TOOLS
    for arg in ("-c", f'mcp_servers.jarvis.tools.{spec.name}.approval_mode="approve"')
]

# След вызовов инструментов в транскрипте сессии Codex: "mcp: jarvis/<имя> (completed)"/"(failed)".
_TOOL_CALL_RE = re.compile(r"jarvis/(\w+) \((?:completed|failed)\)")

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


@dataclass(frozen=True)
class Answer:
    text: str
    transcript: str


def ask(question: str) -> Answer:
    """Один вопрос — одна свежая сессия Codex: без памяти о предыдущих ответах,
    только чтение в песочнице, ответ — в файл, а не в перемешанный stdout.

    Рабочая директория сессии — та же пустая временная папка, где лежит файл
    ответа: у модели там нет ничего, кроме инструментов сервера.

    Признак готовности фазы (раздел 7, п. 5) требует, чтобы цифры приходили из
    инструментов сервера, а не из памяти модели или файлов репозитория. Рабочая
    директория сессии — поэтому именно пустая временная папка, а не корень
    репозитория: с REPO_ROOT в первом прогоне модель прочитала
    docs/handoff/2026-08-14-phase-4a-handoff.md вместо вызова data_quality и
    отдала устаревший XIRR — обходной путь мимо инструментов, который и должен
    был проверить этот признак. REPO_ROOT остаётся только для HANDOFF_DIR: сам
    хендофф прогона кладётся в репозиторий, сессия Codex его не видит."""
    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("codex не найден в PATH — установить Codex CLI или добавить его в PATH")
    with tempfile.TemporaryDirectory() as folder:
        answer_file = Path(folder) / "answer.md"
        try:
            result = subprocess.run(
                [codex, "exec", "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
                 "-C", str(folder), *_APPROVE_TOOLS, "-o", str(answer_file), question],
                check=True, capture_output=True, text=True, encoding="utf-8",
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"codex exec упал (код {exc.returncode}): {exc.stderr}") from exc
        return Answer(
            text=answer_file.read_text(encoding="utf-8"),
            transcript=result.stdout + result.stderr,
        )


def _tool_calls_line(transcript: str) -> str:
    """Кто из инструментов jarvis реально позвал модель и сколько раз — по
    строкам трассы вида "mcp: jarvis/<имя> (completed)"/"(failed)". Не то же
    самое, что текст ответа: ответ мог сослаться на файл вместо инструмента —
    эта строка ловит именно такой случай."""
    calls = _TOOL_CALL_RE.findall(transcript)
    if not calls:
        return "_инструменты не вызывались_"
    counts = Counter(calls)
    parts = ", ".join(f"{name} ×{count}" for name, count in counts.items())
    return f"_Вызовы инструментов: {parts}_"


def render(pairs: list[tuple[str, Answer]], today: date) -> str:
    lines = [
        f"# Фаза 5a: живые вопросы через Codex, {today.isoformat()}", "",
        "Ответы модели записаны как есть, без правок. Сверка с прогонами",
        "`app.valuation_check` и `app.returns.check` — в разделе «Сверка» ниже,",
        "он заполняется руками после прогона.", "",
    ]
    for number, (question, answer) in enumerate(pairs, start=1):
        lines += [f"## {number}. {question}", "", answer.text.strip(), "",
                  _tool_calls_line(answer.transcript), ""]
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
