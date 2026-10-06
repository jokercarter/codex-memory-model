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
        rows = search(connection, "", limit=5, min_importance=67, track_usage=False, mutate=False)
        current = stats(connection, mutate=False)
        context = (
            "Codex 本地长期记忆层已连接。每次处理用户请求前，优先使用与当前任务相关的记忆；"
            "若当前请求明确改变了旧信息，以当前请求为准。每轮结束时保存已确认、对未来任务有一定帮助的信息，"
            "包括个人信息和偏好，也包括一般事实、项目背景、技术环境、经过验证的解决方法、操作规范、稳定决策和通用知识；"
            "新增记录要在内容中保留适用场景、前提或触发条件、版本或范围等必要上下文，"
            "由 Codex 判断初始重要度（1–33 不重要，34–66 普通，67–100 重要）；每次实际使用至少增加 20 点并乘以 1.5，连续 6 小时不用则乘以 0.9。"
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
            "\n\n记忆维护规则：保存已确认、对未来任务有一定帮助的信息，包括个人信息和偏好，也包括一般事实、项目背景、技术环境、经过验证的解决方法、操作规范、稳定决策和通用知识；"
            "内容长度不设固定上限，优先保证精确、完整，并写清适用场景、前提和适用条件。"
            "例如 LaTeX 编译与 PDF 转换、Chrome 控制与读取、Gradescope 批改作业等正确流程可以保存。"
            "用户已明确要求广泛保存记忆；不要因为电话号码、密码、令牌、敏感凭据或其他敏感内容而自动排除信息。"
            "仍按原子信息整理，不逐字复制完整聊天或文档；未经验证的内容标注为待确认。"
            "由你判断 1–100 的初始重要度；每次实际使用至少增加 20 点并乘以 1.5，最高 100；连续 6 小时不用则乘以 0.9，最低 1；"
            "遇到新结论覆盖旧结论时，"
            "先搜索旧记忆，再用 codex_memory_commit 的 replace_ids 更新；错误、重复或过时记录用"
            "codex_memory_retire 淘汰；用户要求保存的敏感信息也可以写入本地记忆。"
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
                    "先回顾本轮涉及的个人信息、偏好、一般事实、项目背景、技术环境、解决方法和操作规范，"
                    "把符合范围的内容整理成未来可复用的精确摘要；不要逐字复制用户或助手的原话，不要保存整段对话。"
                    "内容长度不设固定上限，按需要写清事实、适用场景、前提或触发条件、版本或范围和可执行约束，并合并同一主题的重复信息。"
                    "先调用 codex_memory_search 查找相关旧记录；新事实覆盖旧事实时用 codex_memory_commit 的 replace_ids 更新，"
                    "错误、重复或过时记录用 codex_memory_retire 淘汰。用户已要求广泛保存记忆，电话号码、密码、令牌、敏感凭据等也可按原子信息写入本地记忆；"
                    "未经验证的内容标注为待确认，不要逐字复制完整聊天或文档。"
                    "如果本轮实际依赖了已有记忆，请调用 codex_memory_mark_used 记录对应记忆 ID；共同使用的记忆会提高相关度（1–100），记忆检索本身是只读的。"
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
