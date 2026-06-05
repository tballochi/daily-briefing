"""User briefing preferences, loaded from config.yaml.

Personalisation (which topics to cover, how many stories, an optional always-include
"focus" theme) lives in config.yaml — not in the code — so anyone who clones the repo
just edits one readable file to make the briefing their own. If the file is missing or
partial we fall back to sensible built-in defaults, so the briefing always runs.
"""

import os
import logging

logger = logging.getLogger("briefing.config")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

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
        num_articles: how many stories the briefing contains.
        topics: list of free-text interest areas that steer the agent's searches.
        focus: optional dict {label, priority_query, keywords} for a story that must
               always be present (e.g. shipping/CMA CGM); None if not configured.
    """

    def __init__(self, data: dict):
        try:
            self.num_articles = max(1, int(data.get("num_articles") or 3))
        except (TypeError, ValueError):
            self.num_articles = 3

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
