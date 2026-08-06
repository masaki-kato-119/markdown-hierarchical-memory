from mdmem import manager
from mdmem.search import search


def _setup(root):
    manager.create_file(
        root, "hybrid_rag", "projects", "concept",
        "# HybridRAG\n\nHybridRAGは検索精度向上のための構成。\n",
        "desc", tags=["rag", "knowledge"],
    )
    manager.create_file(
        root, "retrieval_strategy", "projects", "project",
        "# Retrieval Strategy\n\n検索戦略の詳細。\n",
        "desc", tags=["rag"],
    )
    manager.create_file(
        root, "unrelated", "concepts", "concept",
        "# Unrelated\n\n天気予報について。\n",
        "desc", tags=["weather"],
    )
    manager.link_files(root, "hybrid_rag", "retrieval_strategy")


def test_search_finds_keyword_match(root):
    _setup(root)
    results = search(root, "HybridRAG", hop=0)
    ids = [r.id for r in results]
    assert "hybrid_rag" in ids
    assert "unrelated" not in ids


def test_search_expands_one_hop_by_default_target(root):
    _setup(root)
    results = search(root, "HybridRAG", hop=1)
    ids = {r.id: r.hop for r in results}
    assert ids.get("hybrid_rag") == 0
    assert ids.get("retrieval_strategy") == 1
    assert "unrelated" not in ids


def test_search_zero_hop_does_not_expand(root):
    _setup(root)
    results = search(root, "HybridRAG", hop=0)
    ids = {r.id for r in results}
    assert "retrieval_strategy" not in ids
