from mdmem import sections


BODY = "# Title\n\n## A\ncontent a\n\n## B\ncontent b\n"


def test_find_section_bounds():
    bounds = sections.find_section_bounds(BODY, "A")
    lines = BODY.splitlines()
    start, end = bounds
    assert lines[start] == "## A"
    assert lines[end] == "## B"


def test_append_under_section():
    new_body = sections.append_under_section(BODY, "A", "- extra")
    assert "## A\ncontent a\n- extra\n\n## B" in new_body


def test_append_under_missing_section_returns_none():
    assert sections.append_under_section(BODY, "Missing", "x") is None


def test_extract_section_removes_it():
    extracted, remaining = sections.extract_section(BODY, "A")
    assert "content a" in extracted
    assert "## A" not in remaining
    assert "## B" in remaining


def test_list_headings_returns_all_heading_texts_in_order():
    assert sections.list_headings(BODY) == ["Title", "A", "B"]


def test_list_headings_empty_body():
    assert sections.list_headings("") == []
