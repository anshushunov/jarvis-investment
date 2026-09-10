from datetime import date

from app.ai import live_run, registry


def _fake_ask(question: str) -> live_run.Answer:
    return live_run.Answer(
        text=f"ответ на «{question}»",
        transcript="mcp: jarvis/returns (completed)\nmcp: jarvis/returns (completed)\n",
    )


def test_live_run_records_questions_and_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(live_run, "HANDOFF_DIR", tmp_path)
    target = live_run.main(ask_fn=_fake_ask, today=date(2026, 9, 9))
    text = target.read_text(encoding="utf-8")
    assert target.name == "2026-09-09-phase-5a-live-run.md"
    assert len(live_run.QUESTIONS) == 6
    assert all(question in text for question in live_run.QUESTIONS)
    assert "## 6." in text
    assert "## Сверка" in text
    assert "Вызовы инструментов: returns ×2" in text


def test_approve_tools_lists_every_registered_tool():
    mentioned = " ".join(live_run._APPROVE_TOOLS)
    for spec in registry.TOOLS:
        assert spec.name in mentioned
