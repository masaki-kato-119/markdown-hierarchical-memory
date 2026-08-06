"""Wikilink extraction and graph traversal (spec §2, §12, §15)."""
from __future__ import annotations

import re
from pathlib import Path

from .store import MemoryFile, load_all

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]")
_STRUCTURAL_LINK_RE = re.compile(r"^-\s+\[\[([^\[\]|]+)\]\]$")


def extract_links(body: str) -> list[str]:
    """Return the target ids referenced via [[id]] or [[id|label]], de-duplicated
    and order-preserved. Broad match: this also picks up an incidental [[id]]
    woven into prose, not just a structural link. That breadth is intentional
    here -- search's hop expansion (spec §15) wants any mention as a hint, not
    just curated links. For "is this a real §12 structural link" questions
    (link_files' idempotency check, get_links), use extract_structural_links
    instead."""
    seen: dict[str, None] = {}
    for m in _WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if target:
            seen.setdefault(target, None)
    return list(seen.keys())


def extract_structural_links(body: str) -> list[str]:
    """Return ids referenced via a standalone `- [[id]]` line -- the exact
    shape link_files/unlink_files produce and manage (spec §12). Unlike
    extract_links, an [[id]] mention embedded in prose (e.g. "see [[id]] for
    background") does not count: that distinction matters because extract_links
    previously caused link_files to skip adding a real structural line when a
    prose mention already existed, and caused get_links to report such prose
    mentions as if they were real links."""
    seen: dict[str, None] = {}
    for line in body.splitlines():
        m = _STRUCTURAL_LINK_RE.match(line.strip())
        if m:
            target = m.group(1).strip()
            if target:
                seen.setdefault(target, None)
    return list(seen.keys())


class LinkGraph:
    def __init__(self, files: list[MemoryFile]):
        self.by_id: dict[str, MemoryFile] = {mf.id: mf for mf in files}
        self.outgoing: dict[str, list[str]] = {
            mf.id: extract_links(mf.body) for mf in files
        }
        self.incoming: dict[str, list[str]] = {mf.id: [] for mf in files}
        for src, targets in self.outgoing.items():
            for t in targets:
                if t in self.incoming:
                    self.incoming[t].append(src)
                else:
                    self.incoming[t] = [src]

    @classmethod
    def build(cls, root: Path) -> "LinkGraph":
        return cls(load_all(root))

    def backlinks(self, id: str) -> list[str]:
        return list(self.incoming.get(id, []))

    def forwardlinks(self, id: str) -> list[str]:
        return list(self.outgoing.get(id, []))

    def expand(self, seed_ids: list[str], hops: int) -> dict[str, int]:
        """Breadth-first expansion over the undirected union of forward+backward
        links, up to `hops` levels (spec §15 default 1-hop). Returns {id: hop_distance}
        including the seeds themselves at distance 0."""
        distance: dict[str, int] = {sid: 0 for sid in seed_ids if sid in self.by_id}
        frontier = list(distance.keys())
        for depth in range(1, hops + 1):
            next_frontier = []
            for node in frontier:
                neighbors = set(self.outgoing.get(node, [])) | set(self.incoming.get(node, []))
                for n in neighbors:
                    if n in self.by_id and n not in distance:
                        distance[n] = depth
                        next_frontier.append(n)
            frontier = next_frontier
            if not frontier:
                break
        return distance
