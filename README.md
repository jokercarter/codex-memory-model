# Codex Memory Model

本项目是一个只依赖 Python 标准库的本地 Codex 长期记忆层。它把与用户本人有关、或体现长期电脑/Codex 使用偏好的信息整理成可检索的原子记忆，并通过 SQLite、MCP 和 Codex lifecycle hooks 连接到 Codex 桌面版。

This project is a lightweight local long-term memory layer for Codex. It stores atomic, curated memories about the user, durable preferences, reusable project and technical context, and verified solution procedures, then connects them to Codex Desktop through SQLite, MCP, and lifecycle hooks. It uses only the Python standard library.

## 功能 Features

- 本地 SQLite 存储；默认不会上传数据，也不会启动或控制其他应用。
- 1000 条有效记忆容量；淘汰记录不占用有效容量。
- 每条记录包含标题、精确内容、分类、标签、来源、置信度和重要度。
- 初始重要度由 Codex 判断：1–2 不重要，3 普通，4–5 重要。
- 相关记忆每被实际检索使用 3 次提升一级，最高 5 级。
- 连续 3 天没有被检索时降低一级，之后每 3 天继续降低，最低 1 级。
- 新事实可以通过 `replace_ids` 覆盖旧事实；错误、重复或失效记录可以淘汰。
- 检索工具是只读的；只有会话结束的维护步骤才写入、替换、升权或淘汰记录。
- 提供桌面管理器，可搜索、筛选、编辑、合并、导入和导出 JSON。

## 项目结构 Project layout

```text
codex_memory_core.py       # SQLite schema, search, ranking, decay, commit/retire
codex_memory_mcp.py        # stdio JSON-RPC MCP server
codex_memory_hook.py       # SessionStart/UserPromptSubmit/Stop hooks
codex_memory_vault.pyw     # Tkinter desktop manager
启动 Codex 记忆库.bat       # Windows desktop launcher
config/                    # Codex configuration examples
scripts/                   # Windows installer and helper scripts
docs/                      # Design and policy notes
skills/codex-memory/       # Installable Codex Desktop skill
AGENTS.md                  # Memory curation policy for Codex
```

## 快速开始（Windows） Quick start (Windows)

### 1. 准备 Python

需要 Python 3.10 或更高版本。项目不需要安装第三方包。

Install Python 3.10 or newer. No third-party packages are required.

### 2. 克隆仓库并安装文件 Clone and install the files

```powershell
git clone https://github.com/OWNER/codex-memory-model.git
cd codex-memory-model
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1
```

安装脚本只把通用代码复制到 `%USERPROFILE%\.codex\codex_memory`，不会复制或上传数据库。它默认不修改 Codex 配置；如果希望它同时合并 MCP 和 Hooks 配置，显式使用：

