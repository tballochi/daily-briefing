"""AI agent for the daily tech briefing.

This is a real tool-using agent: the LLM (Llama 3.3 70B on Groq) drives the flow.
It decides which searches to run, judges the results, skips articles already sent
on previous days, and calls `submit_briefing` when it has gathered enough. The
agent loop is paced to respect the Groq free-tier limit of 12,000 tokens/minute.
"""

import os
import json
import time
import logging
from datetime import datetime
from urllib.parse import urlparse

from groq import Groq
from tavily import TavilyClient

import history

logger = logging.getLogger("briefing.agent")

GROQ_MODEL = "llama-3.3-70b-versatile"

# Free-tier guardrails ------------------------------------------------------
TPM_LIMIT = 12000          # Groq free-tier tokens-per-minute ceiling
TPM_SAFETY = 0.85          # only use 85% of the budget to stay clear of 429s
MAX_STEPS = 12             # hard cap on agent loop iterations
MAX_SEARCHES = 8           # hard cap on Tavily searches per run (quota friendly)

SYSTEM_PROMPT = """You are an autonomous tech-news research agent. Your goal is to \
assemble one high-quality daily tech briefing for a general professional audience.

You work by calling tools:
- Call `search_news` to search the web for recent news. Run several searches to \
cover all the required topics. Read the results, judge their quality, and run \
follow-up searches if the results are weak or off-topic.
- Each search result is tagged `already_sent: true` if it was sent in a previous \
briefing. NEVER include an already_sent article — pick a different, fresher story.
- When (and only when) you have gathered enough strong, non-duplicate stories for \
every section, call `submit_briefing` with the final content.

Required coverage:
- Section "Artificial Intelligence & LLMs": exactly 3 news (GPT, Claude, Gemini, \
agents, LangChain/LangGraph, MCP, etc.).
- Section "Shipping & Logistics": exactly 2 news (maritime, supply chain, logistics tech).
- Section "Automation & Product": exactly 2 news (n8n, Zapier, Make, no-code, \
AI product tools).

Editorial rules for the summaries you submit:
- 2 to 4 sharp sentences per article, pure factual news brief: what was announced \
or happened, with names, numbers and concrete details from the source.
- Do NOT add commentary about who should care, "why it matters for X", personal \
advice, or any angle tailored to a specific reader or company. Just the facts.
- No filler, no generic phrases, no repetition. Vary sentence structure.
- Keep every real source URL.
- The whole briefing must stay under 1000 words. Quality over length.
- Also provide a genuine "word of the day" (tech term + definition + example) and a \
real, verifiable "quote of the day" from a known tech leader.

Be efficient: you have a limited search budget. Do not loop forever."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "Search the web for recent news (last 7 days) on a query. Returns a "
                "list of articles with title, url, snippet, date and an already_sent "
                "flag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The news search query, e.g. 'Claude Gemini new model release'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_briefing",
            "description": "Submit the final briefing once enough non-duplicate news is gathered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "news": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "url": {"type": "string"},
                                            "summary": {"type": "string"},
                                        },
                                        "required": ["title", "url", "summary"],
                                    },
                                },
                            },
                            "required": ["title", "news"],
                        },
                    },
                    "word_of_the_day": {
                        "type": "object",
                        "properties": {
                            "word": {"type": "string"},
                            "definition": {"type": "string"},
                            "example": {"type": "string"},
                        },
                        "required": ["word", "definition", "example"],
                    },
                    "quote_of_the_day": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "author": {"type": "string"},
                        },
                        "required": ["text", "author"],
                    },
                },
                "required": ["sections", "word_of_the_day", "quote_of_the_day"],
            },
        },
    },
]


# --- API clients -----------------------------------------------------------

def _tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return TavilyClient(api_key=api_key)


def _groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)


# --- Tool implementation ---------------------------------------------------

def search_news(query: str, max_results: int = 4) -> list[dict]:
    """Tavily search returning compact, dedup-annotated results for the agent."""
    try:
        client = _tavily_client()
        response = client.search(
            query=query,
            search_depth="advanced",
            topic="news",
            days=7,
            max_results=max_results,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Tavily search failed for '%s': %s", query, exc)
        return []

    results = []
    for item in response.get("results", []):
        url = item.get("url", "")
        title = item.get("title", "Untitled")
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": (item.get("content", "") or "")[:400],
                "date": item.get("published_date", ""),
                "already_sent": history.is_seen(url, title),
            }
        )
    return results


# --- Adaptive pacing (respect Groq free-tier TPM) --------------------------

def _pace(total_tokens: int) -> None:
    """Sleep just enough so token usage stays under the per-minute ceiling.

    If a call consumed `total_tokens`, waiting (total_tokens / budget) * 60 seconds
    before the next call keeps the rolling one-minute sum under the budget.
    """
    budget = TPM_LIMIT * TPM_SAFETY
    sleep_s = min(55.0, (total_tokens / budget) * 60.0)
    if sleep_s > 0:
        logger.info("Pacing: sleeping %.1fs (last call used %d tokens)", sleep_s, total_tokens)
        time.sleep(sleep_s)


# --- The agent loop --------------------------------------------------------

def _norm_url(url: str) -> str:
    try:
        p = urlparse(url or "")
        host = p.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return f"{host}{p.path.rstrip('/').lower()}"
    except Exception:  # noqa: BLE001
        return (url or "").strip().lower()


def _norm_title(title: str) -> str:
    return " ".join((title or "").strip().lower().split())


def _validate_briefing(briefing: dict, collected: list[dict]) -> dict:
    """Ensure every submitted article maps to a real search result.

    The agent composes the final JSON itself, so it can occasionally attach a URL
    that was never returned by a search. We verify each URL against the real
    results: keep verified ones, repair by title match when possible, drop the
    rest so no fabricated link is ever sent.
    """
    by_url = {_norm_url(a["url"]): a for a in collected if a.get("url")}
    by_title = {_norm_title(a["title"]): a for a in collected if a.get("title")}

    for section in briefing.get("sections", []):
        valid = []
        for item in section.get("news", []):
            url = item.get("url", "")
            if _norm_url(url) in by_url:
                valid.append(item)
                continue
            match = by_title.get(_norm_title(item.get("title", "")))
            if match:
                logger.warning("Repaired URL for '%s' -> %s", item.get("title", ""), match["url"])
                item["url"] = match["url"]
                item["title"] = match["title"]
                valid.append(item)
            else:
                logger.warning("Dropped article with unverifiable URL: %r (%s)", item.get("title", ""), url)
        section["news"] = valid
    return briefing


def _assistant_message_to_dict(msg) -> dict:
    out = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


def run_agent(today: str) -> dict:
    """Run the tool-using agent loop and return the final briefing dict."""
    client = _groq_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Today is {today}. Research and assemble today's tech briefing. "
                "Start by searching for the most important recent news in each topic."
            ),
        },
    ]

    searches_used = 0
    collected: list[dict] = []  # every real article the searches returned

    for step in range(MAX_STEPS):
        # On the last allowed step, force the agent to submit what it has.
        force_submit = step == MAX_STEPS - 1 or searches_used >= MAX_SEARCHES
        tool_choice = (
            {"type": "function", "function": {"name": "submit_briefing"}}
            if force_submit
            else "auto"
        )

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice=tool_choice,
            temperature=0.6,
            max_tokens=2000,
        )
        msg = response.choices[0].message
        messages.append(_assistant_message_to_dict(msg))

        if not msg.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue: run another search_news, or call submit_briefing now.",
                }
            )
            _pace(getattr(response.usage, "total_tokens", 4000))
            continue

        # Handle a submit first if present.
        for tc in msg.tool_calls:
            if tc.function.name == "submit_briefing":
                logger.info("Agent submitted briefing after %d search(es)", searches_used)
                return _validate_briefing(json.loads(tc.function.arguments), collected)

        # Otherwise run the searches the agent asked for.
        for tc in msg.tool_calls:
            if tc.function.name != "search_news":
                continue
            try:
                query = json.loads(tc.function.arguments).get("query", "")
            except Exception:  # noqa: BLE001
                query = ""

            if searches_used >= MAX_SEARCHES:
                content = "Search budget exhausted. Call submit_briefing now."
            else:
                searches_used += 1
                results = search_news(query)
                collected.extend(results)
                logger.info("Search %d/%d: '%s' -> %d results", searches_used, MAX_SEARCHES, query, len(results))
                content = json.dumps(results, ensure_ascii=False)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": "search_news",
                    "content": content,
                }
            )

        _pace(getattr(response.usage, "total_tokens", 4000))

    raise RuntimeError("Agent finished without submitting a briefing")


# --- HTML rendering --------------------------------------------------------

def _domain(url: str) -> str:
    """Extract a clean domain label from a URL for the source line."""
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:  # noqa: BLE001
        return ""


def _news_item_html(item: dict) -> str:
    title = item.get("title", "Untitled")
    url = item.get("url", "#")
    summary = item.get("summary", "")
    source = _domain(url)
    return f"""
        <div style="margin:0 0 26px;">
          <a href="{url}" style="color:#111111;text-decoration:none;">
            <h3 style="margin:0 0 8px;font-family:Georgia,'Times New Roman',serif;
                       font-size:20px;font-weight:700;line-height:1.3;color:#111111;">{title}</h3>
          </a>
          <p style="margin:0 0 8px;font-family:Georgia,'Times New Roman',serif;font-size:15px;
                    line-height:1.65;color:#2b2b2b;text-align:justify;">{summary}</p>
          <a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:11px;
                    letter-spacing:1px;text-transform:uppercase;color:#0B2C4D;
                    text-decoration:none;font-weight:bold;">Source — {source} &rsaquo;</a>
        </div>"""


def _section_html(section: dict) -> str:
    title = section.get("title", "")
    items_html = "".join(_news_item_html(n) for n in section.get("news", []))
    return f"""
        <div style="margin-top:34px;">
          <div style="border-top:2px solid #111111;border-bottom:1px solid #111111;
                      padding:6px 0;margin-bottom:20px;">
            <span style="font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:bold;
                         letter-spacing:2px;text-transform:uppercase;color:#111111;">{title}</span>
          </div>
          {items_html}
        </div>"""


def _render_html(briefing: dict, today: str) -> str:
    """Render the briefing dict into a newspaper-style HTML email."""
    sections_html = "".join(_section_html(s) for s in briefing.get("sections", []))

    word = briefing.get("word_of_the_day", {})
    quote = briefing.get("quote_of_the_day", {})

    word_html = f"""
        <div style="margin-top:34px;border:1px solid #c9c2b4;background-color:#f6f3ec;padding:20px;">
          <div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;
                      letter-spacing:2px;text-transform:uppercase;color:#0B2C4D;margin-bottom:10px;">
            Word of the Day
          </div>
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:22px;font-weight:700;
                      color:#111111;margin-bottom:6px;">{word.get('word', '')}</div>
          <p style="margin:0 0 8px;font-family:Georgia,'Times New Roman',serif;font-size:15px;
                    line-height:1.6;color:#2b2b2b;">{word.get('definition', '')}</p>
          <p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:14px;
                    line-height:1.6;color:#555555;font-style:italic;">&ldquo;{word.get('example', '')}&rdquo;</p>
        </div>"""

    quote_html = f"""
        <div style="margin-top:28px;border-top:1px solid #ddd;border-bottom:1px solid #ddd;
                    padding:24px 16px;text-align:center;">
          <p style="margin:0 0 10px;font-family:Georgia,'Times New Roman',serif;font-size:19px;
                    line-height:1.5;color:#111111;font-style:italic;">&ldquo;{quote.get('text', '')}&rdquo;</p>
          <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;
                    letter-spacing:1px;text-transform:uppercase;color:#777777;">— {quote.get('author', '')}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#e9e6df;">
  <div style="max-width:640px;margin:0 auto;background-color:#ffffff;
              border-left:1px solid #ddd;border-right:1px solid #ddd;">
    <div style="padding:30px 36px 18px;text-align:center;border-bottom:4px double #111111;">
      <div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:3px;
                  text-transform:uppercase;color:#0B2C4D;margin-bottom:8px;">Curated by your AI Agent</div>
      <h1 style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:38px;
                 font-weight:700;letter-spacing:1px;color:#111111;line-height:1.1;">Daily Tech Briefing</h1>
      <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;letter-spacing:2px;
                  text-transform:uppercase;color:#555555;margin-top:10px;">{today}</div>
    </div>
    <div style="padding:6px 36px 30px;">
      {sections_html}
      {word_html}
      {quote_html}
    </div>
    <div style="padding:20px 36px;border-top:2px solid #111111;text-align:center;">
      <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:1px;
                color:#888888;">Curated by your AI Agent &nbsp;|&nbsp; tballochi99@gmail.com &nbsp;|&nbsp; Stay ahead of the curve</p>
    </div>
  </div>
</body>
</html>"""


# --- Public pipeline -------------------------------------------------------

def build_briefing() -> tuple[str, str, list[dict]]:
    """Run the agent and render the email.

    Returns (subject, html, chosen). The caller must call
    history.record_seen(chosen) only AFTER the email was sent successfully.
    """
    today = datetime.now().strftime("%B %d, %Y")
    subject = f"Daily Tech Briefing — {today}"

    briefing = run_agent(today)
    html_body = _render_html(briefing, today)
    chosen = [
        {"url": n.get("url", ""), "title": n.get("title", "")}
        for section in briefing.get("sections", [])
        for n in section.get("news", [])
    ]
    return subject, html_body, chosen
