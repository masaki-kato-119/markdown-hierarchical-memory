"""Mechanical operations backing the spec's Manager Agent (§10-§14, §16).

Semantic judgment (is this the same theme? is cohesion high? is this important?)
is deliberately NOT implemented here — it's left to the calling LLM (spec §17: a
decision matrix is a hint, not an if-else). This module only guarantees the parts
that must be mechanically reliable: atomic writes, concurrency checks, bidirectional
link integrity (§12), index upkeep (§14), and change logging (§10).
"""
from __future__ import annotations

from pathlib import Path

from . import index as index_mod
from . import log as log_mod
from . import models
from . import sections
from .errors import NotFoundError, ValidationError
from .linkgraph import extract_structural_links
from .models import ARCHIVE_DIR
from .store import MemoryFile, check_version, find_by_id, load_all, load_file, require_by_id, write_file


def get_and_touch(root: Path, id: str) -> MemoryFile:
    """spec §11: access_count/last_access are incremented by the retrieval flow
    at the point a file is actually fetched (not merely surfaced in search).

    require_by_id's lookup scans every file under root (O(n) in store size)
    before this function ever touches the target file, which widens the gap
    between "the content we're about to write back" and "the content
    currently on disk" as the store grows. Previously this wrote back the
    body/fm captured by that scan, so a concurrent append_to_file landing in
    that gap got silently reverted (lost update) -- and because this doesn't
    (deliberately) advance `updated`, expected_updated-based optimistic
    locking elsewhere didn't catch it either. Re-reading just the target file
    immediately before writing shrinks the window to a single file's
    read+write, which is the same order of risk as any other single
    write_file call in this module (not a full fix -- that needs real
    locking, see docs/improvement-plan.md)."""
    mf = require_by_id(root, id)
    fresh = load_file(mf.path)
    fresh.fm["access_count"] = int(fresh.fm.get("access_count", 0)) + 1
    fresh.fm["last_access"] = models.today_date()
    write_file(fresh.path, fresh.fm, fresh.body)
    return fresh


def create_file(
    root: Path,
    id: str,
    dir: str,
    type: str,
    content: str,
    description: str,
    tags: list[str] | None = None,
    importance: float = models.DEFAULT_IMPORTANCE,
    pinned: bool = False,
    parent: list[str] | None = None,
    actor: str = "unspecified",
    rationale: str = "",
    _log: bool = True,
) -> MemoryFile:
    if not models.ID_RE.match(id):
        raise ValidationError(f"id must match {models.ID_RE.pattern!r} (letters/digits/underscore/hyphen only), got {id!r}")
    if dir not in models.ALLOWED_DIRS:
        raise ValidationError(f"dir must be one of {sorted(models.ALLOWED_DIRS)}, got '{dir}'")
    if find_by_id(root, id) is not None:
        raise ValidationError(f"id '{id}' already exists")
    path = root / dir / f"{id}.md"
    if path.exists():
        raise ValidationError(f"file already exists at {path}")
    fm = models.new_frontmatter(id, type, tags=tags, importance=importance, pinned=pinned, parent=parent)
    write_file(path, fm, content)
    index_mod.upsert_entry(root, id, description, tags=tags or [])
    if _log:
        log_mod.append(root, "create", [id], rationale or f"created {id} ({type})", actor)
    return load_file(path)


