from src.fetchers.rss import _parse_scraped_title, _strip_html, _truncate


def test_parse_scraped_title_plain():
    _, _, title = _parse_scraped_title("Some Article Title")
    assert title == "Some Article Title"


def test_parse_scraped_title_strips_category():
    _, category, title = _parse_scraped_title("Research Some Article Title")
    assert category == "Research"
    assert title == "Some Article Title"


def test_parse_scraped_title_extracts_date():
    date, _, title = _parse_scraped_title("May 1, 2026 Some Article")
    assert date == "May 1, 2026"
    assert title == "Some Article"


def test_parse_scraped_title_category_and_date():
    date, category, _ = _parse_scraped_title("Announcement January 15, 2026 My Post")
    assert category == "Announcement"
    assert date == "January 15, 2026"


def test_parse_scraped_title_no_metadata():
    date, category, title = _parse_scraped_title("Plain Title")
    assert date == ""
    assert category == ""
    assert title == "Plain Title"


def test_strip_html_removes_tags():
    assert _strip_html("<b>Hello</b> <i>World</i>") == "Hello World"


def test_strip_html_empty():
    assert _strip_html("") == ""


def test_strip_html_nested():
    assert _strip_html("<div><p>Text</p></div>") == "Text"


def test_truncate_short_string_unchanged():
    assert _truncate("hello", max_chars=100) == "hello"


def test_truncate_long_string_adds_ellipsis():
    result = _truncate("a" * 200, max_chars=100)
    assert result.endswith("...")
    assert len(result) == 103


def test_truncate_exact_boundary():
    assert _truncate("a" * 100, max_chars=100) == "a" * 100
