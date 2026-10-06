# Codex Memory Model

本项目是一个只依赖 Python 标准库的本地 Codex 长期记忆层。它把消息中经过确认、整合并且对未来任务有一定帮助的信息保存为原子记忆；这些信息不局限于个人信息或偏好，也可以是一般事实、项目背景、技术环境、已验证的解决方法和操作规范。系统通过 SQLite、MCP 和 Codex lifecycle hooks 连接到 Codex Desktop。记忆库只保存在本机，不会自动上传数据库，也不会启动或控制其他应用。

This project is a lightweight local long-term memory layer for Codex. It stores confirmed information that may help a future task as atomic memories; the scope is broader than personal facts and preferences and can include general facts, project background, technical context, verified solution procedures, and operational playbooks. It connects to Codex Desktop through SQLite, MCP, and Codex lifecycle hooks. The database stays local: the project has no telemetry, automatic upload, or control of other apps.

本项目不单独下载或运行语言模型。信息提取、重要度判断和会话结束维护由当前 Codex 会话调用记忆工具完成；桌面版使用不要求安装 Codex CLI。

The project does not download or run a separate language model. The active Codex session performs extraction, importance judgment, and end-of-turn curation through the memory tools. Codex Desktop can use it without the Codex CLI.

## 先看这里：最快的使用方式 / Fastest path

| 需求 Need | 操作 Action |
| --- | --- |
| 普通安装并自动接入 Codex | 运行安装脚本并加 **-ConfigureCodex** |
| 只安装文件，稍后手动配置 | 运行安装脚本但不加 **-ConfigureCodex** |
| 修改源文件安装位置 | 使用 **-InstallDirectory "D:\Tools\codex_memory"** |
| 打开本地记忆管理器 | 双击 **启动 Codex 记忆库.bat** |
| 备份记忆 | 在管理器中点击“导出 JSON” |
| 以后更新 GitHub | 从专用分支提交并通过 Pull Request，不能直接推送默认分支 |

| Need | Action |
| --- | --- |
| Normal installation with automatic Codex integration | Run the installer with **-ConfigureCodex** |
| Install files and configure Codex later | Run the installer without **-ConfigureCodex** |
| Choose another source directory | Use **-InstallDirectory "D:\Tools\codex_memory"** |
| Open the local memory manager | Double-click **启动 Codex 记忆库.bat** |
| Back up memories | Click “导出 JSON” in the manager |
| Update GitHub in the future | Use a dedicated branch and Pull Request; never push directly to the default branch |

## 功能概览 / Features

- **自动读取 / Automatic retrieval**：SessionStart 会读取高重要度记忆；UserPromptSubmit 会按当前任务检索相关记忆。两种检索都是只读的。
- **会话结束维护 / End-of-turn curation**：Stop hook 会提醒 Codex 只保存精确、对未来任务有一定帮助且带有必要使用语境的信息，不会因为每条消息都自动创建一条记录。
- **双向 Skill / Bidirectional skill**：codex-memory Skill 同时支持在工作前读取相关记忆，以及在工作结束后按规则标记使用、写入、替换和淘汰记忆；它不是只负责写入的工具。
- **原子记忆 / Atomic records**：一条记录表达一个信息点；新事实可以用 replace_ids 覆盖旧事实，错误、重复或失效记录可以淘汰。
- **重要度生命周期 / Importance lifecycle**：初始重要度由 Codex 在 1–100 中判断；每次实际使用至少增加 20 点并乘以 1.5，连续 6 小时没有检索时乘以 0.9。
- **记忆关系 / Memory relations**：记忆之间保存 1–100 的相关度；共同使用会提高相关度，检索先取少量全文索引种子，再沿高相关度边扩展，减少无关搜索。
- **本地管理 / Local manager**：Tkinter 管理器支持搜索、分类、重要度筛选、编辑、合并、删除、JSON 导入和 JSON 导出。
- **轻量部署 / Lightweight deployment**：只使用 Python 标准库，不需要 pip install，MCP 通过标准输入输出运行，不监听网络端口。

The codex-memory skill supports both read and write workflows: it retrieves
relevant memories before work and can mark, create, replace, or retire memories
during end-of-turn curation. It is not a write-only tool.

## 系统要求 / Requirements

### Windows / Windows

