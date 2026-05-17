import base64

from src.fetchers.gmail import _build_query, _clean_body, _decode_body, _extract_urls


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


# --- _build_query ---

def test_build_query_includes_email():
    senders = [{"email": "news@example.com", "name": "Example"}]
    query = _build_query(senders, hours=24)
    assert "from:news@example.com" in query


def test_build_query_name_only_uses_quoted_form():
    senders = [{"name": "Example News"}]
    query = _build_query(senders, hours=24)
    assert 'from:"Example News"' in query


def test_build_query_hours_converts_to_days():
    query = _build_query([{"email": "a@b.com"}], hours=48)
    assert "newer_than:2d" in query


def test_build_query_sub_day_hours_clamp_to_one_day():
    query = _build_query([{"email": "a@b.com"}], hours=6)
    assert "newer_than:1d" in query


# --- _decode_body ---

def test_decode_body_plain_text():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("Hello newsletter")}}
    text, html = _decode_body(payload)
    assert text == "Hello newsletter"
    assert html == ""


def test_decode_body_html():
    payload = {"mimeType": "text/html", "body": {"data": _b64("<p>Hello</p>")}}
    text, html = _decode_body(payload)
    assert text == ""
    assert html == "<p>Hello</p>"


def test_decode_body_multipart_extracts_both_parts():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Plain text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML</p>")}},
        ],
    }
    text, html = _decode_body(payload)
    assert text == "Plain text"
    assert html == "<p>HTML</p>"


def test_decode_body_empty_payload():
    text, html = _decode_body({})
    assert text == ""
    assert html == ""


# --- _extract_urls ---

def test_extract_urls_returns_article_link():
    html = '<a href="https://example.com/article">Read more</a>'
    assert "https://example.com/article" in _extract_urls(html)


def test_extract_urls_skips_unsubscribe():
    html = '<a href="https://example.com/unsubscribe">Unsubscribe</a>'
    assert _extract_urls(html) == []


def test_extract_urls_skips_mailto():
    html = '<a href="mailto:user@example.com">Email us</a>'
    assert _extract_urls(html) == []


def test_extract_urls_deduplicates():
    html = (
        '<a href="https://example.com/article">1</a>'
        '<a href="https://example.com/article">2</a>'
    )
    assert _extract_urls(html).count("https://example.com/article") == 1


def test_extract_urls_skips_non_http():
    html = '<a href="ftp://example.com/file">Download</a>'
    assert _extract_urls(html) == []


# --- _clean_body ---

def test_clean_body_removes_view_on_web_header():
    text = "View this post on the web at https://substack.com/p/example\nActual content"
    result = _clean_body(text)
    assert "View this post" not in result
    assert "Actual content" in result


def test_clean_body_passthrough_for_normal_text():
    text = "Normal newsletter content here."
    assert _clean_body(text) == text


def test_clean_body_strips_substack_redirect_urls():
    text = "Some intro [https://substack.com/redirect/abc?jwt=x] more text"
    result = _clean_body(text)
    assert "substack.com/redirect" not in result
    assert "more text" in result
