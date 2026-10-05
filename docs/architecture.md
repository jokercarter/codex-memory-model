# Architecture / 架构

## Data flow / 数据流

```text
Codex session
    |
    +-- SessionStart hook ------> read-only search of important memories
    |
    +-- UserPromptSubmit hook --> read-only task-aware search
    |
    +-- Codex MCP tools --------> search, mark-used, commit, replace, retire
    |
    +-- Stop hook --------------> asks Codex to perform one curation pass
                                  |
                                  +--> SQLite memory.db
```

`codex_memory_core.py` is the shared storage layer. The MCP server and desktop
manager call the same schema and lifecycle rules. Retrieval hooks explicitly
open SQLite in read-only mode with `query_only`, so retrieval cannot create or
modify records. Writes happen through the MCP write tools during curation.

`codex_memory_core.py` 是共享存储层。MCP 服务和桌面管理器使用同一套表结构与生命周期规则。检索 Hook 使用 SQLite 只读模式和 `query_only`，不会创建或修改记录；写入只通过记忆维护阶段的 MCP 工具完成。

## Record lifecycle / 记录生命周期

1. The curator searches for related active records.
2. A new atomic fact is committed with a model-chosen importance and confidence.
3. A changed fact updates an existing record with `replace_ids`.
4. Wrong, duplicate, or stale records become `obsolete` and leave active capacity.
5. Deliberate use increments `use_count`; every third use promotes importance.
6. Each three-day period without retrieval reduces importance by one level.

1. 维护者先检索相关的有效记录。
2. 新的原子信息由模型判断重要度和置信度后写入。
3. 发生变化的信息通过 `replace_ids` 更新旧记录。
4. 错误、重复或失效记录标记为 `obsolete`，不再占用有效容量。
5. 实际使用会增加 `use_count`，每次实际使用至少增加 20 点并乘以 1.5，最高 100。
6. 连续 6 小时未检索会将重要度乘以 0.9，之后每 6 小时继续衰减，最低 1。
