"""Tests for the coding-research section pulled to the top of the arXiv digest."""

from types import SimpleNamespace

import src.summarizer as summarizer
from src.summarizer import (
    _assemble_arxiv_digest,
    _format_arxiv_papers,
    is_coding_paper,
    partition_coding_papers,
    summarize_arxiv_content,
)

_CODING = {
    "title": "SWE-bench: Evaluating Code Generation on Real GitHub Issues",
    "link": "https://arxiv.org/abs/2401.00001",
    "summary": "A benchmark for software engineering code repair.",
}
_NON_CODING = {
    "title": "Emergent Communication in Multi-Agent Planning",
    "link": "https://arxiv.org/abs/2401.00002",
    "summary": "Studies how agents coordinate via learned protocols.",
}


# --- is_coding_paper ---


def test_is_coding_paper_matches_title_keyword():
    assert is_coding_paper("A study of code generation", "")


def test_is_coding_paper_matches_abstract_keyword():
    assert is_coding_paper("Neutral title", "We fine-tune a code LLM on repos.")


def test_is_coding_paper_case_insensitive():
    assert is_coding_paper("Improving SWE-Bench Results", "")


def test_is_coding_paper_rejects_unrelated():
    assert not is_coding_paper(
        "Diffusion models for protein folding", "No software here."
    )


def test_is_coding_paper_does_not_match_substring_noise():
    # "encode"/"decoder" must not trip the "code" family of keywords.
    assert not is_coding_paper("A transformer encoder-decoder for translation", "")


def test_is_coding_paper_does_not_match_encoding_decoding():
    # "coding" is a substring of "encoding"/"decoding" — must not misfire.
    assert not is_coding_paper("Positional encoding for long sequences", "")
    assert not is_coding_paper("Speculative decoding speeds up inference", "")
    assert not is_coding_paper("An autoencoder for representation learning", "")


def test_is_coding_paper_matches_standalone_coding_word():
    assert is_coding_paper("Pair coding with LLM assistants", "")


# --- partition_coding_papers ---


def test_partition_splits_coding_and_others():
    coding, others = partition_coding_papers([_CODING, _NON_CODING])
    assert coding == [_CODING]
    assert others == [_NON_CODING]


def test_partition_preserves_order():
    a = {"title": "code generation A", "summary": ""}
    b = {"title": "code review B", "summary": ""}
    coding, _ = partition_coding_papers([a, b])
    assert coding == [a, b]


def test_partition_all_non_coding():
    coding, others = partition_coding_papers([_NON_CODING])
    assert coding == []
    assert others == [_NON_CODING]


def test_partition_falls_back_to_body_text():
    paper = {"title": "Neutral", "body_text": "improving unit test generation"}
    coding, _ = partition_coding_papers([paper])
    assert coding == [paper]


# --- _assemble_arxiv_digest ---


def test_assemble_places_coding_first():
    result = _assemble_arxiv_digest("## Coding\nA", "## General\nB")
    assert result.index("## Coding") < result.index("## General")


def test_assemble_only_coding():
    assert _assemble_arxiv_digest("## Coding\nA", "") == "## Coding\nA"


def test_assemble_only_general():
    assert _assemble_arxiv_digest("", "## General\nB") == "## General\nB"


def test_assemble_both_empty():
    assert _assemble_arxiv_digest("", "") == ""


# --- _format_arxiv_papers ---


def test_format_includes_title_and_link():
    out = _format_arxiv_papers([_CODING])
    assert _CODING["title"] in out
    assert _CODING["link"] in out


def test_format_uses_summary_override():
    out = _format_arxiv_papers([_CODING], {_CODING["link"]: "OVERRIDE"})
    assert "OVERRIDE" in out


# --- summarize_arxiv_content (mocked batch client) end-to-end ---


class _FakeResult:
    def __init__(self, custom_id: str, text: str):
        self.custom_id = custom_id
        self.result = SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            ),
        )


class _FakeBatches:
    def __init__(self, responder):
        self._responder = responder
        self.last_requests = None

    def create(self, requests):
        self.last_requests = requests
        return SimpleNamespace(id="batch_1", processing_status="ended")

    def retrieve(self, _id):
        return SimpleNamespace(id="batch_1", processing_status="ended")

    def results(self, _id):
        return [
            _FakeResult(r["custom_id"], self._responder(r["custom_id"]))
            for r in self.last_requests
        ]


class _FakeClient:
    def __init__(self, responder):
        self.messages = SimpleNamespace(batches=_FakeBatches(responder))


def _install_fake_client(monkeypatch, responder) -> _FakeClient:
    client = _FakeClient(responder)
    monkeypatch.setattr(summarizer.anthropic, "Anthropic", lambda: client)
    return client


def test_summarize_arxiv_puts_coding_section_at_top(monkeypatch):
    def responder(custom_id: str) -> str:
        if custom_id == "arxiv-coding":
            return "## 💻 Coding & Software Engineering Research\n[SWE-bench](url)"
        return "## Multi-Agent Systems\n[Planning](url)"

    _install_fake_client(monkeypatch, responder)

    result = summarize_arxiv_content([_NON_CODING, _CODING])

    assert "Coding & Software Engineering Research" in result
    assert result.index("Coding & Software Engineering Research") < result.index(
        "Multi-Agent Systems"
    )


def test_summarize_arxiv_routes_papers_to_correct_sections(monkeypatch):
    client = _install_fake_client(monkeypatch, lambda cid: f"section for {cid}")

    summarize_arxiv_content([_CODING, _NON_CODING])

    requests = {r["custom_id"]: r for r in client.messages.batches.last_requests}
    coding_content = requests["arxiv-coding"]["params"]["messages"][0]["content"]
    digest_content = requests["arxiv-digest"]["params"]["messages"][0]["content"]
    assert _CODING["title"] in coding_content
    assert _CODING["title"] not in digest_content
    assert _NON_CODING["title"] in digest_content
    assert _NON_CODING["title"] not in coding_content


def test_summarize_arxiv_no_coding_section_when_none(monkeypatch):
    client = _install_fake_client(monkeypatch, lambda cid: f"section for {cid}")

    result = summarize_arxiv_content([_NON_CODING])

    custom_ids = {r["custom_id"] for r in client.messages.batches.last_requests}
    assert custom_ids == {"arxiv-digest"}
    assert "arxiv-coding" not in custom_ids
    assert result == "section for arxiv-digest"


def test_summarize_arxiv_empty_returns_empty(monkeypatch):
    _install_fake_client(monkeypatch, lambda cid: "unused")
    assert summarize_arxiv_content([]) == ""
