"""The model fallback chain: a decommissioned model must not kill the briefing.

Groq retires models on a rolling basis (llama-3.3-70b-versatile went away mid-2026 and
404'd every call from then on). These tests pin the behaviour that replaced it: try the
configured model, fall through to the next one on a "model not found" 404, and only
fail once the whole chain is gone.
"""

import pytest

import agent


class FakeNotFound(Exception):
    """Mimics groq.NotFoundError: a 404 whose message carries the API error body."""

    status_code = 404

    def __init__(self, model: str):
        super().__init__(
            f"Error code: 404 - {{'error': {{'message': 'The model `{model}` does not "
            "exist or you do not have access to it.', 'type': 'invalid_request_error', "
            "'code': 'model_not_found'}}}}"
        )


class FakeGroq:
    """Groq client stub: every model in `dead` 404s, anything else succeeds."""

    def __init__(self, dead: set[str]):
        self.dead = dead
        self.calls: list[str] = []
        self.chat = self  # mirrors client.chat.completions.create
        self.completions = self

    def create(self, model: str, **kwargs):
        self.calls.append(model)
        if model in self.dead:
            raise FakeNotFound(model)
        return f"response from {model}"


@pytest.fixture(autouse=True)
def reset_active_model(monkeypatch):
    """Each test starts at the top of the chain (the index is module state)."""
    monkeypatch.setattr(agent, "_active_model", 0, raising=False)
    monkeypatch.setattr(
        agent, "MODEL_CHAIN", ["primary-model", "backup-model", "last-resort-model"]
    )


def test_uses_the_primary_model_when_it_works():
    client = FakeGroq(dead=set())
    assert agent._chat_completion(client, messages=[]) == "response from primary-model"
    assert client.calls == ["primary-model"]


def test_falls_through_to_the_next_model_when_the_primary_is_decommissioned():
    client = FakeGroq(dead={"primary-model"})

    result = agent._chat_completion(client, messages=[])

    assert result == "response from backup-model"
    assert client.calls == ["primary-model", "backup-model"]


def test_a_dead_model_is_not_retried_for_the_rest_of_the_run():
    """Once we know a model is gone, later calls start from the working one."""
    client = FakeGroq(dead={"primary-model"})
    agent._chat_completion(client, messages=[])
    client.calls.clear()

    agent._chat_completion(client, messages=[])

    assert client.calls == ["backup-model"]


def test_fails_only_once_every_model_in_the_chain_is_gone():
    client = FakeGroq(dead={"primary-model", "backup-model", "last-resort-model"})

    with pytest.raises(RuntimeError) as excinfo:
        agent._chat_completion(client, messages=[])

    message = str(excinfo.value)
    assert "primary-model" in message and "last-resort-model" in message
    assert "console.groq.com/docs/deprecations" in message
    assert client.calls == ["primary-model", "backup-model", "last-resort-model"]


def test_non_model_errors_are_not_swallowed_by_the_fallback():
    """A rate limit must surface, not silently downgrade the model."""

    class RateLimited(FakeGroq):
        def create(self, model: str, **kwargs):
            self.calls.append(model)
            raise RuntimeError("Error code: 429 - rate_limit_exceeded")

    client = RateLimited(dead=set())
    with pytest.raises(RuntimeError, match="429"):
        agent._chat_completion(client, messages=[])
    assert client.calls == ["primary-model"]
