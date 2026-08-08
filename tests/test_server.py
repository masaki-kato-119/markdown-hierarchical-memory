"""Tests for the MCP tool layer in server.py. FastMCP's @mcp.tool() decorator
returns the original function unchanged, so tools are callable directly.
server.py resolves its root via store.get_root(), which reads MDMEM_ROOT from
the environment -- tests point it at a tmp_path via monkeypatch."""
from mdmem import server


def test_get_server_info_reports_root_from_env(tmp_path, monkeypatch):
    target = tmp_path / "memory"
    monkeypatch.setenv("MDMEM_ROOT", str(target))
    info = server.get_server_info()
    assert info["root"] == str(target.resolve())
    assert info["root_source"] == "MDMEM_ROOT env var"
    assert info["content_file_count"] == 0


def test_get_server_info_counts_content_files(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="x", description="desc")
    info = server.get_server_info()
    assert info["content_file_count"] == 1


def test_list_types_aggregates_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="insights", content="x", description="d1")
    server.create_memory_file(id="b", dir="projects", type="insights", content="x", description="d2")
    server.create_memory_file(id="c", dir="concepts", type="concept", content="x", description="d3")
    assert server.list_types() == {"insights": 2, "concept": 1}


def test_list_actors_counts_log_entries(tmp_path, monkeypatch):
    # `actor` lives only in the change log, so unlike `type` it cannot be read off
    # the files -- and with nothing surfacing it, one real store drifted to eight
    # spellings for what were a handful of agents.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="x", description="d", actor="cursor")
    server.create_memory_file(id="b", dir="projects", type="project", content="x", description="d", actor="claude")
    server.append_to_memory_file(id="b", content="more\n", actor="claude")
    assert server.list_actors() == {"claude": 2, "cursor": 1}


def test_writes_are_logged_under_the_configured_client(tmp_path, monkeypatch):
    # Regression: every mutating tool defaulted actor to the literal "claude", so a
    # write from any other client was recorded as Claude's.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    monkeypatch.setenv("MDMEM_ACTOR", "cursor")
    server.create_memory_file(id="a", dir="projects", type="project", content="x", description="d")
    assert server.list_actors() == {"cursor": 1}


def test_a_named_role_keeps_the_client_alongside_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    monkeypatch.setenv("MDMEM_ACTOR", "cursor")
    server.create_memory_file(
        id="a", dir="projects", type="project", content="x", description="d",
        actor="memory-manager",
    )
    assert server.list_actors() == {"cursor/memory-manager": 1}


def test_get_server_info_reports_the_logging_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    monkeypatch.setenv("MDMEM_ACTOR", "cursor")
    assert server.get_server_info()["actor"] == "cursor"


def test_list_actors_is_empty_before_anything_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    assert server.list_actors() == {}


def test_check_archive_candidates_accepts_a_days_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="x", description="d")
    assert server.check_archive_candidates() == []
    assert [c["id"] for c in server.check_archive_candidates(days=-1)] == ["a"]


def test_list_dirs_returns_allowed_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    assert server.list_dirs() == ["concepts", "howto", "projects", "reference"]


def test_create_memory_file_reports_similar_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(
        id="hybrid-rag-overview", dir="projects", type="project-overview",
        content="# HybridRAG\nDense and sparse retrieval with RRF fusion.",
        description="HybridRAG library overview",
    )
    result = server.create_memory_file(
        id="hybrid-rag-overview-2", dir="projects", type="project-overview",
        content="# HybridRAG again\nDense and sparse retrieval with RRF fusion.",
        description="HybridRAG library overview",
    )
    assert any(s["id"] == "hybrid-rag-overview" for s in result["similar_existing"])


def test_create_memory_file_similar_existing_excludes_self(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    result = server.create_memory_file(
        id="a", dir="projects", type="project", content="unique content here", description="unique desc"
    )
    assert all(s["id"] != "a" for s in result["similar_existing"])


def test_update_metadata_tool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="insight", content="x", description="d")
    updated = server.update_metadata(id="a", type="insights")
    assert updated["frontmatter"]["type"] == "insights"


def test_get_links_reports_parent_based_backlink(tmp_path, monkeypatch):
    # Regression: get_links's backward previously came only from broad
    # extract_links over body text, ignoring the `parent` frontmatter field
    # entirely -- despite the tool's own docstring promising parent-based
    # backlinks. A file with parent=["a"] and no body mention of "a" should
    # still show up as a's backlink.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\nno mention of b here\n", description="desc a")
    server.create_memory_file(id="b", dir="projects", type="project", content="# B\n", description="desc b", parent=["a"])
    links = server.get_links(id="a")
    assert links["backward"] == ["b"]


def test_get_links_ignores_prose_mention_as_forward_link(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(
        id="a", dir="projects", type="project",
        content="# A\n\nsee [[b]] mentioned inline, not as a real link.\n", description="desc a",
    )
    server.create_memory_file(id="b", dir="projects", type="project", content="# B\n", description="desc b")
    links = server.get_links(id="a")
    assert links["forward"] == []


def test_get_links_reports_structural_forward_link(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="desc a")
    server.create_memory_file(id="b", dir="projects", type="project", content="# B\n", description="desc b")
    server.link_memory_files(from_id="a", to_id="b")
    links = server.get_links(id="a")
    assert links["forward"] == ["b"]


def test_append_past_threshold_returns_attention(tmp_path, monkeypatch):
    # The passive `size_level` field alone did not stop a real file reaching 1126
    # lines over six appends, so a write that crosses §5's 300-line threshold has
    # to say so in words.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d")
    result = server.append_to_memory_file(id="a", content="filler line\n" * 350)
    assert result["size_level"] == 3
    assert "split_memory_file" in result["attention"]


def test_append_past_section_mark_returns_milder_attention(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d")
    result = server.append_to_memory_file(id="a", content="filler line\n" * 150)
    assert result["size_level"] == 2
    assert "Organize it" in result["attention"]


def test_already_sectioned_file_gets_no_mid_size_attention(tmp_path, monkeypatch):
    # §5's prescription at this size is "organize into sections". Ten of the twelve
    # files in the first real audit already were, so the nudge had nothing to ask
    # for -- and advice that never needs acting on is what got size_level ignored.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d")
    result = server.append_to_memory_file(id="a", content="## Section\n" + "line\n" * 150)
    assert result["size_level"] == 2
    assert "attention" not in result


def test_small_append_carries_no_attention(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d")
    result = server.append_to_memory_file(id="a", content="one more line\n")
    assert "attention" not in result


def test_read_does_not_carry_attention(tmp_path, monkeypatch):
    # Advice only rides along with the writes that caused the growth; on reads it
    # would be ambient noise, which is how `size_level` came to be ignored.
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d")
    server.append_to_memory_file(id="a", content="filler line\n" * 350)
    assert "attention" not in server.read_memory_file(id="a")


def test_unlink_memory_files_tool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MDMEM_ROOT", str(tmp_path / "memory"))
    server.create_memory_file(id="a", dir="projects", type="project", content="# A\n", description="d1")
    server.create_memory_file(id="b", dir="projects", type="project", content="# B\n", description="d2")
    server.link_memory_files(from_id="a", to_id="b")
    result = server.unlink_memory_files(from_id="a", to_id="b")
    assert result["to"]["frontmatter"]["parent"] == []
