import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "twitter.yaml"
BASE_URL = "https://api.twitter.com/2"


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
        tweets.append({
            "handle": handle,
            "text": tweet["text"],
            "created_at": tweet["created_at"],
            "likes": tweet.get("public_metrics", {}).get("like_count", 0),
            "retweets": tweet.get("public_metrics", {}).get("retweet_count", 0),
            "url": f"https://x.com/{handle}/status/{tweet['id']}",
        })
    return tweets


def fetch_tweets(hours: int = 36) -> list[dict]:
    accounts = _load_accounts()
    headers = _get_headers()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    all_tweets = []
    for handle in accounts:
        user_id = _get_user_id(handle, headers)
        if not user_id:
            continue
        tweets = _get_tweets(user_id, handle, since, headers)
        all_tweets.extend(tweets)
        logger.info("@%s: %d tweets", handle, len(tweets))

    # Sort by engagement (likes + retweets)
    all_tweets.sort(key=lambda t: t["likes"] + t["retweets"], reverse=True)
    return all_tweets


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("Fetching tweets (last 36 hours)...\n")
    tweets = fetch_tweets(hours=36)
    print(f"Found {len(tweets)} tweets:\n")
    for t in tweets[:20]:
        print(f"  @{t['handle']} ({t['likes']}❤ {t['retweets']}🔁)")
        print(f"  {t['text'][:100]}")
        print(f"  {t['url']}")
        print()
