"""Minimal stdio MCP server exposing the local Codex memory store.

It intentionally avoids third-party dependencies. Codex starts this process
from the user MCP configuration and communicates with JSON-RPC lines on stdin
and stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from codex_memory_core import connect, format_context, mark_used, retire, search, stats, commit_memory


SERVER_NAME = "codex-memory"
SERVER_VERSION = "1.0.0"


TOOLS = [
    {
        "name": "codex_memory_search",
        "description": (
            "Read-only search of the user's local Codex long-term memory. Use this before doing work when the current prompt may relate to stored project conventions, decisions, preferences, or facts. Searching does not create, edit, promote, or decay records."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Current task or keywords to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                "category": {"type": "string", "description": "Optional category filter."},
                "min_importance": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "codex_memory_commit",
        "description": (
            "Store one atomic information point after a Codex turn. It may include any user-requested fact, preference, project context, technical convention, solution procedure, general knowledge, or sensitive information such as contact details, passwords, tokens, or credentials. Broad retention is explicitly authorized by the user, so do not reject a requested fact merely because it is sensitive. Preserve precise facts, conditions, and useful detail without copying complete conversations or documents verbatim. Split independent facts into separate records and label unverified content as tentative. The Codex curator should judge initial importance: 1-2 is unimportant, 3 is normal, and 4-5 is important. If importance is omitted while refining an existing memory, its current level is preserved; if omitted for a new memory, a conservative fallback is used. Repeated deliberate use promotes a memory every three uses, up to 5. After 3 days without retrieval, importance decays by one level per 3-day period. Replace outdated or wrong memories with replace_ids, and retire redundant or stale memories with obsolete_ids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string", "enum": ["通用", "项目", "技术", "决策", "流程", "偏好", "人物", "其他"]},
                "importance": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Initial importance chosen by the Codex curator: 1-2 unimportant, 3 normal, 4-5 important. Omit when refining an existing memory to preserve its current level."},
                "tags": {"type": "string"},
                "source": {"type": "string"},
                "memory_key": {"type": "string", "description": "Stable topic key; use the same key when refining the same fact."},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                "replace_ids": {"type": "array", "items": {"type": "integer"}},
                "obsolete_ids": {"type": "array", "items": {"type": "integer"}},
                "source_session": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "codex_memory_retire",
        "description": "Mark local memories as obsolete because they are wrong, redundant, or no longer useful. Obsolete memories are excluded from future retrieval and do not count toward the 1000 active-memory capacity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_ids": {"type": "array", "items": {"type": "integer"}},
                "reason": {"type": "string"},
                "source_session": {"type": "string"},
            },
            "required": ["memory_ids"],
        },
    },
    {
        "name": "codex_memory_mark_used",
        "description": "Record that the current Codex turn deliberately relied on existing memory IDs. This is a post-turn maintenance action; memory retrieval itself is read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_ids": {"type": "array", "items": {"type": "integer"}},
                "source_session": {"type": "string"},
            },
            "required": ["memory_ids"],
        },
    },
    {
        "name": "codex_memory_stats",
        "description": "Return active, obsolete, important, normal, unimportant, and remaining capacity counts for the local Codex memory store.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def json_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_result(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tool_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": value if isinstance(value, dict) else {"value": value},
        "isError": is_error,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    read_only = name in {"codex_memory_search", "codex_memory_stats"}
    connection = connect(read_only=read_only)
    try:
        if name == "codex_memory_search":
            rows = search(
                connection,
                str(arguments.get("query", "")),
                int(arguments.get("limit", 8)),
                str(arguments.get("category", "")),
                int(arguments.get("min_importance", 0) or 0),
                track_usage=False,
                mutate=False,
            )
            return tool_result(
                {
                    "count": len(rows),
                    "context": format_context(rows),
                    "memories": [dict(row) for row in rows],
                }
            )
        if name == "codex_memory_commit":
            result = commit_memory(
                connection,
                title=str(arguments.get("title", "")),
                content=str(arguments.get("content", "")),
                category=str(arguments.get("category", "通用")),
                importance=(
                    int(arguments["importance"])
                    if arguments.get("importance") is not None
                    else None
                ),
                tags=str(arguments.get("tags", "")),
                source=str(arguments.get("source", "")),
                memory_key=str(arguments.get("memory_key", "")),
                confidence=float(arguments.get("confidence", 0.8)),
                replace_ids=arguments.get("replace_ids", []) or [],
                obsolete_ids=arguments.get("obsolete_ids", []) or [],
                source_session=str(arguments.get("source_session", "")),
            )
            return tool_result({"ok": True, **result, "stats": stats(connection)})
        if name == "codex_memory_retire":
            count = retire(
                connection,
                arguments.get("memory_ids", []) or [],
                str(arguments.get("reason", "")),
                str(arguments.get("source_session", "")),
            )
            return tool_result({"ok": True, "retired": count, "stats": stats(connection)})
        if name == "codex_memory_mark_used":
            count = mark_used(
                connection,
                arguments.get("memory_ids", []) or [],
                str(arguments.get("source_session", "")),
            )
            return tool_result({"ok": True, "updated": count, "stats": stats(connection)})
        if name == "codex_memory_stats":
            return tool_result(stats(connection, mutate=False))
        return tool_result({"error": f"unknown tool: {name}"}, True)
    except Exception as exc:  # MCP tools should return an error object, not kill the server.
        return tool_result({"ok": False, "error": str(exc)}, True)
    finally:
        if connection is not None:
            connection.close()


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        params = request.get("params") or {}
        version = params.get("protocolVersion", "2025-06-18")
        return json_result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Use codex_memory_search before work when relevant; it is read-only and must not touch other applications. At the end of a turn, split confirmed, reusable information into one atomic point per codex_memory_commit call, including verified solution procedures and operational playbooks when they can help future turns. Judge initial importance, and use codex_memory_mark_used, codex_memory_commit, or codex_memory_retire to update this local store. Repeated deliberate use promotes useful memories; long-unused memories decay."
                ),
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return json_result(request_id, {})
    if method == "tools/list":
        return json_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        return json_result(request_id, call_tool(str(params.get("name", "")), params.get("arguments") or {}))
    if request_id is not None:
        return error_result(request_id, -32601, f"Method not found: {method}")
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps(error_result(None, -32700, str(exc)), ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
