from src.emailer import _render_html, send_digest

_SAMPLE_MARKDOWN = """\
## Key Developments

**Claude 4 Released** — Anthropic released Claude 4. [Anthropic Blog](https://anthropic.com/blog/claude-4)
"""


# --- _render_html ---

def test_render_html_returns_nonempty_string():
    html = _render_html(_SAMPLE_MARKDOWN)
    assert isinstance(html, str)
    assert len(html) > 0


def test_render_html_includes_content():
    assert "Claude 4 Released" in _render_html(_SAMPLE_MARKDOWN)


def test_render_html_converts_link():
    assert "https://anthropic.com/blog/claude-4" in _render_html(_SAMPLE_MARKDOWN)


def test_render_html_converts_heading():
    assert "<h2>" in _render_html(_SAMPLE_MARKDOWN)


# --- send_digest (dry_run mode — no SMTP, no env vars required) ---

def test_send_digest_dry_run_returns_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert send_digest(_SAMPLE_MARKDOWN, dry_run=True) is True


def test_send_digest_dry_run_writes_preview_html(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    send_digest(_SAMPLE_MARKDOWN, dry_run=True)
    preview = tmp_path / "digest_preview.html"
    assert preview.exists()
    assert "Claude 4 Released" in preview.read_text()


def test_send_digest_dry_run_includes_raw_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    send_digest(_SAMPLE_MARKDOWN, dry_run=True, raw_sources="### Raw source content")
    html = (tmp_path / "digest_preview.html").read_text()
    assert "Raw source content" in html
