"""AI agent for the daily tech briefing.

Two phases, both driven by Llama 3.3 70B on Groq:

1. Research agent (tool-using loop): the LLM decides which searches to run, judges
   the results, skips articles already sent on previous days, avoids index/nav
   pages, and selects the 3 most important distinct stories.
2. Synthesis: a focused call writes the factual summaries grounded ONLY in the real
   source snippets, plus a word of the day and a quote of the day.

Separating research from writing keeps summaries real and source-grounded, and the
final URLs come from actual search results (the LLM never fabricates a link). The
loop is paced to respect the Groq free-tier limit of 12,000 tokens/minute.
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
MAX_STEPS = 10             # hard cap on agent loop iterations
MAX_SEARCHES = 6           # hard cap on Tavily searches per run (quota friendly)
TARGET_ARTICLES = 3        # how many stories the briefing contains

# Keywords used to guarantee at least one shipping/maritime/logistics story.
SHIPPING_KEYWORDS = (
    "cma cgm", "shipping", "maritime", "port", "container", "freight", "vessel",
    "supply chain", "logistics", "cargo", "ocean carrier", "seafreight", "msc",
    "maersk", "hapag", "boxship", "terminal", "harbor", "harbour",
)

SYSTEM_PROMPT = """You are an autonomous tech-news research agent. Your job is to \
find the 3 most important and recent technology stories of the day for a general \
professional audience, then hand them off for writing.

How you work:
- Call `search_news` to search the web. Run a few searches to cover the tech \
landscape: AI & LLMs (GPT, Claude, Gemini, agents, LangChain/LangGraph, MCP), \
shipping & logistics tech, and automation & product (n8n, Zapier, Make, no-code). \
Read the results, judge their quality, and run follow-up searches if needed.
- Pick SUBSTANTIVE individual articles only. Reject index pages, news round-ups, \
homepages or vague titles like "New Ship News" — they are not real stories.
- Each result is tagged `already_sent: true` if it was sent in a previous briefing. \
NEVER pick an already_sent article.
- MANDATORY: exactly ONE of the 3 stories must be about shipping / maritime / \
logistics. Search specifically for "CMA CGM" first — if there is a relevant, recent \
CMA CGM story, pick it. If not, pick another strong maritime/shipping/logistics \
story instead. Always run a CMA CGM search and a general maritime/shipping search.
- When you have found the 3 strongest, distinct, non-duplicate stories (one of them \
shipping), call `finalize_selection` with their exact URLs copied from the results.

You only research and select. You do NOT write summaries — that happens later."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "Search the web for recent news (last 7 days) on a query. Returns a "
                "list of articles with title, url, snippet, date and an already_sent flag."
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
            "name": "finalize_selection",
            "description": "Submit the 3 chosen articles once strong, non-duplicate stories are found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exactly 3 URLs, copied verbatim from the search results.",
                    }
                },
                "required": ["urls"],
            },
        },
    },
]

SYNTHESIS_SYSTEM = (
    "You are a technology journalist. You write concise, factual news-brief summaries "
    "grounded ONLY in the source snippet provided for each article. Professional, "
    "neutral tone. No filler, no opinion, no advice, no targeting of any reader."
)


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

def search_news(query: str, max_results: int = 5) -> list[dict]:
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
                "snippet": (item.get("content", "") or "")[:500],
                "date": item.get("published_date", ""),
                "already_sent": history.is_seen(url, title),
            }
        )
    return results


# --- Adaptive pacing (respect Groq free-tier TPM) --------------------------

def _pace(total_tokens: int) -> None:
    """Sleep just enough so token usage stays under the per-minute ceiling."""
    budget = TPM_LIMIT * TPM_SAFETY
    sleep_s = min(55.0, (total_tokens / budget) * 60.0)
    if sleep_s > 0:
        logger.info("Pacing: sleeping %.1fs (last call used %d tokens)", sleep_s, total_tokens)
        time.sleep(sleep_s)


# --- Helpers ---------------------------------------------------------------

def _norm_url(url: str) -> str:
    try:
        p = urlparse(url or "")
        host = p.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return f"{host}{p.path.rstrip('/').lower()}"
    except Exception:  # noqa: BLE001
        return (url or "").strip().lower()