def append_to_file(
    root: Path,
    id: str,
    content: str,
    section: str | None = None,
    expected_updated: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> MemoryFile:
    mf = require_by_id(root, id)
    check_version(mf, expected_updated)

    if section:
        new_body = sections.append_under_section(mf.body, section, content)
        if new_body is None:
            headings = sections.list_headings(mf.body)
            raise NotFoundError(
                f"section '{section}' not found in '{id}'. Existing headings: {headings}"
            )
    else:
        sep = "\n" if mf.body and not mf.body.endswith("\n") else ""
        new_body = mf.body + sep + content.rstrip("\n") + "\n"

    mf.fm["updated"] = models.now_stamp()
    write_file(mf.path, mf.fm, new_body)
    log_mod.append(root, "append", [id], rationale or f"appended to {id}", actor)
    return load_file(mf.path)


def update_metadata(
    root: Path,
    id: str,
    type: str | None = None,
    tags: list[str] | None = None,
    importance: float | None = None,
    pinned: bool | None = None,
    dir: str | None = None,
    expected_updated: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> MemoryFile:
    """Update an existing file's front matter fields (type/tags/importance/pinned)
    and/or relocate it to a different `dir`. Unlike create/append/link, this
    targets fields that previously had no update path at all -- callers had to
    hand-edit the markdown files directly, which bypasses the change log.
    `type` is intentionally not validated against a fixed vocabulary (spec's
    semantic judgment stays with the caller); `dir` is validated against
    models.ALLOWED_DIRS since spec §2 fixes the directory layout."""
    mf = require_by_id(root, id)
    check_version(mf, expected_updated)

    new_fm = dict(mf.fm)
    if type is not None:
        new_fm["type"] = type
    if tags is not None:
        new_fm["tags"] = tags
    if importance is not None:
        new_fm["importance"] = importance
    if pinned is not None:
        new_fm["pinned"] = pinned
    new_fm["updated"] = models.now_stamp()

    new_path = mf.path
    if dir is not None:
        if dir not in models.ALLOWED_DIRS:
            raise ValidationError(f"dir must be one of {sorted(models.ALLOWED_DIRS)}, got '{dir}'")
        new_path = root / dir / f"{id}.md"
        if new_path.exists() and new_path != mf.path:
            raise ValidationError(f"destination already exists: {new_path}")

    write_file(new_path, new_fm, mf.body)
    if new_path != mf.path and mf.path.exists():
        mf.path.unlink()

    if tags is not None:
        entries = index_mod.read_index(root)
        current = next((e for e in entries if e.id == id), None)
        index_mod.upsert_entry(
            root, id,
            current.description if current else id,
            tags=tags,
            archived=(ARCHIVE_DIR in new_path.parts),
        )

    log_mod.append(root, "update_metadata", [id], rationale or f"updated metadata of {id}", actor)
    return load_file(new_path)


def _ensure_link_line(body: str, to_id: str, section: str | None) -> str:
    if to_id in extract_structural_links(body):
        return body
    link_line = f"- [[{to_id}]]"
    if section:
        updated = sections.append_under_section(body, section, link_line)
        if updated is not None:
            return updated
    sep = "\n" if body and not body.endswith("\n") else ""
    return body + sep + link_line + "\n"


def _ensure_parent(fm: dict, parent_id: str) -> dict:
    parents = list(fm.get("parent") or [])
    if parent_id not in parents:
        parents.append(parent_id)
    fm["parent"] = parents
    return fm


def link_files(
    root: Path,
    from_id: str,
    to_id: str,
    section: str | None = None,
    expected_updated_from: str | None = None,
    expected_updated_to: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
    _log: bool = True,
) -> tuple[MemoryFile, MemoryFile]:
    """spec §12: create A->B as one indivisible operation (A gets a [[B]] reference,
    B's front matter gets parent: [A]). Both writes are prepared before either is
    committed, and a self-check reloads both files afterward."""
    from_mf = require_by_id(root, from_id)
    to_mf = require_by_id(root, to_id)
    check_version(from_mf, expected_updated_from)
    check_version(to_mf, expected_updated_to)

    new_from_body = _ensure_link_line(from_mf.body, to_id, section)
    new_from_fm = dict(from_mf.fm)
    new_from_fm["updated"] = models.now_stamp()

    new_to_fm = _ensure_parent(dict(to_mf.fm), from_id)
    new_to_fm["updated"] = models.now_stamp()

    original_from_text = (from_mf.path.read_text(encoding="utf-8"), )
    write_file(from_mf.path, new_from_fm, new_from_body)
    try:
        write_file(to_mf.path, new_to_fm, to_mf.body)
    except Exception:
        from_mf.path.write_text(original_from_text[0], encoding="utf-8", newline="\n")
        raise

    reloaded_from = load_file(from_mf.path)
    reloaded_to = load_file(to_mf.path)
    ok_forward = to_id in extract_structural_links(reloaded_from.body)
    ok_backward = from_id in (reloaded_to.fm.get("parent") or [])
    if not (ok_forward and ok_backward):
        raise RuntimeError(
            f"bidirectional link self-check failed for {from_id} -> {to_id} "
            f"(forward={ok_forward}, backward={ok_backward}); spec §12 forbids a one-sided link"
        )

    if _log:
        log_mod.append(root, "link", [from_id, to_id], rationale or f"linked {from_id} -> {to_id}", actor)
    return reloaded_from, reloaded_to


def _has_link_line(body: str, to_id: str) -> bool:
    return to_id in extract_structural_links(body)


def _remove_link_line(body: str, to_id: str) -> str:
    lines = body.splitlines()
    kept = [ln for ln in lines if ln.strip() != f"- [[{to_id}]]"]
    new_body = "\n".join(kept)
    if body.endswith("\n") and new_body:
        new_body += "\n"
    return new_body


def _remove_parent(fm: dict, parent_id: str) -> dict:
    fm["parent"] = [p for p in (fm.get("parent") or []) if p != parent_id]
    return fm


def unlink_files(
    root: Path,
    from_id: str,
    to_id: str,
    expected_updated_from: str | None = None,
    expected_updated_to: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> tuple[MemoryFile, MemoryFile]:
    """Inverse of link_files (spec §12 counterpart): remove the `- [[to_id]]`
    line from from_id's body and remove from_id from to_id's parent list, as
    one indivisible operation. Needed because link_files/_ensure_parent only
    ever appends -- there was previously no way to correct a stale parent
    reference (e.g. after archiving a duplicate) without hand-editing files.

    Only removes a standalone `- [[to_id]]` line (the shape link_files
    produces). An inline mention woven into prose (e.g. "...problem (see
    [[to_id]])...") is left untouched -- rewriting arbitrary prose is a
    semantic edit, not a mechanical one, so it's out of scope here."""
    from_mf = require_by_id(root, from_id)
    to_mf = require_by_id(root, to_id)
    check_version(from_mf, expected_updated_from)
    check_version(to_mf, expected_updated_to)

    new_from_body = _remove_link_line(from_mf.body, to_id)
    new_from_fm = dict(from_mf.fm)
    new_from_fm["updated"] = models.now_stamp()

    new_to_fm = _remove_parent(dict(to_mf.fm), from_id)
    new_to_fm["updated"] = models.now_stamp()

    original_from_text = from_mf.path.read_text(encoding="utf-8")
    write_file(from_mf.path, new_from_fm, new_from_body)
    try:
        write_file(to_mf.path, new_to_fm, to_mf.body)
    except Exception:
        from_mf.path.write_text(original_from_text, encoding="utf-8", newline="\n")
        raise

    reloaded_from = load_file(from_mf.path)
    reloaded_to = load_file(to_mf.path)
    ok_forward = not _has_link_line(reloaded_from.body, to_id)
    ok_backward = from_id not in (reloaded_to.fm.get("parent") or [])
    if not (ok_forward and ok_backward):
        raise RuntimeError(
            f"unlink self-check failed for {from_id} -> {to_id} "
            f"(forward_removed={ok_forward}, backward_removed={ok_backward})"
        )

    log_mod.append(root, "unlink", [from_id, to_id], rationale or f"unlinked {from_id} -> {to_id}", actor)
    return reloaded_from, reloaded_to


def split_file(
    root: Path,
    source_id: str,
    new_id: str,
    new_dir: str,
    new_type: str,
    new_description: str,
    section_to_extract: str | None = None,
    extracted_content: str | None = None,
    new_tags: list[str] | None = None,
    importance: float = models.DEFAULT_IMPORTANCE,
    expected_updated: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> tuple[MemoryFile, MemoryFile]:
    """spec §9/§10 split action: extract content into a new file, remove it from
    the source (if a section name is given), and wire up the bidirectional link
    (§12) as part of the same operation."""
    source_mf = require_by_id(root, source_id)
    check_version(source_mf, expected_updated)

    if section_to_extract:
        result = sections.extract_section(source_mf.body, section_to_extract)
        if result is None:
            headings = sections.list_headings(source_mf.body)
            raise NotFoundError(
                f"section '{section_to_extract}' not found in '{source_id}'. Existing headings: {headings}"
            )
        content, remaining_body = result
        if extracted_content:
            content = extracted_content
    else:
        if not extracted_content:
            raise ValidationError("either section_to_extract or extracted_content is required")
        content, remaining_body = extracted_content, source_mf.body

    new_mf = create_file(
        root,
        id=new_id,
        dir=new_dir,
        type=new_type,
        content=content,
        description=new_description,
        tags=new_tags,
        importance=importance,
        parent=[source_id],
        actor=actor,
        rationale=rationale,
        _log=False,
    )

    # From here, source_mf's file and index.md's new_id entry both exist.
    # A failure in either remaining step previously left an orphan (new file
    # created but not linked, and/or the section already removed from the
    # source with nowhere left holding that content). Snapshot the source's
    # original text so a failure can restore it, and remove the new file +
    # its index entry, leaving no visible trace of the incomplete split.
    original_source_text = source_mf.path.read_text(encoding="utf-8")
    try:
        source_mf.fm["updated"] = models.now_stamp()
        write_file(source_mf.path, source_mf.fm, remaining_body)
        _, new_mf = link_files(root, source_id, new_id, actor=actor, rationale=rationale, _log=False)
    except Exception:
        source_mf.path.write_text(original_source_text, encoding="utf-8", newline="\n")
        if new_mf.path.exists():
            new_mf.path.unlink()
        index_mod.remove_entry(root, new_id)
        raise

    log_mod.append(
        root,
        "split",
        [source_id, new_id],
        rationale or f"split {new_id} out of {source_id}",
        actor,
    )
    return require_by_id(root, source_id), new_mf


def summarize_and_archive(
    root: Path,
    id: str,
    summary_content: str,
    description_for_index: str,
    expected_updated: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> MemoryFile:
    """spec §5/§9/§13: replace body with a summary and physically move the file
    to archive/, keeping its index.md link visible with an (archived) marker.
    Complete deletion is never performed."""
    mf = require_by_id(root, id)
    check_version(mf, expected_updated)

    mf.fm["updated"] = models.now_stamp()
    archive_path = root / ARCHIVE_DIR / f"{id}.md"
    if archive_path.exists() and archive_path != mf.path:
        raise ValidationError(f"archive destination already exists: {archive_path}")

    # Write the new content in place, then a single atomic rename into
    # archive/ -- avoids the previous write-then-unlink window where a file
    # with this `id` briefly existed at both paths simultaneously (a
    # concurrent find_by_id in that window could resolve to either one).
    write_file(mf.path, mf.fm, summary_content)
    if mf.path != archive_path:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        mf.path.replace(archive_path)

    index_mod.upsert_entry(root, id, description_for_index, tags=mf.fm.get("tags", []), archived=True)
    log_mod.append(root, "summarize_and_archive", [id], rationale or f"summarized and archived {id}", actor)
    return load_file(archive_path)


def move_to_archive(
    root: Path,
    id: str,
    expected_updated: str | None = None,
    actor: str = "unspecified",
    rationale: str = "",
) -> MemoryFile:
    """spec §13: plain forget-model archive, no content change."""
    mf = require_by_id(root, id)
    check_version(mf, expected_updated)

    archive_path = root / ARCHIVE_DIR / f"{id}.md"
    if archive_path.exists() and archive_path != mf.path:
        raise ValidationError(f"archive destination already exists: {archive_path}")

    mf.fm["updated"] = models.now_stamp()
    write_file(mf.path, mf.fm, mf.body)
    if mf.path != archive_path:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        mf.path.replace(archive_path)

    index_mod.mark_archived(root, id, archived=True)
    log_mod.append(root, "archive", [id], rationale or f"archived {id} (§13 forget condition)", actor)
    return load_file(archive_path)


def check_archive_candidates(root: Path) -> list[dict]:
    """spec §13/§11: report candidates only. Archiving still requires an explicit
    follow-up call (move_to_archive / summarize_and_archive) — never auto-executed."""
    candidates = []
    for mf in load_all(root):
        if mf.is_archived:
            continue
        if models.is_archive_candidate(mf.fm):
            candidates.append(
                {
                    "id": mf.id,
                    "access_count": mf.fm.get("access_count", 0),
                    "last_access": mf.fm.get("last_access"),
                    "importance": mf.fm.get("importance"),
                    "pinned": mf.fm.get("pinned", False),
                }
            )
    return candidates
