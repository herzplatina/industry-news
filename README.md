# Industry News Digest

Automated daily digest of AI/tech industry news delivered to your inbox. Fetches content from RSS feeds, Gmail newsletters, and Twitter, summarizes everything with Claude Haiku, and emails an HTML digest every morning.

Runs on GitHub Actions at 7 AM PT. Each run deduplicates against a checkpoint so you never see the same article twice.

## How it works

1. **Fetch** — RSS feeds and scraped blog pages (no RSS), Gmail newsletters from an allowlist of senders, and tweets from a list of accounts
2. **Summarize** — each article and newsletter is individually summarized to ~200 words via Claude Haiku (Batch API)
3. **Digest** — all summaries are sent to Claude Haiku with an editor system prompt that produces a categorized markdown digest
4. **Email** — the digest is rendered to HTML and sent via Gmail SMTP; an HTML preview is uploaded as a GitHub Actions artifact

## Setup

### GitHub Actions (primary)

Add the following secrets to your repository (`Settings → Secrets and variables → Actions`):

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GMAIL_SENDER_EMAIL` | Gmail address used to send the digest |
| `GMAIL_APP_PASSWORD` | [Gmail App Password](https://myaccount.google.com/apppasswords) for SMTP |
| `DIGEST_RECIPIENT_EMAIL` | Address to receive the digest |
| `TWITTER_BEARER_TOKEN` | Twitter API v2 Bearer Token |
| `GOOGLE_CREDENTIALS_JSON` | Contents of `credentials.json` from Google Cloud Console |
| `GOOGLE_TOKEN_JSON` | Contents of `token.json` (generated on first local OAuth run) |

The workflow runs daily at 7 AM PT. Trigger it manually anytime from the **Actions** tab.

### Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file at the project root:

```
ANTHROPIC_API_KEY=...
GMAIL_SENDER_EMAIL=...
GMAIL_APP_PASSWORD=...
DIGEST_RECIPIENT_EMAIL=...
TWITTER_BEARER_TOKEN=...
```

For Gmail newsletter fetching, you also need `credentials.json` from the Google Cloud Console (OAuth 2.0 Desktop App). On first run it opens a browser to authorize and saves `token.json`.

## Running

```bash
# Full dry-run (no email, saves HTML preview to digest_preview.html)
python -m src.main --dry-run

# RSS only — no Gmail OAuth required
python -m src.main --dry-run --rss-only

# Print raw fetched items with no API calls
python -m src.main --dry-run --skip-summarize

# Adjust the lookback window (default: 36 hours)
python -m src.main --dry-run --hours 48

# Run individual components
python -m src.fetchers.rss
python -m src.fetchers.gmail
python -m src.fetchers.twitter
python -m src.summarizer    # uses sample data
python -m src.emailer --dry-run
```

## Configuration

All configuration lives in `config/`. No code changes needed to add sources.

**`config/feeds.yaml`** — RSS and scrape sources, organized by company:
- `feeds` — standard RSS feed URLs with labels
- `scrape` — blog pages without RSS, with optional `path_match` and `min_title_length` tuning

**`config/senders.yaml`** — Gmail newsletter sender allowlist (`name` and/or `email` per sender)

**`config/twitter.yaml`** — Twitter accounts to monitor (`handle` per account)

**`src/summarizer.py`** — Claude prompts (`SYSTEM_PROMPT`, `NEWSLETTER_SUMMARY_PROMPT`, `RSS_SUMMARY_PROMPT`) and model/token constants

## Checkpoint

`data/checkpoint.json` tracks seen RSS article links, newsletter message IDs, and tweet URLs across runs to prevent duplicates. In GitHub Actions this file is persisted via `actions/cache`. The `data/` directory is gitignored.