- Windows 10/11 或兼容的 Windows 环境。
- Python 3.10 或更高版本；项目不需要第三方 Python 包。
- 已安装并能运行 Codex Desktop。
- 如果使用自动配置，需要 Codex Desktop 支持 MCP 和 lifecycle hooks。
- Git 只在从 GitHub 克隆或推送更新时需要；下载 ZIP 后可以不安装 Git。

### Windows (English)

- Windows 10/11 or a compatible Windows environment.
- Python 3.10 or newer; no third-party Python packages are required.
- A working Codex Desktop installation.
- MCP and lifecycle hook support in Codex Desktop for automatic configuration.
- Git is needed only to clone or publish updates; it is optional when using a ZIP download.

检查 Python：

~~~powershell
python --version
py -3 --version
~~~

The installer first looks for python.exe. If it is unavailable, it uses py.exe -3. The installer does not replace or install Python for you.

## 5 分钟安装（推荐）/ Five-minute installation (recommended)

### 1. 获取仓库 / Get the repository

~~~powershell
git clone https://github.com/jokercarter/codex-memory-model.git
Set-Location .\codex-memory-model
~~~

也可以从 GitHub 下载 ZIP，解压后在解压目录运行下面的命令。

You can also download a ZIP archive from GitHub and run the commands from the extracted directory.

### 2. 安装并自动配置 / Install and configure

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -ConfigureCodex
~~~

脚本会：

1. 把运行文件复制到 %USERPROFILE%\.codex\codex_memory；
2. 把可调用的 Skill 复制到 %USERPROFILE%\.codex\skills\codex-memory；
3. 合并或创建 %USERPROFILE%\.codex\hooks.json；
4. 在 %USERPROFILE%\.codex\config.toml 中添加带标记的 codex_memory MCP 配置；
5. 修改已有配置前创建带时间戳的 .bak-codex-memory-... 备份；
6. 保留数据库原位，不复制、不上传、不覆盖用户已有记忆。

The installer copies runtime files to %USERPROFILE%\.codex\codex_memory, installs the Codex skill, merges hooks, adds a marked MCP block, creates timestamped backups before configuration changes, and leaves the local database untouched.

### 3. 完全重启 Codex / Fully restart Codex

完全退出 Codex Desktop 后重新打开，让 app-server 重新加载 MCP 和 hooks。第一次使用非托管 Hook 时，在 Codex 的 /hooks 页面检查并信任显示的命令。

Fully quit and reopen Codex Desktop so its app-server reloads MCP and hooks. When Codex asks you to review non-managed hooks, inspect and trust the commands shown on the /hooks page.

### 4. 打开管理器 / Open the manager

在仓库目录双击：

~~~text
启动 Codex 记忆库.bat
~~~

或者运行：

~~~powershell
pythonw .\codex_memory_vault.pyw
~~~

管理器会自动创建数据库目录和 SQLite 文件。默认位置为：

~~~text
%LOCALAPPDATA%\CodexMemoryVault\memory.db
~~~

如果 LOCALAPPDATA 不存在，代码回退到：

~~~text
%USERPROFILE%\.codex_memory_vault\memory.db
~~~

The manager creates the database directory and SQLite file on first launch. The default location is %LOCALAPPDATA%\CodexMemoryVault\memory.db; if LOCALAPPDATA is unavailable, it falls back to %USERPROFILE%\.codex_memory_vault\memory.db.

### 快速验证 / Quick verification

安装后可以先确认文件和配置是否存在：

~~~powershell
$runtime = Join-Path $env:USERPROFILE ".codex\codex_memory"
$skill = Join-Path $env:USERPROFILE ".codex\skills\codex-memory"
Test-Path (Join-Path $runtime "codex_memory_mcp.py")
Test-Path (Join-Path $runtime "codex_memory_hook.py")
Test-Path (Join-Path $skill "SKILL.md")
Select-String -Path (Join-Path $env:USERPROFILE ".codex\config.toml") -Pattern "codex_memory"
Select-String -Path (Join-Path $env:USERPROFILE ".codex\hooks.json") -Pattern "codex_memory_hook.py"
~~~

每个 Test-Path 应返回 True；Select-String 应显示 MCP 和 Hook 配置行。

Each Test-Path should return True, and Select-String should show the MCP and
hook configuration lines.

## 安装脚本参数 / Installer parameters

脚本文件：scripts\install_windows.ps1。

