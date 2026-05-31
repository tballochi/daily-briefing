"""Entry point for the Daily Tech Briefing agent.

Usage:
    python main.py          # start the scheduler (daily at 09:00 Europe/Paris)
    python main.py --now    # build and send a briefing immediately (for testing)
"""

import sys

from dotenv import load_dotenv

from scheduler import setup_logging, start_scheduler, run_briefing


def main() -> None:
    load_dotenv()
    setup_logging()

    if "--now" in sys.argv:
        # One-off run, useful for local testing and manual triggers.
        run_briefing()
        return

    start_scheduler()


if __name__ == "__main__":
    main()
