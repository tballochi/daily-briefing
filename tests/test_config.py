"""config.yaml parsing, defaults, and the friendly missing-secret errors."""

import pytest

import config


def test_defaults_apply_when_config_is_empty():
    """A clone with no config.yaml must still produce a runnable briefing."""
    cfg = config.BriefingConfig({})

    assert cfg.title == "Daily Briefing"
    assert cfg.num_articles == 3
    assert cfg.topics  # never empty, or the agent has nothing to search
    assert cfg.focus is None
    assert cfg.model == config._DEFAULT_MODEL


def test_model_chain_is_the_model_then_its_fallbacks():
    cfg = config.BriefingConfig({"model": "a", "model_fallbacks": ["b", "c"]})
    assert cfg.model_chain == ["a", "b", "c"]


def test_model_chain_drops_duplicates_and_blanks():
    """A model repeated in the fallbacks must not be tried twice."""
    cfg = config.BriefingConfig({"model": "a", "model_fallbacks": ["b", "a", "  ", "c"]})
    assert cfg.model_chain == ["a", "b", "c"]


def test_groq_model_env_var_overrides_the_config_file(monkeypatch):
    """The escape hatch for a retired model: override without editing code."""
    monkeypatch.setenv("GROQ_MODEL", "env/model")
    cfg = config.BriefingConfig({"model": "file/model", "model_fallbacks": ["backup"]})
    assert cfg.model_chain == ["env/model", "backup"]


def test_explicitly_empty_fallbacks_are_respected():
    cfg = config.BriefingConfig({"model": "only", "model_fallbacks": []})
    assert cfg.model_chain == ["only"]


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, 1),
        ("5", 5),          # YAML can hand us a string
        (-3, 1),           # clamped to at least one story
        (0, 3),            # falsy, so treated as "unset" -> default
        ("oops", 3),       # unparseable -> default rather than a crash
        (None, 3),
    ],
)
def test_num_articles_is_coerced_to_a_sane_positive_int(value, expected):
    assert config.BriefingConfig({"num_articles": value}).num_articles == expected


def test_focus_block_is_parsed_when_present():
    cfg = config.BriefingConfig(
        {"focus": {"label": "shipping", "priority_query": "CMA CGM", "keywords": ["Freight", " port "]}}
    )
    assert cfg.focus["label"] == "shipping"
    assert cfg.focus["priority_query"] == "CMA CGM"
    assert cfg.focus["keywords"] == ("freight", "port")  # lowercased for matching


def test_deleting_the_focus_block_disables_the_guaranteed_story():
    assert config.BriefingConfig({"topics": ["x"]}).focus is None


def test_topics_fall_back_when_the_list_is_empty():
    assert config.BriefingConfig({"topics": []}).topics == config._DEFAULT_TOPICS


# --- Friendly errors --------------------------------------------------------

ALL_SECRETS = ("GROQ_API_KEY", "TAVILY_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL")


@pytest.fixture
def no_secrets(monkeypatch):
    for name in ALL_SECRETS:
        monkeypatch.delenv(name, raising=False)


def test_missing_key_names_the_key_and_where_to_get_it(no_secrets):
    with pytest.raises(config.ConfigError) as excinfo:
        config.check_env()

    message = str(excinfo.value)
    assert "GROQ_API_KEY" in message
    assert "https://console.groq.com/keys" in message  # actionable, not a stack trace


def test_dry_run_does_not_require_any_gmail_setup(no_secrets, monkeypatch):
    """The whole point of --dry-run: two free API keys and nothing else."""
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "y")

    config.check_env(delivery=False)  # must not raise

    with pytest.raises(config.ConfigError, match="GMAIL_ADDRESS"):
        config.check_env(delivery=True)


def test_blank_values_count_as_missing(no_secrets, monkeypatch):
    """An empty GitHub secret is a common footgun; treat it as unset."""
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    monkeypatch.setenv("TAVILY_API_KEY", "y")
    with pytest.raises(config.ConfigError, match="GROQ_API_KEY"):
        config.check_env(delivery=False)


def test_nothing_raises_when_everything_is_set(no_secrets, monkeypatch):
    for name in ALL_SECRETS:
        monkeypatch.setenv(name, "value")
    config.check_env(delivery=True)
