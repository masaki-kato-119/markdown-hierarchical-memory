from mdmem import index as index_mod


def test_upsert_and_read_roundtrip(root):
    index_mod.upsert_entry(root, "a", "desc a", tags=["x", "y"])
    index_mod.upsert_entry(root, "b", "desc b")
    entries = index_mod.read_index(root)
    by_id = {e.id: e for e in entries}
    assert by_id["a"].description == "desc a"
    assert by_id["a"].tags == ["x", "y"]
    assert by_id["b"].tags == []
    assert not by_id["a"].archived


def test_upsert_updates_existing_entry(root):
    index_mod.upsert_entry(root, "a", "first")
    index_mod.upsert_entry(root, "a", "second", tags=["z"])
    entries = index_mod.read_index(root)
    assert len(entries) == 1
    assert entries[0].description == "second"
    assert entries[0].tags == ["z"]


def test_mark_archived_keeps_entry_visible(root):
    index_mod.upsert_entry(root, "a", "desc a")
    index_mod.mark_archived(root, "a")
    entries = index_mod.read_index(root)
    assert entries[0].archived is True
    assert entries[0].id == "a"
