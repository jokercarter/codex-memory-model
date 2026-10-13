# Codex Memory Model v2

Codex Memory 是只依赖 Python 标准库的本地记忆系统：SQLite 保存原子事实、版本和来源；MCP 让 Codex 按场景读取、维护记忆、接续项目和复用流程。它也提供本地健康面板、关系图、快照与撤销。

Codex Memory is a local memory system built with the Python standard library. SQLite stores atomic facts, revisions and provenance; MCP lets Codex retrieve scoped context, maintain memories, resume projects and reuse verified procedures. A local health dashboard, relationship graph and recovery snapshots make the store inspectable.

**模型说明 / Model behavior:** 语义提取、同义表达扩展、矛盾判断和综合分析由调用方配置的 Codex 模型完成。本地后端负责存储和确定性规则，不会自行调用模型；无需本地模型、向量数据库或额外 API key. The Codex model configured by the caller performs semantic work. The local backend handles storage and deterministic rules; it does not invoke a model or require a local model, vector database or additional API key.

## 快速开始 / Quick start

需要 Windows、Python 3.10+ 和支持 MCP 的 Codex Desktop；使用 MCP 不要求安装 Codex CLI。无需 pip 安装。Requirements: Windows, Python 3.10+, and Codex Desktop with MCP; no CLI or third-party packages are required.

```powershell
git clone https://github.com/jokercarter/codex-memory-model.git
Set-Location .\codex-memory-model
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -ConfigureCodex
```

完全退出并重新打开 Codex，然后在聊天中输入：

> 使用 $codex-memory，读取与当前任务相关的记忆；确认有长期价值的信息后再维护记忆。

Restart Codex completely, then say: “Use $codex-memory to retrieve relevant context and curate confirmed reusable information.” Explicit MCP/Skill use works independently of lifecycle hooks. Installation and server startup do not prove that desktop hooks executed successfully.

安装器选项 / Installer options:

| 参数 Parameter | 作用 Behavior |
| --- | --- |
| 无参数 / none | 只复制运行代码和 Skill / Copy runtime and skill only |
| `-ConfigureCodex` | 配置 MCP，保留现有 Hook 配置 / Configure MCP, preserve hooks |
| `-ConfigureHooks` | 显式创建/更新记忆 Hook / Explicitly configure memory hooks |
| `-InstallDirectory "D:\Tools\codex_memory"` | 更换代码安装位置 / Change runtime destination |
| `-PythonExecutable "C:\Path\python.exe"` | 指定解释器 / Select Python explicitly |

解释器顺序为显式参数、`CODEX_MEMORY_PYTHON`、Codex 随附 Python、PATH 的 python、py -3。运行文件默认安装到 `%USERPROFILE%\.codex\codex_memory`；Skill 安装到 `%USERPROFILE%\.codex\skills\codex-memory`。升级会覆盖代码；已有数据库和设置继续保留。Interpreter selection follows explicit parameter, environment override, bundled Python, PATH Python, then py -3. Upgrades replace code while preserving data/settings.

数据库默认位于 `%LOCALAPPDATA%\CodexMemoryVault\memory.db`。可用 `CODEX_MEMORY_DB` 指向单独数据库（见实际运行环境的路径设置）。不要把数据库放进 Git 仓库。The database is local. Keep all live data outside source control.

## 日常使用 / Everyday workflows

| 要做什么 Task | 提示词示例 Example |
| --- | --- |
| 读取任务背景 / Retrieve context | “读取 project-demo 空间中与文件导出有关的记忆，场景是 document。” |
| 保存新信息 / Save a fact | “保存这项已确认的配置，用 project-demo 空间；先查旧值，冲突时用新值替换并保留历史。” |
| 接续任务 / Resume work | “读取 project-demo 的任务接续卡，说明下一步并继续。” |
| 复用流程 / Reuse procedure | “找出这个环境下已验证的流程，检查前提和成功标准后使用。” |
| 历史问题 / Ask about history | “查询上周生效的配置，并列出之后发生的变更。” |
| 纠正 / Correct | “这条信息只适用于本项目，改为场景必读，不要全局应用。” |
| 综合分析 / Synthesize | “根据相关记忆给出建议，注明引用的记录版本，区分事实与推断。” |
| 恢复 / Recover | “先创建快照，再撤销记忆 42 的上次修改。” |

所有示例均为虚构 / All examples are synthetic.

## 能力与规则 / Capabilities and rules

### 分层检索 / Scoped retrieval

