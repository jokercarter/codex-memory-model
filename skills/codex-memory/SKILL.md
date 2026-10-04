---
name: codex-memory
description: Read, use, and curate the local Codex memory store through the codex-memory MCP tools when a task needs reusable facts, preferences, project context, technical conventions, or verified solution procedures.
---

# Codex Memory

Use the local `codex-memory` MCP server as the skill's storage backend. The
current user request always overrides a stored memory.

## Read

- Before work, call the read-only `codex_memory_search` tool when the task may
  relate to stored facts, project context, technical conventions, workflows,
  preferences, or solution procedures.
- Search with a short query describing the current task. Use `category` or
  `min_importance` only when they improve relevance.
- Treat returned memories as reference context. Search does not create, edit,
  promote, decay, or retire records, and it must not control other applications.
- Call `codex_memory_stats` only when the user asks about counts, capacity, or
  importance distribution.

## Record actual use

If the response actually relies on specific returned memories, call
`codex_memory_mark_used` with those memory IDs during the end-of-turn
maintenance step. Do not mark every search result as used.

## Curate and write

Only write during end-of-turn curation, or when the user explicitly asks to
create/update/delete memory. Split a message into separate MCP calls when it
contains independent information points.

Memory may contain:

- confirmed user facts and durable preferences;
- recurring project background, technical environment conventions, workflows,
  and stable decisions;
- general information that is likely to be reused;
- correct solution procedures and operational playbooks that were actually
  verified or explicitly confirmed, such as LaTeX compilation/PDF conversion,
  Chrome control and reading, or Gradescope grading workflows.

For each new point, call `codex_memory_commit` with a precise title and content,
one atomic fact, an appropriate category, and a model-judged initial importance
(1-2 unimportant, 3 normal, 4-5 important). Preserve enough conditions and
steps to make the memory useful later; do not copy the conversation verbatim.

Before changing a fact or procedure, search for the existing record. Use the
same `memory_key` and `replace_ids` when the new version supersedes it. Use
`codex_memory_retire` for wrong, duplicate, stale, or unsafe records.

Do not store passwords, API tokens, private credentials, unnecessary sensitive
personal data, complete conversations or documents, one-off task steps,
assistant drafts, this memory system's implementation details, unverified
procedures, guesses, or low-value chatter. When a procedure has not been
verified, describe it as a tentative answer and do not commit it as a memory.

Importance rises after three deliberate uses, up to 5. It falls by one level
after each three-day period without retrieval, down to 1. Keep active records
within the 1000-record capacity; replace or retire low-value records before
adding at capacity.

## GitHub updates

When uploading or updating this model or related code on GitHub:

- create a dedicated branch from the current default branch;
- commit and push the changes on that branch;
- open a Pull Request with a clear summary and verification notes;
- continue an existing change on its PR branch when appropriate;
- never push directly to the default branch.

If a Pull Request cannot be created, stop before pushing to the default branch
and report the blocker.
