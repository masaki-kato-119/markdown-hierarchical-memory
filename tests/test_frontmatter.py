from mdmem import frontmatter


def test_roundtrip():
    fm = {"id": "a", "tags": ["x", "y"], "importance": 0.5}
    body = "# Title\n\nHello world.\n"
    text = frontmatter.dump(fm, body)
    parsed_fm, parsed_body = frontmatter.parse(text)
    assert parsed_fm == fm
    assert parsed_body == body


def test_missing_frontmatter_returns_empty_dict():
    fm, body = frontmatter.parse("# No front matter\n")
    assert fm == {}
    assert body == "# No front matter\n"


def test_unterminated_frontmatter_is_treated_as_body():
    text = "---\nid: a\nno closing delimiter\n"
    fm, body = frontmatter.parse(text)
    assert fm == {}
    assert body == text
