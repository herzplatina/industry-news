"""Tests for the Anthropic company-blog web-search fetcher."""

import json
from types import SimpleNamespace

from src.fetchers.anthropic_blog import (
    SOURCE_LABEL,
    _extract_response_text,
    _is_anthropic_url,
    _normalize_link,
    _parse_search_results,
    _to_articles,
    fetch_anthropic_blog,
)


# --- _normalize_link ---


def test_normalize_strips_trailing_slash():
    assert (
        _normalize_link("https://www.anthropic.com/news/foo/")
        == "https://www.anthropic.com/news/foo"
    )


def test_normalize_strips_query_and_fragment():
    assert (
        _normalize_link("https://www.anthropic.com/news/foo?utm=x#top")
        == "https://www.anthropic.com/news/foo"
    )


def test_normalize_rejects_relative_url():
    assert _normalize_link("/news/foo") == ""


# --- _is_anthropic_url ---


def test_is_anthropic_url_accepts_apex_and_subdomain():
    assert _is_anthropic_url("https://anthropic.com/news/x")
    assert _is_anthropic_url("https://www.anthropic.com/news/x")


def test_is_anthropic_url_rejects_other_domains():
    assert not _is_anthropic_url("https://example.com/news/x")


def test_is_anthropic_url_rejects_lookalike_domain():
    assert not _is_anthropic_url("https://anthropic.com.evil.com/news/x")


# --- _parse_search_results ---


def test_parse_bare_json_array():
    text = '[{"title": "A", "url": "https://anthropic.com/news/a"}]'
    assert _parse_search_results(text) == [
        {"title": "A", "url": "https://anthropic.com/news/a"}
    ]


def test_parse_fenced_json():
    text = '```json\n[{"title": "A", "url": "u"}]\n```'
    assert _parse_search_results(text) == [{"title": "A", "url": "u"}]


def test_parse_array_embedded_in_prose():
    text = 'Here are the posts:\n[{"title": "A", "url": "u"}]\nHope that helps.'
    assert _parse_search_results(text) == [{"title": "A", "url": "u"}]


def test_parse_empty_array():
    assert _parse_search_results("[]") == []


def test_parse_invalid_json_returns_empty():
    assert _parse_search_results("not json at all") == []


def test_parse_non_list_returns_empty():
    assert _parse_search_results('{"title": "A"}') == []


def test_parse_empty_string_returns_empty():
    assert _parse_search_results("") == []


# --- _extract_response_text ---


def test_extract_joins_text_blocks_only():
    blocks = [
        SimpleNamespace(type="text", text="hello"),
        SimpleNamespace(type="server_tool_use", name="web_search"),
        SimpleNamespace(type="text", text="world"),
    ]
    assert _extract_response_text(blocks) == "hello\nworld"


# --- _to_articles ---


def test_to_articles_builds_expected_shape():
    results = [
        {
            "title": "Claude Update",
            "url": "https://www.anthropic.com/news/claude-update",
            "date": "2026-07-27",
            "summary": "A new release.",
        }
    ]
    articles, links = _to_articles(results, set())
    assert links == ["https://www.anthropic.com/news/claude-update"]
    assert articles[0] == {
        "title": "Claude Update",
        "link": "https://www.anthropic.com/news/claude-update",
        "summary": "A new release.",
        "source_label": SOURCE_LABEL,
        "published": "2026-07-27",
        "category": "",
    }


def test_to_articles_dedupes_against_prev_links():
    results = [{"title": "Old", "url": "https://anthropic.com/news/old"}]
    prev = {"https://anthropic.com/news/old"}
    articles, links = _to_articles(results, prev)
    assert articles == []
    assert links == []


def test_to_articles_dedupes_within_batch():
    results = [
        {"title": "A", "url": "https://anthropic.com/news/a"},
        {"title": "A again", "url": "https://anthropic.com/news/a/"},
    ]
    articles, links = _to_articles(results, set())
    assert len(articles) == 1
    assert links == ["https://anthropic.com/news/a"]


def test_to_articles_filters_non_anthropic_domain():
    results = [{"title": "Spam", "url": "https://evil.com/news/x"}]
    articles, _ = _to_articles(results, set())
    assert articles == []


def test_to_articles_skips_missing_title_or_url():
    results = [
        {"title": "", "url": "https://anthropic.com/news/a"},
        {"title": "No URL", "url": ""},
        {"url": "https://anthropic.com/news/b"},  # missing title key
    ]
    articles, _ = _to_articles(results, set())
    assert articles == []


def test_to_articles_defaults_unknown_published():
    results = [{"title": "A", "url": "https://anthropic.com/news/a"}]
    articles, _ = _to_articles(results, set())
    assert articles[0]["published"] == "unknown"


# --- fetch_anthropic_blog (mocked client) end-to-end ---


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class _FakeClient:
    def __init__(self, text: str):
        self.messages = _FakeMessages(text)


def test_fetch_returns_new_articles():
    payload = json.dumps(
        [
            {
                "title": "New Model",
                "url": "https://www.anthropic.com/news/new-model",
                "date": "2026-07-27",
                "summary": "Announced today.",
            }
        ]
    )
    client = _FakeClient(payload)
    articles, links = fetch_anthropic_blog(hours=36, prev_links=set(), client=client)
    assert len(articles) == 1
    assert articles[0]["title"] == "New Model"
    assert links == ["https://www.anthropic.com/news/new-model"]
    # Web search tool must be attached to the request.
    tools = client.messages.calls[0]["tools"]
    assert tools[0]["type"] == "web_search_20250305"
    assert tools[0]["allowed_domains"] == ["anthropic.com"]


def test_fetch_dedupes_against_previous_day():
    payload = json.dumps(
        [{"title": "Yesterday", "url": "https://anthropic.com/news/yesterday"}]
    )
    client = _FakeClient(payload)
    prev = {"https://anthropic.com/news/yesterday"}
    articles, links = fetch_anthropic_blog(hours=36, prev_links=prev, client=client)
    assert articles == []
    assert links == []


def test_fetch_handles_empty_results():
    client = _FakeClient("[]")
    articles, links = fetch_anthropic_blog(hours=36, prev_links=set(), client=client)
    assert articles == []
    assert links == []
