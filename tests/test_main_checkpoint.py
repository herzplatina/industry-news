"""Digests only mark items as seen once the run completes.

A run that fails partway (e.g. the Anthropic API rejects the summary batch)
must leave the checkpoint untouched so the next run picks the same items up.
"""

import json
from unittest.mock import MagicMock

import pytest

from src import checkpoint, main

ARTICLE = {
    "title": "New model",
    "link": "https://example.com/post",
    "source_label": "Example",
    "summary": "",
    "published": "2026-10-03",
}
PAPER = {
    "title": "A paper",
    "link": "https://arxiv.org/abs/1",
    "summary": "",
    "source_type": "arxiv",
}
NEWSLETTER = {
    "subject": "Weekly",
    "sender": "Sender",
    "date": "2026-10-03",
    "body_text": "hello",
}
TWEET = {"url": "https://x.com/a/status/1", "text": "hi", "created_at": "2026-10-03"}


@pytest.fixture
def stubbed_pipeline(tmp_path, monkeypatch):
    """Point the checkpoint at a temp file and stub every fetcher; returns the file."""
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"links": ["https://old.com/a"]}))
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    monkeypatch.setattr(
        main,
        "fetch_rss_articles",
        lambda hours, prev_links: (
            {"example": [dict(ARTICLE)], "arxiv": [dict(PAPER)]},
            [ARTICLE["link"]],
        ),
    )
    monkeypatch.setattr(
        main, "fetch_anthropic_blog", lambda hours, prev_links: ([], [])
    )
    monkeypatch.setattr(
        main,
        "fetch_gmail_newsletters",
        lambda hours, prev_message_ids: ([dict(NEWSLETTER)], ["msg-1"]),
    )
    monkeypatch.setattr(main, "fetch_article_body", lambda link: "body")
    return path


def _fail_summarizing(monkeypatch):
    """Make the Anthropic client raise, as when the account is out of credits."""
    monkeypatch.setattr(
        main.anthropic,
        "Anthropic",
        MagicMock(side_effect=RuntimeError("credit balance is too low")),
    )


def _stub_summarize_and_send(monkeypatch):
    """Let a run summarize (to nothing) and 'send' without touching any API."""
    client = MagicMock()
    client.messages.batches.create.return_value.processing_status = "ended"
    client.messages.batches.results.return_value = []
    monkeypatch.setattr(main.anthropic, "Anthropic", lambda: client)
    monkeypatch.setattr(main, "summarize_arxiv_content", lambda papers, summaries: "")
    monkeypatch.setattr(main, "send_arxiv_digest", lambda markdown, dry_run: None)
    monkeypatch.setattr(main, "summarize_content", lambda *args: "digest")
    monkeypatch.setattr(main, "send_digest", MagicMock())


def test_failed_run_leaves_checkpoint_untouched(stubbed_pipeline, monkeypatch):
    before = stubbed_pipeline.read_text()
    _fail_summarizing(monkeypatch)

    with pytest.raises(RuntimeError):
        main.run_digest(hours=36)

    assert stubbed_pipeline.read_text() == before


def test_successful_run_marks_items_seen(stubbed_pipeline, monkeypatch):
    _stub_summarize_and_send(monkeypatch)

    main.run_digest(hours=36)

    saved = json.loads(stubbed_pipeline.read_text())
    assert set(saved["links"]) == {"https://old.com/a", "https://example.com/post"}
    assert saved["newsletter_message_ids"] == ["msg-1"]


def test_blog_dedupes_against_this_runs_rss_links(stubbed_pipeline, monkeypatch):
    blog_fetcher = MagicMock(return_value=([], []))
    monkeypatch.setattr(main, "fetch_anthropic_blog", blog_fetcher)
    _fail_summarizing(monkeypatch)

    with pytest.raises(RuntimeError):
        main.run_digest(hours=36)

    assert "https://example.com/post" in blog_fetcher.call_args.kwargs["prev_links"]


def test_arxiv_only_run_does_not_mark_company_articles_seen(
    stubbed_pipeline, monkeypatch
):
    _stub_summarize_and_send(monkeypatch)

    main.run_digest(hours=36, arxiv_only=True)

    saved = json.loads(stubbed_pipeline.read_text())
    assert saved["links"] == ["https://old.com/a"]


def test_failed_twitter_send_leaves_tweets_unseen(stubbed_pipeline, monkeypatch):
    before = stubbed_pipeline.read_text()
    monkeypatch.setattr(main, "fetch_tweets", lambda hours: {"a": [dict(TWEET)]})
    monkeypatch.setattr(
        main, "send_twitter_digest", MagicMock(side_effect=RuntimeError("smtp down"))
    )

    with pytest.raises(RuntimeError):
        main.run_twitter_digest(hours=36)

    assert stubbed_pipeline.read_text() == before


@pytest.mark.parametrize("flag", ["dry_run", "skip_summarize"])
def test_preview_runs_leave_checkpoint_untouched(stubbed_pipeline, monkeypatch, flag):
    before = stubbed_pipeline.read_text()
    _stub_summarize_and_send(monkeypatch)

    main.run_digest(hours=36, **{flag: True})

    assert stubbed_pipeline.read_text() == before
