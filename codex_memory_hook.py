"""Codex lifecycle hooks for automatic memory retrieval and review prompts."""

from __future__ import annotations

import json
import sys
from typing import Any

from codex_memory_core import connect, format_context, search, stats


def read_event() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def emit_context(text: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


def session_start(event: dict[str, Any]) -> None:
    connection = connect(read_only=True)
    try:
        rows = search(connection, "", limit=5, min_importance=4, track_usage=False, mutate=False)
        current = stats(connection, mutate=False)
        context = (
            "Codex 本地长期记忆层已连接。每次处理用户请求前，优先使用与当前任务相关的记忆；"
            "若当前请求明确改变了旧信息，以当前请求为准。每轮结束时只保存与用户本人有关、"
            "或体现长期电脑/Codex 使用偏好的已确认信息，"
            "由 Codex 判断初始重要度（1–2 不重要，3 普通，4–5 重要）；重复使用会升权，连续 3 天不用会降权。"
            "本次检索是只读的，不会启动或控制其它应用。"
            "并用 codex_memory_commit 的 replace_ids 或 codex_memory_retire 清理错误、重复和失效记录。\n\n"
            + format_context(rows, heading="高重要度长期记忆")
            + f"\n\n容量：{current['active']} / {current['capacity']} 条有效记忆。"
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context,
                    }
                },
                ensure_ascii=False,
            )
        )
    finally:
        if connection is not None:
            connection.close()


def prompt(event: dict[str, Any]) -> None:
    user_prompt = str(event.get("prompt", "")).strip()
    connection = connect(read_only=True)
    try:
        rows = search(connection, user_prompt, limit=8, track_usage=False, mutate=False)
        context = format_context(rows)
        context += (
            "\n\n记忆维护规则：只保留与用户本人有关、或体现长期电脑/Codex 使用偏好的已确认信息；"
            "内容长度不设固定上限，优先保证精确、完整并写清适用条件。"
            "不要因为本轮有消息就创建记忆，也不要保存普通任务过程、一次性输出、助手方案、记忆库技术规则、实现细节或无关闲聊。"
            "由你判断初始重要度（1–2 不重要，3 普通，4–5 重要）；"
            "遇到新结论覆盖旧结论时，"
            "先搜索旧记忆，再用 codex_memory_commit 的 replace_ids 更新；错误、重复或过时记录用"
            "codex_memory_retire 淘汰。不要保存密码、令牌、临时状态或未经确认的猜测。"
        )
        emit_context(context)
    finally:
        if connection is not None:
            connection.close()


def stop(event: dict[str, Any]) -> None:
    # The first Stop hook asks Codex for one internal curation pass. The second
    # Stop is marked active by Codex and is allowed to finish without recursion.
    if bool(event.get("stop_hook_active")):
        return
    assistant = str(event.get("last_assistant_message") or "").strip()
    if not assistant:
        return
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    "请完成本轮 Codex 记忆维护后再结束，并实际调用记忆工具。"
                    "先回顾本轮涉及的用户本人信息和长期电脑/Codex 使用偏好，"
                    "把符合范围的内容整理成未来可复用的精确摘要；不要逐字复制用户或助手的原话，不要保存整段对话。"
                    "内容长度不设固定上限，按需要写清事实、适用条件和可执行约束，并合并同一主题的重复信息。"
                    "先调用 codex_memory_search 查找相关旧记录；新事实覆盖旧事实时用 codex_memory_commit 的 replace_ids 更新，"
                    "错误、重复或过时记录用 codex_memory_retire 淘汰。不要保存普通任务过程、一次性输出、助手方案、"
                    "记忆库技术规则、实现细节、密码、令牌、临时状态、猜测或低价值闲聊；没有符合范围的信息就不要写入。"
                    "如果本轮实际依赖了已有记忆，请调用 codex_memory_mark_used 记录对应记忆 ID；记忆检索本身是只读的。"
                    "只有实际完成工具调用后才算维护完成，最后用一句话说明新增、替换、淘汰或无变化的结果。"
                ),
            },
            ensure_ascii=False,
        )
    )


def session_end(event: dict[str, Any]) -> None:
    # Retrieval hooks are intentionally side-effect free. Post-turn memory
    # maintenance happens only through the explicit MCP write tools.
    return


def main() -> None:
    event = read_event()
    action = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    if action == "session-start":
        session_start(event)
    elif action == "prompt":
        prompt(event)
    elif action == "stop":
        stop(event)
    elif action == "session-end":
        session_end(event)


if __name__ == "__main__":
    main()
