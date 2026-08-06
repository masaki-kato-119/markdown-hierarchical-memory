"""Search flow (spec §15): index.md -> keyword candidates -> link-graph expansion.

MVP scope: no embeddings. Keyword matching over id/tags/title/body stands in for
the "embedding similarity" first filter; link-graph distance is the second filter,
exactly as the spec's roles are divided.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .index import read_index
from .linkgraph import LinkGraph
from .store import MemoryFile, load_all

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _title(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _score(tokens: list[str], mf: MemoryFile) -> float:
    if not tokens:
        return 0.0
    id_tokens = set(_tokenize(mf.id))
    tag_tokens = set(_tokenize(" ".join(mf.fm.get("tags", []))))
    title_tokens = set(_tokenize(_title(mf.body)))
    body_tokens = _tokenize(mf.body)
    body_counter: dict[str, int] = {}
    for t in body_tokens:
        body_counter[t] = body_counter.get(t, 0) + 1

    score = 0.0
    for tok in tokens:
        if tok in id_tokens:
            score += 5.0
        if tok in tag_tokens:
            score += 4.0
        if tok in title_tokens:
            score += 3.0
        score += 0.5 * body_counter.get(tok, 0)
    return score


def _snippet(tokens: list[str], body: str, width: int = 160) -> str:
    lines = body.splitlines()
    for line in lines:
        low = line.lower()
        if any(tok in low for tok in tokens):
            s = line.strip()
            return s if len(s) <= width else s[: width - 1] + "…"
    return ""


@dataclass
class SearchResult:
    id: str
    path: str
    hop: int
    score: float
    snippet: str
    frontmatter: dict


def search(root: Path, query: str, hop: int = 1, max_results: int = 10) -> list[SearchResult]:
    tokens = _tokenize(query)
    files = load_all(root)
    by_id = {mf.id: mf for mf in files}

    scored = [(_score(tokens, mf), mf) for mf in files]
    scored = [(s, mf) for s, mf in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    primary = [mf.id for _, mf in scored[:max_results]]

    graph = LinkGraph(files)
    distances = graph.expand(primary, hops=hop)

    score_by_id = {mf.id: s for s, mf in scored}
    results = []
    for id, dist in distances.items():
        mf = by_id[id]
        results.append(
            SearchResult(
                id=id,
                path=str(mf.path.relative_to(root)),
                hop=dist,
                score=score_by_id.get(id, 0.0),
                snippet=_snippet(tokens, mf.body) if tokens else "",
                frontmatter=mf.fm,
            )
        )
    results.sort(key=lambda r: (r.hop, -r.score))
    return results[:max_results]
