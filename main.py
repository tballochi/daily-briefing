"""Entry point for the Daily Tech Briefing agent.

Usage:
    python main.py            # start the scheduler (daily at 09:00 Europe/Paris)
    python main.py --now      # send today's briefing now (skips if already sent today)
    python main.py --now --force   # send now even if one was already sent today
"""

import sys

from dotenv import load_dotenv

from scheduler import setup_logging, start_scheduler, run_briefing


def main() -> None:
    load_dotenv()
    setup_logging()

    if "--now" in sys.argv:
        run_briefing(force="--force" in sys.argv)
        return

    start_scheduler()


if __name__ == "__main__":
    main()