The installer is scripts\install_windows.ps1.

| 参数 Parameter | 默认值 Default | 作用 |
| --- | --- | --- |
| -ConfigureCodex | 关闭 off | 同时写入 MCP 和 hooks 配置；不加时只复制文件 |
| -InstallDirectory <path> | %USERPROFILE%\.codex\codex_memory | 修改运行文件的安装目录；路径会被解析为绝对路径 |

| Parameter | Default | Effect |
| --- | --- | --- |
| -ConfigureCodex | Off | Also writes MCP and hook configuration; without it, only files are copied |
| -InstallDirectory <path> | %USERPROFILE%\.codex\codex_memory | Changes the runtime source directory and is resolved to an absolute path |

常用命令：

~~~powershell
# 只复制运行文件和 Skill，不改 Codex 配置
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1

# 自动配置 Codex
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -ConfigureCodex

# 把运行文件放到自定义目录，同时配置 Codex
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -ConfigureCodex -InstallDirectory "D:\Tools\codex_memory"
~~~

常见行为：

- Skill 始终安装到 %USERPROFILE%\.codex\skills\codex-memory；-InstallDirectory 只改变四个 Python 运行文件的位置。
- 已有但没有本项目标记的 mcp_servers.codex_memory 段落会保留，安装器会提示你手动检查，避免覆盖未知配置。
- 已有由本项目生成的 hooks 会被替换，其他应用的 hooks 会保留。
- uninstall_windows.ps1 只删除安装的源文件和 Skill，不自动删除数据库或 Codex 配置，避免误删用户数据。

The skill is always installed under %USERPROFILE%\.codex\skills\codex-memory; -InstallDirectory changes only the four runtime Python files. An unmarked existing MCP block is preserved. Project-managed hooks are replaced while unrelated hooks are retained. Uninstallation leaves the database and Codex configuration unchanged.

## 不使用安装脚本：手动配置 / Manual configuration

手动配置适合需要自定义路径、已有复杂 config.toml，或希望逐项审阅配置的使用者。先把四个 Python 文件放到同一个目录，例如：

Manual configuration is useful when you need custom paths or want to review each configuration change. Put the four Python files in one directory, for example:

~~~text
D:\Tools\codex_memory\
    codex_memory_core.py
    codex_memory_mcp.py
    codex_memory_hook.py
    codex_memory_vault.pyw
~~~

如需手动安装 Skill，把 skills\codex-memory 整个目录复制到
%USERPROFILE%\.codex\skills\codex-memory，然后重启 Codex Desktop。

To install the skill manually, copy the complete skills\codex-memory directory
to %USERPROFILE%\.codex\skills\codex-memory and restart Codex Desktop.

然后把 config\config.toml.example 合并到 %USERPROFILE%\.codex\config.toml，把 <PYTHON> 和 <CODEX_MEMORY_DIR> 换成实际路径：

~~~toml
[mcp_servers.codex_memory]
enabled = true
command = 'C:\Path\to\python.exe'
args = ['D:\Tools\codex_memory\codex_memory_mcp.py']
startup_timeout_sec = 30
tool_timeout_sec = 60
~~~

如果使用 Python Launcher：

~~~toml
[mcp_servers.codex_memory]
enabled = true
command = 'C:\Windows\py.exe'
args = ['-3', 'D:\Tools\codex_memory\codex_memory_mcp.py']
startup_timeout_sec = 30
tool_timeout_sec = 60
~~~

command 必须是能导入同目录模块的 Python 解释器；args 中脚本路径必须指向同一份 codex_memory_mcp.py。MCP 是 stdio 服务，没有端口、API URL 或 API key；界面显示“不支持身份验证”对这个本地传输是正常的。

The command must be a Python interpreter that can import the files in the same directory. The script path in args must point to the same copy of codex_memory_mcp.py. This is a local stdio MCP server: it has no port, API URL, or API key. “Authentication not supported” is expected for this transport.

### Hooks 配置 / Hook configuration

把 config\hooks.json.example 合并到 %USERPROFILE%\.codex\hooks.json。三个事件的用途如下：

Merge config\hooks.json.example into %USERPROFILE%\.codex\hooks.json. The three events are:

