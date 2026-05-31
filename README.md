# Daily Tech Briefing Agent

> AI-powered daily tech briefing delivered to your inbox every morning at 9am.
> Built with Groq LLM + Tavily Search API.

## What you get every morning

- Latest AI & LLMs news
- Shipping & Logistics tech updates
- Automation & Product news
- Word of the day to improve your English
- Inspirational tech quote

## Installation

```bash
git clone https://github.com/tballochi99/daily-tech-briefing
cd daily-tech-briefing
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
```

## Free API Keys needed

* Groq (LLM) : https://console.groq.com — free
* Tavily (Search) : https://tavily.com — 1000 searches/month free
* Gmail App Password : https://myaccount.google.com/apppasswords

## Run locally

```bash
python main.py          # starts the scheduler (daily at 09:00 Europe/Paris)
python main.py --now    # build and send one briefing immediately (for testing)
```

## Deploy for free with GitHub Actions (recommended)

The repo ships with a workflow (`.github/workflows/daily-briefing.yml`) that sends
the briefing every morning at **09:00 Europe/Paris** — no server to keep running.

1. Push this repo to GitHub.
2. In your repo, go to **Settings → Secrets and variables → Actions → New repository secret**
   and add these 5 secrets:

   | Secret name | Value |
   |-------------|-------|
   | `GROQ_API_KEY` | your Groq key |
   | `TAVILY_API_KEY` | your Tavily key |
   | `GMAIL_ADDRESS` | the sending Gmail address |
   | `GMAIL_APP_PASSWORD` | your 16-char Gmail App Password |
   | `RECIPIENT_EMAIL` | where the briefing is delivered |

3. That's it. The workflow runs daily and **commits `data/history.json` back to the
   repo** after each send, so already-sent articles never come back.

To test it immediately: **Actions → Daily Tech Briefing → Run workflow**.

> Note: GitHub cron is UTC, so the workflow triggers at 07:00 and 08:00 UTC and a
> guard step keeps only the run that matches 09:00 Paris time (handles summer/winter).

## Deploy on Railway (alternative)

```bash
railway up
```

On Railway, attach a persistent **Volume** mounted where `data/history.json` lives
so the de-duplication history survives restarts.

## Tech Stack

| Tool | Purpose |
|------|---------|
| Python 3.11+ | Core language |
| Groq API (Llama 3.3 70B) | LLM content generation |
| Tavily API | Real-time web search |
| APScheduler | Daily 9am scheduling |
| smtplib | Gmail email sending |
| python-dotenv | Environment management |

## Project structure

```
daily-tech-briefing/
├── main.py              # Entry point
├── agent.py             # AI agent logic (Tavily search + Groq generation)
├── email_sender.py      # Gmail SMTP delivery
├── scheduler.py         # Daily 9am scheduling + logging
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Author

Timoté Ballochi
GitHub: https://github.com/tballochi99

---
*Staying ahead of the curve, one briefing at a time.*
