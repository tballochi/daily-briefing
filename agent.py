"""AI agent logic: web research via Tavily + briefing generation via Groq/Llama."""

import os
import json
import logging
from datetime import datetime
from urllib.parse import urlparse

from groq import Groq
from tavily import TavilyClient

import history

logger = logging.getLogger("briefing.agent")

# Topics to research every morning. Each entry maps a section to its queries.
TOPICS = {
    "AI & LLMs": [
        "latest AI agents LLM news GPT Claude Gemini",
        "LangChain LangGraph MCP Model Context Protocol news",
    ],
    "Shipping & Logistics Tech": [
        "CMA CGM maritime shipping technology AI news",
        "supply chain logistics automation AI news",
    ],
    "Automation & Product": [
        "n8n Zapier Make no-code automation news",
        "AI product management tools news",
    ],
}

GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a technology journalist writing a concise daily tech briefing for a "
    "general professional audience. Write in clear, professional English. Stick to "
    "the facts, be concise and insightful. Do NOT address or tailor the content to "
    "any specific person or company, and do not give personal advice."
)


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


def fetch_news(topic: str, max_results: int = 3) -> list[dict]:
    """Search the 3 latest news for a topic using Tavily.

    Returns a list of dicts: {title, summary, source, date}.
    """
    try:
        client = _tavily_client()
        response = client.search(
            query=topic,
            search_depth="advanced",
            topic="news",
            days=7,
            max_results=max_results,
        )
    except Exception as exc:  # noqa: BLE001 - we want to keep going on failure
        logger.error("Tavily search failed for '%s': %s", topic, exc)
        return []

    results = []
    for item in response.get("results", []):
        results.append(
            {
                "title": item.get("title", "Untitled"),
                "summary": item.get("content", "")[:800],
                "source": item.get("url", ""),
                "date": item.get("published_date", ""),
            }
        )
    return results


def fetch_all_news() -> dict[str, list[dict]]:
    """Fetch news for every configured section."""
    all_news: dict[str, list[dict]] = {}
    for section, queries in TOPICS.items():
        section_news: list[dict] = []
        for query in queries:
            section_news.extend(fetch_news(query, max_results=3))
        all_news[section] = section_news
        logger.info("Fetched %d items for section '%s'", len(section_news), section)
    return all_news


def _build_user_prompt(all_news: dict[str, list[dict]], today: str) -> str:
    """Build the prompt that asks the model to emit structured JSON."""
    news_blob = json.dumps(all_news, ensure_ascii=False, indent=2)
    return f"""Today is {today}.

Below are raw web search results grouped by section (JSON):

{news_blob}

From these results, produce a sharp, professional daily tech briefing written like
a quality newspaper. Select only the most important, relevant and recent stories —
prioritise concrete announcements, product launches, funding, partnerships and
real-world deployments over vague opinion pieces. Return ONLY a valid JSON object
(no markdown, no commentary) with this exact schema:

{{
  "sections": [
    {{
      "title": "Artificial Intelligence & LLMs",
      "news": [
        {{"title": "...", "url": "...", "summary": "concise, insightful summary in English"}}
      ]
    }},
    {{
      "title": "Shipping & Logistics",
      "news": [ ... ]
    }},
    {{
      "title": "Automation & Product",
      "news": [ ... ]
    }}
  ],
  "word_of_the_day": {{
    "word": "...",
    "definition": "clear English definition",
    "example": "an example sentence using the word"
  }},
  "quote_of_the_day": {{
    "text": "an inspirational quote from a tech leader",
    "author": "the leader's name"
  }}
}}

Rules:
- Section 1 (Artificial Intelligence & LLMs): exactly 3 news.
- Section 2 (Shipping & Logistics): exactly 2 news.
- Section 3 (Automation & Product): exactly 2 news.
- Each summary is 2 to 4 sharp sentences that simply report the facts: what was
  announced or happened, with the names, numbers and concrete details from the
  source. Write it like a neutral news brief.
- Do NOT add commentary about who should care, "why it matters for X", personal
  advice, or any angle tailored to a specific reader or company. Just the facts.
- Quality over length. ABSOLUTELY NO filler, no generic phrases such as "can
  improve efficiency and accuracy", no repetition of the same idea across items.
  Every sentence must carry real information from the search results.
- Vary your sentence structure across items — they must not all read the same.
- Always keep the real source URL from the search results for each news item.
- The WHOLE briefing must stay UNDER 1000 words. A tight 400-700 word briefing that
  is genuinely informative is far better than a padded one. Do not inflate.
- The "word of the day" must be a genuine tech term, with a 1-2 sentence definition
  and a realistic example sentence.
- The quote must be a real, verifiable quote from a known tech leader.
"""


def _generate_structured_briefing(all_news: dict[str, list[dict]], today: str) -> dict:
    """Call Groq/Llama and parse the structured briefing JSON."""
    client = _groq_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(all_news, today)},
        ],
        temperature=0.6,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    return json.loads(content)


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


def generate_briefing(all_news: dict[str, list[dict]]) -> tuple[str, str, list[dict]]:
    """Generate the email from raw news.

    Returns (subject, html_body, chosen) where `chosen` is the list of
    {"url", "title"} dicts actually included, for de-duplication bookkeeping.
    """
    today = datetime.now().strftime("%B %d, %Y")
    subject = f"Daily Tech Briefing — {today}"

    try:
        briefing = _generate_structured_briefing(all_news, today)
    except Exception as exc:  # noqa: BLE001
        logger.error("Groq generation failed: %s", exc)
        raise

    html_body = _render_html(briefing, today)
    chosen = [
        {"url": n.get("url", ""), "title": n.get("title", "")}
        for section in briefing.get("sections", [])
        for n in section.get("news", [])
    ]
    return subject, html_body, chosen


def build_briefing() -> tuple[str, str, list[dict]]:
    """Full pipeline: fetch news -> drop already-seen articles -> generate.

    Returns (subject, html, chosen). The caller should call
    history.record_seen(chosen) only AFTER the email was sent successfully.
    """
    all_news = fetch_all_news()
    all_news = history.filter_unseen(all_news)
    return generate_briefing(all_news)
