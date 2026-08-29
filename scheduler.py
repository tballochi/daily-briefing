"""The briefing jobs, and the local daily schedule at 09:00 Europe/Paris.

`run_briefing` is idempotent per Paris day: it sends at most one briefing per day,
no matter how many times it is triggered. This lets the GitHub workflow fire several
times in the morning window (robust to GitHub cron delays) without ever double-sending.
On failure it retries once after a short delay, then emails a failure alert and
exits non-zero so the run is visibly red in GitHub Actions.

`run_dry_run` builds exactly the same briefing but sends nothing and remembers
nothing — the 2-minute way to see the output with only the two free API keys.
"""

import os
import time
import logging
import logging.handlers
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import history
from agent import build_briefing, render_text
from email_sender import send_email, send_failure_alert

TIMEZONE = "Europe/Paris"
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "briefing.log")
PREVIEW_FILE = os.path.join("data", "preview.html")
RETRY_DELAY_SECONDS = 120

logger = logging.getLogger("briefing")


def setup_logging() -> None:
    """Configure logging to both stdout and logs/briefing.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger("briefing")
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def _paris_today() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def _build_and_send() -> None:
    subject, html_body, payload = build_briefing()
    send_email(subject, html_body)
    history.record_sent(
        payload["articles"], payload.get("word", {}), payload.get("quote", {}), _paris_today()
    )


def run_briefing(force: bool = False) -> None:
    """Send today's briefing unless it was already sent (idempotent per Paris day).

    `force` bypasses the once-a-day guard (used for manual test runs).
    """
    # Checked before any API call so a missing secret is reported as a readable
    # message instead of surfacing as a failure halfway through the run.
    config.check_env(delivery=True)

    today = _paris_today()
    if not force and history.last_sent_date() == today:
        logger.info("Briefing already sent today (%s) — skipping.", today)
        return

    logger.info("=== Starting daily briefing job (%s) ===", today)
    try:
        _build_and_send()
        logger.info("=== Briefing sent successfully ===")
        return
    except Exception as exc:  # noqa: BLE001
        # exception() keeps the traceback in the log, so a failed GitHub Actions run
        # can be diagnosed from the Actions output alone.
        logger.exception("Briefing failed: %s. Retrying once in %ds.", exc, RETRY_DELAY_SECONDS)

    time.sleep(RETRY_DELAY_SECONDS)
    try:
        _build_and_send()
        logger.info("=== Briefing sent successfully on retry ===")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Retry also failed: %s. Sending failure alert.", exc)
        send_failure_alert(str(exc))
        # Re-raise so the process exits non-zero and the GitHub Actions run is marked
        # failed. Swallowing this made twelve days of broken briefings show a green
        # check, which is how a decommissioned model went unnoticed for that long.
        raise


def run_dry_run() -> str:
    """Build today's briefing and preview it — no email, no history written.

    This is the low-friction way to evaluate the project: it needs only GROQ_API_KEY
    and TAVILY_API_KEY, touches neither Gmail nor data/history.json, and leaves the
    rendered email at data/preview.html to open in a browser.
    """
    config.check_env(delivery=False)
    cfg = config.load()
    logger.info(
        "=== Dry run: %r, %d article(s), topics=%d, focus=%s ===",
        cfg.title, cfg.num_articles, len(cfg.topics),
        cfg.focus["label"] if cfg.focus else "none",
    )

    subject, html_body, payload = build_briefing()

    os.makedirs(os.path.dirname(PREVIEW_FILE), exist_ok=True)
    with open(PREVIEW_FILE, "w", encoding="utf-8") as fh:
        fh.write(html_body)

    print("\n" + render_text(subject, payload))
    print(f"Rendered email written to {PREVIEW_FILE} — open it in a browser.")
    print("Dry run: nothing was emailed, and no history was recorded.\n")
    logger.info("=== Dry run complete (nothing sent, nothing recorded) ===")
    return html_body


def start_scheduler() -> None:
    """Start the blocking scheduler that fires every day at 09:00 Paris time."""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        run_briefing,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="daily_briefing",
        name="Daily Briefing at 09:00 Europe/Paris",
        misfire_grace_time=3600,
    )
    logger.info("Scheduler started. Next briefing every day at 09:00 %s.", TIMEZONE)
    scheduler.start()
