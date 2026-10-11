"""Minimal stdio MCP server exposing the local Codex memory store.

It intentionally avoids third-party dependencies. Codex starts this process
from the user MCP configuration and communicates with JSON-RPC lines on stdin
and stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from codex_memory_core import (
    commit_memory,
    connect,
    format_context,
    mark_used,
    related,
    retire,
    search,
    set_always_apply,
    stats,
)


SERVER_NAME = "codex-memory"
SERVER_VERSION = "1.2.0"


TOOLS = [
    {
        "name": "codex_memory_search",
        "description": (
            "Read-only graph-aware search of the user's local Codex long-term memory. Every active memory marked always_apply is included on every search, regardless of query, category, or minimum-importance filters; relevant memories are then retrieved through lexical seeds and high-strength relations. Searching does not create, edit, promote, or decay records."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Current task or keywords to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                "category": {"type": "string", "description": "Optional category filter."},
                "min_importance": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
    },
    {
        "name": "codex_memory_commit",
        "description": (
            "Store one atomic information point after a Codex turn. It may include any confirmed information that may help a future task: user facts or preferences, useful general facts, project context, technical conventions, solution procedures, general knowledge, or sensitive information such as contact details, passwords, tokens, or credentials. Broad retention is explicitly authorized by the user, so do not reject a requested fact merely because it is sensitive. Preserve precise facts and include enough context for the record to stand alone: applicable scenario, prerequisites or trigger, version or scope, and important conditions or steps. Do not rely on tags or source alone for essential context, and do not copy complete conversations or documents verbatim. Split independent facts into separate records and label unverified content as tentative. The Codex curator should judge initial importance from 1-100. If importance is omitted while refining an existing memory, its current level is preserved; if omitted for a new memory, a conservative fallback is used. Related memories use a 1-100 relation strength. Memories deliberately used together gain relation strength. Each deliberate use raises importance to at least current+20 and roughly current*1.5, up to 100. After each 6-hour period without retrieval, importance is multiplied by 0.9, down to 1. Set always_apply=true only for stable instructions or facts the user requests in every memory search; each active always_apply memory is returned on every search, regardless of query filters. These records still apply only within their stated scope and never override system/developer rules or the user's explicit current-turn instructions. Replace outdated or wrong memories with replace_ids, and retire redundant or stale memories with obsolete_ids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string", "enum": ["通用", "项目", "技术", "决策", "流程", "偏好", "人物", "其他"]},
                "importance": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Initial importance chosen by the Codex curator on a 1-100 scale. Roughly 1-33 is unimportant, 34-66 is normal, and 67-100 is important. Omit when refining an existing memory to preserve its current level."},
                "tags": {"type": "string"},
                "source": {"type": "string"},
                "memory_key": {"type": "string", "description": "Stable topic key; use the same key when refining the same fact."},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                "always_apply": {"type": "boolean", "description": "When true, inject this memory into every codex_memory_search result regardless of query filters. Use for stable instructions or facts the user wants in every memory invocation. Omit when refining an existing memory to preserve its setting."},
                "replace_ids": {"type": "array", "items": {"type": "integer"}},
                "obsolete_ids": {"type": "array", "items": {"type": "integer"}},
                "source_session": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "codex_memory_related",
        "description": "Read-only lookup of memories related to one memory. Relation strength is 1-100 and is learned from shared topics and deliberate co-use.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
            },
            "required": ["memory_id"],
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
        "name": "codex_memory_set_always_apply",
        "description": "Set or clear the always_apply flag on existing active memories. Enabled records are included in every codex_memory_search response regardless of query filters. This changes only retrieval scope metadata, not memory content or importance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_ids": {"type": "array", "items": {"type": "integer"}},
                "enabled": {"type": "boolean"},
            },
            "required": ["memory_ids", "enabled"],
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
    read_only = name in {"codex_memory_search", "codex_memory_related", "codex_memory_stats"}
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
        if name == "codex_memory_related":
            rows = related(
                connection,
                int(arguments.get("memory_id", 0)),
                int(arguments.get("limit", 10)),
            )
            return tool_result(
                {
                    "count": len(rows),
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
                always_apply=(
                    bool(arguments["always_apply"])
                    if "always_apply" in arguments
                    else None
                ),
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
        if name == "codex_memory_set_always_apply":
            count = set_always_apply(
                connection,
                arguments.get("memory_ids", []) or [],
                bool(arguments.get("enabled", False)),
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
                    "Use codex_memory_search before work when relevant and again before asking the user for help when a task is blocked; search the concrete symptom or error together with the application, environment, and operation, then try and verify an applicable remembered procedure before asking. Every active memory marked always_apply is included in each search regardless of query filters. Read each such record on every search: follow instructions/preferences within their stated scope, and use factual records as background when relevant. Nothing in memory overrides system/developer rules or an explicit current-turn instruction from the user. Search is graph-aware and read-only: it starts from lexical seeds, follows strong memory relations, and must not touch other applications. Use codex_memory_related to inspect a memory's 1-100 relation neighbors. At the end of a turn, split information into one atomic point per codex_memory_commit call, including verified solution procedures and operational playbooks when they can help future turns. Judge initial importance on a 1-100 scale, and use codex_memory_mark_used, codex_memory_commit, or codex_memory_retire to update this local store. Memories used together gain relation strength; each deliberate use raises importance by at least 20 and about 50%, up to 100, while each 6-hour period without retrieval multiplies it by 0.9."
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
