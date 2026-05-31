"""Persistent de-duplication: remember which articles were already sent.

An article is considered "already seen" if its normalised URL OR its normalised
title was sent in a previous briefing. Seen entries older than RETENTION_DAYS are
pruned so the file does not grow forever.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger("briefing.history")

HISTORY_FILE = os.path.join("data", "history.json")
RETENTION_DAYS = 60


def _normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        host = parts.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        path = parts.path.rstrip("/").lower()
        return f"{host}{path}"
    except Exception:  # noqa: BLE001
        return (url or "").strip().lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _load() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh).get("seen", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read history file: %s", exc)
        return []


def _prune(entries: list[dict]) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    kept = []
    for e in entries:
        try:
            if datetime.fromisoformat(e.get("date", "")) >= cutoff:
                kept.append(e)
        except Exception:  # noqa: BLE001 - keep entries with bad dates
            kept.append(e)
    return kept


def _seen_keys() -> tuple[set[str], set[str]]:
    """Return (set of seen normalised urls, set of seen normalised titles)."""
    entries = _load()
    urls = {e.get("url_key", "") for e in entries}
    titles = {e.get("title_key", "") for e in entries}
    return urls, titles


def is_seen(url: str, title: str) -> bool:
    """True if this article (by URL or title) was already sent before."""
    seen_urls, seen_titles = _seen_keys()
    return _normalize_url(url) in seen_urls or _normalize_title(title) in seen_titles


def filter_unseen(all_news: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop articles that were already sent in a previous briefing."""
    seen_urls, seen_titles = _seen_keys()
    filtered: dict[str, list[dict]] = {}
    dropped = 0
    for section, items in all_news.items():
        kept = []
        for item in items:
            url_key = _normalize_url(item.get("source", ""))
            title_key = _normalize_title(item.get("title", ""))
            if url_key in seen_urls or title_key in seen_titles:
                dropped += 1
                continue
            kept.append(item)
        filtered[section] = kept
    if dropped:
        logger.info("Filtered out %d already-seen article(s)", dropped)
    return filtered


def record_seen(chosen: list[dict]) -> None:
    """Persist the articles that were actually included in the sent briefing.

    `chosen` is a list of {"url": ..., "title": ...} dicts.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    entries = _prune(_load())
    now_iso = datetime.now().isoformat()
    for item in chosen:
        entries.append(
            {
                "url_key": _normalize_url(item.get("url", "")),
                "title_key": _normalize_title(item.get("title", "")),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "date": now_iso,
            }
        )
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump({"seen": entries}, fh, ensure_ascii=False, indent=2)
        logger.info("Recorded %d article(s) in history", len(chosen))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not write history file: %s", exc)