| 事件 Event | 默认行为 Default behavior | 是否写库 Writes |
| --- | --- | --- |
| SessionStart | 读取最多 5 条、重要度至少 67 的高重要度记忆 | 否 No |
| UserPromptSubmit | 根据当前提示词读取最多 8 条相关记忆 | 否 No |
| Stop | 要求 Codex 在结束前完成一次维护；实际写入由 MCP 工具完成 | Hook 本身否；维护按需写入 |

关键字段：

| 字段 Field | 默认值 Default | 修改作用 |
| --- | --- | --- |
| matcher | startup / resume / clear / compact | 限制 SessionStart 触发场景 |
| additionalContextLimit | 示例为 5000 | 限制注入上下文的字符预算；过小可能截断记忆 |
| Stop timeout | 30 秒 seconds | 允许 Stop hook 返回的最长时间 |
| statusMessage | 见示例 | 只改变界面状态提示 |

不要修改传给脚本的三个动作名：session-start、prompt 和 stop。如果手动添加多个同类 hook，请确认每个命令只运行一次，避免重复注入。

Do not change the three action arguments passed to the script: session-start, prompt, and stop. If you add more hooks manually, make sure each command runs only once so the same memory is not injected repeatedly.

## 日常使用 / Daily use

### 在 Codex 中使用 / In Codex

安装并重启后，不需要在每个聊天中输入特殊命令：

1. 新会话或恢复会话时，SessionStart 提供高重要度背景；
2. 每次提交用户消息时，UserPromptSubmit 按当前任务检索；
3. 每轮结束时，Stop hook 提醒 Codex 只整理长期有价值的信息；
4. 只有 Codex 实际调用写入工具时，数据库才会新增、替换或淘汰记录。

也可以在 Codex 中显式使用 Skill 名称 $codex-memory；自动 Hook 和显式 Skill
使用同一个本地 MCP 服务和同一个数据库。

After installation and restart, no special command is required in each chat:

1. SessionStart provides high-importance background;
2. UserPromptSubmit searches for task-relevant memories;
3. Stop requests one curation pass;
4. The database changes only when Codex calls a write tool.

You can also invoke the skill explicitly with $codex-memory. Explicit use and
automatic hooks share the same local MCP server and database.

检索本身是只读的，不会升权、降权、创建记录，也不会启动或控制电脑上的其他应用。实际依赖某条已有记忆后，维护阶段应调用 codex_memory_mark_used，这样使用次数和重要度才会更新。

Retrieval is read-only: it does not create records, change importance, or control other applications. After deliberately relying on an existing memory, the curation step should call codex_memory_mark_used so its use count and importance can be updated.

### 在桌面管理器中使用 / In the desktop manager

| 操作 Operation | 用法 How to use |
| --- | --- |
| 搜索 Search | 输入关键词，回车或点击“搜索”；会查标题、内容、标签和来源 |
| 分类筛选 Category | 选择“通用、项目、技术、决策、流程、偏好、人物、其他” |
| 重要度筛选 Importance | 选择“重要、普通、不重要”或 1–100 的精确级别 |
| 新建 New | 点击“新建”，填写标题和整合后的内容，再点“保存记忆” |
| 编辑 Edit | 单击一条记录，修改字段后保存 |
| 合并 Merge | 多选记录后点“合并选中”；会创建一条新记录，原记录保留 |
| 删除 Delete | 多选后点“删除选中”；这是永久删除，不能撤销 |
| 导出 Export | “文件 → 导出 JSON”，用于备份或迁移 |
| 导入 Import | “文件 → 导入 JSON”；重复记录和超过容量的记录会跳过 |
| 快捷键 Shortcuts | Ctrl+N 新建，Ctrl+S 保存，Ctrl+F 聚焦搜索框 |

每条记忆建议只写一个信息点。内容可以较长，但应让记录脱离原对话也能理解：写清事实、适用场景、前提或触发条件、版本或范围和可执行约束；不要把整段聊天复制进去。标签和来源可以补充语境，但不能代替正文中的关键上下文。

Keep one information point per memory. Content may be detailed, but it should stand on its own by stating the fact, applicable scenario, prerequisites or trigger, version or scope, and actionable constraints without copying a full conversation. Tags and source may supplement context but should not replace essential context in the content.

建议模板 / Suggested template：事实 Fact；适用场景 Applicable scenario；前提或触发条件 Prerequisites or trigger；版本或范围 Version or scope；步骤与限制 Steps and constraints。

## 记忆规则 / Memory rules

