"""Dependency-free, line-delimited stdio MCP interface for Codex Memory."""
from __future__ import annotations
import json
import sys
from typing import Any
import codex_memory_core as core
import codex_memory_features as features

SERVER_NAME = "codex-memory"
SERVER_VERSION = "2.0.0"

def schema(name, description, properties, required=(), read_only=False):
    return {"name": "codex_memory_" + name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": read_only, "openWorldHint": False}}

STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
ID = {"type": "integer", "minimum": 1}
IDS = {"type": "array", "items": ID}
SCORE = {"type": "integer", "minimum": 1, "maximum": 100}
BOOL = {"type": "boolean"}
REVISION = {"type": "integer", "minimum": 1}
REQUEST = {"type": "string", "description": "Idempotency key: reuse only when retrying the same logical operation."}
RELATION_TYPES = ["related", "co_used", "same_project", "prerequisite", "supersedes", "supports", "contradicts"]

CORE_TOOLS = [
    schema("search", "Read-only scoped retrieval. Supply space/scenarios and Codex-expanded aliases. Global and matching scenario rules are included within a bounded context budget. Retrieval does not mark use or launch a model.", {
        "query": STRING, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 8},
        "category": STRING, "min_importance": SCORE, "space": STRING, "scenarios": STRINGS, "aliases": STRINGS,
        "as_of": STRING, "token_budget": {"type": "integer", "minimum": 100}, "include_global": BOOL,
    }, read_only=True),
    schema("get", "Read one complete record without content truncation.", {"memory_id": ID}, ["memory_id"], True),
    schema("history", "Read immutable revisions and provenance for one memory.", {"memory_id": ID}, ["memory_id"], True),
    schema("commit", "Create or revise one precise information unit with scope and evidence. The current Codex caller judges semantics and importance; no backend LLM is invoked. Search before replacement; use expected_revision and request_id. Durable importance is independent of activity.", {
        "title": STRING, "content": STRING, "category": STRING, "importance": SCORE,
        "tags": STRING, "source": STRING, "memory_key": STRING,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "always_apply": BOOL,
        "replace_ids": IDS, "obsolete_ids": IDS, "source_session": STRING, "space": STRING,
        "kind": {"type": "string", "enum": ["fact", "preference", "procedure", "failure", "decision", "event", "profile", "project"]},
        "scope": {"type": "string", "enum": ["global", "scenario", "on_demand"]}, "scenarios": STRINGS,
        "aliases": STRINGS, "evidence": {"type": "array", "items": {"type": ["object", "string"]}},
        "valid_from": STRING, "valid_until": STRING, "expected_revision": REVISION,
        "expected_revisions": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}}, "request_id": REQUEST,
    }, ["title", "content"]),
    schema("related", "Read typed relations and neighboring records.", {
        "memory_id": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    }, ["memory_id"], True),
    schema("relation", "Set an evidenced typed relation. Strength ranges from 1 to 100.", {
        "a": ID, "b": ID, "relation_type": {"type": "string", "enum": RELATION_TYPES}, "strength": SCORE, "evidence": STRING, "request_id": REQUEST,
    }, ["a", "b", "relation_type", "strength"]),
    schema("retire", "Retire wrong or obsolete records while retaining history.", {
        "memory_ids": IDS, "reason": STRING, "source_session": STRING, "request_id": REQUEST,
        "expected_revisions": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}},
    }, ["memory_ids"]),
    schema("mark_used", "Record actual reliance once, not retrieval. Boost activity by max(+20, x1.5), capped at 100; importance stays unchanged. Group IDs only for meaningful co-use.", {
        "memory_ids": IDS, "source_session": STRING, "request_id": REQUEST, "co_use_groups": {"type": "array", "items": IDS},
    }, ["memory_ids"]),
    schema("set_always_apply", "Legacy scope control: enabled means global and disabled means on_demand. Requires each record revision to prevent stale writes; use commit with scope/scenarios for task-specific rules.", {"memory_ids": IDS, "enabled": BOOL, "expected_revisions": {"type":"object","additionalProperties":{"type":"integer","minimum":1}}, "request_id": REQUEST}, ["memory_ids", "enabled"]),
    schema("stats", "Read counts, capacity and scoring configuration without mutations.", {}, read_only=True),
    schema("restore_revision", "Restore an old revision as a new revision without erasing history.", {
        "memory_id": ID, "revision": REVISION, "expected_revision": REVISION, "request_id": REQUEST,
    }, ["memory_id", "revision"]),
    schema("snapshot", "Create a consistent local snapshot before bulk maintenance. Retries with request_id return the same snapshot. Never upload snapshots.", {"label": STRING, "request_id":REQUEST}),
    schema("restore_snapshot", "Restore a whole-store snapshot with a safety snapshot first; retries with request_id do not repeat the restore.", {"snapshot_id": ID, "request_id":REQUEST}, ["snapshot_id"]),
]
TOOLS = CORE_TOOLS + features.TOOLS
READ_ONLY_TOOLS = {t["name"] for t in CORE_TOOLS if t["annotations"]["readOnlyHint"]}

def json_result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}

def error_result(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

def tool_result(value: Any, is_error: bool = False) -> dict:
    value = value if isinstance(value, dict) else {"value": value}
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value, "isError": is_error}

