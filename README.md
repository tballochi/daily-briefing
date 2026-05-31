# Daily Tech Briefing Agent 🚀

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

## Deploy for free on Railway

```bash
railway up
```

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

Timoté Ballochi — Master Data & AI @ Epitech
Currently: AI Product Owner Apprentice @ CMA CGM
Portfolio: https://tbal.vercel.app
GitHub: https://github.com/tballochi99

---
*Staying ahead of the curve, one briefing at a time.*
