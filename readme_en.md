# markdown-hierarchical-memory

An implementation of [markdown-hierarchical-memory-spec.md](markdown-hierarchical-memory-spec.md) v1.

- **MCP server** (`src/mdmem/`): The mechanical execution layer providing file read/write, frontmatter management, a wikilink graph, keyword search with graph expansion, optimistic concurrency control (§16), bidirectional link consistency checks (§12), and a change log (§10/§17). Semantic judgments such as cohesion and importance (§9) are not implemented.
- **Claude Code subagent** ([.claude/agents/memory-manager.md](.claude/agents/memory-manager.md)): The Manager Agent defined in §10 of the specification. This is the component that makes semantic judgments by calling MCP tools.

## Scope

- Of the features in §15, only link graph + keyword search is supported (embedding vector search is not implemented. It can be added by replacing `_score` in `src/mdmem/search.py`).
- The Manager Agent's decision-making logic does not make LLM calls internally within the server. The caller (Claude Code) is expected to make the decisions and pass the results as parameters to tool calls.

## Setup

```bash
pip install -e .
python -m pytest tests/
```

## Registering with Claude Code

Copy `.mcp.json.example` to `.mcp.json` and replace `<ABSOLUTE_PATH_TO_THIS_REPO>` with the absolute path to this repository (`.mcp.json` is excluded by `.gitignore` because it contains a personal local path):

```bash
cp .mcp.json.example .mcp.json
# Edit .mcp.json and fill in the path
```

After restarting Claude Code (or reloading the MCP configuration), the `mdmem` server will be enabled, and the `memory-manager` subagent in `.claude/agents/memory-manager.md` will be able to call the `mcp__mdmem__*` tool set.

```bash
claude mcp list
```

This command can be used to verify that `mdmem` is recognized.

## Registering with Cursor

- MCP: [`.cursor/mcp.json`](.cursor/mcp.json) (points to the same `MDMEM_ROOT` as Claude Code's `.mcp.json`)
- Manager Agent: [`.cursor/skills/memory-manager/SKILL.md`](.cursor/skills/memory-manager/SKILL.md)

After restarting Cursor (or reloading `mdmem` in Settings → Tools & MCP), you can share and use the same `memory/` directory with Claude Code.

## Directory Structure

```
memory/
 ├── index.md          # Pure registry (§14)
 ├── projects/
 ├── concepts/
 └── archive/
      └── _manager_log.md   # Change log (§10/§17)
```

The actual path of `memory/` can be changed with the `MDMEM_ROOT` environment variable (default: `memory/` in the current directory).

## Main MCP Tools

| Tool | Corresponding specification |
|---|---|
| `get_index` / `list_memory_files` / `read_memory_file` / `search_memory` / `get_links` | §14, §15, §11 (`access_count`) |
| `create_memory_file` | §3, §14 |
| `append_to_memory_file` | §4 Step1, §16 |
| `link_memory_files` | §12 (executes bidirectional linking as a single operation, with self-checking) |
| `split_memory_file` | §9/§10 splitting |
| `summarize_and_archive_memory_file` | §5/§9/§13 summarize and archive |
| `move_to_archive` | §13 forgetting model (content unchanged) |
| `check_archive_candidates` | §13 (suggestions only; does not execute them. §11) |
| `get_change_log` | §10/§17 |

All write tools accept `expected_updated` and return `ConflictError` if it differs from the value observed during reading (§16).

## Known Limitations

- **Narrow race condition in concurrent writes**: Optimistic locking with `expected_updated` only guarantees the sequence of "read, then validate, then write" within a single process. When Cursor and Claude Code share the same `MDMEM_ROOT` (a situation actually observed during development of this repository), there is a theoretical possibility that two processes read the same file at nearly the same time, both pass the check, and one update overwrites the other. This is not critical, but it is not a problem when writes are performed by a single process only.
- **Embedding vector search is not implemented** (see the Scope section).
- `id` only accepts `^[A-Za-z0-9_-]+$` (because it is used directly in file paths).

## License

[MIT](LICENSE)
