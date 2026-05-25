import argparse
import logging
import sys
import time

import anthropic
from dotenv import load_dotenv

from src.checkpoint import load_checkpoint, save_checkpoint
from src.fetchers.rss import fetch_rss_articles, fetch_article_body
from src.fetchers.gmail import fetch_gmail_newsletters
from src.fetchers.twitter import fetch_tweets
from src.summarizer import (
    summarize_content,
    MODEL,
    ITEM_SUMMARY_MAX_TOKENS,
    BATCH_POLL_INTERVAL_SECS,
    NEWSLETTER_SUMMARY_PROMPT,
    RSS_SUMMARY_PROMPT,
    ARXIV_SUMMARY_PROMPT,
)

from src.emailer import send_digest, send_twitter_digest

logger = logging.getLogger(__name__)

NEWSLETTER_FALLBACK_CHARS = 2_000  # cap for fallback when summarization fails


def run_digest(
    hours: int = 24,
    dry_run: bool = False,
    rss_only: bool = False,
    skip_summarize: bool = False,
    arxiv_only: bool = False,
) -> None:
    rss_articles = {}
    newsletters = []

    logger.info("Fetching RSS feeds...")
    start = time.time()
    try:
        rss_articles = fetch_rss_articles(hours=hours)
        if arxiv_only:
            rss_articles = {k: v for k, v in rss_articles.items() if k == "arxiv"}
        rss_count = sum(len(v) for v in rss_articles.values())
        logger.info("RSS: %d articles from %d sources (%.1fs)", rss_count, len(rss_articles), time.time() - start)
    except Exception:
        logger.exception("RSS fetcher failed")

    if not rss_only and not arxiv_only:
        logger.info("Fetching Gmail newsletters...")
        start = time.time()
        try:
            checkpoint = load_checkpoint()
            prev_message_ids = set(checkpoint.get("newsletter_message_ids", []))
            newsletters, new_message_ids = fetch_gmail_newsletters(
                hours=hours, prev_message_ids=prev_message_ids
            )
            merged_ids = list(prev_message_ids | set(new_message_ids))
            checkpoint["newsletter_message_ids"] = merged_ids
            save_checkpoint(checkpoint)
            logger.info("Gmail: %d newsletters (%.1fs)", len(newsletters), time.time() - start)
        except FileNotFoundError:
            logger.warning("Gmail OAuth not configured — skipping. Set up credentials.json to enable.")
        except Exception:
            logger.exception("Gmail fetcher failed")

    total = sum(len(v) for v in rss_articles.values()) + len(newsletters)
    if total == 0:
        logger.info("No new content found. Skipping digest.")
        return

    if skip_summarize:
        print(f"\n=== RAW CONTENT: {total} items ===\n")
        for company, articles in rss_articles.items():
            for a in articles:
                print(f"[RSS/{company}] {a['title']} — {a['link']}")
        for n in newsletters:
            print(f"[Email] {n['subject']} — from {n['sender']}")
        return

    client = anthropic.Anthropic()
    newsletter_summaries = {}
    rss_summaries = {}

    batch_requests = []
    for i, n in enumerate(newsletters):
        batch_requests.append({
            "custom_id": f"newsletter-{i}",
            "params": {
                "model": MODEL,
                "max_tokens": ITEM_SUMMARY_MAX_TOKENS,
                "messages": [{
                    "role": "user",
                    "content": NEWSLETTER_SUMMARY_PROMPT.format(
                        subject=n["subject"],
                        sender=n["sender"],
                        body_text=n["body_text"],
                    ),
                }],
            },
        })

    rss_flat = []
    non_arxiv = {k: v for k, v in rss_articles.items() if k != "arxiv"}
    logger.info("Fetching %d article bodies...", sum(len(v) for v in non_arxiv.values()))
    for company, articles in rss_articles.items():
        for a in articles:
            rss_flat.append((company, a))
            if a.get("source_type") == "arxiv":
                content = ARXIV_SUMMARY_PROMPT.format(
                    title=a["title"],
                    link=a["link"],
                    abstract=a.get("body_text") or a.get("summary", ""),
                )
            else:
                body = fetch_article_body(a["link"])
                content = RSS_SUMMARY_PROMPT.format(
                    title=a["title"],
                    source_label=a["source_label"],
                    company=company,
                    link=a["link"],
                    body_text=body or a.get("summary", ""),
                )
            batch_requests.append({
                "custom_id": f"rss-{len(rss_flat) - 1}",
                "params": {
                    "model": MODEL,
                    "max_tokens": ITEM_SUMMARY_MAX_TOKENS,
                    "messages": [{"role": "user", "content": content}],
                },
            })

    if batch_requests:
        logger.info("Summarizing %d items individually via batch...", len(batch_requests))
        batch = client.messages.batches.create(requests=batch_requests)
        logger.info("Summary batch created: %s", batch.id)
        while batch.processing_status != "ended":
            time.sleep(BATCH_POLL_INTERVAL_SECS)
            batch = client.messages.batches.retrieve(batch.id)
        for result in client.messages.batches.results(batch.id):
            cid = result.custom_id
            if cid.startswith("newsletter-"):
                idx = int(cid.split("-")[1])
                subject = newsletters[idx]["subject"]
                if result.result.type == "succeeded":
                    text = result.result.message.content[0].text
                    newsletter_summaries[subject] = text
                else:
                    logger.warning("Failed to summarize newsletter: %s", subject)
                    fallback = newsletters[idx]["body_text"][:NEWSLETTER_FALLBACK_CHARS]
                    newsletter_summaries[subject] = fallback
            elif cid.startswith("rss-"):
                idx = int(cid.split("-")[1])
                company, article = rss_flat[idx]
                link = article["link"]
                if result.result.type == "succeeded":
                    rss_summaries[link] = result.result.message.content[0].text
                else:
                    logger.warning("Failed to summarize RSS article: %s", article["title"])
                    rss_summaries[link] = article.get("summary", "")
    logger.info("Individual summaries complete")

    raw_parts = []
    for company, articles in rss_articles.items():
        raw_parts.append(f"### RSS: {company.upper()}\n")
        for a in articles:
            category = f" *[{a['category']}]*" if a.get("category") else ""
            raw_parts.append(f"**{a['title']}**{category}  ")
            raw_parts.append(f"Link: {a['link']}  ")
            raw_parts.append(f"Published: {a['published']}  ")
            summary = rss_summaries.get(a["link"], a.get("summary", ""))
            if summary:
                raw_parts.append(f"Summary: {summary}")
            raw_parts.append("")
    for n in newsletters:
        raw_parts.append(f"### NEWSLETTER: {n['sender']}\n")
        raw_parts.append(f"**{n['subject']}**  ")
        raw_parts.append(f"Date: {n['date']}  ")
        body_fallback = n["body_text"][:NEWSLETTER_FALLBACK_CHARS]
        raw_parts.append("\n" + newsletter_summaries.get(n["subject"], body_fallback))
        raw_parts.append("")
    raw_sources = "\n".join(raw_parts)

    logger.info("Summarizing %d items with Claude...", total)
    start = time.time()
    digest_markdown = summarize_content(
        rss_articles, newsletters, newsletter_summaries, rss_summaries
    )
    logger.info("Summarization complete (%.1fs)", time.time() - start)

    if dry_run:
        print("\n" + digest_markdown)
        send_digest(digest_markdown, dry_run=True, raw_sources=raw_sources)
        return

    logger.info("Sending digest email...")
    send_digest(digest_markdown, raw_sources=raw_sources)
    logger.info("Done.")