def _create_completion(client, messages: list, tool_choice, max_retries: int = 4):
    """Call Groq tool-use, retrying the flaky 'tool_use_failed' parse error.

    Llama occasionally emits a malformed function-call string that Groq rejects
    with a 400 tool_use_failed. A simple retry almost always recovers.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice=tool_choice,
                temperature=0.5,
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if "tool_use_failed" in str(exc) or "Failed to call a function" in str(exc):
                logger.warning("Groq tool-call parse failed (attempt %d/%d), retrying", attempt + 1, max_retries)
                time.sleep(2)
                continue
            raise
    raise last_exc


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


def _resolve_selection(urls: list[str], collected: list[dict]) -> list[dict]:
    """Map the agent's chosen URLs to real articles, validate, and backfill to 3.

    Only URLs that actually appeared in search results are kept (no fabricated
    links). If fewer than TARGET_ARTICLES survive, fill from the best remaining
    real, non-duplicate articles so the briefing always has 3 stories.
    """
    by_url = {_norm_url(a["url"]): a for a in collected if a.get("url")}

    chosen: list[dict] = []
    used: set[str] = set()
    for url in urls:
        key = _norm_url(url)
        article = by_url.get(key)
        if article and key not in used and not article.get("already_sent"):
            chosen.append(article)
            used.add(key)
        elif not article:
            logger.warning("Dropped fabricated/unknown URL from selection: %s", url)

    if len(chosen) < TARGET_ARTICLES:
        for article in collected:
            key = _norm_url(article.get("url", ""))
            if key in used or article.get("already_sent"):
                continue
            if len(article.get("title", "")) < 15:  # skip nav/index-like entries
                continue
            chosen.append(article)
            used.add(key)
            if len(chosen) >= TARGET_ARTICLES:
                break

    return chosen[:TARGET_ARTICLES]


def _shipping_score(article: dict) -> int:
    """2 if the article is about CMA CGM, 1 if shipping/maritime/logistics, else 0."""
    text = f"{article.get('title', '')} {article.get('snippet', '')}".lower()
    if "cma cgm" in text:
        return 2
    return 1 if any(kw in text for kw in SHIPPING_KEYWORDS) else 0


def _ensure_shipping_news(selected: list[dict], collected: list[dict]) -> list[dict]:
    """Guarantee exactly one shipping story among the selection (prefer CMA CGM).

    If the agent's pick already contains a shipping story, leave it. Otherwise find
    the best shipping candidate (CMA CGM first) from the gathered results, or run a
    dedicated search, and substitute it for the least-prioritised article.
    """
    if any(_shipping_score(a) >= 1 for a in selected):
        return selected

    used = {_norm_url(a.get("url", "")) for a in selected}

    def _eligible(a: dict) -> bool:
        return (
            _norm_url(a.get("url", "")) not in used
            and not a.get("already_sent")
            and len(a.get("title", "")) >= 15
            and _shipping_score(a) >= 1
        )

    candidates = [a for a in collected if _eligible(a)]
    if not candidates:
        for query in ("CMA CGM news", "maritime shipping logistics supply chain news"):
            for a in search_news(query):
                if _eligible(a):
                    candidates.append(a)
            if candidates:
                break

    if not candidates:
        logger.warning("Could not find a shipping story to guarantee coverage")
        return selected

    candidates.sort(key=_shipping_score, reverse=True)  # CMA CGM (2) before generic (1)
    best = candidates[0]
    logger.info("Injecting shipping story for guaranteed coverage: %s", best.get("title", ""))
    selected[-1] = best
    return selected


# --- The research agent loop -----------------------------------------------

def run_agent_selection(today: str) -> tuple[list[dict], list[dict]]:
    """Run the tool-using research loop.

    Returns (selected, collected): the chosen real articles and every article seen
    across all searches (used to guarantee shipping coverage afterwards).
    """
    client = _groq_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Today is {today}. Find the 3 most important recent tech stories, "
                "one of which must be about shipping/maritime/logistics (search CMA CGM "
                "first). Start searching now."
            ),
        },
    ]

    searches_used = 0
    collected: list[dict] = []

    for step in range(MAX_STEPS):
        force_final = step == MAX_STEPS - 1 or searches_used >= MAX_SEARCHES
        tool_choice = (
            {"type": "function", "function": {"name": "finalize_selection"}}
            if force_final
            else "auto"
        )

        response = _create_completion(client, messages, tool_choice)
        msg = response.choices[0].message
        messages.append(_assistant_message_to_dict(msg))

        if not msg.tool_calls:
            messages.append(
                {"role": "user", "content": "Continue: search_news again or call finalize_selection."}
            )
            _pace(getattr(response.usage, "total_tokens", 3000))
            continue

        for tc in msg.tool_calls:
            if tc.function.name == "finalize_selection":
                try:
                    urls = json.loads(tc.function.arguments).get("urls", [])
                except Exception:  # noqa: BLE001
                    urls = []
                logger.info("Agent finalized selection after %d search(es)", searches_used)
                return _resolve_selection(urls, collected), collected

        for tc in msg.tool_calls:
            if tc.function.name != "search_news":
                continue
            try:
                query = json.loads(tc.function.arguments).get("query", "")
            except Exception:  # noqa: BLE001
                query = ""

            if searches_used >= MAX_SEARCHES:
                content = "Search budget exhausted. Call finalize_selection now."
            else:
                searches_used += 1
                results = search_news(query)
                collected.extend(results)
                logger.info("Search %d/%d: '%s' -> %d results", searches_used, MAX_SEARCHES, query, len(results))
                content = json.dumps(results, ensure_ascii=False)

            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "name": "search_news", "content": content}
            )

        _pace(getattr(response.usage, "total_tokens", 3000))

    raise RuntimeError("Agent finished without finalizing a selection")


# --- Phase 2: write the briefing from the selected real articles -----------

def synthesize_briefing(selected: list[dict], today: str) -> dict:
    """Write factual summaries (grounded in snippets) + word & quote of the day."""
    numbered = "\n\n".join(
        f"[{i}] TITLE: {a.get('title', '')}\nSNIPPET: {a.get('snippet', '')}"
        for i, a in enumerate(selected, start=1)
    )
    user = f"""Today is {today}. Here are {len(selected)} selected articles:

