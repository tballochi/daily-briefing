"""AI agent logic: web research via Tavily + briefing generation via Groq/Llama."""

import os
import json
import logging
from datetime import datetime

from groq import Groq
from tavily import TavilyClient

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
    "You are a tech journalist writing a daily briefing for an AI Product Owner "
    "at CMA CGM, a global shipping leader. Write in clear, professional English. "
    "Be concise and insightful."
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
            search_depth="basic",
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
                "summary": item.get("content", "")[:500],
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

From these results, produce a daily tech briefing. Select the most important and
relevant stories. Return ONLY a valid JSON object (no markdown, no commentary)
with this exact schema:

{{
  "sections": [
    {{
      "title": "🤖 AI & LLMs",
      "news": [
        {{"title": "...", "url": "...", "summary": "2-3 sentence summary in English"}}
      ]
    }},
    {{
      "title": "🚢 Shipping & Logistics Tech",
      "news": [ ... ]
    }},
    {{
      "title": "⚙️ Automation & Product",
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
- Section 1 (AI & LLMs): exactly 3 news.
- Section 2 (Shipping & Logistics Tech): exactly 2 news.
- Section 3 (Automation & Product): exactly 2 news.
- Keep each summary to 2-3 sentences, professional but accessible.
- Always keep the real source URL from the search results for each news item.
- Total content should be roughly 400-600 words.
- The "word of the day" must be a genuine tech term.
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
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    return json.loads(content)


def _news_item_html(item: dict) -> str:
    title = item.get("title", "Untitled")
    url = item.get("url", "#")
    summary = item.get("summary", "")
    return f"""
        <div style="margin-bottom:18px;">
          <a href="{url}" style="color:#0B2C4D;font-weight:bold;font-size:16px;text-decoration:none;">
            {title}
          </a>
          <p style="margin:6px 0 0;color:#333;font-size:14px;line-height:1.5;">{summary}</p>
        </div>"""


def _render_html(briefing: dict, today: str) -> str:
    """Render the briefing dict into the final HTML email."""
    sections_html = ""
    for section in briefing.get("sections", []):
        items_html = "".join(_news_item_html(n) for n in section.get("news", []))
        sections_html += f"""
        <h2 style="color:#0B2C4D;font-size:20px;border-bottom:2px solid #0B2C4D;
                   padding-bottom:6px;margin-top:32px;">{section.get('title', '')}</h2>
        {items_html}"""

    word = briefing.get("word_of_the_day", {})
    quote = briefing.get("quote_of_the_day", {})

    word_html = f"""
        <h2 style="color:#0B2C4D;font-size:20px;margin-top:32px;">📖 Word of the Day</h2>
        <div style="background-color:#E6F0FA;border-left:4px solid #0B2C4D;
                    padding:16px;border-radius:6px;">
          <p style="margin:0;font-size:16px;color:#0B2C4D;">
            <strong>{word.get('word', '')}</strong>
          </p>
          <p style="margin:8px 0 0;font-size:14px;color:#333;">{word.get('definition', '')}</p>
          <p style="margin:8px 0 0;font-size:14px;color:#555;font-style:italic;">
            "{word.get('example', '')}"
          </p>
        </div>"""

    quote_html = f"""
        <h2 style="color:#0B2C4D;font-size:20px;margin-top:32px;">💬 Quote of the Day</h2>
        <div style="background-color:#F0F0F0;border-left:4px solid #999;
                    padding:16px;border-radius:6px;">
          <p style="margin:0;font-size:15px;color:#333;font-style:italic;">
            "{quote.get('text', '')}"
          </p>
          <p style="margin:8px 0 0;font-size:14px;color:#666;text-align:right;">
            — {quote.get('author', '')}
          </p>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:640px;margin:0 auto;background-color:#ffffff;">
    <div style="background-color:#0B2C4D;padding:28px;text-align:center;">
      <h1 style="color:#ffffff;margin:0;font-size:26px;">🚀 Daily Tech Briefing</h1>
      <p style="color:#cfe0f0;margin:8px 0 0;font-size:15px;">{today}</p>
    </div>
    <div style="padding:28px;">
      {sections_html}
      {word_html}
      {quote_html}
    </div>
    <div style="background-color:#0B2C4D;padding:18px;text-align:center;">
      <p style="color:#cfe0f0;margin:0;font-size:13px;">
        Curated by your AI Agent | tballochi99@gmail.com | Stay ahead of the curve 🚀
      </p>
    </div>
  </div>
</body>
</html>"""


def generate_briefing(all_news: dict[str, list[dict]]) -> tuple[str, str]:
    """Generate the email subject and HTML body from raw news.

    Returns (subject, html_body).
    """
    today = datetime.now().strftime("%B %d, %Y")
    subject = f"🚀 Daily Tech Briefing — {today}"

    try:
        briefing = _generate_structured_briefing(all_news, today)
    except Exception as exc:  # noqa: BLE001
        logger.error("Groq generation failed: %s", exc)
        raise

    html_body = _render_html(briefing, today)
    return subject, html_body


def build_briefing() -> tuple[str, str]:
    """Full pipeline: fetch news -> generate briefing. Returns (subject, html)."""
    all_news = fetch_all_news()
    return generate_briefing(all_news)
