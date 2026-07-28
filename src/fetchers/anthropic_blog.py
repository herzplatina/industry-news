"""Fetch recent Anthropic company-blog posts via the Anthropic web search tool.

Anthropic's news blog has no first-party RSS feed we can rely on here, so we ask
Claude (with the built-in web search tool) to find posts published on
anthropic.com within the time window and return them as structured JSON. Results
are deduplicated against the shared checkpoint links so a post already surfaced
by the Anthropic RSS feed — or in a previous day's email — is not repeated.
"""

import json
import logging
import re
from urllib.parse import urlsplit

import anthropic
from dotenv import load_dotenv

from src.summarizer import MODEL

logger = logging.getLogger(__name__)

SOURCE_LABEL = "Anthropic Blog"
ALLOWED_DOMAIN = "anthropic.com"
WEB_SEARCH_MAX_USES = 5
SEARCH_MAX_TOKENS = 2048

_SEARCH_PROMPT = (
    "Search anthropic.com for blog and news posts published by Anthropic in the "
    "last {hours} hours (announcements, product updates, research, engineering, "
    "and policy posts on anthropic.com/news and related paths).\n\n"
    "Return ONLY a JSON array (no prose, no markdown fences) where each element is "
    'an object with keys: "title", "url", "date" (ISO 8601 or empty string), and '
    '"summary" (one sentence). Only include posts whose URL is on anthropic.com. '
    "If there are no new posts, return an empty array []."
)


def _build_web_search_tool() -> dict:
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": WEB_SEARCH_MAX_USES,
        "allowed_domains": [ALLOWED_DOMAIN],
    }


def _extract_response_text(content_blocks) -> str:
    """Concatenate the text blocks of a Messages API response."""
    return "\n".join(
        getattr(b, "text", "")
        for b in content_blocks
        if getattr(b, "type", "") == "text"
    ).strip()


def _parse_search_results(text: str) -> list[dict]:
    """Extract a JSON array of post objects from the model's response text."""
    if not text:
        return []
    # Strip a ```json ... ``` fence if the model added one.
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # Fall back to the first bracketed array if there is surrounding prose.
    if not candidate.lstrip().startswith("["):
        bracketed = re.search(r"\[.*\]", candidate, re.DOTALL)
        candidate = bracketed.group(0) if bracketed else candidate
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Could not parse Anthropic blog search results as JSON")
        return []
    return data if isinstance(data, list) else []


def _normalize_link(url: str) -> str:
    """Drop the query/fragment and any trailing slash for stable dedup keys."""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def _is_anthropic_url(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return host == ALLOWED_DOMAIN or host.endswith("." + ALLOWED_DOMAIN)


def _to_articles(
    results: list[dict],
    prev_links: set[str],
) -> tuple[list[dict], list[str]]:
    """Convert parsed search results into article dicts, deduplicating links."""
    articles: list[dict] = []
    new_links: list[str] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        link = _normalize_link(str(item.get("url", "")))
        if not link or not _is_anthropic_url(link):
            continue
        if link in prev_links or link in seen:
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        seen.add(link)
        new_links.append(link)
        articles.append(
            {
                "title": title,
                "link": link,
                "summary": str(item.get("summary", "")).strip(),
                "source_label": SOURCE_LABEL,
                "published": str(item.get("date", "")).strip() or "unknown",
                "category": "",
            }
        )
    return articles, new_links


def fetch_anthropic_blog(
    hours: int = 36,
    prev_links: set[str] | None = None,
    client: anthropic.Anthropic | None = None,
) -> tuple[list[dict], list[str]]:
    """Return (new Anthropic blog articles, their links) found via web search."""
    load_dotenv()
    prev_links = prev_links or set()
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=SEARCH_MAX_TOKENS,
        tools=[_build_web_search_tool()],
        messages=[{"role": "user", "content": _SEARCH_PROMPT.format(hours=hours)}],
    )

    text = _extract_response_text(response.content)
    results = _parse_search_results(text)
    articles, new_links = _to_articles(results, prev_links)
    logger.info("Anthropic blog: %d new posts via web search", len(articles))
    return articles, new_links
