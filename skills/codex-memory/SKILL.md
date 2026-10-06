---
name: codex-memory
description: Read, use, and curate the local Codex memory store through codex-memory MCP tools, including task-aware retrieval before work and end-of-turn writing, replacement, usage marking, and retirement.
---

# Codex Memory

Use the local `codex-memory` MCP server as the skill's storage backend. The
current user request always overrides a stored memory.

This is a bidirectional skill, not a write-only helper. When it is invoked for a
memory-related task, it can both read relevant existing memories before work and
maintain the store after work. Use only the operation that the current task
requires, while preserving the read-before-change and end-of-turn write rules.

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

Memory may contain any confirmed information that may help a future task, including:

- confirmed user facts and durable preferences;
- useful general facts and background, even when they are not about the user;
- recurring project background, technical environment conventions, workflows,
  and stable decisions;
- general information that is likely to be reused;
- correct solution procedures and operational playbooks that were actually
  verified or explicitly confirmed, such as LaTeX compilation/PDF conversion,
  Chrome control and reading, or Gradescope grading workflows.

For each new point, call `codex_memory_commit` with a precise title and content,
one atomic fact, an appropriate category, and a model-judged initial importance
from 1 to 100. Treat 1-33 as unimportant, 34-66 as normal, and 67-100 as
important. Preserve enough conditions and steps to make the memory useful
later; do not copy the conversation verbatim.

Memories can have learned relations with strength from 1 to 100. Deliberately
using memories together increases their relation strength. Search starts with
a small lexical seed set and expands through the strongest relation edges, so
use codex_memory_related when you need to inspect a memory's neighbors.

Before changing a fact or procedure, search for the existing record. Use the
same `memory_key` and `replace_ids` when the new version supersedes it. Use
`codex_memory_retire` for wrong, duplicate, stale, or unsafe records.

The user has explicitly authorized broad retention, including sensitive
information. Do not reject a user-requested fact merely because it contains
contact details, passwords, API tokens, private credentials, or other sensitive
data. Keep the information precise and restrict it to the user's local memory
store. Still split independent facts into atomic records, summarize rather than
copy complete conversations or documents verbatim, and label unverified
content as tentative instead of presenting it as confirmed.

Each deliberate use raises importance to at least current+20 and roughly
current*1.5, capped at 100. Every 6 hours without retrieval multiplies
importance by 0.9, down to 1. Keep active records within the 1000-record
capacity; replace or retire low-value records before adding at capacity.

## GitHub updates

When uploading or updating this model or related code on GitHub:

- create a dedicated branch from the current default branch;
- commit and push the changes on that branch;
- open a Pull Request with a clear summary and verification notes;
- continue an existing change on its PR branch when appropriate;
- never include memory text, relation rows, database files, JSON exports, backups,
  logs, hook payloads, or any local memory context in a commit;
- inspect staged files and the diff before pushing to confirm that the change
  contains only data-free model code, templates, and documentation;
- never push directly to the default branch.

If a Pull Request cannot be created, stop before pushing to the default branch
and report the blocker.