The installer copies only the generic source files to `%USERPROFILE%\.codex\codex_memory` and never copies or uploads a database. It does not change Codex configuration by default. To let it merge the MCP and hook entries, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -ConfigureCodex
```

脚本会在修改配置前创建带时间戳的备份。已有但没有本项目标记的同名 MCP 配置会保留，脚本会提示你手动检查，避免覆盖其他设置。

The script creates timestamped backups before changing configuration. An existing unmarked MCP entry is preserved and reported for manual review so unrelated settings are not overwritten.

### 3. 重启 Codex Restart Codex

完全退出并重新打开 Codex Desktop，让 app-server 重新加载 MCP 和 lifecycle hooks。首次使用非托管 Hooks 时，在 Codex 的 `/hooks` 页面审阅并信任这些命令。

Fully quit and reopen Codex Desktop so its app-server reloads MCP and lifecycle hooks. When Codex asks you to review non-managed hooks, inspect and trust these commands from the `/hooks` page.

### 4. 启动桌面记忆管理器 Launch the desktop manager

双击 `启动 Codex 记忆库.bat`，或运行：

Double-click `启动 Codex 记忆库.bat`, or run:

```powershell
pythonw .\codex_memory_vault.pyw
```

默认数据库位置：`%LOCALAPPDATA%\CodexMemoryVault\memory.db`。如果没有 `LOCALAPPDATA`，会回退到 `~/.codex_memory_vault/memory.db`。

The default database path is `%LOCALAPPDATA%\CodexMemoryVault\memory.db`. When `LOCALAPPDATA` is unavailable, the fallback is `~/.codex_memory_vault/memory.db`.

## 手动配置 Codex Manual Codex configuration

如果不使用安装脚本，请参考 `config/hooks.json.example` 和 `config/config.toml.example`。把示例中的 `<PYTHON>` 和 `<CODEX_MEMORY_DIR>` 替换成实际路径，然后把 Hooks 合并到 `%USERPROFILE%\.codex\hooks.json`，把 MCP 段落合并到 `%USERPROFILE%\.codex\config.toml`。

If you do not use the installer, see `config/hooks.json.example` and `config/config.toml.example`. Replace `<PYTHON>` and `<CODEX_MEMORY_DIR>` with real paths, merge the hooks into `%USERPROFILE%\.codex\hooks.json`, and merge the MCP section into `%USERPROFILE%\.codex\config.toml`.

The MCP command must start `codex_memory_mcp.py` with the same Python interpreter that can import the copied files. Hook commands must point to `codex_memory_hook.py` in the same directory.

## Codex Skill

`skills/codex-memory/` is an installable Codex skill. The Windows installer
copies it to `%USERPROFILE%\\.codex\\skills\\codex-memory`; you can also copy that
directory manually. Restart Codex Desktop after installation. You can invoke it explicitly
with `$codex-memory`, or let Codex select it automatically for memory-related
tasks. The skill uses the local `codex-memory` MCP tools for both read-only
retrieval and end-of-turn curation.

`skills/codex-memory/` 是可安装到 Codex Desktop 的 Skill。把该目录复制到
`%USERPROFILE%\\.codex\\skills\\codex-memory` 后重新启动 Codex；也可以显式使用
`$codex-memory`，让 Codex 读取、标记实际使用、写入、替换或淘汰记忆。Skill
通过本机 `codex-memory` MCP 工具执行读写。

以后向 GitHub 上传或更新本项目时，必须从专用分支提交并创建 Pull Request，
不要直接推送到默认分支。

Future GitHub uploads or updates to this project must be committed on a dedicated
branch and submitted through a Pull Request. Do not push directly to the default branch.

## MCP 工具 MCP tools

| 工具 | 作用 | 写入数据库 |
| --- | --- | --- |
| `codex_memory_search` | 按当前任务检索有效记忆 | 否 |
| `codex_memory_stats` | 查看数量、重要度分布和容量 | 否 |
| `codex_memory_mark_used` | 记录本轮实际依赖的记忆并按规则升权 | 是 |
| `codex_memory_commit` | 新增或替换一条整合后的原子记忆 | 是 |
| `codex_memory_retire` | 淘汰错误、重复或失效记忆 | 是 |

The write tools are intended for the end-of-turn curation step. A normal search is read-only and does not change usage counts or importance.

## 记忆整理规则 Memory policy

可以保存：

- 已确认的个人事实，例如长期教育、工作、项目或技能信息；
- 长期稳定的电脑、编程或 Codex 使用偏好；
- 未来对多个会话有帮助的项目背景、技术环境、约束和决定；
- 已经验证过的正确解决方法和操作规范，例如 LaTeX 编译与 PDF 转换、Chrome 控制与读取、Gradescope 批改作业流程；
- 以后可能反复使用的通用知识。

不要保存：

- 密码、API token、密钥、联系方式或其他敏感凭据；
- 只对本轮有用的临时任务过程、一次性输出、完整聊天记录或完整文档；
- 助手临时方案、本记忆系统实现细节、未经验证的步骤或猜测和低价值闲聊。

Store confirmed, reusable information: personal facts, durable computer/programming/Codex preferences, recurring project or technical context, stable decisions, general knowledge, and solution procedures that have actually been verified. For example, reusable LaTeX/PDF, browser-control, or grading workflows may be remembered. Do not store passwords, API tokens, keys, contact details, complete conversations/documents, one-off task steps, assistant drafts, the memory system's own implementation details, unverified procedures or guesses, or low-value chatter.

When a new fact conflicts with an existing fact, search first and call `codex_memory_commit` with `replace_ids`. Retire records that are wrong, duplicated, or no longer useful.

## 隐私与数据 Privacy and data

记忆库默认只读写本机 SQLite 文件，不包含任何遥测或自动上传逻辑。仓库的 `.gitignore` 会排除数据库、日志、缓存和导出的记忆文件。请不要把自己的 `memory.db`、导出 JSON、Codex 认证文件或本机配置提交到 Git。

The store reads and writes a local SQLite file and contains no telemetry or automatic upload logic. `.gitignore` excludes databases, logs, caches, and memory exports. Never commit your own `memory.db`, exported JSON, Codex authentication files, or machine-specific configuration.

## 许可证 License

MIT License. See `LICENSE`.
