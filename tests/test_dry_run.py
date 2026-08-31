"""--dry-run must be safe to try: it sends nothing and remembers nothing."""

import pytest

import agent
import scheduler


FAKE_PAYLOAD = {
    "articles": [
        {"url": "https://example.com/a", "title": "A real story", "summary": "What happened."},
    ],
    "word": {"word": "idempotency", "definition": "Same result every time.", "example": "Retries are safe."},
    "quote": {"text": "Simplicity is prerequisite for reliability.", "author": "Edsger Dijkstra"},
}


@pytest.fixture
def dry_run_env(tmp_path, monkeypatch):
    """Stub the LLM/search pipeline and redirect every file the run could touch."""
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "y")
    for name in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        scheduler, "build_briefing", lambda: ("Daily Briefing — today", "<html>brief</html>", FAKE_PAYLOAD)
    )
    monkeypatch.setattr(scheduler, "PREVIEW_FILE", str(tmp_path / "preview.html"))
    monkeypatch.setattr(scheduler.history, "HISTORY_FILE", str(tmp_path / "history.json"))
    return tmp_path


def test_dry_run_never_sends_an_email(dry_run_env, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("--dry-run must never send an email")

    monkeypatch.setattr(scheduler, "send_email", explode)
    monkeypatch.setattr(scheduler, "send_failure_alert", explode)

    scheduler.run_dry_run()


def test_dry_run_never_writes_history(dry_run_env):
    """A previewed story must still be available for a real briefing tomorrow."""
    scheduler.run_dry_run()

    assert not (dry_run_env / "history.json").exists()
    assert scheduler.history.is_seen("https://example.com/a", "A real story") is False


def test_dry_run_writes_the_rendered_email_to_a_preview_file(dry_run_env):
    scheduler.run_dry_run()
    assert (dry_run_env / "preview.html").read_text() == "<html>brief</html>"


def test_dry_run_works_without_any_gmail_configuration(dry_run_env):
    """Two free API keys is the whole activation cost."""
    scheduler.run_dry_run()  # Gmail vars are unset in the fixture; must not raise


def test_dry_run_stops_with_a_friendly_error_when_a_key_is_missing(dry_run_env, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(scheduler.config.ConfigError, match="console.groq.com"):
        scheduler.run_dry_run()


def test_the_console_preview_shows_the_story_word_and_quote():
    text = agent.render_text("Daily Briefing — today", FAKE_PAYLOAD)

    assert "A real story" in text
    assert "https://example.com/a" in text
    assert "idempotency" in text
    assert "Edsger Dijkstra" in text


def test_a_failing_command_reports_why_instead_of_exiting_silently(dry_run_env, monkeypatch, caplog):
    """Exiting non-zero with no output is undiagnosable.

    run_briefing logs its own traceback before re-raising, but --dry-run and --setup
    do not, so the top-level handler has to log or the failure is invisible.
    """
    import logging
    import main

    monkeypatch.setattr(scheduler, "build_briefing", lambda: 1 / 0)
    monkeypatch.setattr(main, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--dry-run"])

    with caplog.at_level(logging.ERROR, logger="briefing"):
        assert main.main() == 1

    assert caplog.records, "a failing command must log something"
    assert caplog.records[-1].exc_info, "the traceback must be logged, not just a message"
