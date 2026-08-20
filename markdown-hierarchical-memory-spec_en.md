# Markdown Hierarchical Memory Specification (v1)

## 1. Core Principles

- Humans or LLMs add memories in Markdown format.
- Memories are split based on relationships rather than stored in a single file.
- Links between files (Wikilinks) form a knowledge network.
- When the volume grows, choose either to "summarize and compress" or to "move detailed information into a separate file."
- This design is an independent track from the existing implementation (hybrid-rag-memory MCP: chunking + metadata + FAISS/BM25 hybrid search), and integration is not assumed.

## 2. Memory File Structure

```
memory/
 ├── index.md
 ├── projects/
 │    ├── hybrid_rag.md
 │    └── retrieval_strategy.md
 ├── concepts/
 │    ├── llm_memory.md
 │    └── rag.md
 └── archive/
      └── old_discussion.md
```

Directories are merely auxiliary; the essential structure is the internal Markdown links.

```markdown
# HybridRAG

HybridRAG is an architecture for improving search accuracy.

Details:
- [[retrieval_strategy]]
- [[graph_expansion]]

Related:
- [[LLM_Memory]]
```

## 3. Front Matter

```yaml
---
id: hybrid_rag
type: concept
importance: 0.8
pinned: false
created: 2026-08-04
updated: 2026-08-04
access_count: 52
last_access: 2026-08-04
parent:
  - llm_memory
tags:
  - rag
  - knowledge
---
```

## 4. Addition Rules

**Step 1**: Determine whether the current file can be appended to. Conditions: the same topic, supplementary information to the existing content, and within the size limit. Append the content if all conditions are met.

**Step 2**: If the content is highly related but independent, create a new file and link to it (see Section 12 for bidirectional links).

## 5. Size Control (Guideline)

| Level | Number of lines | Action |
|---|---|---|
| 1 | 100 lines or fewer | Leave as is |
| 2 | 100-300 lines | Organize the sections |
| 3 | More than 300 lines | Split or summarize according to the decision matrix in Section 9 |

## 6-8. (Basic Policies from the Initial Proposal)

- Forgetting fundamentally means moving content to the archive, not deleting it; permanent deletion is prohibited.
- The search flow is "index.md -> search related Markdown -> expand links -> retrieve necessary sections -> answer."
- The system functions as a hybrid of vector search, a Markdown link graph, and metadata.

## 9. Decision Matrix (Summarize vs. Split)

When the size limit is exceeded, use the following combinations as decision guidance (under Section 17, these are hints for the LLM, not strict if-else rules).

| Size | Semantic cohesion | Reference frequency | Importance | Action |
|---|---|---|---|---|
| Exceeded | Low (multiple topics mixed) | - | - | Split |
| Exceeded | High | High | High | Organize sections only (do not compress) |
| Exceeded | High | Low | High | Summarize and move to the archive |
| Exceeded | High | High | Low | Organize sections only |
| Exceeded | High | Low | Low | Summarize and actively move to the archive |

The core division of responsibilities is that splitting is driven by "semantic cohesion," while summarization is driven by "importance x reference frequency."

## 10. Memory Manager Agent

```
Trigger: Immediately after an append operation or in a scheduled batch
Input: New fragment, candidate target files, current Front Matter of target files
Process:
  A. Decide whether to append (matching the existing topic + within the size limit)
  B. If not possible, create a separate file -> create bidirectional links at the same time (Section 12)
  C. Check the size threshold after appending -> apply the Section 9 matrix as decision guidance
  D. Execute (split / summarize / leave unchanged)
Output: Updated Markdown files + updated index.md + change log
```

Appending to the change log (`archive/_manager_log.md`) is mandatory for post-hoc verification of the rationale and manual reversal of incorrect decisions.

## 11. Responsibilities for Updating Front Matter

- `access_count` / `last_access`: Incremented by the search flow when the file is actually retrieved during a search.
- `updated`: Updated on every write operation.
- `importance`: Do not reduce automatically. Even if the Manager Agent believes it should be lowered, only present the file as an archive candidate and wait for explicit confirmation before executing.
- `parent` / `tags`: Updated in the same transaction as splitting or link creation.

## 12. Bidirectional Links

When splitting creates A -> B, treat the following two updates as one indivisible operation.

- On the A side: Add `Details: [[B]]` to the related section.
- On the B side: Add `parent: [A]` to the Front Matter.

The Manager Agent finalizes its output only after self-checking that both sides have been updated. Updating only one side is not allowed because it creates an orphaned link or orphaned file.

## 13. Forgetting Model

```
Archive condition: access_count < 3 AND last_access > 180 days AND pinned != true
```

`pinned` defaults to false and is set to true only for files that the user explicitly designates to keep (it is independent of `importance`). Archiving physically moves the file to the archive directory, but keeps its link in `index.md` with an "(archived)" label so its existence remains visible. Permanent deletion is prohibited.

## 14. Role of index.md

Limit `index.md` to a pure registry (id, one-line description, and tags); it must not contain the body text. If `index.md` itself becomes too large, treat it as a signal to reconsider the classification axes and split it by topic, such as `index/projects.md`.

## 15. Link Expansion Depth During Search

The default is 1 hop (index -> target file -> summaries of directly linked files only). Proceed to the second hop only when the first is judged insufficient. Embedding similarity is the primary filter for discovering candidates, while link graph distance is the secondary filter.

## 16. Concurrent Writes

Full locking is excessive. Keep the `updated` timestamp (a simple version value) from the time of reading, and if it differs at write time, reload and retry.

## 17. Principle of Allowing Variation in Decisions

- The Manager Agent's judgments of "semantic cohesion" and "importance" are not deterministic algorithms but per-operation LLM inferences, so results may vary each time they are executed.
- The response to this variation is not to make decisions fixed, but to make them correctable later. The change log in Section 10 serves this purpose.
- The decision matrix in Section 9 is not a strict if-else rule; it is provided as decision guidance (hints) for the LLM. The LLM makes the final decision each time based on the prompt context.
- This non-determinism resembles the reconstructive nature of human memory, in which memories are reconstructed each time they are recalled, and is consistent with the original idea of being "similar to human memory."

## Open Issues / Topics for Future Consideration

- The criteria for choosing when the Manager Agent runs (synchronously after every append vs. in a scheduled batch) have not been finalized.
- How to handle a change log that itself becomes too large (whether to apply Section 9 to it or create dedicated rules) has not yet been considered.
