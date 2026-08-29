"""Entry point for the Daily Briefing agent.

Usage:
    python main.py --setup    # guided first-time setup (checks every key)
    python main.py --dry-run  # build a briefing and preview it — sends nothing
    python main.py --now      # send today's briefing now (skips if already sent today)
    python main.py --now --force   # send now even if one was already sent today
    python main.py            # start the scheduler (daily at 09:00 Europe/Paris)
"""

import sys

from dotenv import load_dotenv

from config import ConfigError
from scheduler import setup_logging, start_scheduler, run_briefing, run_dry_run


def main() -> int:
    load_dotenv()
    setup_logging()

    try:
        if "--setup" in sys.argv:
            import setup_wizard

            return setup_wizard.main()
        if "--dry-run" in sys.argv:
            run_dry_run()
        elif "--now" in sys.argv:
            run_briefing(force="--force" in sys.argv)
        else:
            start_scheduler()
    except ConfigError as exc:
        # A setting the user can fix: show the explanation, not a stack trace.
        print(f"\n{exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
