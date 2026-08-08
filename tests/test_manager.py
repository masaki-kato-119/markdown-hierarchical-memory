import pytest

from mdmem import manager, models
from mdmem.errors import ConflictError, NotFoundError, ValidationError


def test_create_file_registers_in_index(root):
    mf = manager.create_file(root, "a", "projects", "project", "# A\nbody\n", "desc a", tags=["t1"])
    assert mf.fm["id"] == "a"
    assert mf.fm["access_count"] == 0
    from mdmem.index import read_index

    entries = read_index(root)
    assert entries[0].id == "a"
    assert entries[0].description == "desc a"


def test_create_file_rejects_duplicate_id(root):
    manager.create_file(root, "a", "projects", "project", "content", "desc")
    with pytest.raises(ValidationError):
        manager.create_file(root, "a", "concepts", "concept", "other content", "desc2")


def test_create_file_rejects_unknown_dir(root):
    with pytest.raises(ValidationError):
        manager.create_file(root, "a", "tools", "insights", "content", "desc")


def test_create_file_rejects_path_traversal_id(root):
    # Security regression: id was previously used unsanitized in
    # root / dir / f"{id}.md", allowing writes outside the memory root.
    with pytest.raises(ValidationError):
        manager.create_file(root, "../../evil_outside_root", "projects", "project", "pwned", "desc")
    escaped = root.parent.parent / "evil_outside_root.md"
    assert not escaped.exists()


def test_create_file_rejects_id_with_path_separator(root):
    with pytest.raises(ValidationError):
        manager.create_file(root, "sub/evil", "projects", "project", "content", "desc")


def test_create_file_accepts_hyphen_and_underscore_ids(root):
    mf = manager.create_file(root, "valid_id-123", "projects", "project", "content", "desc")
    assert mf.fm["id"] == "valid_id-123"


def test_append_to_file_end_of_body(root):
    manager.create_file(root, "a", "projects", "project", "# A\n\nintro\n", "desc")
    mf = manager.append_to_file(root, "a", "more text")
    assert mf.body.strip().endswith("more text")


def test_append_to_section(root):
    manager.create_file(root, "a", "projects", "project", "# A\n\n## Notes\nfirst\n\n## Other\nx\n", "desc")
    mf = manager.append_to_file(root, "a", "second", section="Notes")
    assert "## Notes\nfirst\nsecond" in mf.body
    assert mf.body.index("## Notes") < mf.body.index("## Other")


def test_append_to_missing_section_raises(root):
    manager.create_file(root, "a", "projects", "project", "# A\n\n## Real\nx\n", "desc")
    with pytest.raises(NotFoundError) as exc_info:
        manager.append_to_file(root, "a", "x", section="Nope")
    assert "Real" in str(exc_info.value)


def test_append_conflict_on_stale_expected_updated(root):
    mf = manager.create_file(root, "a", "projects", "project", "body", "desc")
    stale = mf.fm["updated"]
    manager.append_to_file(root, "a", "first edit")  # bumps `updated`
    with pytest.raises(ConflictError):
        manager.append_to_file(root, "a", "second edit", expected_updated=stale)


def test_update_metadata_changes_type_tags_importance_pinned(root):
    manager.create_file(root, "a", "projects", "insight", "body", "desc", tags=["x"], importance=0.5)
    mf = manager.update_metadata(root, "a", type="insights", tags=["x", "y"], importance=0.9, pinned=True)
    assert mf.fm["type"] == "insights"
    assert mf.fm["tags"] == ["x", "y"]
    assert mf.fm["importance"] == 0.9
    assert mf.fm["pinned"] is True


def test_update_metadata_syncs_tags_into_index(root):
    manager.create_file(root, "a", "projects", "project", "body", "desc", tags=["old"])
    manager.update_metadata(root, "a", tags=["new"])
    from mdmem.index import read_index

    entry = next(e for e in read_index(root) if e.id == "a")
    assert entry.tags == ["new"]
    assert entry.description == "desc"


