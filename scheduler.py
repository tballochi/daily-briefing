"""Daily scheduling at 09:00 Europe/Paris.

`run_briefing` is idempotent per Paris day: it sends at most one briefing per day,
no matter how many times it is triggered. This lets the GitHub workflow fire several
times in the morning window (robust to GitHub cron delays) without ever double-sending.
On failure it retries once after a short delay, then emails a failure alert.
"""

import os
import time
import logging
import logging.handlers
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import history
from agent import build_briefing
from email_sender import send_email, send_failure_alert

TIMEZONE = "Europe/Paris"
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "briefing.log")
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
        logger.error("Briefing failed: %s. Retrying once in %ds.", exc, RETRY_DELAY_SECONDS)

    time.sleep(RETRY_DELAY_SECONDS)
    try:
        _build_and_send()
        logger.info("=== Briefing sent successfully on retry ===")
    except Exception as exc:  # noqa: BLE001
        logger.error("Retry also failed: %s. Sending failure alert.", exc)
        send_failure_alert(str(exc))


def start_scheduler() -> None:
    """Start the blocking scheduler that fires every day at 09:00 Paris time."""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        run_briefing,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="daily_briefing",
        name="Daily Tech Briefing at 09:00 Europe/Paris",
        misfire_grace_time=3600,
    )
    logger.info("Scheduler started. Next briefing every day at 09:00 %s.", TIMEZONE)
    scheduler.start()