- 有效容量为 1000 条；标记为 obsolete 的记录不占用有效容量。
- 记忆不局限于个人信息或偏好；任何已确认、对未来任务有一定帮助的一般事实、项目背景、技术信息、操作经验或通用知识都可以保存。
- 新记录应带有足够上下文：至少说明它在什么场景、前提或触发条件、版本或范围下成立；只有场景显然的简单事实才可以省略重复说明。
- 初始重要度由 Codex 判断：1–33 不重要，34–66 普通，67–100 重要。
- 每次实际使用至少增加 20 点并乘以 1.5，最高 100。
- 连续 6 小时没有检索时乘以 0.9，之后每 6 小时继续降低，最低 1 点。
- 记忆之间的相关度为 1–100；相同对话中共同被实际使用的记忆会提高相关度。检索先用少量种子，再沿高相关度关系扩展。
- 从旧版本升级时，旧的 1–5 重要度会自动映射为 1、26、51、76、100；已有记忆关系会从主题和标签自动建立。
- 新事实覆盖旧事实时，先检索旧记录，再用 replace_ids 更新。
- 错误、重复或过时记录用 codex_memory_retire 淘汰。
- 用户明确要求保存时，电话号码、密码、令牌、私钥、敏感凭据等也可以保存；仍按原子信息整理，未经验证内容标注为待确认，不逐字复制完整聊天或文档。

The active capacity is 1000 records; obsolete records do not consume it. Memories are not limited to personal facts or preferences: any confirmed general fact, project background, technical detail, operating experience, or general knowledge that may help a future task can be stored. New records should carry enough context to stand alone by stating the applicable scenario, prerequisites or trigger, version or scope, and important conditions; only simple facts with an obvious context may omit repeated wording. Codex chooses initial importance from 1–100: 1–33 unimportant, 34–66 normal, and 67–100 important. Each deliberate use raises importance to at least current+20 and roughly current*1.5, capped at 100. Each 6-hour period without retrieval multiplies it by 0.9, down to 1. Memories also maintain learned relation strengths from 1–100; memories used together become more strongly related. Search starts with a small full-text seed set and expands through strong relation edges. Changed facts should replace old records with replace_ids; wrong, duplicate, or stale records should be retired. User-requested memories may include phone numbers, passwords, tokens, private keys, and other sensitive data. Keep them atomic and summarized, label unverified content as tentative, and do not copy complete conversations or documents verbatim.

When upgrading from the previous 1–5 version, existing importance values are mapped to 1, 26, 51, 76, and 100. Existing memories receive initial relation edges from shared topics and tags.

## MCP 工具和参数 / MCP tools and parameters

MCP server name: codex-memory.

### codex_memory_search（只读 / read-only）

| 参数 Parameter | 必须 Required | 默认 Default | 说明 |
| --- | --- | --- | --- |
| query | 是 Yes | — | 当前任务或关键词 |
| limit | 否 No | 8 | 返回 1–20 条；越大注入上下文越多 |
| category | 否 No | 空 empty | 精确分类筛选 |
| min_importance | 否 No | 0 | 最低重要度 1–100 |

示例：

~~~json
{
  "query": "LaTeX 编译 PDF",
  "limit": 8,
  "category": "流程",
  "min_importance": 67
}
~~~

Searching does not change any record or usage count.

### codex_memory_commit（新增或替换 / create or replace）

| 参数 Parameter | 必须 Required | 默认 Default | 说明 |
| --- | --- | --- | --- |
| title | 是 Yes | — | 精确、短的标题 |
| content | 是 Yes | — | 一个可复用的信息点；正文应包含必要的适用场景、前提或范围 |
| category | 否 No | 通用 | 见上面的八个分类 |
| importance | 否 No | 由模型判断 | 1–100；更新旧记录时省略可保留原值 |
| tags | 否 No | 空 empty | 逗号分隔标签 |
| source | 否 No | 空 empty | 来源或验证依据 |
| memory_key | 否 No | 从标题生成 | 同一主题更新时保持不变 |
| confidence | 否 No | 0.8 | 0–1 的置信度 |
| replace_ids | 否 No | [] | 被新事实替换的旧记录编号 |
| obsolete_ids | 否 No | [] | 同时淘汰的重复或失效记录 |
| source_session | 否 No | 空 empty | 可选的会话标识 |

示例：

