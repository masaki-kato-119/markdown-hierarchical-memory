"""File system layer: locate, read, and atomically write memory files.

Directory layout follows spec §2. `id` -> path resolution is done by scanning
front matter (not by filename), since the spec models identity via `id`, not path.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter
from .errors import ConflictError, NotFoundError
from .models import ARCHIVE_DIR, INDEX_NAME, LOG_NAME


def get_root() -> Path:
    root = Path(os.environ.get("MDMEM_ROOT", "memory")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_actor(explicit: str | None) -> str:
    """Who to record in the change log: configured client identity, plus an optional
    role the caller names.

    Every mutating tool used to default `actor` to the literal "claude", so a call
    from any other client that didn't pass one was logged as Claude -- the log was
    not merely inconsistent, it was wrong. And the drift the log did show (eight
    spellings for a handful of agents) persisted despite both agent definitions
    already instructing which value to pass, because an instruction only reaches the
    agent that reads it, not the main session calling these tools directly.

    Which client is running is not a judgment an LLM should be making: the
    configuration knows it. MDMEM_ACTOR supplies it, the same way MDMEM_ROOT supplies
    the root. A caller-supplied role still means something the environment cannot
    know (`memory-manager` acting inside a session), so the two combine rather than
    one overwriting the other -- otherwise recording the role would erase the client.
    """
    client = os.environ.get("MDMEM_ACTOR", "").strip()
    role = (explicit or "").strip()
    if client and role and client != role:
        return f"{client}/{role}"
    return client or role or "unspecified"


@dataclass
class MemoryFile:
    path: Path
    fm: dict
    body: str

    @property
    def id(self) -> str:
        return self.fm.get("id", self.path.stem)

    @property
    def is_archived(self) -> bool:
        return ARCHIVE_DIR in self.path.parts


def _is_content_file(root: Path, path: Path) -> bool:
    if path.name == INDEX_NAME and path.parent == root:
        return False
    if path.name == LOG_NAME:
        return False
    return True


def iter_content_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        if _is_content_file(root, path):
            yield path


def load_file(path: Path) -> MemoryFile:
    text = path.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    return MemoryFile(path=path, fm=fm, body=body)


def load_all(root: Path) -> list[MemoryFile]:
    return [load_file(p) for p in iter_content_files(root)]


def find_by_id(root: Path, id: str) -> MemoryFile | None:
    for mf in load_all(root):
        if mf.id == id:
            return mf
    return None


def require_by_id(root: Path, id: str) -> MemoryFile:
    mf = find_by_id(root, id)
    if mf is None:
        raise NotFoundError(f"no memory file with id '{id}'")
    return mf


def write_file(path: Path, fm: dict, body: str) -> None:
    """Atomic write: write to a temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = frontmatter.dump(fm, body)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def check_version(mf: MemoryFile, expected_updated: str | None) -> None:
    """spec §16 optimistic concurrency check."""
    if expected_updated is None:
        return
    actual = mf.fm.get("updated")
    if actual != expected_updated:
        raise ConflictError(mf.id, expected_updated, actual)
