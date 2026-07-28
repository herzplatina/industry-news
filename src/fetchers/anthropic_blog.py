"""Discover new Anthropic company blog posts via Claude web search.

The Anthropic company blog (https://www.anthropic.com/news) has no RSS feed,
so new posts are discovered with the Anthropic API's web search tool
(restricted to the anthropic.com domain) instead of a feed or HTML scraper.
Links are deduplicated against the shared checkpoint so a post that was
already included in a previous day's email is never included again.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import anthropic
from dotenv import load_dotenv

from src.checkpoint import load_checkpoint, save_checkpoint
from src.summarizer import MODEL

logger = logging.getLogger(__name__)

BLOG_DOMAIN = "anthropic.com"
BLOG_PATH_PREFIX = "/news/"
SOURCE_LABEL = "Anthropic Blog"
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
WEB_SEARCH_MAX_USES = 5
WEB_SEARCH_MAX_TOKENS = 4096

SEARCH_PROMPT = (
    "Search the Anthropic company blog at https://www.anthropic.com/news for "
    "posts published in the last {hours} hours. "
    "Find every new blog post — announcements, product news, research, and "
    "policy posts."
)

_DATE_PATTERN = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})"
)


def _get_field(obj, field: str, default=None):
    """Read a field from an SDK object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _parse_page_age(page_age: str | None) -> datetime | None:
    """Parse a web-search page_age string like 'May 1, 2026' into a datetime."""
    if not page_age:
        return None
    match = _DATE_PATTERN.search(page_age)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%B %d, %Y")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_blog_post_url(url: str) -> bool:
    """Return True for Anthropic company blog post URLs (anthropic.com/news/...)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host != BLOG_DOMAIN and not host.endswith("." + BLOG_DOMAIN):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 2 and parts[0] == BLOG_PATH_PREFIX.strip("/")


def _extract_search_results(response) -> list[dict]:
    """Pull (title, url, page_age) results out of a web-search API response."""
    results = []
    for block in _get_field(response, "content", []) or []:
        if _get_field(block, "type") != "web_search_tool_result":
            continue
        content = _get_field(block, "content")
        if not isinstance(content, list):
            logger.warning(
                "Web search tool error: %s", _get_field(content, "error_code", content)
            )
            continue
        for item in content:
            if _get_field(item, "type") != "web_search_result":
                continue
            results.append(
                {
                    "title": _get_field(item, "title", ""),
                    "url": _get_field(item, "url", ""),
                    "page_age": _get_field(item, "page_age"),
                }
            )
    return results


def fetch_anthropic_blog_posts(hours: int = 24) -> list[dict]:
    """Find Anthropic company blog posts published in the last `hours` hours.

    Discovers posts via web search (the blog has no RSS feed) and returns
    article dicts in the same shape as the RSS fetcher so they flow through
    the standard summarize-and-digest pipeline. Links already in the
    checkpoint — i.e. included in a previous day's email — are skipped, and
    newly found links are added to the checkpoint.
    """
    load_dotenv()
    client = anthropic.Anthropic()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    checkpoint = load_checkpoint()
    prev_links = {link.rstrip("/") for link in checkpoint.get("links", [])}

    response = client.messages.create(
        model=MODEL,
        max_tokens=WEB_SEARCH_MAX_TOKENS,
        tools=[
            {
                "type": WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": WEB_SEARCH_MAX_USES,
                "allowed_domains": [BLOG_DOMAIN],
            }
        ],
        messages=[{"role": "user", "content": SEARCH_PROMPT.format(hours=hours)}],
    )

    articles = []
    new_links = []
    seen_links = set()
    for result in _extract_search_results(response):
        url = result["url"].strip()
        if not url or not _is_blog_post_url(url):
            continue
        link = url.rstrip("/")
        if link in prev_links or link in seen_links:
            continue
        published = _parse_page_age(result["page_age"])
        if published and published < cutoff:
            continue

        seen_links.add(link)
        new_links.append(link)
        articles.append(
            {
                "title": result["title"].strip() or "Untitled",
                "link": link,
                "summary": "",
                "source_label": SOURCE_LABEL,
                "published": published.isoformat() if published else "unknown",
                "category": "",
            }
        )

    if new_links:
        checkpoint["links"] = list(prev_links | set(new_links))
        checkpoint["last_run"] = datetime.now(timezone.utc).isoformat()
        save_checkpoint(checkpoint)

    return articles
