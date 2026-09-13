"""The writing step must degrade, never take the briefing down.

On 2026-09-13 Groq rejected the synthesis call twice with json_validate_failed: the
reasoning model spent the whole token budget thinking and the JSON never came out.
The run retried the entire research phase and failed again, so no briefing was sent.
"""

import json

import pytest

import agent


class Msg:
    def __init__(self, content):
        self.content = content


class Resp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": Msg(content)})()]


GOOD = json.dumps({
    "summaries": {"1": "First summary.", "2": "Second summary.", "3": "Third summary."},
    "word_of_the_day": {"word": "idempotency", "definition": "d", "example": "e"},
    "quote_of_the_day": {"text": "q", "author": "a"},
})

JSON_REFUSED = RuntimeError(
    "Error code: 400 - {'code': 'json_validate_failed', 'failed_generation': "
    "'max completion tokens reached before generating a valid document'}"
)


class ScriptedGroq:
    """Each call pops the next scripted outcome: an exception to raise or content."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.chat = self
        self.completions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Resp(outcome)


@pytest.fixture(autouse=True)
def top_of_chain(monkeypatch):
    monkeypatch.setattr(agent, "_active_model", 0, raising=False)
    monkeypatch.setattr(agent, "MODEL_CHAIN", ["primary-model"])


# --- The call shapes ---------------------------------------------------------

def test_first_attempt_is_strict_json_with_low_reasoning_effort():
    client = ScriptedGroq([GOOD])
    agent._synthesis_completion(client, [])
    first = client.calls[0]
    assert first["response_format"] == {"type": "json_object"}
    assert first["reasoning_effort"] == "low"
    assert first["max_tokens"] == agent.SYNTHESIS_MAX_TOKENS


def test_budget_is_no_longer_the_old_1500_cap():
    """gpt-oss-120b needed ~1430 tokens for three articles; 1500 left no margin."""
    assert agent.SYNTHESIS_MAX_TOKENS >= 4000


def test_a_refused_json_response_is_retried_with_a_looser_call():
    client = ScriptedGroq([JSON_REFUSED, GOOD])
    data = agent._synthesis_completion(client, [])
    assert data["summaries"]["1"] == "First summary."
    assert "reasoning_effort" not in client.calls[1]


def test_a_rejected_reasoning_effort_parameter_is_dropped_and_retried():
    client = ScriptedGroq([
        RuntimeError("Error code: 400 - `reasoning_effort` must be one of `low`, `medium`, or `high`"),
        GOOD,
    ])
    assert agent._synthesis_completion(client, []) is not None


def test_leaked_reasoning_around_the_json_is_tolerated():
    """Some models wrap the answer in <think> even in plain mode."""
    client = ScriptedGroq([JSON_REFUSED, JSON_REFUSED, "<think>hmm</think>\nSure:\n" + GOOD + "\nDone."])
    data = agent._synthesis_completion(client, [])
    assert data["word_of_the_day"]["word"] == "idempotency"
    assert "response_format" not in client.calls[2]


def test_returns_none_only_after_every_shape_has_failed():
    client = ScriptedGroq([JSON_REFUSED, JSON_REFUSED, "not json at all"])
    assert agent._synthesis_completion(client, []) is None
    assert len(client.calls) == 3


def test_a_model_outage_is_not_mistaken_for_a_json_problem():
    """model_not_found must still reach the fallback chain, not be swallowed here."""
    outage = RuntimeError("Error code: 404 - model_not_found")
    client = ScriptedGroq([outage])
    with pytest.raises(RuntimeError, match="model_not_found"):
        agent._synthesis_completion(client, [])


# --- The briefing still ships ----------------------------------------------

def test_the_briefing_falls_back_to_snippets_when_synthesis_is_impossible(monkeypatch):
    """A digest of real excerpts and links beats a failure email."""
    monkeypatch.setattr(agent, "_groq_client", lambda: ScriptedGroq([JSON_REFUSED, JSON_REFUSED, ""]))
    monkeypatch.setattr(agent.history, "recent_words", lambda **k: [])
    monkeypatch.setattr(agent.history, "recent_quotes", lambda **k: [])
    selected = [
        {"title": "T1", "url": "https://example.com/1", "snippet": "Snippet one about the story."},
        {"title": "T2", "url": "https://example.com/2", "snippet": "Snippet two about the story."},
    ]

    briefing = agent.synthesize_briefing(selected, "September 13, 2026")

    news = briefing["sections"][0]["news"]
    assert [n["summary"] for n in news] == ["Snippet one about the story.", "Snippet two about the story."]
    assert briefing["word_of_the_day"] == {}
    assert briefing["quote_of_the_day"] == {}
