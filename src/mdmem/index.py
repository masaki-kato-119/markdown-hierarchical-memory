"""index.md registry: pure id/one-line-description/tags listing (spec §14).

Format (one entry per line, kept intentionally simple so it stays diffable):

    - [[id]] — one line description `tags: tag1, tag2`
    - [[id]] (archived) — one line description `tags: tag1, tag2`
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import INDEX_NAME

_LINE_RE = re.compile(
    r"^- \[\[(?P<id>[^\]]+)\]\](?P<archived> \(archived\))? — (?P<desc>.*?)"
    r"(?: `tags: (?P<tags>[^`]*)`)?\s*$"
)

_HEADER = "# Index\n\nPure registry (id / one-line description / tags). No prose here — see spec §14.\n"


@dataclass
class IndexEntry:
    id: str
    description: str
    tags: list[str] = field(default_factory=list)
    archived: bool = False

    def render(self) -> str:
        tags_part = f" `tags: {', '.join(self.tags)}`" if self.tags else ""
        archived_part = " (archived)" if self.archived else ""
        return f"- [[{self.id}]]{archived_part} — {self.description}{tags_part}"


def index_path(root: Path) -> Path:
    return root / INDEX_NAME


def read_index(root: Path) -> list[IndexEntry]:
    path = index_path(root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        tags = [t.strip() for t in m.group("tags").split(",")] if m.group("tags") else []
        entries.append(
            IndexEntry(
                id=m.group("id"),
                description=m.group("desc"),
                tags=tags,
                archived=bool(m.group("archived")),
            )
        )
    return entries


def write_index(root: Path, entries: list[IndexEntry]) -> None:
    path = index_path(root)
    body_lines = [e.render() for e in sorted(entries, key=lambda e: e.id)]
    text = _HEADER + "\n" + "\n".join(body_lines) + ("\n" if body_lines else "")
    path.write_text(text, encoding="utf-8", newline="\n")


def upsert_entry(
    root: Path, id: str, description: str, tags: list[str] | None = None, archived: bool = False
) -> None:
    entries = read_index(root)
    tags = tags or []
    for e in entries:
        if e.id == id:
            e.description = description
            e.tags = tags
            e.archived = archived
            break
    else:
        entries.append(IndexEntry(id=id, description=description, tags=tags, archived=archived))
    write_index(root, entries)


def mark_archived(root: Path, id: str, archived: bool = True) -> None:
    entries = read_index(root)
    for e in entries:
        if e.id == id:
            e.archived = archived
            write_index(root, entries)
            return
