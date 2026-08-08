import pytest

from mdmem import sections
from mdmem.errors import ValidationError


_MULTI = "# T\n\n## A\na1\n\n## B\nb1\n\n## C\nc1\n"


def test_extract_sections_takes_several_at_once():
    extracted, remaining = sections.extract_sections(_MULTI, ["A", "C"])
    assert extracted == "## A\na1\n\n## C\nc1"
    assert "## A" not in remaining and "## C" not in remaining
    assert "## B" in remaining


def test_extract_sections_keeps_document_order():
    # A theme worth splitting out usually accumulated across several appends, so
    # the caller names headings in whatever order they thought of them.
    extracted, _ = sections.extract_sections(_MULTI, ["C", "A"])
    assert extracted.index("## A") < extracted.index("## C")


def test_extract_sections_is_all_or_nothing_on_a_missing_heading():
    assert sections.extract_sections(_MULTI, ["A", "nope"]) is None


def test_extract_section_leaves_file_level_links_behind():
    # link_files appends `- [[x]]` at end of body, so it lands inside whatever
    # section is last. Splitting that section used to carry the file's links away.
    body = "# T\n\n## A\na1\n\n## Last\nl1\n\n- [[other]]\n"
    extracted, remaining = sections.extract_section(body, "Last")
    assert "[[other]]" not in extracted
    assert "- [[other]]" in remaining


def test_extract_sections_leaves_file_level_links_behind():
    body = "# T\n\n## A\na1\n\n## Last\nl1\n\n- [[other]]\n"
    extracted, remaining = sections.extract_sections(body, ["A", "Last"])
    assert "[[other]]" not in extracted
    assert "- [[other]]" in remaining


def test_extract_section_keeps_a_trailing_list_that_is_not_links():
    body = "# T\n\n## Last\n- a plain bullet\n"
    extracted, _ = sections.extract_section(body, "Last")
    assert "- a plain bullet" in extracted


def test_extract_sections_rejects_nested_overlap():
    body = "# T\n\n## Outer\nx\n\n### Inner\ny\n\n## Other\nz\n"
    with pytest.raises(ValidationError):
        sections.extract_sections(body, ["Outer", "Inner"])


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
