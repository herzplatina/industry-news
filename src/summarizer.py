import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert industry news editor. Given a collection of articles and newsletter content from AI/tech companies and industry newsletters, produce a concise daily digest.

Format the digest in markdown with the following sections. Only include a section if there are relevant items for it:

## Key Developments
Major announcements, launches, and significant industry events.

## Research & Papers
Notable research publications, technical breakthroughs, and scientific findings.

## Product Updates
New features, product launches, updates, and improvements from companies.

## Industry Moves
Partnerships, acquisitions, hiring, funding rounds, and strategic shifts.

## Worth Watching
Emerging trends, opinion pieces, and items that may become significant.

Rules:
- Each item: 2-3 sentence summary with inline citation links in markdown format: [Source Name](url)
- EVERY bullet point MUST have at least one clickable URL citation. Never cite a source without a link.
- For RSS items: use the article's Link field as the citation URL
- For newsletter items: use the most specific article URL from the "Links in newsletter" list that corresponds to the story being summarized. Prefer the original source URL over the newsletter's own URL.
- If the same story appears in multiple sources, merge into one item citing all sources with their respective URLs
- Deduplicate: if the same story appears in multiple sources, merge into one item citing all sources
- Prioritize by significance and novelty
- Be concise but informative — the reader should understand the key takeaway without clicking through
- If content is sparse, don't pad the digest — shorter is better than filler
- Write in a professional, neutral tone
"""

MODEL = "claude-sonnet-4-6"


def _format_rss_content(rss_articles: dict[str, list[dict]]) -> str:
    parts = []
    for company, articles in rss_articles.items():
        parts.append(f"=== RSS: {company.upper()} ===")
        for a in articles:
            parts.append(f"Title: {a['title']}")
            if a.get("category"):
                parts.append(f"Category: {a['category']}")
            parts.append(f"Link: {a['link']}")
            parts.append(f"Source: {a['source_label']}")
            parts.append(f"Published: {a['published']}")
            if a.get("summary"):
                parts.append(f"Summary: {a['summary']}")
            parts.append("")
    return "\n".join(parts)


def _format_newsletter_content(newsletters: list[dict]) -> str:
    parts = []
    for n in newsletters:
        parts.append(f"=== NEWSLETTER: {n['sender']} ===")
        parts.append(f"Subject: {n['subject']}")
        parts.append(f"Date: {n['date']}")
        parts.append(f"Content: {n['body_text']}")
        if n.get("urls"):
            parts.append(f"Links in newsletter: {' | '.join(n['urls'])}")
        parts.append("")
    return "\n".join(parts)


def summarize_content(
    rss_articles: dict[str, list[dict]],
    newsletters: list[dict] | None = None,
) -> str:
    load_dotenv()
    client = anthropic.Anthropic()

    user_parts = []
    if rss_articles:
        user_parts.append("# RSS Feed Articles\n\n" + _format_rss_content(rss_articles))
    if newsletters:
        user_parts.append("# Newsletter Content\n\n" + _format_newsletter_content(newsletters))

    user_content = "\n\n---\n\n".join(user_parts)
    user_content += "\n\nPlease produce today's industry news digest based on the above content."

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    usage = response.usage
    logger.info(
        "Token usage — input: %d, output: %d, cache_creation: %s, cache_read: %s",
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_creation_input_tokens", "n/a"),
        getattr(usage, "cache_read_input_tokens", "n/a"),
    )

    return response.content[0].text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sample_rss = {
        "anthropic": [
            {
                "title": "Claude 4 Released with Enhanced Reasoning",
                "link": "https://anthropic.com/blog/claude-4",
                "summary": "Anthropic releases Claude 4, featuring significant improvements in reasoning, code generation, and multi-step task completion.",
                "source_label": "Anthropic News",
                "published": "2026-05-01T00:00:00+00:00",
            }
        ],
        "openai": [
            {
                "title": "GPT-5 Turbo Now Available in API",
                "link": "https://openai.com/blog/gpt5-turbo-api",
                "summary": "OpenAI makes GPT-5 Turbo generally available through its API with improved latency and reduced costs.",
                "source_label": "OpenAI News",
                "published": "2026-05-01T00:00:00+00:00",
            }
        ],
    }

    sample_newsletters = [
        {
            "sender": "TLDR",
            "subject": "TLDR AI: Big week in AI",
            "date": "2026-05-01",
            "body_text": "This week saw major releases from both Anthropic and OpenAI. Google DeepMind also published a new paper on efficient transformer architectures.",
        }
    ]

    print("Testing summarizer with sample content...\n")
    digest = summarize_content(sample_rss, sample_newsletters)
    print(digest)