`scope=global` 表示全局规则，`scope=scenario` 配合 `scenarios` 表示特定场景必读，`scope=on_demand` 表示按需召回。`space` 将全局、课程、求职或项目分开；搜索通常包含指定空间和全局空间。旧的 `always_apply` 接口保留兼容；将旧记录改成场景必读应先核对语义，不能仅凭分类猜测。

Use global rules for universally applicable instructions, scenario rules for matched tasks, and on-demand records for ordinary facts. Project spaces avoid mixing unrelated work. Legacy always-apply controls remain available; content-aware reclassification is a curation step.

检索结合关键词、中文短语、调用方提供的 `aliases` 和类型化关系扩展。相关性优先，返回量受 `limit` 和 `token_budget` 约束；通过 `get` 读取完整正文。没有后台自动生成同义词或向量服务。Retrieval uses lexical/CJK matching, caller-supplied aliases and typed edges. Results fit a context budget; use `get` for full content. Query expansion and final relevance judgment belong to Codex.

### 四个独立维度 / Four independent dimensions

| 字段 Field | 含义 Meaning | 默认规则 Default |
| --- | --- | --- |
| `importance` | 长期价值 / Durable value | Codex 判断 1–100，不因闲置直接衰减 / Caller-judged, stable |
| `activity` | 最近使用程度 / Recent activity | 每次实际使用取 `max(当前+20, 当前×1.5)`，最高100；每6小时闲置×0.9，最低1 |
| `confidence` | 证据可信度 / Evidence confidence | 0–1；根据确认和验证判断 / Based on evidence |
| `valid_from`, `valid_until` | 事实生效区间 / Validity interval | 使用 ISO 8601 时间 / ISO 8601 timestamps |

搜索完全只读，不会更新使用次数或存储分数。`mark_used` 只记录实际依赖的记忆；不能把所有搜索结果都标为使用。活跃度低不等于信息错误。Search is read-only. Mark only actual reliance. Low activity alone is not a reason to discard durable knowledge.

### 版本、关系和恢复 / Revisions, relations and recovery

更新保留不可变历史、来源和替换原因。`expected_revision` 防止多个聊天相互覆盖；`request_id` 防止重试造成重复写入或使用计数。遇到版本冲突先重新读取并合并。Historical revisions are retained; optimistic revisions and idempotency keys prevent conflicting writes and duplicate retries.

关系类型：`related`、`co_used`、`same_project`、`prerequisite`、`supersedes`、`supports`、`contradicts`，强度 1–100。共同使用与语义关系分别处理；过时正文的旧关系需要重新审查。Typed edges distinguish shared use from prerequisites, replacement and evidence.

批量维护前可创建 SQLite 一致性快照。单条撤销生成新版本；整库恢复先创建安全快照。快照包含真实数据，始终留在本机。Snapshots are consistent database backups; revision restore appends history, and whole-store restore makes a safety snapshot first.

### 项目与经验 / Projects and reusable experience

- **项目空间 / Spaces**：全局背景与项目知识并存，可显式查询。
- **任务记忆包 / Packets**：组合相关事实、适用规则、任务状态和流程，遵守上下文预算。
- **个人资料视图 / Profiles**：从来源记录派生字段；缺失信息保持缺失，不另造一份权威资料。
- **任务接续卡 / Task cards**：目标、完成项、下一步、文件和待确认问题；默认保留7天，完成后关闭。
- **流程与失败库 / Procedures and failures**：保留环境、前提、步骤、成功判据、验证时间和证据；失败条目记录可复现条件与恢复方法。
- **反馈 / Feedback**：记录 useful / irrelevant / incorrect，区分一次性要求和长期偏好。
- **文件联动 / File fingerprints**：显式关联本地文件路径和指纹，显式检查变化并标记需要复核；不会静默读取所有文件或监听其它应用。
- **带依据分析 / Cited reflection**：先准备证据，由当前 Codex 综合，再保存引用 ID/版本的派生结论；来源变化后标记过时。
- **Skill 草稿 / Skill drafts**：从带验证证据的流程生成可审阅草稿；草稿不会自行安装或执行。
- **健康与关系图 / Health and graph**：检查缺少来源、重复候选、过期任务/流程和失效引用，并查看类型化关系。

**容量 / Capacity:** 1000 条是有效长期原子记忆的默认上限。历史版本、任务卡、派生视图、快照不重复占用这1000个名额，但仍占用磁盘；需要定期检查健康面板并清理过期任务/不需要的快照。The active-record limit excludes revisions, task cards, derived views and snapshots; monitor disk usage separately.

## MCP 接口 / MCP tools

所有工具名称带 `codex_memory_` 前缀。以下为主要参数，完整类型由 `tools/list` 提供。All names use the prefix; discover authoritative schemas through MCP `tools/list`.

