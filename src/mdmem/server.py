"""MCP server exposing the mechanical layer of markdown-hierarchical-memory-spec.md.

Deliberately NOT included here: any judgment about semantic cohesion, importance,
or "is this worth summarizing". Those calls stay with the connected LLM (see the
`memory-manager` subagent), which calls these tools to carry out its decisions.
Concurrency (spec §16) is enforced via the `expected_updated` parameter on every
mutating tool: pass the `updated` value you last read; a mismatch raises a
conflict error telling you to re-read and retry.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import health
from . import index as index_mod
from . import log as log_mod
from . import manager
from . import models
from .linkgraph import extract_structural_links
from .models import line_count, size_level
from .search import search as search_impl
from .store import MemoryFile, get_root, iter_content_files, load_all, resolve_actor

mcp = FastMCP(
    "mdmem",
    instructions=(
        "Markdown hierarchical memory store (see markdown-hierarchical-memory-spec.md). "
        "Use search_memory/get_index to find files, read_memory_file to fetch full content, "
        "and the mutating tools (append/create/link/split/summarize_and_archive/move_to_archive) "
        "to change them. All mutating tools take expected_updated for optimistic concurrency (§16) "
        "and are logged automatically (§10/§17). Semantic decisions (cohesion, importance, "
        "whether §9's matrix applies) are yours to make -- the server only executes and checks integrity. "
        "When a write pushes a file past a §5 size threshold the result carries an `attention` string: "
        "act on it or consciously decide not to, rather than letting files grow unbounded."
    ),
)


def _mf_to_dict(
    mf: MemoryFile, root: Path, include_body: bool = True, include_attention: bool = False
) -> dict[str, Any]:
    d = {
        "id": mf.id,
        "path": str(mf.path.relative_to(root)),
        "frontmatter": mf.fm,
        "line_count": line_count(mf.body),
        "size_level": size_level(mf.body),
        "archived": mf.is_archived,
    }
    if include_body:
        d["body"] = mf.body
    # Only the tools that just *grew* a file carry the nudge. Attaching it to reads
    # and listings too would make it ambient noise, which is how the plain
    # `size_level` number came to be ignored in the first place.
    if include_attention:
        attention = models.size_attention(mf.body)
        if attention:
            d["attention"] = attention
    return d


@mcp.tool()
def get_server_info() -> dict:
    """Diagnostic: the resolved MDMEM_ROOT path, whether it came from the
    MDMEM_ROOT env var or the "memory" (cwd-relative) default, a content
    file count, and the identity this server logs changes under. Call this first
    when get_index/list_memory_files and read_memory_file seem to disagree -- that
    usually means the caller is talking to a server resolving a different root than
    expected, not a caching problem.

    `actor` reading "unspecified" means MDMEM_ACTOR is unset for this server, so
    every change it logs is unattributable -- set it in the client's mcp.json."""
    root = get_root()
    return {
        "root": str(root),
        "root_source": "MDMEM_ROOT env var" if "MDMEM_ROOT" in os.environ else "default 'memory' (cwd-relative)",
        "content_file_count": sum(1 for _ in iter_content_files(root)),
        "actor": resolve_actor(None),
    }


@mcp.tool()
def get_index() -> list[dict]:
    """Return the pure registry from index.md (id, one-line description, tags,
    archived flag) -- spec §14. Cheap starting point before searching further."""
    root = get_root()
    return [e.__dict__ for e in index_mod.read_index(root)]


@mcp.tool()
def list_memory_files(include_archived: bool = True) -> list[dict]:
    """List every memory file with its front matter and size info, without body
    content. Use to get an overview or to compute §5/§9 size-based decisions."""
    root = get_root()
    out = []
    for mf in load_all(root):
        if not include_archived and mf.is_archived:
            continue
        out.append(_mf_to_dict(mf, root, include_body=False))
    return out