def run_twitter_digest(hours: int = 36, dry_run: bool = False) -> None:
    logger.info("Fetching tweets...")
    start = time.time()
    try:
        tweets_by_handle = fetch_tweets(hours=hours)
        total = sum(len(v) for v in tweets_by_handle.values())
        logger.info("Twitter: %d tweets from %d accounts (%.1fs)", total, len(tweets_by_handle), time.time() - start)
    except Exception:
        logger.exception("Twitter fetcher failed")
        return

    checkpoint = load_checkpoint()
    prev_tweet_urls = set(checkpoint.get("tweet_urls", []))
    new_tweet_urls = []
    filtered = {}
    for handle, tweets in tweets_by_handle.items():
        new_tweets = [t for t in tweets if t["url"] not in prev_tweet_urls]
        if new_tweets:
            filtered[handle] = new_tweets
            new_tweet_urls.extend(t["url"] for t in new_tweets)

    merged_urls = list(prev_tweet_urls | set(new_tweet_urls))
    checkpoint["tweet_urls"] = merged_urls
    save_checkpoint(checkpoint)

    if not filtered:
        logger.info("No new tweets found. Skipping Twitter digest.")
        return

    new_total = sum(len(v) for v in filtered.values())
    logger.info("Twitter: %d new tweets after checkpoint filter", new_total)

    parts = ["# Twitter Digest\n"]
    for handle, tweets in filtered.items():
        parts.append(f"## @{handle}\n")
        for t in tweets:
            timestamp = t["created_at"][:16].replace("T", " ")
            parts.append(f"**{timestamp}**  ")
            parts.append(f"{t['text']}  ")
            parts.append(f"[Link]({t['url']})")
            parts.append("")
    digest_markdown = "\n".join(parts)

    if dry_run:
        print("\n" + digest_markdown)
        send_twitter_digest(digest_markdown, dry_run=True)
        return

    logger.info("Sending Twitter digest email...")
    send_twitter_digest(digest_markdown)
    logger.info("Twitter digest done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Industry News Digest")
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending email")
    parser.add_argument("--hours", type=int, default=36, help="Time window in hours (default: 36)")
    parser.add_argument("--rss-only", action="store_true", help="Skip Gmail fetcher")
    parser.add_argument("--skip-summarize", action="store_true", help="Print raw items without summarizing")
    parser.add_argument("--skip-twitter", action="store_true", help="Skip Twitter digest")
    parser.add_argument("--arxiv-only", action="store_true", help="Only include arXiv papers, skip all other sources")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    load_dotenv()

    try:
        run_digest(
            hours=args.hours,
            dry_run=args.dry_run,
            rss_only=args.rss_only,
            skip_summarize=args.skip_summarize,
            arxiv_only=args.arxiv_only,
        )
    except Exception:
        logger.exception("Digest pipeline failed")
        sys.exit(1)

    if not args.skip_twitter:
        try:
            run_twitter_digest(hours=args.hours, dry_run=args.dry_run)
        except Exception:
            logger.exception("Twitter digest failed")


if __name__ == "__main__":
    main()