{numbered}

For each article, write a 2-4 sentence factual news-brief summary about the story in
its TITLE, based ONLY on its snippet. Focus strictly on that one story: IGNORE any
unrelated headlines, "recent news also includes...", or round-up items that may
appear in the snippet. Do not invent facts beyond the snippet; if it is thin,
summarise only what is clearly about the title's story. No filler, no opinion, no
"why it matters", vary the phrasing.

Then add:
- "word_of_the_day": a genuine, specific tech term (NOT something as generic as
  "AI"; pick e.g. inference, embedding, idempotency, vector database, fine-tuning,
  webhook, latency, quantization...) with a one-sentence definition and a natural
  example sentence.
- "quote_of_the_day": a real, verifiable quote from a well-known tech leader, with
  the author's name.

Return ONLY JSON with this schema:
{{
  "summaries": {{ "1": "...", "2": "...", "3": "..." }},
  "word_of_the_day": {{ "word": "...", "definition": "...", "example": "..." }},
  "quote_of_the_day": {{ "text": "...", "author": "..." }}
}}"""

    client = _groq_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.5,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)

    summaries = data.get("summaries", {})
    news = []
    for i, article in enumerate(selected, start=1):
        news.append(
            {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "date": article.get("date", ""),
                "summary": summaries.get(str(i), "") or article.get("snippet", "")[:300],
            }
        )

    return {
        "sections": [{"title": "Top Tech News", "news": news}],
        "word_of_the_day": data.get("word_of_the_day", {}),
        "quote_of_the_day": data.get("quote_of_the_day", {}),
    }


# --- HTML rendering --------------------------------------------------------

def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:  # noqa: BLE001
        return ""


def _format_date(raw: str) -> str:
    """Format a publication date as 'May 28, 2026'; fall back to the raw value."""
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(raw, fmt).strftime("%B %d, %Y")
        except ValueError:
            continue
    return raw[:24]


def _news_item_html(item: dict) -> str:
    title = item.get("title", "Untitled")
    url = item.get("url", "#")
    summary = item.get("summary", "")
    source = _domain(url)
    pub_date = _format_date(item.get("date", ""))
    meta = f"Source — {source}"
    if pub_date:
        meta += f" &nbsp;&middot;&nbsp; {pub_date}"
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
                    text-decoration:none;font-weight:bold;">{meta} &rsaquo;</a>
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
    """Run the agent, write the briefing, render the email.

    Returns (subject, html, chosen). The caller must call
    history.record_seen(chosen) only AFTER the email was sent successfully.
    """
    today = datetime.now().strftime("%B %d, %Y")
    subject = f"Daily Tech Briefing — {today}"

    selected, collected = run_agent_selection(today)
    selected = _ensure_shipping_news(selected, collected)
    if not selected:
        raise RuntimeError("Agent selected no valid articles")

    briefing = synthesize_briefing(selected, today)
    html_body = _render_html(briefing, today)
    chosen = [{"url": a.get("url", ""), "title": a.get("title", "")} for a in selected]
    return subject, html_body, chosen
