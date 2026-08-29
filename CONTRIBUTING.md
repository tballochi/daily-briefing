# Contributing

Thanks for taking a look. Issues and pull requests are both welcome, including
"this broke for me" reports, which are genuinely useful.

## Set up

```bash
git clone https://github.com/tballochi/daily-briefing.git
cd daily-briefing
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
```

## Run the tests

```bash
pytest -q
```

The suite mocks the network, so it needs no API keys and finishes in about a second.
CI runs it on Python 3.11 and 3.13 for every push and pull request.

## Try your change for real

```bash
python main.py --setup    # or write the two keys into .env yourself
python main.py --dry-run
```

`--dry-run` runs the whole pipeline (research, writing, HTML rendering) but sends no
email and writes nothing to `data/history.json`. The rendered email lands in
`data/preview.html`. Use it rather than `--now` while developing: `--now` really emails
you and marks the day as sent.

## Opening a PR

- Branch off `main`, one focused change per PR.
- Add or update a test when you change behaviour. If a bug got through, the PR that
  fixes it is a good place for the test that would have caught it.
- Keep the free-tier, no-server promise intact: no paid services, nothing that has to
  stay running, no new required infrastructure.
- Match the surrounding style: the code favours short modules and comments that explain
  *why* rather than *what*.
- Run `pytest -q` before pushing.

## Good first contributions

- Another delivery channel behind a config flag (Telegram, Discord webhook).
- Support for a non-Gmail SMTP provider without editing `email_sender.py`.
- Better source-quality filtering (rejecting SEO round-up pages more reliably).
- Docs fixes, including anything that tripped you up during setup.

## Reporting a bug

Use the bug report template. If the agent failed, the **exact error and the Groq model in
use** are the two things that make it triageable. Model deprecations are the most common
cause of a sudden failure, and the Actions log names the model in its first lines.
