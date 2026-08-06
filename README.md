# mdmem

[markdown-hierarchical-memory-spec.md](markdown-hierarchical-memory-spec.md) v1 の実装。

- **MCPサーバー** (`src/mdmem/`): ファイル読み書き、frontmatter管理、wikilinkグラフ、
  キーワード+グラフ展開検索、楽観的並行制御(§16)、双方向リンク整合性チェック(§12)、
  変更ログ(§10/§17) を提供する機械的実行層。意味的判断（凝集度・重要度など §9）は
  実装していない。
- **Claude Code subagent** ([.claude/agents/memory-manager.md](.claude/agents/memory-manager.md)):
  仕様書§10のManager Agent。MCPツールを呼び出して意味的判断を行う側。

## スコープ

- 検索は §15 のうちリンクグラフ+キーワード検索のみ（埋め込みベクトル検索は未実装。
  `src/mdmem/search.py` の `_score` を差し替えれば追加できる）。
- Manager Agentの判断ロジックはサーバー内部にLLM呼び出しを持たない。呼び出し元
  （Claude Code）が判断し、判断結果をツール呼び出しのパラメータとして渡す想定。

## セットアップ

```bash
pip install -e .
python -m pytest tests/
```

## Claude Codeへの登録

`.mcp.json.example` を `.mcp.json` にコピーし、`<ABSOLUTE_PATH_TO_THIS_REPO>` をこのリポジトリの
絶対パスに書き換える（`.mcp.json` は個人のローカルパスを含むため `.gitignore` 対象）:

```bash
cp .mcp.json.example .mcp.json
# .mcp.json を編集してパスを埋める
```

Claude Codeを再起動（またはMCP設定を再読込）すると`mdmem` サーバーが有効になり、
`.claude/agents/memory-manager.md` の `memory-manager` subagentから `mcp__mdmem__*` ツール群を呼び出せる。

```bash
claude mcp list
```
で `mdmem` が認識されているか確認できる。

## Cursorへの登録

- MCP: [`.cursor/mcp.json`](.cursor/mcp.json)（Claude Codeの `.mcp.json` と同じ `MDMEM_ROOT` を指す）
- Manager Agent: [`.cursor/skills/memory-manager/SKILL.md`](.cursor/skills/memory-manager/SKILL.md)

Cursorを再起動（または Settings → Tools & MCP で `mdmem` を再読込）すると、
同じ `memory/` を Claude Code と共有して使える。

## ディレクトリ

```
memory/
 ├── index.md          # 純粋なレジストリ(§14)
 ├── projects/
 ├── concepts/
 └── archive/
      └── _manager_log.md   # 変更ログ(§10/§17)
```

`memory/` の実体パスは環境変数 `MDMEM_ROOT` で変更できる(デフォルト: カレントディレクトリの `memory/`)。

## 主なMCPツール

| ツール | 対応する仕様 |
|---|---|
| `get_index` / `list_memory_files` / `read_memory_file` / `search_memory` / `get_links` | §14, §15, §11(access_count) |
| `create_memory_file` | §3, §14 |
| `append_to_memory_file` | §4 Step1, §16 |
| `link_memory_files` | §12（双方向リンクを1操作として実行、自己チェック付き） |
| `split_memory_file` | §9/§10 分割 |
| `summarize_and_archive_memory_file` | §5/§9/§13 要約してarchive |
| `move_to_archive` | §13 忘却モデル（内容そのまま） |
| `check_archive_candidates` | §13（提案のみ、実行はしない。§11） |
| `get_change_log` | §10/§17 |

すべての書き込み系ツールは `expected_updated` を受け取り、読み取り時の値と不一致なら
`ConflictError` を返す（§16）。

## 既知の制限

- **並行書き込みの狭いレース条件**: `expected_updated`の楽観ロックは「読んだ後に検証してから書く」
  までを1プロセス内でしか保証していない。CursorとClaude Codeが同じ`MDMEM_ROOT`を共有する運用
  （実際にこのリポジトリの開発中に両者が同時に書き込んでいる場面を確認済み）では、2プロセスが
  ほぼ同時に同じファイルを読んで両方チェックを通過し、片方の更新が消える理論上の余地がある。
  致命的ではないが、単一プロセスからのみ書き込む運用であれば問題にならない。
- **埋め込みベクトル検索は未実装**（スコープの節を参照）。
- `id`は`^[A-Za-z0-9_-]+$`のみ許可（ファイルパスに直接使われるため）。

## ライセンス

[MIT](LICENSE)
