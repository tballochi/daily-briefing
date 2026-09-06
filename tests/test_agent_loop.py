"""The research loop must not lose a briefing at the last step.

Groq rejects the whole request when the model ignores a forced `tool_choice` and
tries to search again, which killed runs that had already gathered good articles.
"""

import pytest

import agent


class ForcedFinalizeRejected:
    """Groq client stub: the forced-finalize call always 400s."""

    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise RuntimeError(
            "Error code: 400 - Tool call validation failed: attempted to call tool "
            "'search_news' which does not match request.tool_choice: 'finalize_selection'"
        )


ARTICLES = [
    {"url": "https://example.com/one", "title": "A properly substantial headline here",
     "snippet": "text", "already_sent": False},
    {"url": "https://example.com/two", "title": "Another properly substantial headline",
     "snippet": "text", "already_sent": False},
    {"url": "https://example.com/three", "title": "A third properly substantial headline",
     "snippet": "text", "already_sent": False},
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network: every gathered article is live, and searches return the fixtures."""
    monkeypatch.setattr(agent, "_url_alive", lambda *a, **k: True)
    monkeypatch.setattr(agent, "_pace", lambda *a, **k: None)
    monkeypatch.setattr(agent, "search_news", lambda *a, **k: list(ARTICLES))
    monkeypatch.setattr(agent.history, "recent_titles", lambda **k: [])
    monkeypatch.setattr(agent, "_groq_client", lambda: ForcedFinalizeRejected())


def test_a_rejected_forced_finalize_still_produces_a_selection():
    """The articles were already gathered; a last-step API refusal must not lose them."""
    monkey = agent.MAX_SEARCHES
    try:
        # searches_used starts at 0, so step 0 is only forced once MAX_SEARCHES is 0.
        agent.MAX_SEARCHES = 0
        selected, collected = agent.run_agent_selection("September 1, 2026")
    finally:
        agent.MAX_SEARCHES = monkey

    assert selected == []  # nothing gathered yet at step 0, but the run did not raise


def test_the_fallback_selects_from_articles_already_gathered(monkeypatch):
    """With results in hand, a refused finalize still returns real articles."""
    client = ForcedFinalizeRejected()
    monkeypatch.setattr(agent, "_groq_client", lambda: client)
    monkeypatch.setattr(agent, "MAX_SEARCHES", 0)

    real_resolve = agent._resolve_selection
    monkeypatch.setattr(
        agent, "_resolve_selection",
        lambda urls, collected: real_resolve(urls, collected or list(ARTICLES)),
    )

    selected, _ = agent.run_agent_selection("September 1, 2026")

    assert len(selected) == agent.TARGET_ARTICLES
    assert all(a["url"].startswith("https://example.com/") for a in selected)


def test_a_failure_before_the_forced_step_is_not_swallowed(monkeypatch):
    """Only the last step degrades; an earlier API error must still surface."""
    monkeypatch.setattr(agent, "MAX_SEARCHES", 99)
    monkeypatch.setattr(agent, "MAX_STEPS", 99)

    with pytest.raises(RuntimeError, match="400"):
        agent.run_agent_selection("September 1, 2026")