@mcp.tool()
def read_memory_file(id: str) -> dict:
    """Fetch a memory file's full content by id. This counts as an actual
    retrieval, so access_count/last_access are incremented here (spec §11)."""
    root = get_root()
    mf = manager.get_and_touch(root, id)
    return _mf_to_dict(mf, root)


@mcp.tool()
def search_memory(query: str, hop: int = 1, max_results: int = 10) -> list[dict]:
    """Keyword search over id/tags/title/body, then expand `hop` levels through
    the wikilink graph (spec §15 -- default 1-hop; go to 2 only if 1 was
    insufficient). Returns snippets, not full bodies; follow up with
    read_memory_file for the ones you actually need."""
    root = get_root()
    results = search_impl(root, query, hop=hop, max_results=max_results)
    return [r.__dict__ for r in results]


@mcp.tool()
def get_links(id: str) -> dict:
    """Return the forward links (standalone `- [[id]]` lines in this file's
    body -- the shape link_files/unlink_files manage) and backlinks (files
    whose front matter lists this id as parent, or that structurally link to
    it) for `id`. Useful before deciding whether a link is one-sided (§12).
    An [[id]] mention embedded in prose does not count as a link here --
    that's search_memory's job (its hop expansion intentionally matches any
    mention, structural or not)."""
    root = get_root()
    files = load_all(root)
    target = next((mf for mf in files if mf.id == id), None)
    forward = extract_structural_links(target.body) if target is not None else []
    backward = [
        mf.id for mf in files
        if mf.id != id and (id in (mf.fm.get("parent") or []) or id in extract_structural_links(mf.body))
    ]
    return {"id": id, "forward": forward, "backward": backward}


@mcp.tool()
def list_types() -> dict[str, int]:
    """Existing `type` values in use across all memory files, with counts.
    `type` is free-form (semantic judgment stays with the caller per spec),
    but vocabulary drifts fast without visibility -- call this before
    create_memory_file/update_metadata to reuse an existing value instead of
    introducing a near-duplicate synonym (e.g. "insight" vs "insights")."""
    root = get_root()
    counts: dict[str, int] = {}
    for mf in load_all(root):
        t = mf.fm.get("type", "")
        counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


@mcp.tool()
def list_actors() -> dict[str, int]:
    """Every `actor` value recorded in the change log, with entry counts.

    The counterpart to list_types for the other free-form field. Call it before
    passing `actor` to a mutating tool and reuse an existing value: with nothing
    surfacing them, one real store ended up logging claude / cursor / cursor-auto /
    memory-manager for what were three agents, which makes the log harder to read
    back than it needs to be."""
    return log_mod.list_actors(get_root())


@mcp.tool()
def list_dirs() -> list[str]:
    """Allowed `dir` values for create_memory_file / update_metadata (spec §2
    layout). archive/ is excluded -- it's reserved for move_to_archive /
    summarize_and_archive and is never a valid target for a fresh file."""
    return sorted(models.ALLOWED_DIRS)


