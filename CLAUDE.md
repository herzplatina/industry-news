# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this does

Daily pipeline that fetches AI/tech industry news from RSS feeds, Gmail newsletters, and Twitter, summarizes everything via Claude Haiku (Batch API), then emails an HTML digest. Runs on GitHub Actions at 7 AM PT.

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Dry-run (prints digest + saves HTML preview, no email sent)
python -m src.main --dry-run

# Limit to RSS only (no Gmail OAuth required)
python -m src.main --dry-run --rss-only

# Adjust time window
python -m src.main --dry-run --hours 48

# Print raw fetched items without summarizing (fast, no API calls)
python -m src.main --dry-run --skip-summarize

# Run individual component smoke tests
python -m tests.test_rss
python -m tests.test_gmail
python -m tests.test_twitter
python -m tests.test_summarizer       # uses sample data, calls real API
python -m tests.test_emailer --dry-run  # renders HTML preview, no email sent
```

Required env vars (put in `.env` for local use):
- `ANTHROPIC_API_KEY` — for summarization
- `GMAIL_SENDER_EMAIL`, `GMAIL_APP_PASSWORD`, `DIGEST_RECIPIENT_EMAIL` — for sending email
- `TWITTER_BEARER_TOKEN` — for Twitter fetching

Gmail OAuth additionally requires `credentials.json` and `token.json` at the project root. On first local run it opens a browser to authorize; in CI these are written from GitHub Secrets.

## Architecture

```
src/main.py          — orchestrates the full pipeline
src/checkpoint.py    — shared checkpoint load/save (deduplication across runs)
src/summarizer.py    — Claude Haiku batch summarization; holds all prompt constants
src/emailer.py       — renders HTML via Jinja2 + sends via Gmail SMTP
src/fetchers/
  rss.py             — fetches RSS feeds + scrapes blog pages without RSS
  gmail.py           — reads newsletters from Gmail via Google API
  twitter.py         — fetches tweets via Twitter API v2
config/
  feeds.yaml         — RSS feed URLs and blog scrape targets per company
  senders.yaml       — Gmail newsletter sender allowlist
  twitter.yaml       — Twitter accounts to follow
templates/
  digest.html        — Jinja2 email template
```

**Pipeline flow:**
1. RSS + scrape fetcher: fetches up to 10 articles per feed, filters by `--hours` cutoff, skips links already in checkpoint
2. Gmail fetcher: queries allowed senders, decodes MIME, extracts article URLs from HTML
3. Individual summarization batch: each article/newsletter summarized to ~200 words via Haiku Batch API
4. Final digest batch: all summaries sent to Haiku with the editor system prompt → categorized markdown digest
5. Email: markdown rendered to HTML via Jinja2 template, sent via Gmail SMTP; HTML preview also saved to repo root for GH Actions artifact upload

**Checkpoint (`data/checkpoint.json`):** Tracks seen RSS article links, newsletter message IDs, and tweet URLs to deduplicate across runs. In CI this is persisted via `actions/cache`. The `data/` directory is gitignored.

## Config files

`config/feeds.yaml` has two top-level keys:
- `feeds` — standard RSS feeds, keyed by company name, each with `url` and `label`
- `scrape` — HTML scraping targets with optional `path_match` and `min_title_length` overrides

To add a new source, add an entry under the appropriate key. No code changes needed.

`config/senders.yaml` — list of `{name, email}` objects for allowed Gmail newsletter senders.

`config/twitter.yaml` — list of `{handle}` objects.

## Key design notes

- Both the individual summarization step and the final digest use the Anthropic **Batch API** (async, polled until `processing_status == "ended"`). This keeps costs low but adds latency.
- All Claude prompts (`SYSTEM_PROMPT`, `NEWSLETTER_SUMMARY_PROMPT`, `RSS_SUMMARY_PROMPT`) and model/token constants (`MODEL`, `ITEM_SUMMARY_MAX_TOKENS`, `DIGEST_MAX_TOKENS`) live in `src/summarizer.py` — that's the single place to tune summarization behavior.
- Preview HTML files (`digest_preview.html`, `twitter_digest_preview.html`) are always written to the repo root and uploaded as GH Actions artifacts — useful for inspecting output without an email client.
