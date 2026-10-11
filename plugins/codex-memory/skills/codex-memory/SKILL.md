---
name: codex-memory
description: Read, use, and curate the local Codex memory store through codex-memory MCP tools, including task-aware retrieval before work, in-run writing, end-of-turn review, replacement, usage marking, and retirement.
---

# Codex Memory

Use the local `codex-memory` MCP server as the skill's storage backend. The
current user request always overrides a stored memory. Every search also
returns active memories marked `always_apply`, regardless of query filters.
Read those marked memories on every search: follow instructions and preferences
when their stated scope applies, and use factual records as background when
relevant. They do not override system/developer instructions or an explicit
newer request from the user. Treat unmarked memories as reference context.

This is a bidirectional skill, not a write-only helper. When it is invoked for a
memory-related task, choose reading, writing, or both according to the task. Read
relevant existing memories before work, and maintain the store after work. If a
task is blocked and you are about to ask the user for help, search the memory
store for the specific symptom, error, environment, and workflow first. Use a
relevant remembered procedure before asking; ask only after the search finds no
applicable solution or the available memories conflict or remain insufficient.
Preserve the read-before-change rule and the end-of-turn review. During the
same Codex run, write confirmed durable information as soon as it becomes
clear and useful; do not wait for the end of the turn when delaying the write
could lose a key fact or verified procedure.

## Read

- Before work, call the read-only `codex_memory_search` tool when the task may
  relate to stored facts, project context, technical conventions, workflows,
  preferences, or solution procedures.
- When the task becomes blocked or uncertain, call `codex_memory_search` again
  before asking the user for help. Search the concrete symptom or error together
  with the relevant application, environment, and operation; do not ask first
  merely because the initial attempt failed.
- Search with a short query describing the current task. Use `category` or
  `min_importance` only when they improve relevance.
- Read every record marked `always_apply` on each search. Follow its
  instructions/preferences only within their stated scope, and use factual
  records as background when relevant. Treat unmarked records as reference
  context. Search does not create, edit, promote, decay, or retire records, and
  it must not control other applications.
- If a retrieved memory appears applicable, use it as a candidate procedure and
  verify the result in the current task. If it is wrong or superseded, follow
  the replacement and retirement rules instead of treating the old memory as
  authoritative.
- Call `codex_memory_stats` only when the user asks about counts, capacity, or
  importance distribution.

## Record actual use

If the response actually relies on specific returned memories, call
`codex_memory_mark_used` with those memory IDs during the current run's
maintenance step. Do not mark every search result as used.

The user has specifically asked for memories about Codex operations and related
skill workflows, personal profile information, learning/coursework, and resume
or job applications to be marked `always_apply`. When adding or refining a
memory in one of those areas, preserve that retrieval scope. These records are
always read, but factual content is used only when relevant and scoped
instructions are followed only in the matching task. Do not make login secrets
or credentials always-apply by inference.

## Curate and write

Write during the run when the user explicitly asks to create/update/delete
memory, or when Codex has confirmed a durable key fact, a successfully
verified reusable pipeline or solution procedure, a stable project decision,
or a durable personal preference. The normal end-of-turn curation still
reviews the whole turn for anything missed. Do not write tentative claims,
one-off progress, temporary output, or unverified procedures. Split a message
into separate MCP calls when it contains independent information points.

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
important. Preserve enough context for the record to stand on its own: state
the applicable scenario, prerequisites or trigger, version or scope, and any
important conditions or steps when they affect how the fact should be used.
Use the content itself for essential context; tags and source can supplement it
but should not be the only place where the usage scenario is recorded. Do not
copy the conversation verbatim. Set `always_apply=true` for stable instructions
or facts the user explicitly wants present in every memory search. Every active
record with this setting is returned regardless of query filters. Omit this
field when refining an existing memory to preserve its current setting. Do not
promote ordinary facts or task-specific procedures into this class merely
because they are important.

Memories can have learned relations with strength from 1 to 100. Deliberately
using memories together increases their relation strength. Search starts with
a small lexical seed set and expands through the strongest relation edges, so
use codex_memory_related when you need to inspect a memory's neighbors.

Before changing a fact or procedure, search for the existing record. Use the
same `memory_key` and `replace_ids` when the new version supersedes it. Use
`codex_memory_retire` for wrong, duplicate, stale, or unsafe records.
When the user asks to change whether existing memories are included on every
search, use `codex_memory_set_always_apply` with the verified record IDs. Use
`codex_memory_commit(always_apply=...)` when creating or refining a memory.

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