~~~json
{
  "title": "GitHub 更新必须通过 Pull Request",
  "content": "以后更新仓库时先从默认分支创建专用分支，在分支上提交并推送，最后创建 Pull Request。",
  "category": "流程",
  "importance": 85,
  "tags": "GitHub,Pull Request",
  "memory_key": "github-updates-use-pull-requests",
  "confidence": 1.0
}
~~~

### codex_memory_mark_used（记录实际使用 / deliberate use）

必须传 memory_ids 数组。它只应包含本轮确实依赖的记录，不要把搜索结果全部标记为已使用。

Pass a memory_ids array containing only the records that the turn actually relied on. Do not mark every search result as used.

### codex_memory_related（只读 / read-only）

传入一个 memory_id，返回与它相关的记忆以及 relation_strength（1–100）。
检索会先找到少量文本匹配的种子记忆，再沿高相关度边扩展；共同调用
codex_memory_mark_used 的记忆会提高它们之间的相关度。

Pass a memory_id to return related memories and their relation_strength (1–100).
Search starts with a small lexical seed set and follows strong relation edges.
Memories passed together to codex_memory_mark_used become more strongly related.

### codex_memory_retire（淘汰 / retire）

必须传 memory_ids 数组；可选 reason 和 source_session。淘汰后不再参与检索，也不占有效容量。

Pass memory_ids; reason and source_session are optional. Retired records are excluded from retrieval and active capacity.

### codex_memory_stats（统计 / statistics）

不需要参数，返回有效数、淘汰数、重要/普通/不重要分布、容量和剩余容量。

No arguments are required. It returns active, obsolete, importance distribution, capacity, and remaining capacity.

## 参数如何修改 / How to customize parameters

下面列出的是真正被运行时代码读取的位置。只修改 pyproject.toml 中的说明值不会改变已经安装的运行行为；修改源码后要重新运行安装脚本，把新文件复制到安装目录。

The locations below are the values read by the runtime. Changing only the metadata in pyproject.toml does not change an installed runtime. After editing source files, rerun the installer to copy them to the active install directory.

| 想修改的内容 Change | 文件和字段 File and field | 默认 Default | 注意 |
| --- | --- | --- | --- |
| 有效记忆容量 Active capacity | codex_memory_core.py 和 codex_memory_vault.pyw 的 MAX_MEMORIES | 1000 | 两处一起改；MCP 和管理器必须一致 |
| 遗忘周期 Decay interval | core 的 DECAY_INTERVAL_HOURS | 6 | 单位是小时；每个周期按 0.9 倍衰减 |
| 分类 Categories | core、vault 的 CATEGORIES；MCP 的 TOOLS 分类枚举 | 八类 | 三处一起改 |
| 会话启动检索 SessionStart | codex_memory_hook.py 的 limit=5、min_importance=67 | 5 条、重要度至少 67 | 增大可能占用更多上下文 |
| 用户消息检索 Prompt | codex_memory_hook.py 的 limit=8 | 8 条 | 增大可能影响回答上下文长度 |
| 注入上下文预算 Context budget | hooks.json 的 additionalContextLimit | 示例 5000 | 太小会截断，太大可能挤占任务上下文 |
| MCP 启动超时 Startup timeout | config.toml 的 startup_timeout_sec | 30 秒 | 只在启动很慢时增大 |
| MCP 工具超时 Tool timeout | config.toml 的 tool_timeout_sec | 60 秒 | 只在工具操作很慢时增大 |
| Stop hook 超时 Stop timeout | hooks.json 中 Stop hook 的 timeout | 30 秒 | 超时会导致维护提醒失败 |
| 源文件安装目录 Source path | 安装脚本 -InstallDirectory | %USERPROFILE%\.codex\codex_memory | 不需要改源码 |
| 数据库路径 Database path | core 的 database_path() 和 vault 的 data_directory() | %LOCALAPPDATA%\CodexMemoryVault | 当前版本没有独立 DB_PATH 参数；两处必须保持一致 |
| 重要度范围 Importance scale | core、vault 的 IMPORTANCE_MIN/MAX 和 IMPORTANT_MIN/NORMAL_MIN | 1–100；67 起为重要 | 改动时同步 MCP 参数说明 |
| 关系范围 Relation scale | core 的 RELATION_MIN/MAX | 1–100 | 关系边由新记忆主题匹配和共同使用自动维护 |
| 关系扩展预算 Relation budget | core 的 RELATION_SEED_LIMIT、RELATION_EXPANSION_LIMIT | 12 个种子、32 个邻居 | 增大可覆盖更多关系，亦会增加上下文开销 |