def test_update_metadata_moves_dir_and_id_still_resolves(root):
    manager.create_file(root, "a", "projects", "project-overview", "body", "desc")
    mf = manager.update_metadata(root, "a", dir="concepts")
    assert mf.path.parent.name == "concepts"
    assert manager.get_and_touch(root, "a").id == "a"


def test_update_metadata_rejects_unknown_dir(root):
    manager.create_file(root, "a", "projects", "project", "body", "desc")
    with pytest.raises(ValidationError):
        manager.update_metadata(root, "a", dir="tools")


def test_update_metadata_conflict_on_stale_expected_updated(root):
    mf = manager.create_file(root, "a", "projects", "project", "body", "desc")
    stale = mf.fm["updated"]
    manager.update_metadata(root, "a", importance=0.9)
    with pytest.raises(ConflictError):
        manager.update_metadata(root, "a", importance=0.1, expected_updated=stale)


def test_create_file_accepts_howto_dir(root):
    # The store already contained a memory/howto/ file this validation rejected.
    mf = manager.create_file(root, "a", "howto", "howto", "# A\n", "desc")
    assert mf.path.parent.name == "howto"


def test_split_file_extracts_several_sections_into_one_file(root):
    manager.create_file(
        root, "src", "reference", "reference",
        "# Src\n\n## Keep\nk\n\n## Sound A\na\n\n## Other\no\n\n## Sound B\nb\n",
        "desc",
    )
    source, new = manager.split_file(
        root, "src", "sound", "reference", "reference", "sound notes",
        sections_to_extract=["Sound A", "Sound B"],
    )
    assert "## Sound A" in new.body and "## Sound B" in new.body
    assert "## Sound A" not in source.body and "## Sound B" not in source.body
    assert "## Keep" in source.body and "## Other" in source.body


def test_split_file_rejects_both_section_arguments(root):
    manager.create_file(root, "src", "reference", "reference", "# S\n\n## A\na\n", "desc")
    with pytest.raises(ValidationError):
        manager.split_file(
            root, "src", "new", "reference", "reference", "d",
            section_to_extract="A", sections_to_extract=["A"],
        )


def test_split_file_names_the_missing_section(root):
    manager.create_file(root, "src", "reference", "reference", "# S\n\n## A\na\n", "desc")
    with pytest.raises(NotFoundError, match="ghost"):
        manager.split_file(
            root, "src", "new", "reference", "reference", "d",
            sections_to_extract=["A", "ghost"],
        )


def test_create_file_with_parent_writes_both_sides(root):
    # `parent` used to be recorded on the child only, which is the one-sided link
    # §12 forbids -- reachable through an ordinary documented call.
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    child = manager.create_file(
        root, "b", "projects", "project", "# B\n", "desc b", parent=["a"]
    )
    assert child.fm["parent"] == ["a"]
    assert "- [[b]]" in manager.require_by_id(root, "a").body