| 工具 Tool | 主要参数 Main arguments | 读写 Access |
| --- | --- | --- |
| `search` | query, space, scenarios, aliases, limit, token_budget, category, min_importance, as_of, include_global | 只读 Read |
| `get`, `history` | memory_id | 只读 Read |
| `commit` | title, content, importance, confidence, memory_key, replace_ids, expected_revision, request_id, space, kind, scope, scenarios, evidence, valid_from/until | 写 Write |
| `retire`, `mark_used` | memory_ids, source_session, request_id；mark_used可加co_use_groups | 写 Write |
| `related` / `relation` | memory_id / a, b, relation_type, strength, evidence | 读 / 写 Read / write |
| `set_always_apply` | memory_ids, enabled | 兼容写 Legacy write |
| `stats` | 无 / none | 只读 Read |
| `restore_revision` | memory_id, revision, expected_revision | 写 Write |
| `snapshot`, `restore_snapshot` | label / snapshot_id | 写 Write |
| `spaces` | action=list/get/create, key, title, description | 按action / By action |
| `task` | action=list/get/save/close, key, space, goal, completed, next_steps, files, questions, ttl_hours | 按action |
| `procedure` | action=list/get/save/feedback/skill_draft, memory_id, procedure_type, steps, prerequisites, success_criteria, environment, evidence | 按action |
| `profile`, `packet` | fields/space；query/space/scenarios/token_budget | 只读 Read |
| `reflect` | action=prepare/save/get/list, topic, conclusion, citations, inference | 按action |
| `file` | action=attach/check/list, path, memory_ids | list只读；attach/check写 |
| `feedback` | memory_id, outcome, context, correction, scope | 写 Write |
| `health`, `graph`, `maintenance` | space / memory_id / limit按schema | 只读分析 Read |

`reflect.save` 的引用形如 `[{"id":42,"revision":3}]`。推断应显式标注，不能自动变成确认事实。`expected_version` 用于任务卡等扩展对象；长期记忆用 `expected_revision`。Citations pin source revisions; derived inference is not a confirmed fact. Feature objects use expected_version; core records use expected_revision.

写入示例 / Example write:

```json
{"title":"Demo project export command","content":"For the demo project's current toolchain, export with the documented build command and verify that the PDF opens.","space":"project-demo","kind":"procedure","scope":"scenario","scenarios":["document"],"importance":72,"confidence":0.9,"memory_key":"export-procedure","evidence":[{"type":"verified","note":"Synthetic example only"}],"request_id":"demo-export-create-1"}
```

## 参数调整 / Configuration

复制 `config/memory-settings.json.example` 为数据库目录下的 `settings.json`，或用环境变量 `CODEX_MEMORY_SETTINGS` 指定配置文件。修改后重启 MCP，使各进程使用一致设置。Copy the template to `settings.json` next to the database, or select it with `CODEX_MEMORY_SETTINGS`, then restart MCP. Unknown keys and invalid values are rejected on writable initialization.

| 设置 Setting | 默认 Default | 作用 Effect |
| --- | --- | --- |
| max_memories | 1000 | 有效长期记录上限 / Active memory cap |
| decay_interval_hours | 6 | 活跃度衰减间隔 / Activity decay interval |
| activity_decay_factor | 0.9 | 每个间隔的活跃度倍率 / Decay multiplier |
| activity_boost_factor | 1.5 | 实际使用时的增长倍率 / Use multiplier |
| activity_boost_min | 20 | 每次使用最低增长 / Minimum use boost |
| context_token_budget | 4000 | 默认上下文预算；近似估计 / Approximate default budget |
| relation_seed_limit | 12 | 初始召回候选数 / Initial seed count |
| relation_expansion_limit | 32 | 图扩展候选数 / Graph expansion count |
| relation_min_strength | 30 | 扩展所需最低关系强度 / Edge threshold |
| relation_half_life_days | 30 | 共同使用关系半衰期 / Co-use edge half-life |
| default_task_ttl_hours | 168 | 任务接续卡默认有效期 / Default task TTL |

示例：只想减少上下文量，把 `context_token_budget` 改成 2000；想延长近期活跃度的保留，把 `decay_interval_hours` 改成 12。重要度本身不随这些参数衰减。To reduce context, set the budget to 2000; to slow activity decay, set the interval to 12. Neither changes durable importance.

## 本地管理与维护 / Local management

