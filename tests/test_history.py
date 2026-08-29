"""De-duplication memory: a story that has been sent must never come back."""

import json

import pytest

import history


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    """Point history at a throwaway file so tests never touch data/history.json."""
    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "history.json"))


def send(url, title, date="2026-08-29"):
    history.record_sent([{"url": url, "title": title}], {"word": "w"}, {"text": "q"}, date)


def test_a_missing_history_file_is_not_an_error():
    """First run on a fresh clone: nothing has been seen yet."""
    assert history.is_seen("https://example.com/a", "Anything") is False
    assert history.last_sent_date() == ""


def test_an_already_sent_story_is_recognised_by_url():
    send("https://example.com/story", "A big story")
    assert history.is_seen("https://example.com/story", "A different headline") is True


def test_url_matching_ignores_www_trailing_slash_and_case():
    """The same article from a slightly different link is still the same article."""
    send("https://www.example.com/Story/", "A big story")
    assert history.is_seen("https://example.com/story", "Whatever") is True


def test_an_already_sent_story_is_recognised_by_title():
    """Syndicated copies get a new URL but keep the headline."""
    send("https://example.com/story", "A big story")
    assert history.is_seen("https://other-outlet.com/reprint", "  A BIG   story ") is True


def test_an_unrelated_story_is_not_flagged():
    send("https://example.com/story", "A big story")
    assert history.is_seen("https://example.com/other", "Something else") is False


def test_last_sent_date_drives_the_once_a_day_guard():
    send("https://example.com/story", "A big story", date="2026-08-29")
    assert history.last_sent_date() == "2026-08-29"


def test_recent_titles_feed_the_agent_its_own_no_repeat_list():
    send("https://example.com/story", "A big story")
    assert "A big story" in history.recent_titles(days=14)


def test_words_and_quotes_are_remembered_so_they_are_not_reused():
    history.record_sent(
        [{"url": "https://example.com/a", "title": "T"}],
        {"word": "idempotency"},
        {"text": "Move fast", "author": "Someone"},
        "2026-08-29",
    )
    assert "idempotency" in history.recent_words()
    assert "Move fast" in history.recent_quotes()


def test_history_accumulates_across_days_instead_of_overwriting():
    send("https://example.com/one", "Day one story", date="2026-08-28")
    send("https://example.com/two", "Day two story", date="2026-08-29")

    assert history.is_seen("https://example.com/one", "Day one story") is True
    assert history.is_seen("https://example.com/two", "Day two story") is True
    assert history.last_sent_date() == "2026-08-29"


def test_a_corrupt_history_file_does_not_crash_the_briefing():
    """Better to risk repeating a story than to fail the morning send."""
    with open(history.HISTORY_FILE, "w", encoding="utf-8") as fh:
        fh.write("{not valid json")

    assert history.is_seen("https://example.com/a", "T") is False
    send("https://example.com/a", "T")
    assert history.is_seen("https://example.com/a", "T") is True


def test_recorded_entries_keep_only_what_history_needs():
    """Summaries and other payload extras must not leak into the committed file."""
    history.record_sent(
        [{"url": "https://example.com/a", "title": "T", "summary": "should not be stored"}],
        {}, {}, "2026-08-29",
    )
    stored = json.load(open(history.HISTORY_FILE, encoding="utf-8"))
    assert set(stored["seen"][0]) == {"url_key", "title_key", "url", "title", "date"}
