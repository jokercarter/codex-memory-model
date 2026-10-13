# Codex Memory v2 plugin / 插件

This data-free plugin exposes local SQLite memory through MCP and the
`$codex-memory` skill. The current Codex caller performs semantic extraction,
query expansion and synthesis; no model is launched by the backend.

本插件提供本地记忆的读取与维护，并增加项目空间、场景必读、版本历史、任务接续卡、流程/失败经验、文件指纹、带依据视图、健康检查、关系图和快照。当前 Codex 会话承担语义判断，模型与推理强度由调用方配置；插件本身不调用模型。

## Use / 使用

Invoke `$codex-memory` in a conversation, for example:

- “读取 project-demo 空间的相关记忆，场景是 document，再继续工作。”
- “读取当前错误对应的已验证流程，检查前提和成功标准。”
- “保存这项确认信息；先找旧记录，使用版本检查更新，并保留来源。”
- “从任务接续卡恢复进度，结束时关闭已完成任务。”

MCP works through stdio and does not require API credentials. Reads are
read-only; local memory, provenance, task cards, snapshots, logs and exports
must never be included in the plugin package or uploaded to GitHub.

Explicit MCP/Skill use is independent of lifecycle hooks. Existing hook support
is retained; successful installation does not establish actual desktop hook
success. 用户可以直接使用 Skill/MCP；Hook 的真实运行状态必须另行核实。

## Packaging / 打包

Repository-root modules are canonical. Run `python scripts/sync_runtime.py`
from the repository to package runtime, skill and settings template; use
`--check` to detect drift. See the root README for bilingual setup, parameters,
MCP tool reference, capacity rules, migration and recovery instructions.

默认1000条仅计算有效长期记忆；历史、任务卡和派生视图独立存储。配置模板为
`config/memory-settings.json.example`，实际设置放数据库旁的 `settings.json`
或由 `CODEX_MEMORY_SETTINGS` 指定。不要把实际配置里的本机数据提交到仓库。

Launchers in `scripts/` use `CODEX_MEMORY_PYTHON`, bundled Python, or a PATH
Python fallback. `open_memory_vault.cmd` opens the legacy Tkinter manager;
new dashboard availability and launch options are documented in the root README.