新管理面板可双击 `%USERPROFILE%\.codex\codex_memory\启动 Codex 记忆面板.bat`，或在源代码目录运行 `pythonw .\codex_memory_dashboard.py`。旧入口 `pythonw .\codex_memory_vault.pyw` 会转到同一面板。它提供记忆检索与编辑、场景/空间、任务接续、流程库、资料视图、证据摘要、文件指纹、健康报告、关系图、版本和快照恢复。浏览数据库以只读方式打开；保存、导入和恢复才写入本地库。新面板只在本机运行。Launch the dashboard from the installed batch file or run `pythonw .\codex_memory_dashboard.py` in the source tree. The legacy entry point opens the same workbench. Browsing stays read-only; explicit save/import/restore operations write to the local store.

升级前创建快照；第一次可写连接迁移旧结构并保留内容和旧关系。旧的“每次必读”记录按标题/标签中的场景线索迁为候选范围，并标记 `needs_review`；Codex 在依赖它们作为指令前应核对正文与适用场景。只读连接不执行迁移，未初始化或版本过旧时应先完成本地升级再读取。Migrations occur on writable initialization, never during reads. Legacy scope suggestions remain visible in the health panel until reviewed.

## 验证、打包与发布 / Validation and packaging

```powershell
python -m unittest discover -s tests -v
python .\scripts\sync_runtime.py
python .\scripts\sync_runtime.py --check
powershell -ExecutionPolicy Bypass -File .\scripts\check_repository_data_free.ps1
git diff --check
```

评测仅使用虚构资料、临时数据库和固定时间；覆盖原子化/同义表达、跨项目检索、版本更新、历史问题、缺失证据、流程失效、幂等和恢复。语义提取由调用方负责，应使用同一组虚构对话比较不同调用模型的质量。Tests use synthetic fixtures and temporary databases. Backend tests cover storage/retrieval invariants; extraction quality must be evaluated with the chosen caller model.

根目录运行模块为唯一代码源；`sync_runtime.py` 只复制明确列出的无数据运行文件、Skill和设置模板到插件包，`--check` 检测漂移。不要手工长期维护多套运行代码。Canonical modules live at the repository root; the sync script packages only an explicit allowlist.

已安装本地插件或独立 Skill 更新后，可分别指定目标来同步：

```powershell
python .\scripts\sync_runtime.py --installed-plugin "$env:USERPROFILE\.codex\plugins\cache\<marketplace>\codex-memory\<version>" --installed-skill-dir "$env:USERPROFILE\.codex\skills\codex-memory" --hook-runtime "$env:USERPROFILE\.codex\codex_memory"
python .\scripts\sync_runtime.py --check --installed-plugin "$env:USERPROFILE\.codex\plugins\cache\<marketplace>\codex-memory\<version>" --installed-skill-dir "$env:USERPROFILE\.codex\skills\codex-memory" --hook-runtime "$env:USERPROFILE\.codex\codex_memory"
```

同步命令只更新运行代码和 Skill；不会修改 Hook 配置、重启 Codex 或触碰记忆正文。安装后的 MCP/Skill 由 Codex 在下次启动时重新载入。

GitHub 仅存放代码、配置模板、说明和虚构测试。记忆正文、来源、关系、数据库、快照、备份、日志、任务卡、个人资料和导出均禁止提交。所有更新从专用分支通过 Pull Request 合并。Publish only data-free code and synthetic examples, through dedicated branches and Pull Requests.

## 故障处理与边界 / Troubleshooting and limits

- **连接不存在 / Missing database:** 首次创建记录或启动管理器完成初始化；读取不会悄悄创建库。Initialize with a write or the manager.
- **版本冲突 / Version conflict:** 重新读取最新记录并判断如何合并，使用新的操作键提交；不能只改版本号盲目重试。Reread and reconcile.
- **重复请求 / Retry:** 同一操作重用 request_id；更改参数时使用新键。Reuse the key only for the same logical request.
- **检索不足 / Weak recall:** 指定 space/scenarios，提供少量 aliases，检查有效期和 scope；用 get 查看全文。Inspect scope, validity and aliases.
- **流程或摘要过时 / Stale procedure/view:** 检查引用版本、文件指纹和验证日期，再重新验证并保存。Revalidate evidence before reuse.
- **Hook 报错 / Hook failure:** 本版本功能验收不等于桌面端 Hook 成功。可直接调用 Skill/MCP；Hook 需要在真实桌面会话中单独确认，不能以“信任状态”替代执行结果。Explicit MCP use remains available; verify hooks separately.
- **容量达到上限 / Capacity:** 先审查重复和失效记录，再合并或淘汰；不要仅凭活跃度清理稳定事实。Curate before adding at capacity.

更详细的实现说明见 [架构 / Architecture](docs/architecture.md)。