修改容量或遗忘周期的示例：

~~~text
1. 在 codex_memory_core.py 中改 MAX_MEMORIES 或 DECAY_INTERVAL_HOURS。
2. 如需修改桌面显示说明，同时更新 codex_memory_vault.pyw。
3. 如需新分类，同时更新 MCP 的分类枚举。
4. 重新运行 install_windows.ps1。
5. 完全重启 Codex，并重新打开桌面管理器。
~~~

Example workflow:

~~~text
1. Edit MAX_MEMORIES or DECAY_INTERVAL_HOURS in codex_memory_core.py.
2. Update the desktop explanation in codex_memory_vault.pyw if needed.
3. Update the MCP category enum if you add a category.
4. Rerun install_windows.ps1.
5. Fully restart Codex and reopen the manager.
~~~

如果经常需要切换数据库位置，建议先使用管理器导出 JSON，再修改两处路径，重新启动后导入 JSON；不要在 Codex 或管理器仍运行时移动正在使用的 SQLite 文件。

For frequent database moves, export JSON first, change both path functions, then restart and import the JSON. Do not move an SQLite file while Codex or the manager is using it.

## 备份、迁移和卸载 / Backup, migration, and uninstall

### 推荐的备份方式 / Recommended backup

1. 打开管理器；
2. 选择“文件 → 导出 JSON”；
3. 把导出的文件放在安全位置；
4. 迁移到另一台机器后，先安装本项目，再选择“文件 → 导入 JSON”。

导出的 JSON 包含有效记忆和它们之间的相关度边。导入支持三种格式：

- 直接的记忆数组；
- 只包含 memories 数组的 codex-memory-v1 对象；
- 包含 memories 和 relations 数组的 codex-memory-v2 对象。

Import skips duplicate title/content pairs and records beyond the 1000-record active limit. Relation edges are restored when both endpoint memories are imported. Never commit a personal export JSON or memory.db to GitHub.

### 卸载 / Uninstall

~~~powershell
# 使用默认安装目录
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows.ps1

# 使用自定义安装目录
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows.ps1 -InstallDirectory "D:\Tools\codex_memory"
~~~

卸载脚本会删除运行文件和 Skill，但会保留数据库和 Codex 配置。卸载后如果不再需要 hooks/MCP，请手动从 %USERPROFILE%\.codex\hooks.json 和 %USERPROFILE%\.codex\config.toml 删除本项目段落，并先保存备份。

The uninstall script removes runtime files and the skill but preserves the database and Codex configuration. If you no longer want integration, remove the project entries from hooks.json and config.toml manually after making a backup.

## 故障排查 / Troubleshooting

### python 找不到 / Python is not found

~~~powershell
python --version
py -3 --version
Get-Command python.exe -ErrorAction SilentlyContinue
Get-Command py.exe -ErrorAction SilentlyContinue
~~~

安装 Python 3.10+ 并确保 python.exe 或 py.exe 在 PATH 中，然后重新运行安装脚本。脚本不会自动下载 Python。

Install Python 3.10+ and make sure python.exe or py.exe is on PATH. The installer does not download Python.

### /hooks 没有命令或 Hook 退出码为 1 / Missing hooks or exit code 1

1. 确认安装目录中存在 codex_memory_hook.py；
2. 用 -ConfigureCodex 重新运行安装器；
3. 完全退出并重开 Codex；
4. 在 PowerShell 中直接测试 Hook 是否能启动：

~~~powershell
$python = (Get-Command python.exe).Source
$hook = Join-Path $env:USERPROFILE ".codex\codex_memory\codex_memory_hook.py"
'{"prompt":"test"}' | & $python $hook prompt
~~~

正常情况下会输出一行 JSON。若自定义了安装目录，把 $hook 改成实际路径；若只有 Python Launcher，把 $python 换成 py 并在命令中加入 -3。

The command should print one JSON line. With a custom install directory, update $hook; with only the Python Launcher, use py -3.

### MCP 显示未连接 / MCP is not connected