def validate(arguments: dict, tool: dict) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    spec = tool["inputSchema"]
    missing = set(spec.get("required", [])) - arguments.keys()
    if missing:
        raise ValueError("missing arguments: " + ", ".join(sorted(missing)))
    if spec.get("additionalProperties") is False:
        unknown = arguments.keys() - spec.get("properties", {}).keys()
        if unknown:
            raise ValueError("unknown arguments: " + ", ".join(sorted(unknown)))
    checks = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}
    for key, value in arguments.items():
        rule = spec.get("properties", {}).get(key, {})
        expected = rule.get("type")
        if isinstance(expected, str) and expected in checks and not checks[expected](value):
            raise ValueError(f"{key} must be {expected}")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"invalid {key}")
        if expected in ("integer", "number"):
            if value < rule.get("minimum", float("-inf")) or value > rule.get("maximum", float("inf")):
                raise ValueError(f"{key} is outside its allowed range")

def call_tool(name: str, arguments: dict[str, Any]) -> dict:
    connection = None
    try:
        tool = next((item for item in TOOLS if item["name"] == name), None)
        if tool is None:
            raise ValueError(f"unknown tool: {name}")
        validate(arguments, tool)
        feature = name not in {item["name"] for item in CORE_TOOLS}
        read_only = features.is_read_only(name, arguments) if feature else name in READ_ONLY_TOOLS
        connection = core.connect(read_only=read_only)
        if connection is None:
            if name == "codex_memory_stats":
                return tool_result(core.stats(None, mutate=False))
            if name == "codex_memory_search":
                return tool_result({"count":0,"memories":[],"message":"Memory database has not been initialized."})
            if feature and read_only:
                return tool_result({"initialized":False,"message":"Memory database has not been initialized; this read did not create it."})
            raise FileNotFoundError("Memory database is not initialized; create a memory or initialize the manager first.")
        if feature:
            if not read_only:
                features.ensure_schema(connection)
            result=features.dispatch(connection, name, arguments)
            if not read_only:
                # Feature schema initialization opens an outer SQLite write
                # transaction. Releasing the handler savepoint is not enough;
                # commit before closing so MCP writes persist.
                connection.commit()
            return tool_result(result)
        if name == "codex_memory_search":
            rows = core.search(connection, **arguments, track_usage=False, mutate=False)
            return tool_result({"count": len(rows), "memories": [dict(row) for row in rows]})
        if name == "codex_memory_get":
            row = core.get(connection, arguments["memory_id"])
            return tool_result({"memory": dict(row) if row else None})
        if name == "codex_memory_history":
            return tool_result({"revisions": core.history(connection, arguments["memory_id"])})
        if name == "codex_memory_commit":
            return tool_result({"ok": True, **core.commit_memory(connection, **arguments)})
        if name == "codex_memory_related":
            rows = core.related(connection, arguments["memory_id"], arguments.get("limit", 10))
            return tool_result({"count": len(rows), "memories": [dict(row) for row in rows]})
        if name == "codex_memory_relation":
            return tool_result(core.set_relation(connection, **arguments))
        if name == "codex_memory_retire":
            return tool_result({"ok": True, "retired": core.retire(connection, **arguments)})
        if name == "codex_memory_mark_used":
            return tool_result({"ok": True, "updated": core.mark_used(connection, **arguments)})
        if name == "codex_memory_set_always_apply":
            return tool_result({"ok": True, "updated": core.set_always_apply(connection, **arguments)})
        if name == "codex_memory_stats":
            return tool_result(core.stats(connection, mutate=False))
        if name == "codex_memory_restore_revision":
            return tool_result(core.restore_revision(connection, **arguments))
        if name == "codex_memory_snapshot":
            return tool_result(core.snapshot(connection, **arguments))
        if name == "codex_memory_restore_snapshot":
            return tool_result(core.restore_snapshot(connection, arguments["snapshot_id"]))
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:
        return tool_result({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, True)
    finally:
        if connection is not None:
            connection.close()

def handle(request: dict) -> dict | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return error_result(None, -32600, "Invalid JSON-RPC request")
    method, request_id = request.get("method"), request.get("id")
    if method == "initialize":
        params = request.get("params") or {}
        return json_result(request_id, {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Use memory before relevant work and before asking for help when blocked. Choose space/scenarios and query aliases; follow applicable global/scenario rules. System/developer and current user instructions override stored memories. Reads do not change storage or other apps. The current Codex caller performs semantic extraction, query expansion and evidence-based synthesis; this server invokes no model. Save useful confirmed atomic information with context, sources and expected_revision; replace contradictions with newer confirmed evidence and preserve history. Mark actual reliance once with request_id. Importance is durable value; activity gains max(20 points,50%) per use and decays 10% per 6 hours. Confidence and validity are independent. Use task cards for temporary progress, procedures for verified workflows and cited derived views for analysis. Never upload local memory data, snapshots, evidence or logs to GitHub.",
        })
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "ping":
        return json_result(request_id, {})
    if method == "tools/list":
        return json_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        return json_result(request_id, call_tool(str(params.get("name", "")), params.get("arguments", {})))
    return error_result(request_id, -32601, f"Method not found: {method}") if request_id is not None else None

def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
        except (ValueError, TypeError) as exc:
            response = error_result(None, -32700, str(exc))
        except Exception as exc:
            response = error_result(None, -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
