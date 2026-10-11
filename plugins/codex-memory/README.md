# Codex Memory plugin（本机版）

这个插件把本地 Codex 记忆模型接入 Codex Desktop：

- `UserPromptSubmit` 每次提交用户消息时只读检索相关记忆；
- `SessionStart`、恢复、清空或压缩会话时加载高重要度和“每次调用必读”记忆；
- `Stop` 在结束前要求完成一次记忆维护；实际写入由 MCP 工具完成；
- MCP 服务器通过标准输入输出运行，不监听端口，也不需要 API key；
- 数据库、关系、导出文件、日志和 Hook 上下文继续保留在本机 `%LOCALAPPDATA%\CodexMemoryVault`。

插件包本身只包含无数据的代码、Skill、配置模板和启动器，不包含任何本地记忆内容。

## 显式调用

在对话中可以使用 `$codex-memory`，例如：

- `使用 $codex-memory，先检索与当前错误和环境有关的记忆，再开始排查。`
- `使用 $codex-memory，读取与 LaTeX 编译相关的已验证流程。`
- `使用 $codex-memory，把下面这条已确认的信息按一个信息点写入本地记忆，并先检查是否和旧记录矛盾：……`

正常情况下不必每条消息手动输入前缀：插件启用后，生命周期 Hook 会在每个对话回合自动读取，停止回合时请求维护。

## 本地启动器

- `scripts\launch_codex_memory_mcp.cmd`：启动 MCP；
- `scripts\launch_codex_memory_hook.cmd <session-start|prompt|stop>`：运行生命周期 Hook；
- `scripts\open_memory_vault.cmd`：打开 Tkinter 记忆管理器。

启动器优先使用 `CODEX_MEMORY_PYTHON`，其次使用 Codex 随附的 Python，再回退到 PATH 中的 `python.exe` 或 `py.exe -3`。
