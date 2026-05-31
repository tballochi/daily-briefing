"""Daily scheduling at 9:00 Europe/Paris, with one retry on failure."""

import os
import logging
import logging.handlers
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from agent import build_briefing
from email_sender import send_email

TIMEZONE = "Europe/Paris"
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "briefing.log")

logger = logging.getLogger("briefing")


def setup_logging() -> None:
    """Configure logging to both stdout and logs/briefing.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

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


def run_briefing() -> None:
    """Build and send the briefing. Retries once after 5 minutes on failure."""
    logger.info("=== Starting daily briefing job ===")
    try:
        subject, html_body = build_briefing()
        send_email(subject, html_body)
        logger.info("=== Briefing sent successfully ===")
    except Exception as exc:  # noqa: BLE001
        logger.error("Briefing job failed: %s. Scheduling one retry in 5 min.", exc)
        _schedule_retry()


def _schedule_retry() -> None:
    """Schedule a single one-off retry 5 minutes from now."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from datetime import timedelta

    retry_scheduler = BackgroundScheduler(timezone=TIMEZONE)
    run_time = datetime.now() + timedelta(minutes=5)
    retry_scheduler.add_job(_retry_once, "date", run_date=run_time)
    retry_scheduler.start()
    logger.info("Retry scheduled at %s", run_time.isoformat())


def _retry_once() -> None:
    logger.info("=== Retrying daily briefing job ===")
    try:
        subject, html_body = build_briefing()
        send_email(subject, html_body)
        logger.info("=== Briefing sent successfully on retry ===")
    except Exception as exc:  # noqa: BLE001
        logger.error("Retry also failed: %s. Giving up until next schedule.", exc)


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
