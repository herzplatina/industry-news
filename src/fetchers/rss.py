import json
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

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
CHECKPOINT_PATH = PROJECT_ROOT / "data" / "checkpoint.json"
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "IndustryNewsDigest/1.0"}

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


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def _save_checkpoint(checkpoint: dict):
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2))


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


def _fetch_rss_feed(url: str, label: str, cutoff: datetime, prev_links: set) -> list[dict]:
    """Fetch articles from an RSS feed, skipping any already in the checkpoint."""
    articles = []
    try:
        parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed error for %s (%s): %s", label, url, parsed.bozo_exception)
            return articles

        for entry in parsed.entries[:10]:
            published = _parse_entry_time(entry)
            link = getattr(entry, "link", "").rstrip("/")

            if link in prev_links:
                continue
            if published and published < cutoff:
                continue

            raw_title = getattr(entry, "title", "Untitled")
            date_str, category, clean_title = _parse_scraped_title(raw_title)

            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            articles.append({
                "title": clean_title or raw_title,
                "link": link,
                "summary": _truncate(_strip_html(summary_raw)),
                "source_label": label,
                "published": published.isoformat() if published else "unknown",
                "category": category,
            })
    except Exception:
        logger.exception("Failed to fetch feed: %s (%s)", label, url)
    return articles


def _scrape_blog_page(url: str, label: str, cutoff: datetime, prev_links: set, max_articles: int = 10, path_match: str = "/blog/", min_title_length: int = 5) -> list[dict]:
    """Scrape blog page for articles, skipping any already in the checkpoint."""
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
            full_url = urljoin(url, href).rstrip("/")

            if path_match not in full_url or full_url == url.rstrip("/"):
                continue
            if full_url in seen_links or full_url in prev_links:
                continue
            seen_links.add(full_url)

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
                    parsed_date = datetime.strptime(date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
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
                "summary": _truncate(summary, 500),
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

    # Load previous checkpoint
    checkpoint = _load_checkpoint()
    prev_links = {link.rstrip("/") for link in checkpoint.get("links", [])}

    results = {}
    all_links = []

    for company, feeds in config.get("feeds", {}).items():
        articles = []
        for feed_info in feeds:
            articles.extend(_fetch_rss_feed(feed_info["url"], feed_info["label"], cutoff, prev_links))
            time.sleep(0.5)
        if articles:
            results[company] = articles
            all_links.extend(a["link"] for a in articles)

    for company, pages in config.get("scrape", {}).items():
        articles = []
        for page_info in pages:
            path_match = page_info.get("path_match", "/blog/")
            min_title_length = page_info.get("min_title_length", 5)
            articles.extend(_scrape_blog_page(page_info["url"], page_info["label"], cutoff, prev_links, path_match=path_match, min_title_length=min_title_length))
            time.sleep(0.5)
        if articles:
            results[company] = articles
            all_links.extend(a["link"] for a in articles)

    # Save checkpoint: merge current links with previous to avoid re-sending
    merged_links = list(prev_links | {link.rstrip("/") for link in all_links})
    checkpoint["links"] = merged_links
    checkpoint["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_checkpoint(checkpoint)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("Fetching RSS feeds and blog pages (last 24 hours)...\n")
    articles = fetch_rss_articles(hours=24)

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
