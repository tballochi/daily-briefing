"""Persistent memory for de-duplication.

Stores, in data/history.json:
- "seen": articles already sent (dedup by normalised URL or title)
- "words": words of the day already used (avoid repeats)
- "quotes": quotes already used (avoid repeats)
- "last_sent_date": the last Paris date a briefing was actually sent (idempotency)

Everything here is free: it is just a JSON file committed back to the repo by the
daily GitHub Action.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger("briefing.history")

HISTORY_FILE = os.path.join("data", "history.json")
SEEN_RETENTION_DAYS = 60
EXTRAS_RETENTION_DAYS = 45


def _normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        host = parts.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return f"{host}{parts.path.rstrip('/').lower()}"
    except Exception:  # noqa: BLE001
        return (url or "").strip().lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _load_doc() -> dict:
    doc = {"seen": [], "words": [], "quotes": [], "last_sent_date": ""}
    if not os.path.exists(HISTORY_FILE):
        return doc
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        doc.update({k: data.get(k, doc[k]) for k in doc})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read history file: %s", exc)
    return doc


def _within(entries: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    kept = []
    for e in entries:
        try:
            if datetime.fromisoformat(e.get("date", "")) >= cutoff:
                kept.append(e)
        except Exception:  # noqa: BLE001 - keep entries with unparseable dates
            kept.append(e)
    return kept


# --- De-duplication lookups (exact, for the search annotations) ------------

def _seen_keys() -> tuple[set[str], set[str]]:
    entries = _load_doc()["seen"]
    return (
        {e.get("url_key", "") for e in entries},
        {e.get("title_key", "") for e in entries},
    )


def is_seen(url: str, title: str) -> bool:
    """True if this article (by URL or title) was already sent before."""
    seen_urls, seen_titles = _seen_keys()
    return _normalize_url(url) in seen_urls or _normalize_title(title) in seen_titles


def filter_unseen(all_news: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop articles already sent (kept for completeness / non-agent callers)."""
    seen_urls, seen_titles = _seen_keys()
    filtered: dict[str, list[dict]] = {}
    for section, items in all_news.items():
        filtered[section] = [
            it
            for it in items
            if _normalize_url(it.get("source", "")) not in seen_urls
            and _normalize_title(it.get("title", "")) not in seen_titles
        ]
    return filtered


# --- Recall for the LLM (semantic-dedup hints) -----------------------------

def recent_titles(days: int = 14) -> list[str]:
    """Titles sent in the last `days` days, so the agent can avoid same stories."""
    return [e.get("title", "") for e in _within(_load_doc()["seen"], days) if e.get("title")]


def recent_words(days: int = EXTRAS_RETENTION_DAYS) -> list[str]:
    return [e.get("word", "") for e in _within(_load_doc()["words"], days) if e.get("word")]


def recent_quotes(days: int = EXTRAS_RETENTION_DAYS) -> list[str]:
    return [e.get("text", "") for e in _within(_load_doc()["quotes"], days) if e.get("text")]


# --- Idempotency -----------------------------------------------------------

def last_sent_date() -> str:
    return _load_doc().get("last_sent_date", "")


# --- Persist after a successful send ---------------------------------------

def record_sent(articles: list[dict], word: dict, quote: dict, sent_date: str) -> None:
    """Persist everything a successful briefing should remember.

    `articles` is a list of {"url", "title"}; `word`/`quote` are the day's extras;
    `sent_date` is the Paris date string used for once-a-day idempotency.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    doc = _load_doc()
    now_iso = datetime.now().isoformat()

    seen = _within(doc["seen"], SEEN_RETENTION_DAYS)
    for item in articles:
        seen.append(
            {
                "url_key": _normalize_url(item.get("url", "")),
                "title_key": _normalize_title(item.get("title", "")),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "date": now_iso,
            }
        )

    words = _within(doc["words"], EXTRAS_RETENTION_DAYS)
    if word.get("word"):
        words.append({"word": word.get("word", ""), "date": now_iso})

    quotes = _within(doc["quotes"], EXTRAS_RETENTION_DAYS)
    if quote.get("text"):
        quotes.append({"text": quote.get("text", ""), "author": quote.get("author", ""), "date": now_iso})

    doc = {"seen": seen, "words": words, "quotes": quotes, "last_sent_date": sent_date}
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        logger.info("Recorded %d article(s), word=%r, quote saved", len(articles), word.get("word", ""))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not write history file: %s", exc)
