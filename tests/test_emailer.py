import base64

import src.emailer as emailer
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


# --- send_digest (real send — Gmail API path, mocked credentials) ---


class _FakeSend:
    def __init__(self, recorder):
        self._recorder = recorder

    def send(self, userId, body):  # noqa: N803 — matches Gmail API kwarg
        self._recorder["userId"] = userId
        self._recorder["raw"] = body["raw"]
        return self

    def execute(self):
        return {"id": "sent-1"}


class _FakeService:
    def __init__(self, recorder):
        self._recorder = recorder

    def users(self):
        return self

    def messages(self):
        return _FakeSend(self._recorder)


def test_send_digest_sends_via_gmail_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "me@example.com")
    monkeypatch.setenv("GMAIL_SENDER_EMAIL", "sender@example.com")

    recorder = {}
    monkeypatch.setattr(emailer, "get_credentials", lambda: object())
    monkeypatch.setattr(emailer, "build", lambda *a, **k: _FakeService(recorder))

    assert send_digest(_SAMPLE_MARKDOWN) is True
    assert recorder["userId"] == "me"
    # The Gmail API expects a base64url-encoded RFC822 message.
    decoded = base64.urlsafe_b64decode(recorder["raw"]).decode()
    assert "To: me@example.com" in decoded
    assert "From: sender@example.com" in decoded
    assert "multipart/alternative" in decoded


def test_send_digest_omits_from_when_sender_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIGEST_RECIPIENT_EMAIL", "me@example.com")
    monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)

    recorder = {}
    monkeypatch.setattr(emailer, "get_credentials", lambda: object())
    monkeypatch.setattr(emailer, "build", lambda *a, **k: _FakeService(recorder))

    send_digest(_SAMPLE_MARKDOWN)
    decoded = base64.urlsafe_b64decode(recorder["raw"]).decode()
    assert "From:" not in decoded
    assert "To: me@example.com" in decoded
