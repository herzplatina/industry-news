import logging
import time

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

MODEL = "claude-haiku-4-5-20251001"
ITEM_SUMMARY_MAX_TOKENS = 400
DIGEST_MAX_TOKENS = 4096
BATCH_POLL_INTERVAL_SECS = 5

NEWSLETTER_SUMMARY_PROMPT = (
    "Summarize this newsletter in approximately 200 words. "
    "Preserve all key facts, names, numbers, and conclusions. "
    "Write in plain prose, no bullet points.\n\n"
    "Subject: {subject}\n"
    "From: {sender}\n\n"
    "{body_text}"
)

ARXIV_SUMMARY_PROMPT = (
    "Summarize this research paper in 2 sentences: what it does and its key contribution. "
    "Then add 1 sentence explaining why it matters for practitioners building LLM agent systems, "
    "orchestration frameworks, or agent harnesses. "
    "Write in plain prose, no bullet points.\n\n"
    "Title: {title}\n"
    "Link: {link}\n\n"
    "{abstract}"
)

RSS_SUMMARY_PROMPT = (
    "Summarize this article in approximately 200 words. "
    "Preserve all key facts, names, numbers, and conclusions. "
    "Write in plain prose, no bullet points.\n\n"
    "Title: {title}\n"
    "Source: {source_label} ({company})\n"
    "Link: {link}\n\n"
    "{body_text}"
)


def _format_rss_content(
    rss_articles: dict[str, list[dict]],
    rss_summaries: dict[str, str] | None = None,
) -> str:
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
            summary = (rss_summaries or {}).get(a['link'], a.get('summary', ''))
            if summary:
                parts.append(f"Summary: {summary}")
            parts.append("")
    return "\n".join(parts)


def _format_newsletter_content(
    newsletters: list[dict],
    newsletter_summaries: dict[str, str] | None = None,
) -> str:
    parts = []
    for n in newsletters:
        parts.append(f"=== NEWSLETTER: {n['sender']} ===")
        parts.append(f"Subject: {n['subject']}")
        parts.append(f"Date: {n['date']}")
        if newsletter_summaries:
            content = newsletter_summaries.get(n["subject"], n["body_text"])
        else:
            content = n["body_text"]
        parts.append(f"Content: {content}")
        if n.get("urls"):
            parts.append(f"Links in newsletter: {' | '.join(n['urls'])}")
        parts.append("")
    return "\n".join(parts)


def summarize_content(
    rss_articles: dict[str, list[dict]],
    newsletters: list[dict] | None = None,
    newsletter_summaries: dict[str, str] | None = None,
    rss_summaries: dict[str, str] | None = None,
) -> str:
    load_dotenv()
    client = anthropic.Anthropic()

    user_parts = []
    if rss_articles:
        user_parts.append(
            "# RSS Feed Articles\n\n" + _format_rss_content(rss_articles, rss_summaries)
        )
    if newsletters:
        user_parts.append(
            "# Newsletter Content\n\n"
            + _format_newsletter_content(newsletters, newsletter_summaries)
        )

    user_content = "\n\n---\n\n".join(user_parts)
    user_content += "\n\nPlease produce today's industry news digest based on the above content."

    batch = client.messages.batches.create(requests=[{
        "custom_id": "digest",
        "params": {
            "model": MODEL,
            "max_tokens": DIGEST_MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        },
    }])
    logger.info("Digest batch created: %s", batch.id)

    while batch.processing_status != "ended":
        time.sleep(BATCH_POLL_INTERVAL_SECS)
        batch = client.messages.batches.retrieve(batch.id)

    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            msg = result.result.message
            logger.info(
                "Token usage — input: %d, output: %d",
                msg.usage.input_tokens,
                msg.usage.output_tokens,
            )
            return msg.content[0].text

    raise RuntimeError("Digest batch failed")

