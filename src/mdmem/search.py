"""Search flow (spec §15): index.md -> keyword candidates -> link-graph expansion.

MVP scope: no embeddings. Keyword matching over id/tags/index-description/title/body
stands in for the "embedding similarity" first filter; link-graph distance is the
second filter, exactly as the spec's roles are divided.

Two properties matter more than they look. Tokenization splits the ASCII/CJK
boundary and bigrams CJK runs, without which a mostly-Japanese store is barely
searchable at all. And the body term is BM25 rather than a raw count, without which
the single longest file wins every query.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import models
from .index import read_index
from .linkgraph import LinkGraph
from .store import MemoryFile, load_all

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# `\w+` swallows a run of kanji/kana wholesale -- and fuses it with any adjacent
# ASCII -- so a body line like "px68k起動しない" collapsed into ONE token. Since
# scoring is exact-token, a query for "起動しない" could never match it (measured:
# 0 results against a store that documents exactly that problem), and the queries
# that did work only worked because punctuation happened to isolate the word.
# Splitting the ASCII/CJK boundary and expanding CJK runs into character bigrams
# restores partial matching without pulling in a morphological analyzer.
_CJK_RE = re.compile(
    "["
    "぀-ゟ"  # hiragana
    "゠-ヿ"  # katakana
    "ㇰ-ㇿ"  # katakana phonetic extensions
    "㐀-䶿"  # CJK unified ideographs extension A
    "一-鿿"  # CJK unified ideographs
    "豈-﫿"  # CJK compatibility ideographs
    "ｦ-ﾟ"  # halfwidth katakana
    "]+"
)


def _split_run(run: str) -> list[str]:
    """Split one `\\w+` run into ASCII segments plus bigram-expanded CJK segments.

    A lone CJK character is kept as-is (there is no bigram to form), which means a
    single-character CJK query still won't match a longer run -- no worse than the
    previous behaviour, where it matched nothing at all.
    """
    out: list[str] = []
    pos = 0
    for m in _CJK_RE.finditer(run):
        if m.start() > pos:
            out.append(run[pos : m.start()])
        seg = m.group()
        if len(seg) == 1:
            out.append(seg)
        else:
            out.extend(seg[i : i + 2] for i in range(len(seg) - 1))
        pos = m.end()
    if pos < len(run):
        out.append(run[pos:])
    return out


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for run in _TOKEN_RE.findall(text):
        tokens.extend(t.lower() for t in _split_run(run))
    return tokens


def _title(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


# Body hits used to score `0.5 * occurrences`, unbounded and blind to document
# length, so the longest file in the store won every query by sheer mass -- a
# 1126-line file outranked the file actually titled after the query. Bigram
# expansion made it worse, since a long document accumulates common bigrams. The
# body term is therefore BM25: saturating in term frequency, normalised by length,
# and weighted by inverse document frequency so filler bigrams (ない, しな) stop
# dominating. The id/tag/title bonuses stay flat -- they're structural signals
# about the whole file, not evidence that accumulates with repetition.
_K1 = 1.5  # term-frequency saturation
_B = 0.75  # length-normalisation strength
_BODY_WEIGHT = 2.0  # scales the body term into the same range as the flat bonuses

# `importance` was stored and maintained but read by nothing -- not ranking, not the
# §13 forget condition -- so the axis §9 frames every decision around had no effect
# anywhere. It applies as a mild prior on the whole score: 0.0 -> 0.5x, the 0.5
# default -> 1.0x (leaving existing ranking untouched), 1.0 -> 1.5x. Deliberately
# mild, because it says how much the file matters in general, not how well it
# answers this query; a file has to be within ~3x on relevance before it flips.
#
# `pinned` is left out on purpose. §11 makes it the retention flag -- "the user said
# keep this" -- and explicitly an axis independent of importance. Feeding it into
# ranking would quietly conflate "don't forget this" with "this is what you asked for".
_IMPORTANCE_FLOOR = 0.5

# Bigrams restore recall but lose word order, and unrelated CJK words share fragments
# freely: a racing-game proposal matched all seven bigrams of "ブレークポイント" out of
# チェックポイント + ブレーキ + レース, and outranked the file actually about breakpoints.
# Requiring more bigrams to match cannot separate those two -- both matched 7/7 -- so
# the phrase itself has to count. A flat bonus, not one that scales with occurrences,
# since accumulating body mass is the failure mode this scoring already had to undo.
_PHRASE_WEIGHT = 6.0


def _counts(tokens: list[str]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for t in tokens:
        counter[t] = counter.get(t, 0) + 1
    return counter


@dataclass
class _Corpus:
    """Corpus-wide statistics needed to length-normalise body scores."""

    body_counts: dict[str, dict[str, int]]  # id -> token -> occurrences
    lengths: dict[str, int]  # id -> body token count
    df: dict[str, int]  # token -> number of documents containing it
    n_docs: int
    avg_len: float
    descriptions: dict[str, str]  # id -> curated one-liner from index.md
    haystacks: dict[str, str]  # id -> lowercased description + body, for phrase matching


def _build_corpus(files: list[MemoryFile], root: Path) -> _Corpus:
    body_counts = {mf.id: _counts(_tokenize(mf.body)) for mf in files}
    lengths = {id: sum(c.values()) for id, c in body_counts.items()}
    df: dict[str, int] = {}
    for counts in body_counts.values():
        for tok in counts:
            df[tok] = df.get(tok, 0) + 1
    n_docs = len(files)
    avg_len = (sum(lengths.values()) / n_docs) if n_docs else 1.0
    descriptions = {e.id: e.description for e in read_index(root)}
    haystacks = {
        mf.id: (descriptions.get(mf.id, "") + "\n" + mf.body).lower() for mf in files
    }
    return _Corpus(body_counts, lengths, df, n_docs, avg_len or 1.0, descriptions, haystacks)


def _score(tokens: list[str], mf: MemoryFile, corpus: _Corpus, phrase: str = "") -> float:
    if not tokens:
        return 0.0
    id_tokens = set(_tokenize(mf.id))
    tag_tokens = set(_tokenize(" ".join(mf.fm.get("tags", []))))
    title_tokens = set(_tokenize(_title(mf.body)))
    # index.md's one-liner is the most deliberately-written summary a file has,
    # and it was previously unsearchable -- read_index was imported here but never
    # called, so §15's "start from index.md" step didn't exist. It matters most
    # when description and body are written in different languages, which is
    # exactly the case for files whose notes are English but whose summary is not.
    desc_tokens = set(_tokenize(corpus.descriptions.get(mf.id, "")))
    body_counter = corpus.body_counts.get(mf.id, {})
    doc_len = corpus.lengths.get(mf.id, 0)

    score = 0.0
    if len(phrase) >= 2 and phrase in corpus.haystacks.get(mf.id, ""):
        score += _PHRASE_WEIGHT
    for tok in tokens:
        if tok in id_tokens:
            score += 5.0
        if tok in tag_tokens:
            score += 4.0
        if tok in desc_tokens:
            score += 4.0
        if tok in title_tokens:
            score += 3.0

        tf = body_counter.get(tok, 0)
        if not tf:
            continue
        df = corpus.df.get(tok, 0)
        idf = math.log(1 + (corpus.n_docs - df + 0.5) / (df + 0.5))
        norm = tf + _K1 * (1 - _B + _B * doc_len / corpus.avg_len)
        score += _BODY_WEIGHT * idf * tf * (_K1 + 1) / norm
    return score * (_IMPORTANCE_FLOOR + _importance_of(mf))


def _importance_of(mf: MemoryFile) -> float:
    """Front matter is caller-supplied, so a missing or malformed value falls back to
    the default rather than taking ranking down with it."""
    try:
        value = float(mf.fm.get("importance", models.DEFAULT_IMPORTANCE))
    except (TypeError, ValueError):
        return models.DEFAULT_IMPORTANCE
    return min(1.0, max(0.0, value))


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

    corpus = _build_corpus(files, root)
    phrase = query.strip().lower()
    scored = [(_score(tokens, mf, corpus, phrase), mf) for mf in files]
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
