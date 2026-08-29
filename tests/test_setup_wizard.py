"""The setup wizard's file and repo handling.

The interactive prompts aren't tested (they need a TTY), but everything that writes
to disk or is parsed from the environment is.
"""

import json
import os

import pytest

import setup_wizard


@pytest.fixture(autouse=True)
def in_tmp_dir(tmp_path, monkeypatch):
    """The wizard writes relative paths, so run each test in a scratch directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- .env writing -----------------------------------------------------------

def test_writes_the_collected_keys(in_tmp_dir):
    setup_wizard._write_env({"GROQ_API_KEY": "g", "TAVILY_API_KEY": "t"})

    written = (in_tmp_dir / ".env").read_text()
    assert "GROQ_API_KEY=g" in written
    assert "TAVILY_API_KEY=t" in written


def test_keeps_unrelated_keys_already_in_the_env_file(in_tmp_dir):
    """Re-running setup must not wipe settings the wizard doesn't manage."""
    (in_tmp_dir / ".env").write_text("GROQ_MODEL=custom/model\nGROQ_API_KEY=old\n")

    setup_wizard._write_env({"GROQ_API_KEY": "new"})

    written = (in_tmp_dir / ".env").read_text()
    assert "GROQ_MODEL=custom/model" in written
    assert "GROQ_API_KEY=new" in written
    assert "old" not in written


def test_backs_up_an_existing_env_file_before_overwriting(in_tmp_dir):
    (in_tmp_dir / ".env").write_text("GROQ_API_KEY=original\n")

    setup_wizard._write_env({"GROQ_API_KEY": "replacement"})

    assert (in_tmp_dir / ".env.backup").read_text() == "GROQ_API_KEY=original\n"


def test_skipped_values_do_not_land_in_the_env_file(in_tmp_dir):
    """Declining the Gmail step must not write empty credentials."""
    setup_wizard._write_env({"GROQ_API_KEY": "g", "GMAIL_ADDRESS": "", "RECIPIENT_EMAIL": ""})

    written = (in_tmp_dir / ".env").read_text()
    assert "GMAIL_ADDRESS" not in written
    assert "RECIPIENT_EMAIL" not in written


# --- History reset ----------------------------------------------------------

def test_reset_clears_history_inherited_from_the_template(in_tmp_dir):
    """A repo made from the template carries the author's sent articles; clear them."""
    os.makedirs("data")
    with open(setup_wizard.HISTORY_FILE, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "seen": [{"url_key": "example.com/a", "title_key": "old", "date": "2026-01-01"}],
                "words": [{"word": "inherited"}],
                "quotes": [{"text": "inherited"}],
                "last_sent_date": "2026-08-29",
            },
            fh,
        )

    setup_wizard._reset_history()

    doc = json.load(open(setup_wizard.HISTORY_FILE, encoding="utf-8"))
    assert doc == {"seen": [], "words": [], "quotes": [], "last_sent_date": ""}


def test_reset_clearing_last_sent_date_unblocks_the_first_briefing(in_tmp_dir):
    """An inherited last_sent_date of today would silently skip the very first send."""
    os.makedirs("data")
    with open(setup_wizard.HISTORY_FILE, "w", encoding="utf-8") as fh:
        json.dump({"seen": [], "words": [], "quotes": [], "last_sent_date": "2026-08-29"}, fh)

    setup_wizard._reset_history()

    import history

    monkey = history.HISTORY_FILE
    history.HISTORY_FILE = setup_wizard.HISTORY_FILE
    try:
        assert history.last_sent_date() == ""
    finally:
        history.HISTORY_FILE = monkey


def test_reset_works_when_there_is_no_history_file_yet(in_tmp_dir):
    setup_wizard._reset_history()
    assert json.load(open(setup_wizard.HISTORY_FILE, encoding="utf-8"))["seen"] == []


# --- Repo detection ---------------------------------------------------------

@pytest.mark.parametrize(
    "remote,expected",
    [
        ("git@github.com:tballochi/daily-briefing.git", "tballochi/daily-briefing"),
        ("https://github.com/someone/my-briefing.git", "someone/my-briefing"),
        ("https://github.com/someone/my-briefing", "someone/my-briefing"),
    ],
)
def test_repo_slug_is_read_from_the_git_remote(remote, expected, monkeypatch):
    """It pre-fills the pinger URL, so a wrong slug means a silently broken cron job."""

    class Result:
        stdout = remote

    monkeypatch.setattr(setup_wizard.subprocess, "run", lambda *a, **k: Result())
    assert setup_wizard._repo_slug() == expected


def test_repo_slug_falls_back_to_a_placeholder_outside_a_git_repo(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("not a git repository")

    monkeypatch.setattr(setup_wizard.subprocess, "run", explode)
    assert setup_wizard._repo_slug() == "<you>/daily-briefing"
