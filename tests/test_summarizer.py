from src.summarizer import _format_newsletter_content, _format_rss_content

_RSS = {
    "anthropic": [
        {
            "title": "Claude 4 Released",
            "link": "https://anthropic.com/blog/claude-4",
            "summary": "A new model release.",
            "source_label": "Anthropic News",
            "published": "2026-05-01T00:00:00+00:00",
            "category": "Announcement",
        }
    ]
}

_NEWSLETTERS = [
    {
        "sender": "TLDR",
        "subject": "TLDR AI: Big week",
        "date": "2026-05-01",
        "body_text": "Big AI news this week.",
        "urls": ["https://example.com/story"],
    }
]


# --- _format_rss_content ---

def test_format_rss_includes_title():
    assert "Claude 4 Released" in _format_rss_content(_RSS)


def test_format_rss_includes_link():
    assert "https://anthropic.com/blog/claude-4" in _format_rss_content(_RSS)


def test_format_rss_includes_category():
    assert "Announcement" in _format_rss_content(_RSS)


def test_format_rss_includes_source_label():
    assert "Anthropic News" in _format_rss_content(_RSS)


def test_format_rss_uses_summary_override():
    summaries = {"https://anthropic.com/blog/claude-4": "Overridden summary."}
    result = _format_rss_content(_RSS, summaries)
    assert "Overridden summary." in result


def test_format_rss_empty_returns_empty_string():
    assert _format_rss_content({}) == ""


# --- _format_newsletter_content ---

def test_format_newsletter_includes_subject():
    assert "TLDR AI: Big week" in _format_newsletter_content(_NEWSLETTERS)


def test_format_newsletter_includes_body():
    assert "Big AI news this week." in _format_newsletter_content(_NEWSLETTERS)


def test_format_newsletter_includes_urls():
    assert "https://example.com/story" in _format_newsletter_content(_NEWSLETTERS)


def test_format_newsletter_includes_sender():
    assert "TLDR" in _format_newsletter_content(_NEWSLETTERS)


def test_format_newsletter_uses_summary_override():
    summaries = {"TLDR AI: Big week": "Summarized content here."}
    result = _format_newsletter_content(_NEWSLETTERS, summaries)
    assert "Summarized content here." in result
    assert "Big AI news this week." not in result


def test_format_newsletter_empty_returns_empty_string():
    assert _format_newsletter_content([]) == ""
