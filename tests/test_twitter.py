from src.fetchers.twitter import _unfurl_tweet_text


def test_unfurl_no_entities_returns_text_unchanged():
    assert _unfurl_tweet_text("Hello world", {}) == "Hello world"


def test_unfurl_empty_urls_list_returns_text_unchanged():
    assert _unfurl_tweet_text("Hello world", {"urls": []}) == "Hello world"


def test_unfurl_removes_media_link():
    text = "Check this out https://t.co/abc123"
    entities = {
        "urls": [{
            "url": "https://t.co/abc123",
            "expanded_url": "https://pic.x.com/photo123",
            "display_url": "pic.x.com/photo123",
        }]
    }
    result = _unfurl_tweet_text(text, entities)
    assert "https://t.co/abc123" not in result


def test_unfurl_replaces_tco_with_titled_markdown(monkeypatch):
    monkeypatch.setattr(
        "src.fetchers.twitter._fetch_page_title", lambda url: "Article Title"
    )
    text = "Read this https://t.co/abc123"
    entities = {
        "urls": [{
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "display_url": "example.com/article",
        }]
    }
    result = _unfurl_tweet_text(text, entities)
    assert "Article Title" in result
    assert "https://t.co/abc123" not in result


def test_unfurl_falls_back_to_expanded_url_when_no_title(monkeypatch):
    monkeypatch.setattr(
        "src.fetchers.twitter._fetch_page_title", lambda url: None
    )
    text = "Check https://t.co/abc123"
    entities = {
        "urls": [{
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "display_url": "example.com/article",
        }]
    }
    result = _unfurl_tweet_text(text, entities)
    assert "https://example.com/article" in result
    assert "https://t.co/abc123" not in result


def test_unfurl_skips_url_not_in_text():
    text = "No link here"
    entities = {
        "urls": [{
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
        }]
    }
    result = _unfurl_tweet_text(text, entities)
    assert result == "No link here"
