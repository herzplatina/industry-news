import logging
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

from src.checkpoint import load_checkpoint, save_checkpoint

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "feeds.yaml"
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "IndustryNewsDigest/1.0"}
ARTICLE_BODY_MAX_CHARS = 8_000
FEED_MAX_ENTRIES = 10
ARXIV_MAX_ENTRIES = 100
FEED_REQUEST_DELAY_SECS = 0.5
SUMMARY_FALLBACK_MAX_CHARS = 2_000
SCRAPE_SNIPPET_MAX_CHARS = 500

_DATE_PATTERN = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})"
)

_KNOWN_CATEGORIES = sorted([
    "Cross-Industry", "Societal Impacts", "Societal Impact",
    "AI Agents", "AI Agent", "AI Assistant",
    "Policy", "Research", "Productivity", "Product", "Government", "Alignment",
    "Technology", "Sales", "Engineering",
    "Safety", "Announcements", "Announcement", "Company",
    "Enterprise", "Security", "Customers", "Customer",
], key=len, reverse=True)


def _matches_arxiv_exclude(title: str, exclude_keywords: list[str]) -> bool:
    """Return True if the title matches any exclude keyword (case-insensitive)."""
    lower = title.lower()
    return any(kw.lower() in lower for kw in exclude_keywords)


def _strip_arxiv_title(title: str) -> str:
    """Remove the trailing arXiv ID suffix, e.g. '(arXiv:2401.12345v1 [cs.AI])'."""
    return re.sub(r"\s*\(arXiv:[^\)]+\)\s*$", "", title).strip()


