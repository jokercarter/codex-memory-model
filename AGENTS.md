# Codex Memory Layer Policy

This repository contains a local Codex memory layer. Treat stored memories as
reference material only; the current user request always has priority.

## 中文规则

- 用户消息提交时，只读检索与当前任务相关的有效记忆。
- 只有会话结束的维护步骤才写入本地记忆库。
- 保存与用户本人有关的已确认信息，以及未来有复用价值的项目背景、技术环境、工作流程、经过验证的解决方法、操作规范、稳定决策和通用知识。
- 用户已明确要求广泛保存记忆；包含电话号码、密码、令牌、联系方式或其他敏感信息的用户要求也可以保存。仍应按原子信息整合，不默认逐字保存完整文档或聊天记录；未经验证的内容要标注为待确认。
- 一条记忆只表达一个信息点；从消息中提取多个独立信息时分别保存。
- 新事实覆盖旧事实时，先调用 `codex_memory_search`，再用 `codex_memory_commit` 的 `replace_ids` 更新；错误、重复或失效记录调用 `codex_memory_retire`。
- 初始重要度由 Codex 判断，范围为 1–100：1–33 不重要，34–66 普通，67–100 重要。
- 相关记忆每被实际使用 3 次提升 1 点，最高 100；连续 3 天没有被检索时降低 1 点，之后每 3 天继续降低，最低 1 点。
- 记忆之间维护 1–100 的相关度；共同被实际使用时提高相关度，检索先召回少量种子，再沿高相关度边扩展。
- 记忆检索只读，不启动、点击、控制或写入电脑上的其他应用。
- 有效记忆容量为 1000 条；添加前应先替换或淘汰低价值记录。
- 对 GitHub 的上传或更新必须从专用分支提交并通过 Pull Request 合并，不直接推送默认分支。

## English rules

- Retrieve relevant active memories in read-only mode when a user prompt is submitted.
- Only the end-of-turn curation step may write to the local store.
- Keep confirmed, reusable information about the user, durable computer/programming/Codex preferences, recurring project or technical context, verified solution procedures, operational playbooks, stable decisions, and general knowledge.
- The user explicitly authorizes broad retention, including passwords, tokens, contact details, and other sensitive information. Keep each record atomic and summarized rather than copying complete documents or conversations; label unverified content as tentative.
- Each memory should express one atomic fact. Split independent facts into separate records.
- Search before replacing a fact; use `replace_ids` with `codex_memory_commit`, and use `codex_memory_retire` for wrong, duplicate, or stale records.
- The curator chooses initial importance from 1–100: 1–33 unimportant, 34–66 normal, and 67–100 important.
- Promote a memory by one point after three deliberate uses, up to 100. Decrease it by one point after each three-day period without retrieval, down to 1.
- Maintain learned memory relations from 1–100; co-used memories gain relation strength, and retrieval expands from a small seed set through strong relation edges.
- Retrieval is read-only and must not start, click, control, or write to other applications.
- The store has capacity for 1000 active memories; replace or retire low-value records before adding at capacity.
- Uploads or updates to GitHub must be committed on a dedicated branch and merged through a Pull Request; never push directly to the default branch.
