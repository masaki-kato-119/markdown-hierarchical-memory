from mdmem import manager
from mdmem.health import check_health
from mdmem.store import write_file


def test_clean_store_reports_nothing(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    report = check_health(root)
    assert report["oversized"] == []
    assert report["orphans"] == []
    assert report["index_missing_entry"] == []
    assert report["index_stale_entry"] == []
    assert report["one_sided_links"] == []
    assert report["broken_links"] == []
    assert report["checked_file_count"] == 2


def test_reports_file_already_past_threshold(root):
    # The write-time `attention` nudge only fires on the write that crosses the
    # line, so a file that grew and was then left alone is only visible here.
    manager.create_file(root, "big", "projects", "project", "line\n" * 400, "desc")
    oversized = check_health(root)["oversized"]
    assert [o["id"] for o in oversized] == ["big"]
    assert oversized[0]["size_level"] == 3
    assert "split_memory_file" in oversized[0]["attention"]


def test_oversized_sorted_by_size(root):
    manager.create_file(root, "big", "projects", "project", "line\n" * 400, "d1")
    manager.create_file(root, "mid", "projects", "project", "line\n" * 150, "d2")
    assert [o["id"] for o in check_health(root)["oversized"]] == ["big", "mid"]


def test_reports_orphan(root):
    manager.create_file(root, "lonely", "projects", "project", "# Lonely\n", "desc")
    assert check_health(root)["orphans"] == ["lonely"]


def test_linked_file_is_not_an_orphan(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b")
    manager.link_files(root, "a", "b")
    assert check_health(root)["orphans"] == []


def test_reports_index_entry_without_file(root):
    manager.create_file(root, "gone", "projects", "project", "# Gone\n", "desc")
    (root / "projects" / "gone.md").unlink()
    report = check_health(root)
    assert report["index_stale_entry"] == ["gone"]
    assert report["index_missing_entry"] == []


def test_reports_file_without_index_entry(root):
    # A file written outside create_memory_file never reaches index.md (§14).
    manager.create_file(root, "known", "projects", "project", "# Known\n", "desc")
    write_file(
        root / "projects" / "unregistered.md",
        {"id": "unregistered", "type": "project", "parent": []},
        "# Unregistered\n",
    )
    assert check_health(root)["index_missing_entry"] == ["unregistered"]


def _write_raw(root, id, body, parent=None):
    """Write a file straight to disk, bypassing create_file's §12 guarantees.

    This is how the damaged states actually arise -- hand edits, or files written
    by an older version of the code -- and it is the only way to produce them now
    that create_file links both ways.
    """
    write_file(
        root / "projects" / f"{id}.md",
        {"id": id, "type": "project", "parent": list(parent or [])},
        body,
    )


def test_reports_parent_without_forward_link(root):
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    _write_raw(root, "b", "# B\n", parent=["a"])
    assert check_health(root)["one_sided_links"] == [
        {
            "from": "a",
            "to": "b",
            "has_forward": False,
            "has_backward": True,
            "prose_mention_only": False,
        }
    ]


def test_distinguishes_prose_mention_from_missing_link(root):
    # An older link_files skipped writing the structural line when a prose
    # mention already existed; those files still need promoting, not creating.
    manager.create_file(
        root, "a", "projects", "project", "# A\n\n詳細は [[b]] を参照。\n", "desc a"
    )
    _write_raw(root, "b", "# B\n", parent=["a"])
    one_sided = check_health(root)["one_sided_links"]
    assert len(one_sided) == 1
    assert one_sided[0]["prose_mention_only"] is True


def test_create_with_parent_is_not_reported_as_one_sided(root):
    # Regression for the six real one-sided links create_file itself produced.
    manager.create_file(root, "a", "projects", "project", "# A\n", "desc a")
    manager.create_file(root, "b", "projects", "project", "# B\n", "desc b", parent=["a"])
    assert check_health(root)["one_sided_links"] == []


def test_reports_reference_to_missing_id(root):
    manager.create_file(
        root, "a", "projects", "project", "# A\n\n- [[ghost]]\n", "desc a"
    )
    assert check_health(root)["broken_links"] == [
        {"from": "a", "to": "ghost", "kind": "reference"}
    ]


def test_reports_parent_pointing_at_missing_id(root):
    _write_raw(root, "a", "# A\n", parent=["ghost"])
    assert check_health(root)["broken_links"] == [
        {"from": "a", "to": "ghost", "kind": "parent"}
    ]


def test_archived_file_is_excluded_from_size_and_orphan_checks(root):
    manager.create_file(root, "big", "projects", "project", "line\n" * 400, "desc")
    manager.move_to_archive(root, "big")
    report = check_health(root)
    assert report["oversized"] == []
    assert report["orphans"] == []