def _fetch_arxiv_feed(
    url: str,
    label: str,
    cutoff: datetime,
    prev_links: set[str],
    seen_links: set[str],
    exclude_keywords: list[str],
) -> list[dict]:
    """Fetch papers from an arXiv RSS feed, applying title-based exclude filtering."""
    articles = []
    try:
        parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Feed error for %s (%s): %s", label, url, parsed.bozo_exception
            )
            return articles

        for entry in parsed.entries[:ARXIV_MAX_ENTRIES]:
            link = getattr(entry, "link", "").rstrip("/")
            if not link or link in prev_links or link in seen_links:
                continue

            published = _parse_entry_time(entry)
            if published and published < cutoff:
                continue

            raw_title = getattr(entry, "title", "Untitled")
            clean_title = _strip_arxiv_title(raw_title)

            if _matches_arxiv_exclude(clean_title, exclude_keywords):
                continue

            abstract_raw = (
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            abstract = _truncate(_strip_html(abstract_raw), SUMMARY_FALLBACK_MAX_CHARS)

            seen_links.add(link)
            articles.append({
                "title": clean_title or raw_title,
                "link": link,
                "summary": abstract,
                "body_text": abstract,
                "source_label": label,
                "published": published.isoformat() if published else "unknown",
                "category": "",
                "source_type": "arxiv",
            })
    except Exception:
        logger.exception("Failed to fetch arXiv feed: %s (%s)", label, url)
    return articles


def fetch_article_body(url: str) -> str:
    """Fetch and extract main text content from an article URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove nav, footer, script, style
        for tag in soup(["nav", "footer", "script", "style", "header", "aside"]):
            tag.decompose()
        # Try article tag first, fall back to body
        article = soup.find("article") or soup.find("main") or soup.body
        if not article:
            return ""
        text = article.get_text(separator=" ", strip=True)
        return text[:ARTICLE_BODY_MAX_CHARS]
    except Exception:
        return ""


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


def _parse_scraped_title(raw_title: str) -> tuple[str, str, str]:
    """Parse a scraped title into (date, category, clean_title)."""
    text = raw_title.strip()
    date = ""
    categories = []

    date_match = _DATE_PATTERN.search(text)
    if date_match:
        date = date_match.group(1)
        text = text[:date_match.start()] + text[date_match.end():]
        text = text.strip()

    changed = True
    while changed:
        changed = False
        for cat in _KNOWN_CATEGORIES:
            if text.startswith(cat):
                categories.append(cat)
                text = text[len(cat):].strip()
                changed = True
                break

    category = ", ".join(categories) if categories else ""
    return date, category, text


def _fetch_rss_feed(
    url: str,
    label: str,
    cutoff: datetime,
    prev_links: set[str],
) -> list[dict]:
    """Fetch articles from an RSS feed, skipping any already in the checkpoint."""
    articles = []
    try:
        parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Feed error for %s (%s): %s", label, url, parsed.bozo_exception
            )
            return articles

        for entry in parsed.entries[:FEED_MAX_ENTRIES]:
            published = _parse_entry_time(entry)
            link = getattr(entry, "link", "").rstrip("/")

            if link in prev_links:
                continue
            if published and published < cutoff:
                continue

            raw_title = getattr(entry, "title", "Untitled")
            date_str, category, clean_title = _parse_scraped_title(raw_title)

            summary_raw = (
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            summary = _truncate(_strip_html(summary_raw), SUMMARY_FALLBACK_MAX_CHARS)
            articles.append({
                "title": clean_title or raw_title,
                "link": link,
                "summary": summary,
                "source_label": label,
                "published": published.isoformat() if published else "unknown",
                "category": category,
            })
    except Exception:
        logger.exception("Failed to fetch feed: %s (%s)", label, url)
    return articles


def _scrape_blog_page(
    url: str,
    label: str,
    cutoff: datetime,
    prev_links: set[str],
    max_articles: int = 10,
    path_match: str = "/blog/",
    min_title_length: int = 5,
) -> list[dict]:
    """Scrape blog page for articles, skipping any already in the checkpoint."""
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen_links = set()
        candidates_checked = 0
        for a_tag in soup.find_all("a", href=True):
            if len(articles) >= max_articles:
                break
            if candidates_checked >= max_articles * 2:
                break

            href = a_tag["href"].split("?")[0]
            full_url = urljoin(url, href).rstrip("/")

            if path_match not in full_url or full_url == url.rstrip("/"):
                continue
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            candidates_checked += 1
            if full_url in prev_links:
                continue

            full_text = a_tag.get_text(strip=True)
            if not full_text or len(full_text) < 10:
                continue

            # Parse date and category from full text
            date_str, category, _ = _parse_scraped_title(full_text)

            # Use heading for clean title if available
            heading = a_tag.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading:
                clean_title = heading.get_text(strip=True)
            else:
                _, _, clean_title = _parse_scraped_title(full_text)

            if not clean_title or len(clean_title) < min_title_length:
                continue

            # Date-based filtering
            if date_str:
                try:
                    parsed_date = datetime.strptime(date_str, "%B %d, %Y")
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    if parsed_date < cutoff:
                        continue
                except ValueError:
                    pass

            # Split title from trailing description if too long
            title = clean_title
            summary = ""
            if len(clean_title) > 80:
                slug = full_url.rstrip("/").split("/")[-1]
                slug_words = len(slug.replace("-", " ").split())
                words = clean_title.split()
                if slug_words >= 3 and slug_words < len(words):
                    title = " ".join(words[:slug_words + 2])
                    summary = " ".join(words[slug_words + 2:])
                else:
                    for sep in [". ", "—", " - "]:
                        idx = clean_title.find(sep, 20)
                        if 20 < idx < 150:
                            title = clean_title[:idx].rstrip(".")
                            summary = clean_title[idx + len(sep):]
                            break
                    else:
                        title = clean_title[:80].rsplit(" ", 1)[0]
                        summary = clean_title[len(title):].strip()

            articles.append({
                "title": title,
                "link": full_url,
                "summary": _truncate(summary, SCRAPE_SNIPPET_MAX_CHARS),
                "source_label": label,
                "published": date_str or "unknown",
                "category": category,
            })
    except Exception:
        logger.exception("Failed to scrape blog: %s (%s)", label, url)
    return articles


def fetch_rss_articles(hours: int = 24) -> dict[str, list[dict]]:
    config = _load_config()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    checkpoint = load_checkpoint()
    prev_links = {link.rstrip("/") for link in checkpoint.get("links", [])}

    results = {}
    all_links = []

    for company, feeds in config.get("feeds", {}).items():
        articles = []
        for feed_info in feeds:
            new = _fetch_rss_feed(
                feed_info["url"], feed_info["label"], cutoff, prev_links
            )
            articles.extend(new)
            time.sleep(FEED_REQUEST_DELAY_SECS)
        if articles:
            results[company] = articles
            all_links.extend(a["link"] for a in articles)

    arxiv_config = config.get("arxiv", {})
    if arxiv_config:
        exclude_kw = arxiv_config.get("exclude_keywords", [])
        seen_arxiv_links: set[str] = set()
        arxiv_articles = []
        for feed_info in arxiv_config.get("feeds", []):
            new = _fetch_arxiv_feed(
                feed_info["url"],
                feed_info["label"],
                cutoff,
                prev_links,
                seen_arxiv_links,
                exclude_kw,
            )
            arxiv_articles.extend(new)
            time.sleep(FEED_REQUEST_DELAY_SECS)
        if arxiv_articles:
            results["arxiv"] = arxiv_articles
            all_links.extend(a["link"] for a in arxiv_articles)

    for company, pages in config.get("scrape", {}).items():
        articles = []
        for page_info in pages:
            path_match = page_info.get("path_match", "/blog/")
            min_title_length = page_info.get("min_title_length", 5)
            articles.extend(
                _scrape_blog_page(
                    page_info["url"],
                    page_info["label"],
                    cutoff,
                    prev_links,
                    path_match=path_match,
                    min_title_length=min_title_length,
                )
            )
            time.sleep(FEED_REQUEST_DELAY_SECS)
        if articles:
            results[company] = articles
            all_links.extend(a["link"] for a in articles)

    merged_links = list(prev_links | {link.rstrip("/") for link in all_links})
    checkpoint["links"] = merged_links
    checkpoint["last_run"] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(checkpoint)

    return results

