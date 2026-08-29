"""User briefing preferences, loaded from config.yaml.

Personalisation (which topics to cover, how many stories, an optional always-include
"focus" theme, which Groq model to use) lives in config.yaml — not in the code — so
anyone who clones the repo just edits one readable file to make the briefing their own.
If the file is missing or partial we fall back to sensible built-in defaults, so the
briefing always runs.
"""

import os
import logging

logger = logging.getLogger("briefing.config")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# Groq deprecates models regularly, so the model is config-driven with a fallback
# chain: if the primary one is decommissioned the agent degrades to the next instead of
# failing the whole morning. Check what is still live before changing these:
# https://console.groq.com/docs/deprecations
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_DEFAULT_MODEL_FALLBACKS = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

# Used when config.yaml is absent/unreadable so the agent never hard-fails on config.
_DEFAULT_TOPICS = [
    "AI & LLMs (GPT, Claude, Gemini, agents, MCP)",
    "automation & no-code (n8n, Zapier, Make)",
    "shipping & logistics tech",
]


def _load_raw() -> dict:
    """Read config.yaml into a dict; return {} on any problem (defaults take over)."""
    try:
        import yaml
    except Exception:  # noqa: BLE001 - PyYAML missing; run on defaults
        logger.warning("PyYAML not installed; using default briefing config")
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("config.yaml must be a mapping at the top level")
        return data
    except FileNotFoundError:
        logger.info("No config.yaml found; using default briefing config")
        return {}
    except Exception as exc:  # noqa: BLE001 - malformed YAML; fall back to defaults
        logger.error("Could not read config.yaml (%s); using defaults", exc)
        return {}


class BriefingConfig:
    """Validated, normalised view of the user's preferences.

    Attributes:
        title: name shown in the email subject and header (topic-agnostic default).
        footer_note: small line at the bottom of the email (empty to omit).
        num_articles: how many stories the briefing contains.
        model: the Groq model the agent prefers.
        model_fallbacks: models tried, in order, if `model` is unavailable.
        model_chain: `model` followed by `model_fallbacks` (deduplicated) — the exact
               order the agent tries when a model 404s as deprecated/decommissioned.
        topics: list of free-text interest areas that steer the agent's searches.
        focus: optional dict {label, priority_query, keywords} for a story that must
               always be present (e.g. shipping/CMA CGM); None if not configured.
    """

    def __init__(self, data: dict):
        self.title = str(data.get("title") or "").strip() or "Daily Briefing"

        # Deliberately not a personal address: this renders in every clone's inbox.
        self.footer_note = str(data.get("footer_note", "Stay ahead of the curve") or "").strip()

        try:
            self.num_articles = max(1, int(data.get("num_articles") or 3))
        except (TypeError, ValueError):
            self.num_articles = 3

        # GROQ_MODEL wins over config.yaml so a dead model can be worked around from
        # the environment (a GitHub secret/variable) without editing and pushing code.
        self.model = (
            os.getenv("GROQ_MODEL", "").strip()
            or str(data.get("model") or "").strip()
            or _DEFAULT_MODEL
        )

        fallbacks = data.get("model_fallbacks")
        if fallbacks is None:
            fallbacks = _DEFAULT_MODEL_FALLBACKS
        self.model_fallbacks = [str(m).strip() for m in fallbacks if str(m).strip()]

        self.model_chain = []
        for name in [self.model, *self.model_fallbacks]:
            if name not in self.model_chain:
                self.model_chain.append(name)

        topics = data.get("topics") or _DEFAULT_TOPICS
        self.topics = [str(t).strip() for t in topics if str(t).strip()] or list(_DEFAULT_TOPICS)

        self.focus = None
        focus = data.get("focus")
        if isinstance(focus, dict):
            label = str(focus.get("label", "")).strip()
            keywords = tuple(
                str(k).strip().lower()
                for k in (focus.get("keywords") or [])
                if str(k).strip()
            )
            if label or keywords:
                self.focus = {
                    "label": label,
                    "priority_query": str(focus.get("priority_query", "")).strip(),
                    "keywords": keywords,
                }


def load() -> BriefingConfig:
    """Load and validate the user's briefing preferences."""
    return BriefingConfig(_load_raw())


# --- Environment validation -------------------------------------------------

class ConfigError(Exception):
    """A missing/invalid setting the user can fix. Printed as a plain message.

    Raised instead of letting an API client blow up 40 lines deep: someone trying
    the project for the first time should be told which key is missing and where to
    get it, not handed a stack trace.
    """


# Every secret the agent can need, with a human explanation of how to get it.
_ENV_HELP = {
    "GROQ_API_KEY": "the AI brain. Get one free at https://console.groq.com/keys",
    "TAVILY_API_KEY": "live web search. Get one free at https://app.tavily.com",
    "GMAIL_ADDRESS": "the Gmail account that sends the briefing, e.g. you@gmail.com",
    "GMAIL_APP_PASSWORD": (
        "a 16-character Gmail App Password (NOT your normal password) from "
        "https://myaccount.google.com/apppasswords — needs 2FA enabled"
    ),
    "RECIPIENT_EMAIL": "the address the briefing is delivered to",
}

# Building a briefing only needs the two API keys; delivery also needs the Gmail set.
RESEARCH_ENV = ("GROQ_API_KEY", "TAVILY_API_KEY")
DELIVERY_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL")


def check_env(*, delivery: bool = True) -> None:
    """Fail early and readably if a required secret is missing.

    `delivery=False` for --dry-run, which builds a briefing but never sends it, so
    it can be tried with just the two free API keys and no Gmail setup at all.
    """
    required = list(RESEARCH_ENV) + (list(DELIVERY_ENV) if delivery else [])
    missing = [name for name in required if not (os.getenv(name) or "").strip()]
    if not missing:
        return

    lines = [
        f"Missing {len(missing)} required setting(s):",
        "",
        *(f"  {name}  —  {_ENV_HELP[name]}" for name in missing),
        "",
        "Set them in a .env file (copy .env.example) for a local run, or as GitHub",
        "Actions secrets when running on GitHub.",
    ]
    if not delivery:
        lines.append("")
        lines.append("Tip: --dry-run only needs GROQ_API_KEY and TAVILY_API_KEY.")
    raise ConfigError("\n".join(lines))
