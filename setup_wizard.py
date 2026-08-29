"""Interactive first-time setup: `python main.py --setup`.

Collects the five secrets, then *verifies each one against the real API* before writing
anything. Getting this wrong is the single most likely reason someone gives up — an
unverified Gmail App Password fails silently at 8am tomorrow rather than now — so every
key is checked here, while the person is still watching.

It also resets the de-duplication history, which matters when the repo was created from
the template: without it a new user inherits someone else's "already sent" articles.
"""

import os
import re
import json
import shutil
import subprocess
import sys

import config

ENV_FILE = ".env"
HISTORY_FILE = os.path.join("data", "history.json")

# The five values a full deployment needs, in the order we ask for them.
GROQ, TAVILY = "GROQ_API_KEY", "TAVILY_API_KEY"
GMAIL_ADDRESS, GMAIL_PASSWORD, RECIPIENT = "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"
DELIVERY_KEYS = (GMAIL_ADDRESS, GMAIL_PASSWORD, RECIPIENT)


# --- Console helpers --------------------------------------------------------

def _headline(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m")


def _ok(text: str) -> None:
    print(f"  \033[32m✓\033[0m {text}")


def _fail(text: str) -> None:
    print(f"  \033[31m✗\033[0m {text}")


def _ask(prompt: str, *, secret_hint: str = "") -> str:
    if secret_hint:
        print(f"  {secret_hint}")
    return input(f"  {prompt}: ").strip()


def _confirm(prompt: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"  {prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


# --- Key verification -------------------------------------------------------
#
# Each verifier returns (ok, message) and never raises: a wrong key should produce an
# explanation and another attempt, not a traceback.

def _verify_groq(key: str) -> tuple[bool, str]:
    """Check the key works AND that the configured model chain is actually reachable."""
    try:
        from groq import Groq

        available = {m.id for m in Groq(api_key=key).models.list().data}
    except Exception as exc:  # noqa: BLE001
        return False, f"Groq rejected the key: {_short(exc)}"

    chain = config.load().model_chain
    live = [m for m in chain if m in available]
    if not live:
        return False, (
            f"key works, but none of your configured models exist: {', '.join(chain)}.\n"
            "    Update `model` in config.yaml — see https://console.groq.com/docs/deprecations"
        )
    if live[0] != chain[0]:
        return True, f"key works. Note: {chain[0]!r} is unavailable, will fall back to {live[0]!r}"
    return True, f"key works, model {live[0]!r} is available"


def _verify_tavily(key: str) -> tuple[bool, str]:
    try:
        from tavily import TavilyClient

        TavilyClient(api_key=key).search(query="test", max_results=1)
    except Exception as exc:  # noqa: BLE001
        return False, f"Tavily rejected the key: {_short(exc)}"
    return True, "key works, search returned results"


def _verify_gmail(address: str, password: str) -> tuple[bool, str]:
    """Log in to Gmail SMTP for real — the check people most often skip and regret."""
    import ssl
    import smtplib

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
            server.login(address, password)
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Gmail refused those credentials.\n"
            "    It must be a 16-character App Password (not your normal password),\n"
            "    from https://myaccount.google.com/apppasswords with 2FA enabled."
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Gmail: {_short(exc)}"
    return True, "Gmail login succeeded"


def _short(exc: Exception) -> str:
    return str(exc).splitlines()[0][:160] or type(exc).__name__


def _collect(name: str, prompt: str, hint: str, verify) -> str:
    """Ask for a value and re-ask until it verifies (or the user chooses to move on)."""
    while True:
        value = _ask(prompt, secret_hint=hint)
        if not value:
            _fail("That can't be empty.")
            continue

        print("  checking…")
        ok, message = verify(value)
        if ok:
            _ok(message)
            return value

        _fail(message)
        if not _confirm("Try again?"):
            return value


# --- Repo / environment writing ---------------------------------------------

def _repo_slug() -> str:
    """Best-effort 'owner/repo' from the git remote, to pre-fill the pinger URL."""
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "<you>/daily-briefing"
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return match.group(1) if match else "<you>/daily-briefing"


def _write_env(values: dict) -> None:
    """Write .env, preserving any unrelated keys already in it."""
    existing = {}
    if os.path.exists(ENV_FILE):
        shutil.copyfile(ENV_FILE, ENV_FILE + ".backup")
        for line in open(ENV_FILE, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, val = line.partition("=")
                existing[key.strip()] = val.strip()

    existing.update({k: v for k, v in values.items() if v})
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        for key, value in existing.items():
            fh.write(f"{key}={value}\n")


def _reset_history() -> None:
    """Start with an empty memory.

    A repo created from the template carries the original author's sent articles, so a
    new user would have stories wrongly marked "already sent" — and, if the inherited
    last_sent_date happens to be today, their first briefing would be skipped entirely.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
        json.dump({"seen": [], "words": [], "quotes": [], "last_sent_date": ""}, fh, indent=2)


def _push_secrets_to_github(values: dict) -> bool:
    """Upload the secrets with the gh CLI, if it's installed and logged in."""
    if not shutil.which("gh"):
        return False
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        return False
    if not _confirm("The GitHub CLI is available. Set these as repo secrets now?"):
        return False

    for name, value in values.items():
        if not value:
            continue
        result = subprocess.run(
            ["gh", "secret", "set", name, "--body", value], capture_output=True, text=True
        )
        if result.returncode == 0:
            _ok(f"{name} set")
        else:
            _fail(f"{name}: {result.stderr.strip()[:120]}")
    return True


# --- The wizard -------------------------------------------------------------

def run() -> int:
    print("\n\033[1mDaily Briefing — setup\033[0m")
    print("Every key is checked against the real API before anything is written.")
    print("Press Ctrl-C at any point to stop; nothing is saved until the end.\n")

    cfg = config.load()
    print(f"Briefing: {cfg.title!r} · {cfg.num_articles} article(s) · {len(cfg.topics)} topic(s)")
    print("Edit config.yaml to change those.")

    values: dict[str, str] = {}

    _headline("1/3 · Groq — the AI brain")
    values[GROQ] = _collect(
        GROQ, "Groq API key", "Free key: https://console.groq.com/keys", _verify_groq
    )

    _headline("2/3 · Tavily — live web search")
    values[TAVILY] = _collect(
        TAVILY, "Tavily API key", "Free key: https://app.tavily.com", _verify_tavily
    )

    _headline("3/3 · Gmail — delivery")
    print("  Skip this to use --dry-run only (preview in your terminal, no email).")
    if _confirm("Set up email delivery now?"):
        while True:
            address = _ask("Gmail address that sends the briefing")
            password = _ask(
                "Gmail App Password",
                secret_hint="16 characters, from https://myaccount.google.com/apppasswords (needs 2FA)",
            )
            print("  checking…")
            ok, message = _verify_gmail(address, password)
            if ok:
                _ok(message)
                values[GMAIL_ADDRESS], values[GMAIL_PASSWORD] = address, password
                values[RECIPIENT] = _ask("Deliver the briefing to") or address
                break
            _fail(message)
            if not _confirm("Try again?"):
                break
    else:
        print("  Skipped — you can re-run this any time with `python main.py --setup`.")

    _headline("Saving")
    _write_env(values)
    _ok(f"Wrote {ENV_FILE} (gitignored — your keys stay on this machine)")

    if _confirm("Reset the de-duplication history for a fresh start?"):
        _reset_history()
        _ok("History cleared — no story will be wrongly marked as already sent")

    _push_secrets_to_github(values)

    _headline("Next")
    print("  1. See what you'd get, right now:\n       python main.py --dry-run\n")
    if all(values.get(k) for k in DELIVERY_KEYS):
        print("  2. Send one for real:\n       python main.py --now\n")
        print("  3. Deploy free on GitHub Actions: add the same values as repo secrets")
        print("     (Settings → Secrets and variables → Actions), then set up the pinger:\n")
        slug = _repo_slug()
        print("       POST https://api.github.com/repos/"
              f"{slug}/actions/workflows/daily-briefing.yml/dispatches")
        print('       Body:    {"ref":"main"}')
        print("       Headers: Accept: application/vnd.github+json")
        print("                Authorization: Bearer <your github_pat_...>")
        print("                X-GitHub-Api-Version: 2022-11-28")
        print("\n     Full instructions are in the README.\n")
    else:
        print("  2. When you want it delivered by email, re-run:\n       python main.py --setup\n")
    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("\n\nStopped. Nothing was saved.\n")
        return 130
