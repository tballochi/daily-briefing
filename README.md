# Daily Tech Briefing Agent

An AI agent that emails you the **3 most important tech stories of the day**, every
morning (around 8am, Europe/Paris). Free to run, no server to maintain.

Built with **Groq (Llama 3.3 70B)** for the AI and **Tavily** for live web search.

---

## What you get every morning

A clean, newspaper-style email with:

- **3 top tech stories** — across the topics *you* choose in `config.yaml` (defaults:
  AI & LLMs, shipping/logistics, automation). You can also pin a theme that's always
  included (e.g. **shipping**, with CMA CGM preferred when there's relevant news).
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

## Make it your own

All personalisation lives in **`config.yaml`** — no code to touch:

```yaml
num_articles: 3
topics:
  - AI & LLMs (GPT, Claude, agents, MCP)
  - automation & no-code (n8n, Zapier, Make)
  - dev tools & open source
focus:                       # optional: a story that's ALWAYS included
  label: shipping / maritime / logistics
  priority_query: CMA CGM    # searched first; preferred when there's fresh news
  keywords: [cma cgm, shipping, maritime, container, freight]
```

Reword the `topics` to your interests, change `num_articles`, and either set your own
`focus` theme or delete the whole `focus:` block if you don't want a guaranteed story.
Edit, commit, and the next run uses it. (No `config.yaml`? It falls back to sensible
defaults so it always runs.)

---

## Setup

### 1. Get 3 free API keys

| Key | Where | Free |
|-----|-------|------|
| Groq | https://console.groq.com/keys | yes |
| Tavily | https://app.tavily.com | yes (1000 searches/month) |
| Gmail App Password | https://myaccount.google.com/apppasswords | needs 2FA enabled |

> The Gmail App Password is a 16-character code — **not** your normal password.

### 2. Run it daily for free with GitHub Actions

No computer needs to stay on. GitHub Actions does the work; the secrets below let it run.

1. Push this repo to your GitHub account.
2. Go to **Settings → Secrets and variables → Actions** and add these 5 secrets:

   | Secret | Value |
   |--------|-------|
   | `GROQ_API_KEY` | your Groq key |
   | `TAVILY_API_KEY` | your Tavily key |
   | `GMAIL_ADDRESS` | the Gmail address that sends the email |
   | `GMAIL_APP_PASSWORD` | your 16-char Gmail App Password |
   | `RECIPIENT_EMAIL` | where the briefing is delivered |

The workflow remembers past articles automatically (it commits `data/history.json` back
to the repo after each send) and is **idempotent**: it sends at most one briefing per
day, so multiple triggers never double-send.

**Test it now:** Actions → *Daily Tech Briefing* → **Run workflow** (tick `force` to send
even if today's was already sent).

### 3. Trigger it on time with a free external pinger

GitHub's own `schedule:` cron is unreliable on low-activity repos — it drops most
triggers and can fire hours late, so a fixed "before 10am" delivery isn't guaranteed by
it alone. The fix (still 100% free) is a tiny external cron that calls GitHub at a fixed
time. GitHub's cron stays enabled as a **best-effort backup**.

**a) Create a GitHub token** — https://github.com/settings/personal-access-tokens/new
   - Repository access: *Only select repositories* → this repo
   - Permissions → **Actions: Read and write**
   - Generate and copy the `github_pat_...` value.

**b) Create a free job on [cron-job.org](https://cron-job.org)** that runs daily at
   **08:00 Europe/Paris** with:
   - **Method**: `POST`
   - **URL**: `https://api.github.com/repos/<you>/daily-tech-briefing/actions/workflows/daily-briefing.yml/dispatches`
   - **Body**: `{"ref":"main"}`
   - **Headers**:
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <your github_pat_...>`
     - `X-GitHub-Api-Version: 2022-11-28`

A successful call returns **HTTP 204**. The pinger fires *without* forcing, so it still
passes the morning-window + once-a-day guard and can never double-send.

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
| GitHub Actions | Free runtime for the daily job |
| cron-job.org | Free external pinger that triggers it on time (~8am Paris) |
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
├── .github/workflows/daily-briefing.yml   # Morning run: window guard + idempotency
├── requirements.txt
└── .env.example
```

---

## Author

Timoté Ballochi — https://github.com/tballochi99