def test_create_file_with_multiple_parents_links_each(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.create_file(
        root, "c", "projects", "project", "# C\n", "desc c", parent=["a", "b"]
    )
    assert "- [[c]]" in manager.require_by_id(root, "a").body
    assert "- [[c]]" in manager.require_by_id(root, "b").body


def test_create_file_rejects_unknown_parent(root):
    with pytest.raises(NotFoundError):
        manager.create_file(
            root, "b", "projects", "project", "# B\n", "desc b", parent=["ghost"]
        )


def test_create_file_leaves_nothing_behind_when_parent_is_unknown(root):
    with pytest.raises(NotFoundError):
        manager.create_file(
            root, "b", "projects", "project", "# B\n", "desc b", parent=["ghost"]
        )
    assert not (root / "projects" / "b.md").exists()
    assert manager.find_by_id(root, "b") is None


def test_link_files_is_bidirectional(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    from_mf, to_mf = manager.link_files(root, "a", "b")
    assert "b" in from_mf.body or "[[b]]" in from_mf.body
    assert to_mf.fm["parent"] == ["a"]


def test_link_files_adds_structural_line_even_if_prose_already_mentions_target(root):
    # Regression: _ensure_link_line previously used extract_links (broad match),
    # so an incidental [[b]] mention in prose made it think a real link already
    # existed and skipped adding the structural "- [[b]]" line.
    manager.create_file(
        root, "a", "projects", "project",
        "# A\n\nbackground: [[b]] mentioned here inline.\n", "desc a",
    )
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    from_mf, to_mf = manager.link_files(root, "a", "b")
    assert "- [[b]]" in from_mf.body
    assert to_mf.fm["parent"] == ["a"]


def test_link_files_is_idempotent(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    from_mf, to_mf = manager.link_files(root, "a", "b")
    assert from_mf.body.count("[[b]]") == 1
    assert to_mf.fm["parent"] == ["a"]


def test_unlink_files_removes_bidirectional_link(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    from_mf, to_mf = manager.unlink_files(root, "a", "b")
    assert "[[b]]" not in from_mf.body
    assert to_mf.fm["parent"] == []


def test_unlink_files_preserves_other_parents(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "c", "projects", "project", "# C\n", "desc c")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    manager.link_files(root, "c", "b")
    _, to_mf = manager.unlink_files(root, "a", "b")
    assert to_mf.fm["parent"] == ["c"]


def test_unlink_files_succeeds_when_only_inline_prose_mention_remains(root):
    # Regression test: a body can mention [[to_id]] inline inside prose
    # (not as the standalone "- [[to_id]]" line link_files produces). The
    # self-check must not treat that leftover prose mention as a failure --
    # only the standalone line is link_files/unlink_files's concern.
    manager.create_file(
        root, "a", "projects", "project",
        "# A\n\nSee also (background: [[b]]) for context.\n", "desc a",
    )
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    from_mf, to_mf = manager.unlink_files(root, "a", "b")
    assert "(background: [[b]])" in from_mf.body  # inline prose left untouched
    assert to_mf.fm["parent"] == []


def test_unlink_files_conflict_on_stale_expected_updated(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    from_mf, _ = manager.link_files(root, "a", "b")
    stale = from_mf.fm["updated"]
    manager.append_to_file(root, "a", "unrelated edit")  # bumps `updated` again
    with pytest.raises(ConflictError):
        manager.unlink_files(root, "a", "b", expected_updated_from=stale)


def test_split_file_creates_bidirectional_link_and_removes_section(root):
    manager.create_file(
        root, "a", "projects", "project",
        "# A\n\n## Detail\nsome detail text\n\n## Other\nkeep me\n",
        "desc a",
    )
    source_mf, new_mf = manager.split_file(
        root, source_id="a", new_id="a_detail", new_dir="projects", new_type="project",
        new_description="split-out detail", section_to_extract="Detail",
    )
    assert "## Detail" not in source_mf.body
    assert "## Other" in source_mf.body
    assert new_mf.fm["parent"] == ["a"]
    assert "some detail text" in new_mf.body
    assert "a_detail" in source_mf.body  # backlink present on source side too


def test_split_file_rolls_back_on_failure_after_create(root, monkeypatch):
    # Regression: create_file -> source rewrite -> link_files had no rollback.
    # A failure in link_files previously left an orphaned, unlinked new file
    # (and, if the section had already been removed from the source, no copy
    # of that content left anywhere). Force link_files to fail and verify the
    # source is restored and the new file/index entry are cleaned up.
    manager.create_file(
        root, "a", "projects", "project",
        "# A\n\n## Detail\nsome detail text\n\n## Other\nkeep me\n",
        "desc a",
    )

    def boom(*args, **kwargs):
        raise RuntimeError("simulated link_files failure")

    monkeypatch.setattr(manager, "link_files", boom)

    with pytest.raises(RuntimeError):
        manager.split_file(
            root, source_id="a", new_id="a_detail", new_dir="projects", new_type="project",
            new_description="split-out detail", section_to_extract="Detail",
        )

    source_mf = manager.require_by_id(root, "a")
    assert "## Detail" in source_mf.body
    assert "some detail text" in source_mf.body
    from mdmem.store import find_by_id

    assert find_by_id(root, "a_detail") is None
    from mdmem.index import read_index

    assert all(e.id != "a_detail" for e in read_index(root))


def test_summarize_and_archive_moves_file_and_keeps_index_visible(root):
    manager.create_file(root, "a", "projects", "project", "long content", "desc a")
    archived = manager.summarize_and_archive(root, "a", "short summary", "desc a (archived)")
    assert archived.is_archived
    assert archived.body == "short summary"
    from mdmem.index import read_index

    entry = next(e for e in read_index(root) if e.id == "a")
    assert entry.archived


def test_move_to_archive_preserves_content(root):
    manager.create_file(root, "a", "projects", "project", "keep this content\n", "desc a")
    archived = manager.move_to_archive(root, "a")
    assert archived.is_archived
    assert "keep this content" in archived.body


def test_move_to_archive_leaves_no_file_at_original_path(root):
    manager.create_file(root, "a", "projects", "project", "content\n", "desc a")
    archived = manager.move_to_archive(root, "a")
    original_path = archived.path.parent.parent / "projects" / "a.md"
    assert not original_path.exists()

    # exactly one file resolves to this id -- no transient duplicate
    matches = [mf for mf in manager.load_all(root) if mf.id == "a"]
    assert len(matches) == 1


def test_summarize_and_archive_leaves_no_file_at_original_path(root):
    manager.create_file(root, "a", "projects", "project", "long content", "desc a")
    manager.summarize_and_archive(root, "a", "short summary", "desc a (archived)")
    matches = [mf for mf in manager.load_all(root) if mf.id == "a"]
    assert len(matches) == 1
    assert matches[0].is_archived


def test_get_and_touch_rereads_before_writing_back(root, monkeypatch):
    # Regression: get_and_touch wrote back the body/fm captured by
    # require_by_id's scan, so a concurrent append landing after that scan
    # but before this function's own write got silently reverted (lost
    # update), and since `updated` isn't advanced, optimistic locking
    # elsewhere didn't catch it. Simulate the race by pinning require_by_id
    # to a stale snapshot, then let a "concurrent" append land before the
    # (now re-reading) get_and_touch writes.
    manager.create_file(root, "a", "projects", "project", "original body", "desc")
    stale_mf = manager.require_by_id(root, "a")
    monkeypatch.setattr(manager, "require_by_id", lambda root, id: stale_mf)

    manager.append_to_file(root, "a", "concurrent append")
    touched = manager.get_and_touch(root, "a")

    assert "concurrent append" in touched.body
    assert touched.fm["access_count"] == 1


def test_check_archive_candidates_respects_pinned(root):
    manager.create_file(root, "a", "projects", "project", "x", "desc", pinned=True)
    mf = manager.get_and_touch(root, "a")
    # force it to look old/rarely-accessed except for the pinned flag
    mf.fm["last_access"] = "2020-01-01"
    from mdmem.store import write_file

    write_file(mf.path, mf.fm, mf.body)
    candidates = manager.check_archive_candidates(root)
    assert candidates == []


def _age(root, id, last_access):
    from mdmem.store import write_file

    mf = manager.require_by_id(root, id)
    mf.fm["last_access"] = last_access
    write_file(mf.path, mf.fm, mf.body)


def test_check_archive_candidates_days_is_adjustable(root):
    # The 180-day default cannot fire in a store younger than 180 days, which left
    # no way to see whether the rule behaves as intended before the day it matters.
    manager.create_file(root, "a", "projects", "project", "x", "desc")
    _age(root, "a", "2026-01-01")
    assert manager.check_archive_candidates(root, days=10000) == []
    assert [c["id"] for c in manager.check_archive_candidates(root, days=1)] == ["a"]


def test_check_archive_candidates_defaults_to_the_spec_window(root):
    manager.create_file(root, "a", "projects", "project", "x", "desc")
    _age(root, "a", models.today_date())
    assert manager.check_archive_candidates(root) == []


def test_days_does_not_override_the_access_count_condition(root):
    # §13 is a conjunction: a well-read file is not a candidate however old it is.
    manager.create_file(root, "a", "projects", "project", "x", "desc")
    for _ in range(3):
        manager.get_and_touch(root, "a")
    _age(root, "a", "2020-01-01")
    assert manager.check_archive_candidates(root, days=0) == []
