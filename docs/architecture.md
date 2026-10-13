# Architecture / 架构

## Components / 组件

```text
Current Codex caller (semantic extraction, aliases, evidence-based synthesis)
    | MCP stdio / explicit Skill
    v
codex_memory_mcp.py -----> codex_memory_core.py -----> local SQLite
    |                      revisions, search, activity, edges, snapshots
    +-------------------> codex_memory_features.py
                           spaces, task cards, procedures, feedback,
                           files, cited views, packets, health
Local dashboard --------> same core/features APIs (loopback only)
Optional lifecycle hooks -> existing integration, independently verified
```

The caller supplies semantic decisions and selects its model through its own
configuration. No component launches a model, downloads weights, opens unrelated
apps or uploads local data. Hook execution is not required for explicit MCP
calls, and a healthy MCP server is not evidence of successful hooks.

当前会话承担语义工作；后端执行索引、事务、预算、版本与确定性计算。可显式调用 MCP 和 Skill；Hook 运行需要单独验证。

## Storage and migration / 存储与迁移

- `memories` retains stable IDs and active/obsolete state, with independent
  importance, activity, confidence, validity, space and applicability scope.
- Immutable revisions preserve earlier content and provenance; restoration
  writes a new revision. Core replacements use optimistic `expected_revision`.
- Typed `memory_edges` coexist with legacy relation data for compatibility;
  semantic edges and decaying co-use edges have distinct meanings.
- Feature objects store task cards, verified procedure metadata, file hashes,
  feedback and cited derived views. Views refer to source IDs/revisions instead
  of becoming a second authoritative fact store.
- Writable initialization migrates schema once. Read-only connections use
  SQLite URI `mode=ro` and `query_only`; searches cannot initialize schemas,
  rebuild indexes or update use/decay timestamps.
- The active long-term cap is 1000 by default. Revisions, task cards, derived
  views and snapshots are separate storage, not extra active fact slots.

有效记忆、历史、任务状态、派生视图分别建模。升级只在可写初始化执行；只读查询不迁移、不更新索引、不写使用次数。快照和历史仍占磁盘，需要独立管理。

## Retrieval and curation / 检索与维护

1. Caller selects a space, scenarios and a few query aliases. The server ranks
   lexical/CJK seeds and expands suitable strong typed edges within a budget.
2. Applicable global/scenario rules precede on-demand results. Full content is
   available through `get`; `as_of` and history support temporal questions.
3. Caller verifies relevance and evidence, uses facts/procedures, and records
   actual reliance with an idempotency key. Search itself is read-only.
4. Actual use boosts activity by max(20 points,50%), capped at 100. Six idle
   hours reduce activity by 10%; importance remains durable. Confidence and
   fact validity never mean the same thing as activity.
5. New confirmed facts replace older contradictory facts with a source and
   expected revision. Duplicate/conflict candidates require semantic review.
6. Files and citations carry fingerprints/revisions. A change marks dependent
   material stale; a cited analysis is prepared from evidence and synthesized
   by the current caller, not by a hidden backend model.

查询时先限定空间与场景，再关键词召回、关系扩展和预算控制。维护时由 Codex 判断事实与矛盾，使用版本号和幂等键避免并发覆盖、重试重复。派生视图失效后重新核验来源。

## Consistency and recovery / 一致性与恢复

Mutations use transactions; retries carry a stable request_id, and feature
objects use expected_version. A version conflict returns a real tool error.
The caller rereads before reconciliation. Snapshot creation uses SQLite's
consistent backup facility. Whole-store restoration makes a safety snapshot;
no restore silently reports success after an exception. Protocol output is
ASCII JSON (valid UTF-8) regardless of the Windows console code page.

事务、乐观锁、幂等键和一致性快照分别处理部分写入、并发、重复请求和回滚。异常返回错误，不能用空成功响应掩盖故障。

## Packaging and verification / 打包与验证

The repository-root modules are canonical. `scripts/sync_runtime.py` copies an
explicit data-free allowlist to plugin runtime and checks drift with `--check`.
Installer upgrades copy code/settings templates, preserve the data store and
existing settings, and change hooks only with explicit `-ConfigureHooks`.

Synthetic tests cover migrations, unchanged read-only database state, scoped
retrieval, aliases, temporal versions, exact-once use, stale dependencies,
capacity, citations, recovery and MCP error handling. Local test databases,
real memory, logs, file evidence and snapshots must never be committed.

根目录为唯一代码源；打包脚本只复制白名单代码与模板。测试使用虚构资料和临时目录，真实记忆及派生数据不得提交 GitHub。
