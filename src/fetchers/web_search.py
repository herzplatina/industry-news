"""Discover blog posts via web search (for sources without RSS feeds)."""

import logging
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15
SNIPPET_MAX_CHARS = 500
SEARCH_URL = "https://html.duckduckgo.com/html/"


def _extract_ddg_url(href: str) -> str | None:
    """Extract the actual URL from a DuckDuckGo redirect wrapper."""
    if not href:
        return None
    if "duckduckgo.com/l/" in href:
        qs = parse_qs(urlparse(href).query)
        candidates = qs.get("uddg", [])
        if candidates:
            return unquote(candidates[0])
    if href.startswith("http"):
        return href
    return None


def fetch_web_search_articles(
    query: str,
    label: str,
    url_match: str,
    prev_links: set[str] | None = None,
) -> list[dict]:
    """Search via DuckDuckGo HTML and return articles whose URLs contain *url_match*.

    Parameters
    ----------
    query:
        The search query string (e.g. ``"site:anthropic.com/company"``).
    label:
        Human-readable source label attached to every returned article.
    url_match:
        Substring that must appear in the result URL for it to be included.
    prev_links:
        Set of previously-seen link URLs to skip (checkpoint deduplication).

    Returns
    -------
    list[dict]
        Article dicts compatible with the RSS article format used elsewhere.
    """
    if prev_links is None:
        prev_links = set()

    articles: list[dict] = []

    try:
        resp = requests.post(
            SEARCH_URL,
            data={"q": query, "b": ""},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen: set[str] = set()
        for a_tag in soup.find_all("a", class_="result__a"):
            raw_href = a_tag.get("href", "")
            url = _extract_ddg_url(raw_href)
            if not url or url_match not in url:
                continue

            url = url.rstrip("/")
            if url in prev_links or url in seen:
                continue
            seen.add(url)

            title = a_tag.get_text(strip=True)
            if not title:
                continue

            # The snippet lives in the next sibling with class result__snippet
            snippet = ""
            snippet_tag = a_tag.find_next(class_="result__snippet")
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)[:SNIPPET_MAX_CHARS]

            articles.append(
                {
                    "title": title,
                    "link": url,
                    "summary": snippet,
                    "source_label": label,
                    "published": "unknown",
                    "category": "",
                }
            )
    except Exception:
        logger.exception("Web search failed for query: %s", query)

    return articles
