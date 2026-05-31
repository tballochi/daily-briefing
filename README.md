# Daily Tech Briefing

An AI agent that emails you the **3 most important tech stories of the day**, every
morning at 9am (Europe/Paris). Free to run, no server to maintain.

Built with **Groq (Llama 3.3 70B)** for the AI and **Tavily** for live web search.

---

## What you get every morning

A clean, newspaper-style email with:

- **3 top tech stories** — across AI & LLMs, shipping/logistics, and automation.
  One story is always about **shipping** (CMA CGM when there's relevant news).
- For each story: a short factual summary, the **publication date**, and a link to
  the source.
- **Word of the day** — a real tech term with a definition and example.
- **Quote of the day** — from a well-known tech leader.

No repeats: an article that was sent once never comes back.

---

## How it works

It's a real **AI agent**, not a fixed script. In two phases:

1. **Research** — the agent decides what to search, runs several web searches,
   judges the results, skips articles already sent on previous days, and picks the
   3 best stories.
2. **Writing** — a second step writes the summaries from the real source text, so
   nothing is invented.

The whole run stays within the **Groq free tier** (calls are paced automatically).

---

## Setup

### 1. Get 3 free API keys

| Key | Where | Free |
|-----|-------|------|
| Groq | https://console.groq.com/keys | yes |
| Tavily | https://app.tavily.com | yes (1000 searches/month) |
| Gmail App Password | https://myaccount.google.com/apppasswords | needs 2FA enabled |

> The Gmail App Password is a 16-character code — **not** your normal password.

### 2. Run it daily for free with GitHub Actions (recommended)

No computer needs to stay on. GitHub runs it every morning at 9am Paris.

1. Push this repo to your GitHub account.
2. Go to **Settings → Secrets and variables → Actions** and add these 5 secrets:

   | Secret | Value |
   |--------|-------|
   | `GROQ_API_KEY` | your Groq key |
   | `TAVILY_API_KEY` | your Tavily key |
   | `GMAIL_ADDRESS` | the Gmail address that sends the email |
   | `GMAIL_APP_PASSWORD` | your 16-char Gmail App Password |
   | `RECIPIENT_EMAIL` | where the briefing is delivered |

3. Done. It sends every day at ~9am Paris and remembers past articles automatically
   (it commits `data/history.json` back to the repo after each send).

**Test it now:** Actions → *Daily Tech Briefing* → **Run workflow**.

---

## Run locally (optional)

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
python main.py --now      # build and send one briefing right now
python main.py            # start the local scheduler (sends daily at 9am Paris)
```

---

## Tech stack

| Tool | Role |
|------|------|
| Python 3.11+ | Core language |
| Groq — Llama 3.3 70B | The agent's brain (decides, summarises) |
| Tavily | Real-time news search |
| GitHub Actions | Free daily scheduling at 9am Paris |
| smtplib | Sends the email via Gmail |

## Project structure

```
daily-tech-briefing/
├── main.py                         # Entry point (--now to send once)
├── agent.py                        # The AI agent (research + writing + HTML)
├── email_sender.py                 # Gmail delivery
├── scheduler.py                    # Local daily scheduler + logging
├── history.py                      # Remembers sent articles (no repeats)
├── data/history.json               # The de-duplication memory
├── .github/workflows/daily-briefing.yml   # Daily run at 9am Paris
├── requirements.txt
└── .env.example
```

---

## Author

Timoté Ballochi — https://github.com/tballochi99
