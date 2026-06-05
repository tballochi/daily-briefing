# Daily Briefing Agent

A small **AI agent that emails you a personalised news briefing every morning** — on the
topics *you* choose, written from real, freshly-searched articles. It runs **100% free**,
needs **no server** (nothing has to stay on), and delivers reliably **before 10am**.

Built with **Groq (Llama 3.3 70B)** for the AI brain and **Tavily** for live web search.

> Out of the box it's tuned for tech (AI, shipping/logistics, automation), but every
> topic is configurable — point it at finance, sports, climate, your industry, whatever
> you want to wake up informed about.

---

## The concept

Every morning, an autonomous agent:

1. **Researches** — runs several live web searches across *your* topics, judges the
   results, and skips anything already sent on a previous day.
2. **Writes** — summarises the chosen stories from their real source text (no
   hallucinated facts, no fabricated links).
3. **Delivers** — emails you a clean, newspaper-style digest.

It's a real tool-using agent, not a fixed script: it decides what to search and what's
worth keeping. The whole run fits inside the **Groq + Tavily free tiers**, executes on
**free GitHub Actions** minutes, and is triggered on time by a **free external pinger**.
No infrastructure, no cost.

### What lands in your inbox

A newspaper-style email with:

- **N top stories** (you pick how many) across your chosen topics. Optionally, one slot
  is reserved for a **focus theme** you never want to miss.
- For each: a short factual summary, the **publication date**, and a link to the source.
- **Word of the day** — a real term with a definition and an example.
- **Quote of the day** — from a well-known figure.

No repeats: once a story is sent, it never comes back.

---

## Initialize it (start to finish)

### 1. Clone & install

```bash
git clone https://github.com/<you>/daily-briefing.git
cd daily-briefing
pip install -r requirements.txt
```

### 2. Make it yours — `config.yaml`

This is the **one file** you edit to define the briefing. No code, no secrets:

```yaml
title: Daily Briefing        # shown in the email subject + header
num_articles: 3              # how many stories per morning

topics:                      # what the agent researches (free text)
  - AI & LLMs (GPT, Claude, agents, MCP)
  - automation & no-code (n8n, Zapier, Make)
  - dev tools & open source

focus:                       # OPTIONAL — a story that's ALWAYS included
  label: shipping / maritime / logistics
  priority_query: CMA CGM    # searched first; preferred when there's fresh news
  keywords: [cma cgm, shipping, maritime, container, freight]
```

- **`topics`** — reword to your interests; the agent turns them into searches.
- **`focus`** — guarantees one story on a niche you care about. Set `priority_query` to a
  specific subject to prefer it, or leave it empty (`""`) to just guarantee the theme.
  **Don't want a guaranteed story? Delete the whole `focus:` block.**
- No `config.yaml` at all? The agent falls back to sensible defaults, so it always runs.

### 3. Get 3 free API keys

| Key | Where | Free tier |
|-----|-------|-----------|
| Groq | https://console.groq.com/keys | yes |
| Tavily | https://app.tavily.com | yes (1000 searches/month) |
| Gmail App Password | https://myaccount.google.com/apppasswords | needs 2FA enabled |

> The Gmail App Password is a 16-character code — **not** your normal Gmail password.

### 4. Choose how to run it

**Option A — locally** (good for a first test):

```bash
cp .env.example .env      # then fill in the 5 values below
python main.py --now      # build & send one briefing right now
python main.py            # or start the local scheduler (daily at 09:00 Paris)
```

Your `.env` holds the secrets:

```
GROQ_API_KEY=...
TAVILY_API_KEY=...
GMAIL_ADDRESS=...            # the Gmail that sends the email
GMAIL_APP_PASSWORD=...       # the 16-char app password
RECIPIENT_EMAIL=...          # where the briefing is delivered
```

**Option B — automatically on GitHub (recommended, nothing stays on):**

1. Push the repo to your GitHub account.
2. **Settings → Secrets and variables → Actions** → add the same 5 values as **secrets**:
   `GROQ_API_KEY`, `TAVILY_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
   `RECIPIENT_EMAIL`.
3. Test it immediately: **Actions → *Daily Briefing* → Run workflow** (tick `force` to
   send even if today's already went out).

The workflow is **idempotent** — it sends at most one briefing per day and commits the
de-duplication history (`data/history.json`) back to the repo after each send, so
multiple triggers can never double-send.

### 5. Make it punctual — a free external pinger

GitHub's own `schedule:` cron is unreliable on low-activity repos: it drops most triggers
and can fire hours late, so a fixed "before 10am" delivery isn't guaranteed by it alone.
The fix (still 100% free) is a tiny external cron that calls GitHub at a fixed time;
GitHub's own cron stays on as a **best-effort backup**.

**a) Create a GitHub token** — https://github.com/settings/personal-access-tokens/new
   - Repository access: *Only select repositories* → this repo
   - Permissions → **Actions: Read and write**
   - Generate and copy the `github_pat_...` value (keep it secret).

**b) Create a free job on [cron-job.org](https://cron-job.org)** that runs daily at
   **~08:00 Europe/Paris** with:
   - **Method**: `POST`
   - **URL**: `https://api.github.com/repos/<you>/daily-briefing/actions/workflows/daily-briefing.yml/dispatches`
   - **Body**: `{"ref":"main"}`
   - **Headers**:
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <your github_pat_...>`
     - `X-GitHub-Api-Version: 2022-11-28`

A successful call returns **HTTP 204**. The pinger fires *without* forcing, so it still
passes the morning-window + once-a-day guard — it can never double-send.

> Renamed the repo later? Update the `<you>/daily-briefing` part of this URL on
> cron-job.org. GitHub redirects GETs but not reliably POSTs, so fix it by hand.

---

## Reliability notes

- **Window guard** — the job only sends between **06:00–11:00 Europe/Paris**; outside that
  it no-ops, so a stray trigger never emails you at night.
- **Resilient search** — Tavily calls are throttled and retried with backoff, so a
  transient blip or free-tier rate limit can't sink the morning's briefing.
- **Failure alert** — if the agent genuinely finds nothing valid, it emails you a short
  "couldn't send today" note instead of silently failing.

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
| PyYAML | Reads your `config.yaml` |

## Project structure

```
daily-briefing/
├── config.yaml                     # Your preferences: title, topics, focus
├── config.py                       # Loads/validates config.yaml (with defaults)
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

Timoté Ballochi — https://github.com/tballochi
