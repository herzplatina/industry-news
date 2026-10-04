"""run_digest only marks items as seen once the run completes.

A run that fails partway (e.g. the Anthropic API rejects the summary batch)
must leave the checkpoint untouched so the next run picks the same items up.
"""

import json

import pytest

from src import checkpoint, main

ARTICLE = {
    "title": "New model",
    "link": "https://example.com/post/",
    "source_label": "Example",
    "summary": "",
    "published": "2026-10-03",
}
PAPER = {"title": "A paper", "link": "https://arxiv.org/abs/1", "summary": ""}
NEWSLETTER = {
    "subject": "Weekly",
    "sender": "Sender",
    "date": "2026-10-03",
    "body_text": "hello",
}


@pytest.fixture
def checkpoint_file(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"links": ["https://old.com/a"]}))
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", path)
    monkeypatch.setattr(
        main,
        "fetch_rss_articles",
        lambda hours: {"example": [dict(ARTICLE)], "arxiv": [dict(PAPER)]},
    )
    monkeypatch.setattr(
        main, "fetch_anthropic_blog", lambda hours, prev_links: ([], [])
    )
    monkeypatch.setattr(
        main,
        "fetch_gmail_newsletters",
        lambda hours, prev_message_ids: ([dict(NEWSLETTER)], ["msg-1"]),
    )
    return path


def test_failed_run_leaves_checkpoint_untouched(checkpoint_file, monkeypatch):
    before = checkpoint_file.read_text()

    def broken_client():
        raise RuntimeError("credit balance is too low")

    monkeypatch.setattr(main.anthropic, "Anthropic", broken_client)
    monkeypatch.setattr(main, "fetch_article_body", lambda link: "body")

    with pytest.raises(RuntimeError):
        main.run_digest(hours=36)

    assert checkpoint_file.read_text() == before


def test_successful_run_marks_items_seen(checkpoint_file):
    main.run_digest(hours=36, skip_summarize=True)

    saved = json.loads(checkpoint_file.read_text())
    assert set(saved["links"]) == {"https://old.com/a", "https://example.com/post"}
    assert saved["newsletter_message_ids"] == ["msg-1"]
    assert "last_run" in saved


def test_blog_dedupes_against_this_runs_rss_links(checkpoint_file, monkeypatch):
    seen_by_blog_fetcher = {}

    def fake_blog(hours, prev_links):
        seen_by_blog_fetcher.update(prev_links=prev_links)
        return [], []

    monkeypatch.setattr(main, "fetch_anthropic_blog", fake_blog)
    monkeypatch.setattr(main, "fetch_article_body", lambda link: "body")
    # Stop right after fetching: summarizing isn't under test here.
    monkeypatch.setattr(main.anthropic, "Anthropic", lambda: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        main.run_digest(hours=36)

    assert "https://example.com/post" in seen_by_blog_fetcher["prev_links"]
