"""The two guards that stop a stray trigger from double-sending or waking you at 3am.

1. The workflow's shell window guard: only run between 06:00 and 11:00 Paris.
2. The Python once-a-day guard: send at most one briefing per Paris day.

The window guard is tested by executing the exact shell snippet shipped in the
workflow file, so editing the workflow badly fails the build.
"""

import os
import re
import subprocess

import pytest

import scheduler

WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows", "daily-briefing.yml",
)


# --- The workflow's morning window guard ------------------------------------

def _gate_case_block() -> str:
    """Pull the real `case "$H" in ... esac` hour test out of the workflow file."""
    text = open(WORKFLOW, encoding="utf-8").read()
    match = re.search(r'case "\$H" in.*?esac', text, re.S)
    assert match, "the hour window guard is missing from the workflow"
    return "\n".join(line.strip() for line in match.group(0).splitlines())


def _gate_decision(hour: str, tmp_path) -> str:
    """Run the shipped guard for a given Paris hour; return its run= output."""
    output_file = tmp_path / "gh_output"
    script = f'H="{hour}"\nGITHUB_OUTPUT="{output_file}"\n{_gate_case_block()}\n'
    subprocess.run(["bash", "-c", script], check=True)
    return output_file.read_text().strip()


@pytest.mark.parametrize("hour", ["06", "07", "08", "09", "10", "11"])
def test_the_window_guard_runs_during_the_morning_window(hour, tmp_path):
    assert _gate_decision(hour, tmp_path) == "run=true"


@pytest.mark.parametrize("hour", ["00", "03", "05", "12", "18", "23"])
def test_the_window_guard_blocks_every_hour_outside_the_window(hour, tmp_path):
    """A stray trigger at night must never email anyone."""
    assert _gate_decision(hour, tmp_path) == "run=false"


def test_the_workflow_only_forces_a_send_on_a_manual_run():
    """The cron pinger must go through the idempotency guard, never force past it."""
    text = open(WORKFLOW, encoding="utf-8").read()
    force_line = re.search(r".*force=--force.*", text).group(0)
    guard = text[: text.index(force_line)]

    # The only branch that can set --force is gated on a human clicking Run workflow.
    assert "workflow_dispatch" in guard
    assert "github.event.inputs.force" in guard


# --- The Python once-a-day guard --------------------------------------------

@pytest.fixture
def secrets(monkeypatch):
    for name in ("GROQ_API_KEY", "TAVILY_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"):
        monkeypatch.setenv(name, "test-value")


@pytest.fixture
def spy_send(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "_build_and_send", lambda: calls.append(1))
    return calls


def test_a_second_trigger_on_the_same_day_sends_nothing(secrets, spy_send, monkeypatch):
    """Several morning triggers, one email — the whole point of the guard."""
    monkeypatch.setattr(scheduler.history, "last_sent_date", lambda: scheduler._paris_today())

    scheduler.run_briefing()
    scheduler.run_briefing()

    assert spy_send == []


def test_the_first_trigger_of_the_day_sends(secrets, spy_send, monkeypatch):
    monkeypatch.setattr(scheduler.history, "last_sent_date", lambda: "2026-01-01")
    scheduler.run_briefing()
    assert spy_send == [1]


def test_force_overrides_the_once_a_day_guard(secrets, spy_send, monkeypatch):
    """The manual "Run workflow" test path."""
    monkeypatch.setattr(scheduler.history, "last_sent_date", lambda: scheduler._paris_today())
    scheduler.run_briefing(force=True)
    assert spy_send == [1]


def test_a_missing_secret_is_reported_before_any_api_call(monkeypatch, spy_send):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(scheduler.history, "last_sent_date", lambda: "2026-01-01")

    with pytest.raises(scheduler.config.ConfigError, match="GROQ_API_KEY"):
        scheduler.run_briefing()

    assert spy_send == []
