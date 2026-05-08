import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "feeds.yaml"
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "IndustryNewsDigest/1.0"}


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _parse_entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _truncate(text: str, max_chars: int = 2000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _fetch_rss_feed(url: str, label: str, cutoff: datetime) -> list[dict]:
    articles = []
    try:
        parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed error for %s (%s): %s", label, url, parsed.bozo_exception)
            return articles

        for entry in parsed.entries:
            published = _parse_entry_time(entry)
            if published and published < cutoff:
                continue

            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            articles.append({
                "title": getattr(entry, "title", "Untitled"),
                "link": getattr(entry, "link", ""),
                "summary": _truncate(_strip_html(summary_raw)),
                "source_label": label,
                "published": published.isoformat() if published else "unknown",
            })
    except Exception:
        logger.exception("Failed to fetch feed: %s (%s)", label, url)
    return articles


def _scrape_blog_page(url: str, label: str, max_articles: int = 10) -> list[dict]:
    """Scrape the most recent article titles and links from a blog index page."""
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen_links = set()
        for a_tag in soup.find_all("a", href=True):
            if len(articles) >= max_articles:
                break

            href = a_tag["href"].split("?")[0]
            full_url = urljoin(url, href)

            if "/blog/" not in full_url or full_url.rstrip("/") == url.rstrip("/"):
                continue
            if full_url in seen_links:
                continue
            seen_links.add(full_url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            articles.append({
                "title": _truncate(title, 200),
                "link": full_url,
                "summary": "",
                "source_label": label,
                "published": "unknown",
            })
    except Exception:
        logger.exception("Failed to scrape blog: %s (%s)", label, url)
    return articles


def fetch_rss_articles(hours: int = 24) -> dict[str, list[dict]]:
    config = _load_config()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = {}

    for company, feeds in config.get("feeds", {}).items():
        articles = []
        for feed_info in feeds:
            articles.extend(_fetch_rss_feed(feed_info["url"], feed_info["label"], cutoff))
            time.sleep(0.5)
        if articles:
            results[company] = articles

    for company, pages in config.get("scrape", {}).items():
        articles = []
        for page_info in pages:
            articles.extend(_scrape_blog_page(page_info["url"], page_info["label"]))
            time.sleep(0.5)
        if articles:
            results[company] = articles

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("Fetching RSS feeds and blog pages (last 72 hours for testing)...\n")
    articles = fetch_rss_articles(hours=72)

    total = 0
    for company, items in articles.items():
        print(f"[{company}] — {len(items)} article(s)")
        for item in items:
            print(f"  - {item['title']}")
            print(f"    {item['link']}")
            print(f"    Published: {item['published']}")
            print()
        total += len(items)

    print(f"Total: {total} articles from {len(articles)} companies")
