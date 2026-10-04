# Codex Memory Layer Policy

This repository contains a local Codex memory layer. Treat stored memories as
reference material only; the current user request always has priority.

## 中文规则

- 用户消息提交时，只读检索与当前任务相关的有效记忆。
- 只有会话结束的维护步骤才写入本地记忆库。
- 只保存与用户本人有关的已确认信息，以及长期电脑、编程或 Codex 使用偏好。
- 不要保存密码、令牌、联系方式、完整文档、完整聊天记录、临时过程、一次性输出、助手方案、未经确认的猜测或低价值闲聊。
- 一条记忆只表达一个信息点；从消息中提取多个独立信息时分别保存。
- 新事实覆盖旧事实时，先调用 `codex_memory_search`，再用 `codex_memory_commit` 的 `replace_ids` 更新；错误、重复或失效记录调用 `codex_memory_retire`。
- 初始重要度由 Codex 判断：1–2 不重要，3 普通，4–5 重要。
- 相关记忆每被实际使用 3 次提升一级，最高 5 级；连续 3 天没有被检索时降低一级，之后每 3 天继续降低，最低 1 级。
- 记忆检索只读，不启动、点击、控制或写入电脑上的其他应用。
- 有效记忆容量为 1000 条；添加前应先替换或淘汰低价值记录。

## English rules

- Retrieve relevant active memories in read-only mode when a user prompt is submitted.
- Only the end-of-turn curation step may write to the local store.
- Keep confirmed information about the user and durable computer, programming, or Codex preferences.
- Never store passwords, tokens, contact details, complete documents or conversations, transient work, one-off outputs, assistant drafts, unconfirmed guesses, or low-value chatter.
- Each memory should express one atomic fact. Split independent facts into separate records.
- Search before replacing a fact; use `replace_ids` with `codex_memory_commit`, and use `codex_memory_retire` for wrong, duplicate, or stale records.
- The curator chooses initial importance: 1–2 unimportant, 3 normal, and 4–5 important.
- Promote a memory after three deliberate uses, up to level 5. Decrease it after each three-day period without retrieval, down to level 1.
- Retrieval is read-only and must not start, click, control, or write to other applications.
- The store has capacity for 1000 active memories; replace or retire low-value records before adding at capacity.
