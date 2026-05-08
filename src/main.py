import argparse
import logging
import sys
import time

from dotenv import load_dotenv

from src.fetchers.rss import fetch_rss_articles
from src.fetchers.gmail import fetch_gmail_newsletters
from src.summarizer import summarize_content
from src.emailer import send_digest

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

    # Build raw sources string for debugging
    raw_parts = []
    for company, articles in rss_articles.items():
        for a in articles:
            raw_parts.append(f"[RSS/{company}] {a['title']}\n  Link: {a['link']}\n  Published: {a['published']}\n  Summary: {a.get('summary', '')[:200]}")
    for n in newsletters:
        raw_parts.append(f"[Email] {n['subject']}\n  From: {n['sender']}\n  Date: {n['date']}\n  Preview: {n['body_text'][:200]}")
    raw_sources = "\n\n".join(raw_parts)

    # Summarize
    logger.info("Summarizing %d items with Claude...", total)
    start = time.time()
    digest_markdown = summarize_content(rss_articles, newsletters)
    logger.info("Summarization complete (%.1fs)", time.time() - start)

    if dry_run:
        print("\n" + digest_markdown)
        send_digest(digest_markdown, dry_run=True, raw_sources=raw_sources)
        return

    # Send
    logger.info("Sending digest email...")
    send_digest(digest_markdown, raw_sources=raw_sources)
    logger.info("Done.")


def main():
    parser = argparse.ArgumentParser(description="Industry News Digest")
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending email")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours (default: 24)")
    parser.add_argument("--rss-only", action="store_true", help="Skip Gmail fetcher")
    parser.add_argument("--skip-summarize", action="store_true", help="Print raw items without summarizing")
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


if __name__ == "__main__":
    main()
