from mdmem.linkgraph import LinkGraph, extract_links, extract_structural_links
from mdmem.store import MemoryFile
from pathlib import Path


def test_extract_links_dedupes_and_ignores_labels():
    body = "See [[foo]] and [[bar|Bar Label]] and [[foo]] again."
    assert extract_links(body) == ["foo", "bar"]


def test_extract_structural_links_matches_standalone_line():
    body = "# Title\n\nintro\n\n- [[foo]]\n- [[bar]]\n"
    assert extract_structural_links(body) == ["foo", "bar"]


def test_extract_structural_links_ignores_prose_mentions():
    body = "See [[foo]] mentioned inline (background: [[bar]]) but no standalone line.\n"
    assert extract_structural_links(body) == []


def test_extract_structural_links_dedupes():
    body = "- [[foo]]\n- [[foo]]\n"
    assert extract_structural_links(body) == ["foo"]


def _mf(id, links_to):
    body = " ".join(f"[[{t}]]" for t in links_to)
    return MemoryFile(path=Path(f"{id}.md"), fm={"id": id}, body=body)


def test_backlinks_and_forwardlinks():
    files = [_mf("a", ["b"]), _mf("b", []), _mf("c", ["a"])]
    g = LinkGraph(files)
    assert g.forwardlinks("a") == ["b"]
    assert set(g.backlinks("a")) == {"c"}
    assert g.backlinks("b") == ["a"]


def test_expand_respects_hop_limit():
    # a -> b -> c -> d, linear chain
    files = [_mf("a", ["b"]), _mf("b", ["c"]), _mf("c", ["d"]), _mf("d", [])]
    g = LinkGraph(files)
    dist_1hop = g.expand(["a"], hops=1)
    assert dist_1hop == {"a": 0, "b": 1}
    dist_2hop = g.expand(["a"], hops=2)
    assert dist_2hop == {"a": 0, "b": 1, "c": 2}
