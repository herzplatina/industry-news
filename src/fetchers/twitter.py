import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "twitter.yaml"
BASE_URL = "https://api.twitter.com/2"


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_data(self, data):
        if self._in_title:
            self.title = data.strip()
            self._in_title = False


_OG_TITLE_RE = __import__("re").compile(
    r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']'
)


def _fetch_page_title(url: str) -> str | None:
    """Fetch page title from a URL via <title> tag or og:title meta."""
    try:
        resp = requests.get(
            url, timeout=5,
            headers={"User-Agent": "Twitterbot/1.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text[:20000]
        # Try og:title first (works better for JS-rendered sites)
        og_match = _OG_TITLE_RE.search(html)
        if og_match:
            title = og_match.group(1) or og_match.group(2)
            if title:
                import html as html_mod
                title = html_mod.unescape(title).strip()
                if len(title) > 120:
                    title = title[:117] + "..."
                return title
        # Fall back to <title> tag
        parser = _TitleParser()
        parser.feed(html)
        title = parser.title
        if title and len(title) > 120:
            title = title[:117] + "..."
        return title
    except Exception:
        return None


def _unfurl_tweet_text(text: str, entities: dict) -> str:
    """Replace t.co links with [Title](expanded_url) using Twitter entities and page scraping."""
    urls = entities.get("urls", [])
    if not urls:
        return text
    for url_entity in urls:
        tco_url = url_entity["url"]
        expanded = url_entity.get("expanded_url", tco_url)
        if tco_url not in text:
            continue
        # Skip media links (photos/videos) — just remove the t.co link
        if url_entity.get("media_key") or "pic.x.com" in url_entity.get("display_url", ""):
            text = text.replace(tco_url, "")
            continue
        title = _fetch_page_title(expanded)
        if title:
            text = text.replace(tco_url, f"\n> *[{title}]({expanded})*")
        else:
            text = text.replace(tco_url, expanded)
    return text.strip()


def _load_accounts() -> list[str]:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    return [a["handle"] for a in config["accounts"]]


def _get_headers() -> dict:
    load_dotenv()
    token = os.environ["TWITTER_BEARER_TOKEN"]
    return {"Authorization": f"Bearer {token}"}


def _get_user_id(handle: str, headers: dict) -> str | None:
    resp = requests.get(
        f"{BASE_URL}/users/by/username/{handle}",
        headers=headers,
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning("Failed to look up @%s: %s", handle, resp.status_code)
        return None
    return resp.json().get("data", {}).get("id")


def _get_tweets(user_id: str, handle: str, since: datetime, headers: dict) -> list[dict]:
    params = {
        "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_results": 20,
        "tweet.fields": "created_at,public_metrics,entities",
        "exclude": "retweets,replies",
    }
    resp = requests.get(
        f"{BASE_URL}/users/{user_id}/tweets",
        headers=headers,
        params=params,
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning("Failed to fetch tweets for @%s: %s", handle, resp.status_code)
        return []

    tweets = []
    for tweet in resp.json().get("data", []):
        entities = tweet.get("entities", {})
        tweets.append({
            "handle": handle,
            "text": _unfurl_tweet_text(tweet["text"], entities),
            "created_at": tweet["created_at"],
            "likes": tweet.get("public_metrics", {}).get("like_count", 0),
            "retweets": tweet.get("public_metrics", {}).get("retweet_count", 0),
            "url": f"https://x.com/{handle}/status/{tweet['id']}",
        })
    return tweets


def fetch_tweets(hours: int = 36) -> dict[str, list[dict]]:
    """Returns tweets grouped by handle, each list sorted chronologically (oldest first)."""
    accounts = _load_accounts()
    headers = _get_headers()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    results = {}
    for handle in accounts:
        user_id = _get_user_id(handle, headers)
        if not user_id:
            continue
        tweets = _get_tweets(user_id, handle, since, headers)
        if tweets:
            tweets.sort(key=lambda t: t["created_at"])
            results[handle] = tweets
        logger.info("@%s: %d tweets", handle, len(tweets))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("Fetching tweets (last 36 hours)...\n")
    results = fetch_tweets(hours=36)
    total = sum(len(v) for v in results.values())
    print(f"Found {total} tweets from {len(results)} accounts:\n")
    for handle, tweets in results.items():
        print(f"@{handle} — {len(tweets)} tweets")
        for t in tweets:
            print(f"  [{t['created_at']}] {t['text'][:80]}")
        print()