- 检查 %USERPROFILE%\.codex\config.toml 中的 [mcp_servers.codex_memory]；
- 确认 command 是实际可用的 Python 解释器；
- 确认 args 中的脚本路径存在；
- 确认解释器能从该目录导入 codex_memory_core.py；
- 删除重复或错误的旧配置后重新运行安装器；
- 完全重启 Codex。

Use the same Python interpreter for MCP and hooks. The local server is stdio, so it does not provide a web endpoint or authentication flow.

### 能读取但没有新增记忆 / Retrieval works but nothing is saved

这是设计行为：读取 Hook 是只读的，Stop hook 只要求 Codex 进行一次维护；只有 Codex 判断本轮存在已确认且对未来任务有一定帮助的信息并实际调用 codex_memory_commit，才会新增或更新记录。没有可复用信息时不写入是正常的。

This is intentional. Retrieval hooks are read-only, and Stop only requests a curation pass. A record is created or updated only when Codex decides that the turn contains confirmed information that may help a future task and calls codex_memory_commit.

### 记忆数量或重要度看起来不对 / Counts or importance look wrong

打开管理器查看顶部统计，或调用 codex_memory_stats。注意：

- obsolete 不计入有效容量；
- 搜索不会增加使用次数；
- 只有实际依赖后调用 codex_memory_mark_used 才会升权；
- 遗忘按 6 小时周期在下一次写入维护或管理器刷新时应用。

Obsolete records do not consume active capacity. Search does not count as use when it is read-only; deliberate mark_used calls do. Each deliberate use applies the minimum +20 and 1.5x increase. Decay is applied during the next write maintenance or manager refresh, using one 0.9x step per 6 hours without retrieval.

### 数据库被占用 / Database is locked

先关闭 Codex Desktop 和记忆管理器，再进行移动、备份或恢复。SQLite 可能同时存在 memory.db-wal 和 memory.db-shm 文件；不要只复制其中一个正在使用的文件，优先使用 JSON 导出。

Close Codex Desktop and the manager before moving or restoring the database. SQLite may have memory.db-wal and memory.db-shm sidecar files; JSON export is safer than copying a live database.

## 项目结构 / Project layout

~~~text
codex_memory_core.py       # SQLite schema, search, ranking, decay, commit/retire
codex_memory_mcp.py        # stdio JSON-RPC MCP server
codex_memory_hook.py       # SessionStart/UserPromptSubmit/Stop hooks
codex_memory_vault.pyw     # Tkinter desktop manager
启动 Codex 记忆库.bat       # Windows launcher
config/                    # Manual MCP and hook examples
scripts/                   # Windows install and uninstall scripts
docs/                      # Architecture and lifecycle notes
skills/codex-memory/       # Installable Codex skill
AGENTS.md                  # Repository memory curation policy
~~~

## 隐私、Git 和 Pull Request / Privacy, Git, and Pull Requests

记忆库默认只读写本机 SQLite，不包含遥测或自动上传逻辑。任何记忆信息都不得上传到 GitHub，包括记忆文本、关系边、数据库、导出 JSON、备份、日志、Hook 载荷和本机记忆上下文。gitignore 会排除常见数据库、备份、日志、缓存和记忆导出文件；提交前必须检查暂存区和 diff，只能提交不含记忆数据的模型代码、配置模板和说明。可以运行 powershell -ExecutionPolicy Bypass -File .\scripts\check_repository_data_free.ps1 -Staged 做文件级检查。

The store reads and writes a local SQLite file and has no telemetry or automatic upload. Never upload any memory information to GitHub, including memory text, relation edges, databases, JSON exports, backups, logs, hook payloads, or local memory context. gitignore excludes common database, backup, log, cache, and memory-export files. Before pushing, inspect staged files and the diff; run powershell -ExecutionPolicy Bypass -File .\scripts\check_repository_data_free.ps1 -Staged; only data-free model code, configuration templates, and documentation may be committed.

以后修改本项目时必须遵循：

1. 从默认分支创建专用分支；
2. 在专用分支提交并推送；
3. 创建 Pull Request，写清变更摘要和验证结果；
4. 通过 Pull Request 合并，不直接推送默认分支。

Future project changes must:

1. start from a dedicated branch;
2. be committed and pushed on that branch;
3. be submitted as a Pull Request with a summary and verification notes;
4. be merged through the Pull Request rather than pushed directly to the default branch.

## 许可证 / License

MIT License. See LICENSE.
