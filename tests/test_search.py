import pytest

from mdmem import manager
from mdmem.search import _tokenize, search
from mdmem.store import write_file


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


def test_tokenize_keeps_ascii_runs_whole():
    assert _tokenize("px68k hello") == ["px68k", "hello"]


def test_tokenize_splits_ascii_cjk_boundary_and_bigrams_cjk():
    # `\w+` matched "px68k起動しない" as a single token, so neither "px68k" nor
    # any part of the Japanese could ever match it.
    assert _tokenize("px68k起動しない") == ["px68k", "起動", "動し", "しな", "ない"]


def test_tokenize_keeps_lone_cjk_character():
    assert _tokenize("音") == ["音"]


def test_search_matches_japanese_fused_with_ascii(root):
    # Regression: querying "起動" returned 0 results against a body containing
    # "px68k起動しない", because the whole run collapsed into one token.
    manager.create_file(
        root, "boot_notes", "reference", "reference",
        "# Boot\n\npx68k起動しない場合のFDC待ちを確認する。\n",
        "起動トラブルの記録", tags=["px68k"],
    )
    ids = [r.id for r in search(root, "起動", hop=0)]
    assert ids == ["boot_notes"]


def test_search_matches_inflected_japanese_phrase(root):
    manager.create_file(
        root, "boot_notes", "reference", "reference",
        "# Boot\n\npx68k起動しない場合の対処。\n", "desc", tags=[],
    )
    assert [r.id for r in search(root, "起動しない", hop=0)] == ["boot_notes"]


def test_long_file_does_not_outrank_focused_file_by_bulk(root):
    # The 1126-line file in the real store won every query on mass alone: body
    # hits scored 0.5 * occurrences with no length normalisation.
    manager.create_file(
        root, "sprawling", "reference", "reference",
        "# Sprawling\n\n" + "無関係な記述の行がここに続く。\n" * 200 + "スプライトの話も一度だけ出る。\n" * 10,
        "雑多な作業ログ", tags=[],
    )
    manager.create_file(
        root, "sprite_hw", "reference", "reference",
        "# スプライト ハードウェア\n\nPCGとパレットの配置。\n", "スプライトの資料", tags=[],
    )
    ids = [r.id for r in search(root, "スプライト", hop=0)]
    assert ids[0] == "sprite_hw"


def test_contiguous_phrase_beats_scattered_bigrams(root):
    # Regression: "チェックポイント" + "ブレーキ" + "レース" between them supply every
    # bigram of "ブレークポイント", so bigram overlap alone cannot tell the two apart.
    manager.create_file(
        root, "racing", "projects", "project",
        "# レースゲーム\n\nチェックポイント通過とブレーキ操作。レース中のポイント加算。\n",
        "レースゲーム企画",
    )
    manager.create_file(
        root, "debugging", "reference", "reference",
        "# デバッグ\n\nブレークポイントで待ち伏せする。\n", "ブレークポイント運用",
    )
    assert [r.id for r in search(root, "ブレークポイント", hop=0)][0] == "debugging"


def test_phrase_bonus_also_matches_the_index_description(root):
    manager.create_file(
        root, "english_body", "reference", "reference",
        "# Screen not showing\n\nHost is not a real Raspberry Pi.\n",
        "px68kで「画面が出ない」問題の原因と対処",
    )
    assert [r.id for r in search(root, "画面が出ない", hop=0)] == ["english_body"]


def test_importance_breaks_a_tie_between_equally_relevant_files(root):
    # importance was stored and read by nothing; §9 frames its decisions around it.
    body = "# Doc\n\nスプライトの配置について。\n"
    manager.create_file(root, "low", "reference", "reference", body, "d1", importance=0.1)
    manager.create_file(root, "high", "reference", "reference", body, "d2", importance=0.9)
    assert [r.id for r in search(root, "スプライト", hop=0)][0] == "high"


def test_importance_does_not_override_a_much_better_match(root):
    # A mild prior: it should nudge, not outrank a file that plainly answers the query.
    manager.create_file(
        root, "off_topic", "reference", "reference",
        "# Off topic\n\nスプライトに一度だけ触れる。\n", "d1", importance=1.0,
    )
    manager.create_file(
        root, "on_topic", "reference", "reference",
        "# スプライト ハードウェア\n\nスプライトのPCG配置とパレット。スプライト制御。\n",
        "スプライトの資料", tags=["sprite", "スプライト"], importance=0.1,
    )
    assert [r.id for r in search(root, "スプライト", hop=0)][0] == "on_topic"


def test_importance_scales_the_score_by_the_documented_factor(root):
    # 0.0 -> 0.5x, 0.5 (the default) -> 1.0x, 1.0 -> 1.5x.
    body = "# Doc\n\nスプライトの配置。\n"
    manager.create_file(root, "mid", "reference", "reference", body, "d1", importance=0.5)
    manager.create_file(root, "top", "reference", "reference", body, "d2", importance=1.0)
    scores = {r.id: r.score for r in search(root, "スプライト", hop=0)}
    assert scores["top"] == pytest.approx(scores["mid"] * 1.5)


def test_malformed_importance_falls_back_to_default(root):
    manager.create_file(root, "a", "reference", "reference", "# A\n\nスプライト。\n", "d")
    manager.update_metadata(root, "a", importance=0.5)
    mf = manager.require_by_id(root, "a")
    mf.fm["importance"] = "not a number"
    write_file(mf.path, mf.fm, mf.body)
    assert [r.id for r in search(root, "スプライト", hop=0)] == ["a"]


def test_search_uses_index_description(root):
    # read_index was imported by search.py but never called, so a file whose body
    # is English and whose curated summary is Japanese was unreachable in Japanese.
    manager.create_file(
        root, "raspi_debug", "reference", "reference",
        "# px68k on raspi — screen not showing\n\nHost is not a real Raspberry Pi.\n",
        "px68kをraspiで動かした際の「画面が出ない」問題の原因と対処", tags=[],
    )
    assert [r.id for r in search(root, "画面が出ない", hop=0)] == ["raspi_debug"]
