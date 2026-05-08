import argparse
import logging
import sys
import time

import anthropic
from dotenv import load_dotenv

from src.fetchers.rss import fetch_rss_articles
from src.fetchers.gmail import fetch_gmail_newsletters
from src.fetchers.twitter import fetch_tweets
from src.summarizer import summarize_content
from src.emailer import send_digest, send_twitter_digest

logger = logging.getLogger(__name__)


def run_digest(hours: int = 24, dry_run: bool = False, rss_only: bool = False, skip_summarize: bool = False):
    load_dotenv()

    rss_articles = {}
    newsletters = []

    # Fetch RSS
    logger.info("Fetching RSS feeds...")
    start = time.time()
    try:
        rss_articles = fetch_rss_articles(hours=hours)
        rss_count = sum(len(v) for v in rss_articles.values())
        logger.info("RSS: %d articles from %d companies (%.1fs)", rss_count, len(rss_articles), time.time() - start)
    except Exception:
        logger.exception("RSS fetcher failed")

    # Fetch Gmail
    if not rss_only:
        logger.info("Fetching Gmail newsletters...")
        start = time.time()
        try:
            newsletters = fetch_gmail_newsletters(hours=hours)
            logger.info("Gmail: %d newsletters (%.1fs)", len(newsletters), time.time() - start)
        except FileNotFoundError:
            logger.warning("Gmail OAuth not configured — skipping. Set up credentials.json to enable.")
        except Exception:
            logger.exception("Gmail fetcher failed")

    total = sum(len(v) for v in rss_articles.values()) + len(newsletters)
    if total == 0:
        logger.info("No new content found. Skipping digest.")
        return

    # Skip summarize — just print raw content
    if skip_summarize:
        print(f"\n=== RAW CONTENT: {total} items ===\n")
        for company, articles in rss_articles.items():
            for a in articles:
                print(f"[RSS/{company}] {a['title']} — {a['link']}")
        for n in newsletters:
            print(f"[Email] {n['subject']} — from {n['sender']}")
        return

    # Summarize each newsletter individually for the raw sources section
    logger.info("Summarizing %d newsletters individually...", len(newsletters))
    client = anthropic.Anthropic()
    newsletter_summaries = {}
    for n in newsletters:
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Summarize this newsletter in approximately 1000 words. "
                        f"Preserve all key facts, names, numbers, and conclusions. "
                        f"Write in plain prose, no bullet points.\n\n"
                        f"Subject: {n['subject']}\n"
                        f"From: {n['sender']}\n\n"
                        f"{n['body_text']}"
                    ),
                }],
            )
            newsletter_summaries[n['subject']] = resp.content[0].text
        except Exception:
            logger.warning("Failed to summarize newsletter: %s", n['subject'])
            newsletter_summaries[n['subject']] = n['body_text'][:2000]
    logger.info("Newsletter summaries complete")

    # Build raw sources appendix for the email (proper markdown)
    raw_parts = []
    for company, articles in rss_articles.items():
        raw_parts.append(f"### RSS: {company.upper()}\n")
        for a in articles:
            category = f" *[{a['category']}]*" if a.get("category") else ""
            raw_parts.append(f"**{a['title']}**{category}  ")
            raw_parts.append(f"Link: {a['link']}  ")
            raw_parts.append(f"Published: {a['published']}  ")
            if a.get("summary"):
                raw_parts.append(f"Summary: {a['summary']}")
            raw_parts.append("")
    for n in newsletters:
        raw_parts.append(f"### NEWSLETTER: {n['sender']}\n")
        raw_parts.append(f"**{n['subject']}**  ")
        raw_parts.append(f"Date: {n['date']}  ")
        raw_parts.append(f"\n{newsletter_summaries.get(n['subject'], n['body_text'][:2000])}")
        raw_parts.append("")
    raw_sources = "\n".join(raw_parts)

    # Summarize
    logger.info("Summarizing %d items with Claude...", total)
    start = time.time()
    digest_markdown = summarize_content(rss_articles, newsletters, newsletter_summaries)
    logger.info("Summarization complete (%.1fs)", time.time() - start)

    if dry_run:
        print("\n" + digest_markdown)
        send_digest(digest_markdown, dry_run=True, raw_sources=raw_sources)
        return

    # Send
    logger.info("Sending digest email...")
    send_digest(digest_markdown, raw_sources=raw_sources)
    logger.info("Done.")


def run_twitter_digest(hours: int = 36, dry_run: bool = False):
    load_dotenv()

    logger.info("Fetching tweets...")
    start = time.time()
    try:
        tweets = fetch_tweets(hours=hours)
        logger.info("Twitter: %d tweets (%.1fs)", len(tweets), time.time() - start)
    except Exception:
        logger.exception("Twitter fetcher failed")
        return

    if not tweets:
        logger.info("No tweets found. Skipping Twitter digest.")
        return

    # Summarize tweets with Claude
    client = anthropic.Anthropic()
    tweet_text = "\n\n".join(
        f"@{t['handle']} ({t['likes']} likes, {t['retweets']} RTs)\n"
        f"{t['text']}\n"
        f"Link: {t['url']}"
        for t in tweets
    )

    logger.info("Summarizing %d tweets with Claude...", len(tweets))
    start = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": (
                "You are an expert tech industry analyst. Given tweets from AI/tech leaders, "
                "produce a concise digest highlighting the most interesting and significant posts. "
                "Group by theme, not by person. Each item: 1-2 sentence summary with the tweet link. "
                "Deduplicate related tweets. Prioritize by significance and engagement. "
                "Format in markdown with section headers. Include the tweeter's handle in each item."
            ),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": f"# Tweets from the past {hours} hours\n\n{tweet_text}\n\nProduce today's Twitter digest.",
        }],
    )
    digest_markdown = response.content[0].text
    logger.info("Twitter summarization complete (%.1fs)", time.time() - start)

    # Build raw tweets section
    raw_parts = ["### Raw Tweets\n"]
    for t in tweets:
        raw_parts.append(f"**@{t['handle']}** ({t['likes']} likes, {t['retweets']} RTs)  ")
        raw_parts.append(f"{t['text']}  ")
        raw_parts.append(f"Link: {t['url']}")
        raw_parts.append("")
    raw_sources = "\n".join(raw_parts)

    if dry_run:
        print("\n" + digest_markdown)
        send_twitter_digest(digest_markdown, dry_run=True, raw_sources=raw_sources)
        return

    logger.info("Sending Twitter digest email...")
    send_twitter_digest(digest_markdown, raw_sources=raw_sources)
    logger.info("Twitter digest done.")


def main():
    parser = argparse.ArgumentParser(description="Industry News Digest")
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending email")
    parser.add_argument("--hours", type=int, default=36, help="Time window in hours (default: 36)")
    parser.add_argument("--rss-only", action="store_true", help="Skip Gmail fetcher")
    parser.add_argument("--skip-summarize", action="store_true", help="Print raw items without summarizing")
    parser.add_argument("--skip-twitter", action="store_true", help="Skip Twitter digest")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        run_digest(
            hours=args.hours,
            dry_run=args.dry_run,
            rss_only=args.rss_only,
            skip_summarize=args.skip_summarize,
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