@mcp.tool()
def create_memory_file(
    id: str,
    dir: str,
    type: str,
    content: str,
    description: str,
    tags: list[str] | None = None,
    importance: float = 0.5,
    pinned: bool = False,
    parent: list[str] | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Create a new memory file at memory/<dir>/<id>.md with default front matter
    (spec §3), and register it in index.md. Fails if `id` already exists anywhere
    (ids must be unique regardless of file path). The result includes
    `similar_existing`: other files whose id/tags/title/body keyword-match
    `description` -- not a hard block (that would require semantic judgment
    the server doesn't make), but check it before writing near-duplicate
    content under a slightly different id."""
    root = get_root()
    mf = manager.create_file(
        root, id, dir, type, content, description,
        tags=tags, importance=importance, pinned=pinned, parent=parent,
        actor=resolve_actor(actor), rationale=rationale,
    )
    similar = search_impl(root, description, hop=0, max_results=4)
    result = _mf_to_dict(mf, root, include_attention=True)
    result["similar_existing"] = [
        {"id": r.id, "score": r.score, "snippet": r.snippet} for r in similar if r.id != id
    ][:3]
    return result


@mcp.tool()
def append_to_memory_file(
    id: str,
    content: str,
    section: str | None = None,
    expected_updated: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Append `content` to file `id` (spec §4 step1: append when same theme /
    supplements existing info / still within size). If `section` is given,
    inserts at the end of that heading's content instead of end-of-file.
    Pass `expected_updated` (from a prior read) to avoid clobbering a concurrent
    write (§16); on conflict, re-read and retry.

    If the append pushes the file past a §5 size threshold the result carries an
    `attention` string. It is advice, not an error — but read it and decide, rather
    than letting the file grow unbounded across many appends."""
    root = get_root()
    mf = manager.append_to_file(
        root, id, content, section=section, expected_updated=expected_updated,
        actor=resolve_actor(actor), rationale=rationale,
    )
    return _mf_to_dict(mf, root, include_attention=True)


@mcp.tool()
def update_metadata(
    id: str,
    type: str | None = None,
    tags: list[str] | None = None,
    importance: float | None = None,
    pinned: bool | None = None,
    dir: str | None = None,
    expected_updated: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Update an existing file's type/tags/importance/pinned, and/or move it to
    a different `dir` (must be one of concepts/projects/reference). Fields left
    as None are unchanged. Use this instead of hand-editing markdown files --
    direct edits bypass the change log (§10/§17). Pass expected_updated for
    optimistic concurrency (§16), same as the other mutating tools."""
    root = get_root()
    mf = manager.update_metadata(
        root, id, type=type, tags=tags, importance=importance, pinned=pinned, dir=dir,
        expected_updated=expected_updated, actor=resolve_actor(actor), rationale=rationale,
    )
    return _mf_to_dict(mf, root)


@mcp.tool()
def link_memory_files(
    from_id: str,
    to_id: str,
    section: str | None = None,
    expected_updated_from: str | None = None,
    expected_updated_to: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Create a bidirectional link from_id -> to_id as one atomic operation
    (spec §12): adds [[to_id]] into from_id's body (under `section` if given)
    AND adds from_id to to_id's `parent` list. Self-checks both sides after
    writing and raises rather than leaving a one-sided link."""
    root = get_root()
    from_mf, to_mf = manager.link_files(
        root, from_id, to_id, section=section,
        expected_updated_from=expected_updated_from, expected_updated_to=expected_updated_to,
        actor=resolve_actor(actor), rationale=rationale,
    )
    return {"from": _mf_to_dict(from_mf, root), "to": _mf_to_dict(to_mf, root)}


@mcp.tool()
def unlink_memory_files(
    from_id: str,
    to_id: str,
    expected_updated_from: str | None = None,
    expected_updated_to: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Inverse of link_memory_files: removes the `[[to_id]]` reference from
    from_id's body and removes from_id from to_id's parent list, as one atomic
    operation. Use to correct a stale parent link (e.g. after archiving a
    duplicate and re-pointing to the surviving file)."""
    root = get_root()
    from_mf, to_mf = manager.unlink_files(
        root, from_id, to_id,
        expected_updated_from=expected_updated_from, expected_updated_to=expected_updated_to,
        actor=resolve_actor(actor), rationale=rationale,
    )
    return {"from": _mf_to_dict(from_mf, root), "to": _mf_to_dict(to_mf, root)}


@mcp.tool()
def split_memory_file(
    source_id: str,
    new_id: str,
    new_dir: str,
    new_type: str,
    new_description: str,
    section_to_extract: str | None = None,
    extracted_content: str | None = None,
    new_tags: list[str] | None = None,
    importance: float = 0.5,
    expected_updated: str | None = None,
    actor: str | None = None,
    rationale: str = "",
    sections_to_extract: list[str] | None = None,
) -> dict:
    """Split part of `source_id` out into a new file `new_id` (spec §9/§10
    split action). Name one existing heading via `section_to_extract`, or several
    via `sections_to_extract` (each is removed from the source; the new file keeps
    them in document order), or supply `extracted_content` directly and leave the
    source body untouched. Wires up the bidirectional link (§12) and index.md
    entry automatically.

    Prefer `sections_to_extract` when a theme accumulated across several appends
    under different headings, which is the usual shape -- extracting them one at a
    time would scatter one topic across several thin files."""
    root = get_root()
    source_mf, new_mf = manager.split_file(
        root, source_id, new_id, new_dir, new_type, new_description,
        section_to_extract=section_to_extract, extracted_content=extracted_content,
        new_tags=new_tags, importance=importance, expected_updated=expected_updated,
        actor=resolve_actor(actor), rationale=rationale, sections_to_extract=sections_to_extract,
    )
    return {
        "source": _mf_to_dict(source_mf, root, include_attention=True),
        "new": _mf_to_dict(new_mf, root, include_attention=True),
    }


@mcp.tool()
def summarize_and_archive_memory_file(
    id: str,
    summary_content: str,
    description_for_index: str,
    expected_updated: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Replace `id`'s content with `summary_content` and physically move it to
    archive/ (spec §5/§9/§13). index.md keeps the link with an (archived)
    marker -- never fully deleted. Use when importance x reference-frequency
    is low but the content still has some value; get explicit user confirmation
    first per §11 before calling this."""
    root = get_root()
    mf = manager.summarize_and_archive(
        root, id, summary_content, description_for_index,
        expected_updated=expected_updated, actor=resolve_actor(actor), rationale=rationale,
    )
    return _mf_to_dict(mf, root)


@mcp.tool()
def move_to_archive(
    id: str,
    expected_updated: str | None = None,
    actor: str | None = None,
    rationale: str = "",
) -> dict:
    """Physically move `id` to archive/ without changing its content (spec §13
    plain forget model). index.md keeps the link marked (archived)."""
    root = get_root()
    mf = manager.move_to_archive(root, id, expected_updated=expected_updated, actor=resolve_actor(actor), rationale=rationale)
    return _mf_to_dict(mf, root)


@mcp.tool()
def check_health() -> dict:
    """Audit the whole store and report what needs attention, without changing
    anything. Covers files past a §5 size threshold, orphans (nothing links to
    them and they link to nothing, so §15's hop expansion can never reach them),
    index.md entries that disagree with disk (§14), one-sided links and links to
    ids that no longer exist (§12).

    Use this as the entry point for "tidy up the memory". It complements the
    `attention` field on writes, which only fires on the write that crosses a
    threshold -- a file that is already oversized and simply not being appended
    to any more will never announce itself, and shows up only here.

    Reporting only. Deciding what to split, summarize, relink or archive stays
    with you (§11/§17); for the forgetting condition specifically, see
    check_archive_candidates."""
    return health.check_health(get_root())


@mcp.tool()
def check_archive_candidates(days: int = models.FORGET_AFTER_DAYS) -> list[dict]:
    """Report files matching spec §13's forget condition (access_count < 3 AND
    last_access older than `days` AND not pinned). This only reports candidates --
    per §11, actually archiving requires an explicit follow-up call after user
    confirmation, never automatic action on this result alone.

    `days` defaults to the spec's 180. Pass a smaller value to inspect what the rule
    would catch: in a store younger than that the default cannot return anything at
    all, so there is otherwise no way to see how it behaves until the day it starts
    firing on real files."""
    root = get_root()
    return manager.check_archive_candidates(root, days=days)


@mcp.tool()
def get_change_log(limit: int = 20) -> str:
    """Return the tail of archive/_manager_log.md (spec §10/§17), for reviewing
    or manually reverting past Manager Agent decisions."""
    root = get_root()
    path = log_mod.log_path(root)
    if not path.exists():
        return ""
    entries = path.read_text(encoding="utf-8").split("\n## ")
    header = entries[0]
    tail = ["## " + e for e in entries[1:][-limit:]]
    return header + "\n".join(tail)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
