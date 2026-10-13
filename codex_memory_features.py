"""Local, dependency-free workspaces, resumable tasks and evidence-backed views.

Semantic conclusions are supplied by Codex. This module validates, stores and
retrieves them; it never starts a model, browser, shell or other application.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any = None) -> Any:
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _text(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _strings(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError(f"{name} must be an array of strings")
    return [v.strip() for v in value if v.strip()]


def _table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Add feature tables inside the caller's migration transaction."""
    statements = [
        "CREATE TABLE IF NOT EXISTS cm_spaces (key TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS cm_procedures (memory_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,stale INTEGER NOT NULL DEFAULT 0,success_count INTEGER NOT NULL DEFAULT 0,failure_count INTEGER NOT NULL DEFAULT 0,last_outcome TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS cm_tasks (key TEXT PRIMARY KEY,space TEXT NOT NULL,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS cm_summaries (space TEXT NOT NULL,topic TEXT NOT NULL,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,stale INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(space,topic))",
        "CREATE TABLE IF NOT EXISTS cm_files (path TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS cm_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT,memory_id INTEGER NOT NULL,memory_revision INTEGER NOT NULL DEFAULT 1,outcome TEXT NOT NULL,context TEXT NOT NULL DEFAULT '',correction TEXT NOT NULL DEFAULT '',scope TEXT NOT NULL DEFAULT 'global',created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS cm_feedback_memory ON cm_feedback(memory_id,scope,outcome)",
        "CREATE TABLE IF NOT EXISTS cm_events (id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,target TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS cm_requests (request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS cm_tasks_space ON cm_tasks(space)",
    ]
    for statement in statements:
        conn.execute(statement)
    if "memory_revision" not in {row[1] for row in conn.execute("PRAGMA table_info(cm_feedback)")}:
        conn.execute("ALTER TABLE cm_feedback ADD COLUMN memory_revision INTEGER NOT NULL DEFAULT 1")
    conn.execute("INSERT OR IGNORE INTO cm_spaces(key,title,description,updated_at) VALUES('global','Global','Shared memory',?)", (_now(),))


@contextmanager
def _atomic(conn: sqlite3.Connection):
    conn.execute("SAVEPOINT cm_feature_write")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT cm_feature_write")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT cm_feature_write")
        conn.execute("RELEASE SAVEPOINT cm_feature_write")
        raise


def _version(row: Any, expected: Any) -> int:
    current = int(row["version"]) if row else 0
    if row and expected is None:
        raise ValueError(f"expected_version is required for updates (current {current})")
    if expected is not None and int(expected) != current:
        raise ValueError(f"version conflict: expected {expected}, current {current}")
    return current + 1


def _space(conn: sqlite3.Connection, key: str) -> str:
    key = _text(key, "space")
    if not _table(conn, "cm_spaces") or not conn.execute("SELECT 1 FROM cm_spaces WHERE key=?", (key,)).fetchone():
        if key == "global":
            return key
        raise ValueError(f"unknown memory space: {key}")
    return key


def _event(conn: sqlite3.Connection, kind: str, target: Any, details: dict) -> None:
    conn.execute("INSERT INTO cm_events(kind,target,details,created_at) VALUES(?,?,?,?)", (kind, str(target), _json(details), _now()))


def _memory(conn: sqlite3.Connection, memory_id: int, active: bool = True) -> dict:
    row = conn.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
    if row is None or (active and row["status"] != "active"):
        raise ValueError(f"memory {memory_id} is missing or inactive")
    return dict(row)


def _evidence_row(row: dict) -> dict:
    return {key: row.get(key, "") for key in ("id", "revision", "title", "content", "source", "confidence", "updated_at", "valid_from", "valid_until", "memory_key", "space")}


def _spaces(conn: sqlite3.Connection, args: dict) -> dict:
    action = args.get("action", "list")
    if action == "list":
        rows = conn.execute("SELECT * FROM cm_spaces ORDER BY key").fetchall() if _table(conn, "cm_spaces") else []
        return {"spaces": [dict(row) for row in rows]}
    key = _text(args.get("key"), "key")
    row = conn.execute("SELECT * FROM cm_spaces WHERE key=?", (key,)).fetchone() if _table(conn,"cm_spaces") else None
    if action == "get":
        return {"space": dict(row) if row else None}
    if action != "create":
        raise ValueError("spaces action must be list, get or create")
    if not re.fullmatch(r"[\w./-]{1,120}", key, re.UNICODE):
        raise ValueError("space key must contain letters, numbers, underscores, dots, slashes or hyphens")
    version = _version(row, args.get("expected_version"))
    title = _text(args.get("title", row["title"] if row else key), "title")
    conn.execute("INSERT INTO cm_spaces(key,title,description,version,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET title=excluded.title,description=excluded.description,version=excluded.version,updated_at=excluded.updated_at", (key, title, str(args.get("description", row["description"] if row else "")), version, _now()))
    return {"space": dict(conn.execute("SELECT * FROM cm_spaces WHERE key=?", (key,)).fetchone()), "operation": "updated" if row else "created", "version": version}


def _procedure_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    result = dict(row)
    result.update(_load(result.pop("payload"), {}))
    memory = conn.execute("SELECT * FROM memories WHERE id=?", (result["memory_id"],)).fetchone()
    stale_reasons = []
    if memory:
        source = dict(memory)
        result.update({key: source.get(key) for key in ("title", "content", "space", "status", "revision")})
        if source.get("revision", 1) != result.get("memory_revision", 1):
            stale_reasons.append("memory_revision_changed")
        if source["status"] != "active":
            stale_reasons.append("memory_inactive")
        if source.get("valid_until") and _date(source["valid_until"]) <= datetime.now(timezone.utc):
            stale_reasons.append("memory_expired")
    else:
        stale_reasons.append("memory_missing")
    if result.get("stale"):
        stale_reasons.append("file_changed_or_failure_reported")
    result["stale"] = bool(stale_reasons)
    result["stale_reasons"] = stale_reasons
    return result


def _procedures(conn: sqlite3.Connection, space: str = "global", include_global: bool = True) -> list[dict]:
    if not _table(conn, "cm_procedures"):
        return []
    values = []
    for row in conn.execute("SELECT * FROM cm_procedures ORDER BY updated_at DESC"):
        result = _procedure_view(conn, row)
        if result.get("space", "global") == space or (include_global and result.get("space", "global") == "global"):
            values.append(result)
    return values


def _procedure(conn: sqlite3.Connection, args: dict) -> dict:
    action = args.get("action", "list")
    if action == "list":
        return {"procedures": _procedures(conn, args.get("space", "global"))}
    memory_id = int(args.get("memory_id") or 0)
    row = conn.execute("SELECT * FROM cm_procedures WHERE memory_id=?", (memory_id,)).fetchone() if _table(conn,"cm_procedures") else None
    if action == "get":
        return {"procedure": _procedure_view(conn, row) if row else None}
    if action == "skill_draft":
        if not row:
            raise ValueError("procedure does not exist")
        procedure = _procedure_view(conn, row)
        if procedure["stale"] or not procedure.get("verified_at") or procedure["success_count"] < 2:
            raise ValueError("Skill drafts require a current verified procedure with at least two successful execution reports")
        title = procedure["title"].replace("\n", " ")
        slug = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or f"memory-procedure-{memory_id}"
        parts = ["---", f"name: {slug[:64]}", "description: " + json.dumps(title, ensure_ascii=False), "---", "", f"# {title}", "", procedure["content"], "", "## Applicable environment", "", json.dumps(procedure.get("environment", {}), ensure_ascii=False, indent=2), "", "## Prerequisites", ""]
        parts.extend(f"- {item}" for item in procedure["prerequisites"])
        parts.extend(["", "## Steps", ""])
        parts.extend(f"{i}. {item}" for i, item in enumerate(procedure["steps"], 1))
        parts.extend(["", "## Success criteria", ""])
        parts.extend(f"- {item}" for item in procedure["success_criteria"])
        parts.extend(["", "## Provenance", "", f"Memory {memory_id}, revision {procedure['revision']}; verified {procedure['verified_at']}.", "Draft only: review its scope and permissions before installation."])
        return {"skill_draft": "\n".join(parts) + "\n", "installed": False, "memory_id": memory_id, "revision": procedure["revision"]}
    if action == "feedback":
        if not row:
            raise ValueError("procedure does not exist")
        version = _version(row, args.get("expected_version"))
        outcome = args.get("outcome")
        if outcome not in {"success", "failure"}:
            raise ValueError("procedure outcome must be success or failure")
        notes = _text(args.get("notes"), "notes describing observed result")
        payload = _load(row["payload"], {})
        current = _memory(conn, memory_id)
        if outcome == "success" and current.get("revision", 1) != payload.get("memory_revision", 1):
            raise ValueError("save the updated procedure before verifying a different memory revision")
        if outcome == "success":
            payload["verified_at"] = _now()
        conn.execute("UPDATE cm_procedures SET payload=?,version=?,success_count=success_count+?,failure_count=failure_count+?,last_outcome=?,stale=?,updated_at=? WHERE memory_id=?", (_json(payload), version, int(outcome == "success"), int(outcome == "failure"), outcome, int(outcome == "failure"), _now(), memory_id))
        _event(conn, "procedure_feedback", memory_id, {"outcome": outcome, "notes": notes, "memory_revision": current.get("revision", 1)})
        return {**_procedure(conn, {"action": "get", "memory_id": memory_id}), "version": version}
    if action != "save":
        raise ValueError("unknown procedure action")
    version = _version(row, args.get("expected_version"))
    old_payload = _load(row["payload"], {}) if row else {}
    space = _space(conn, args.get("space", old_payload.get("space", "global")))
    steps = _strings(args.get("steps", old_payload.get("steps")), "steps")
    criteria = _strings(args.get("success_criteria", old_payload.get("success_criteria")), "success_criteria")
    if not steps or not criteria:
        raise ValueError("procedure requires steps and success_criteria")
    environment = args.get("environment", old_payload.get("environment", {}))
    if not isinstance(environment, dict):
        raise ValueError("environment must be an object")
    verified = str(args.get("verified_at", ""))
    evidence = _strings(args.get("evidence", old_payload.get("evidence")), "evidence")
    if verified:
        if _date(verified) > datetime.now(timezone.utc):
            raise ValueError("verified_at cannot be in the future")
        if not evidence:
            raise ValueError("verified procedures require evidence")
    kind = args.get("procedure_type", old_payload.get("procedure_type", "procedure"))
    if kind not in {"procedure", "failure"}:
        raise ValueError("procedure_type must be procedure or failure")
    old_memory = _memory(conn, memory_id) if memory_id else {}
    if memory_id and args.get("expected_revision") is None:
        raise ValueError("expected_revision is required to update procedure memory")
    from codex_memory_core import commit_memory
    result = commit_memory(conn, title=_text(args.get("title", old_memory.get("title")), "title"), content=_text(args.get("content", old_memory.get("content")), "content"), category="流程", kind=kind, space=space, importance=args.get("importance"), memory_key=args.get("memory_key", old_memory.get("memory_key", "")), replace_ids=[memory_id] if memory_id else [], expected_revision=args.get("expected_revision"), evidence=evidence)
    memory_id = int(result["id"])
    if not row and conn.execute("SELECT 1 FROM cm_procedures WHERE memory_id=?", (memory_id,)).fetchone():
        raise ValueError("procedure already exists; provide memory_id and expected_version")
    payload = {"space": space, "procedure_type": kind, "steps": steps, "prerequisites": _strings(args.get("prerequisites", old_payload.get("prerequisites")), "prerequisites"), "success_criteria": criteria, "environment": environment, "verified_at": verified, "evidence": evidence, "memory_revision": _memory(conn, memory_id).get("revision", 1)}
    conn.execute("INSERT INTO cm_procedures(memory_id,payload,version,updated_at) VALUES(?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET payload=excluded.payload,version=excluded.version,stale=0,success_count=0,failure_count=0,last_outcome='',updated_at=excluded.updated_at", (memory_id, _json(payload), version, _now()))
    return {**_procedure(conn, {"action": "get", "memory_id": memory_id}), "operation": "updated" if row else "created", "version": version}


def _task_view(row: sqlite3.Row) -> dict:
    result = dict(row)
    result.update(_load(result.pop("payload"), {}))
    result["expired"] = bool(result.get("expires_at") and _date(result["expires_at"]) <= datetime.now(timezone.utc))
    return result


def _task(conn: sqlite3.Connection, args: dict) -> dict:
    action = args.get("action", "list")
    if action == "list":
        space = args.get("space", "global")
        rows = conn.execute("SELECT * FROM cm_tasks WHERE space=? ORDER BY updated_at DESC", (space,)).fetchall() if _table(conn, "cm_tasks") else []
        return {"tasks": [_task_view(row) for row in rows]}
    key = _text(args.get("key"), "key")
    row = conn.execute("SELECT * FROM cm_tasks WHERE key=?", (key,)).fetchone() if _table(conn,"cm_tasks") else None
    if action == "get":
        return {"task": _task_view(row) if row else None}
    if action not in {"save", "close"}:
        raise ValueError("task action must be list, get, save or close")
    if action == "close" and row is None:
        raise ValueError("task does not exist")
    version = _version(row, args.get("expected_version"))
    old = _task_view(row) if row else {}
    space = _space(conn, args.get("space", old.get("space", "global")))
    status = "completed" if action == "close" else args.get("status", old.get("status", "active"))
    if status not in {"active", "blocked", "paused", "completed", "cancelled"}:
        raise ValueError("invalid task status")
    from codex_memory_core import load_settings
    ttl = float(args.get("ttl_hours", load_settings().get("default_task_ttl_hours", 168)))
    if not 1 <= ttl <= 8760:
        raise ValueError("ttl_hours must be between 1 and 8760")
    payload = {"goal": _text(args.get("goal", old.get("goal")), "goal"), "status": status, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=ttl)).isoformat(timespec="seconds")}
    for field in ("completed", "next_steps", "files", "questions"):
        payload[field] = _strings(args.get(field, old.get(field)), field)
    conn.execute("INSERT INTO cm_tasks(key,space,payload,version,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET space=excluded.space,payload=excluded.payload,version=excluded.version,updated_at=excluded.updated_at", (key, space, _json(payload), version, _now()))
    return {**_task(conn, {"action": "get", "key": key}), "operation": "updated" if row else "created", "version": version}


def _normal(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _profile(conn: sqlite3.Connection, args: dict) -> dict:
    space = _space(conn, args.get("space", "global"))
    fields = _strings(args.get("fields"), "fields")
    if not fields:
        raise ValueError("profile requires requested fields; use stable memory keys or aliases")
    now = datetime.now(timezone.utc)
    candidates = []
    for row in conn.execute("SELECT * FROM memories WHERE status='active' AND space IN (?, 'global')", (space,)):
        item = dict(row)
        if item.get("valid_from") and _date(item["valid_from"]) > now:
            continue
        if item.get("valid_until") and _date(item["valid_until"]) <= now:
            continue
        candidates.append(item)
    result = []
    for field in fields:
        normalized = _normal(field)
        matches = []
        for item in candidates:
            keys = [item.get("memory_key", ""), item["title"], *_load(item.get("aliases", "[]"), [])]
            if normalized and any(_normal(str(key)) == normalized for key in keys):
                matches.append(item)
        # Explicit project facts override inherited global fields of the same name.
        local = [item for item in matches if item.get("space") == space]
        matches = local or matches
        values = {_normal(item["content"]) for item in matches}
        status = "known" if len(values) == 1 else "ambiguous" if matches else "unknown"
        result.append({"field": field, "status": status, "records": [_evidence_row(item) for item in matches]})
    return {"space": space, "fields": result, "derived": True}


def _summary_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    result = dict(row)
    result.update(_load(result.pop("payload"), {}))
    reasons = []
    for citation in result.get("citations", []):
        memory = conn.execute("SELECT * FROM memories WHERE id=?", (citation["id"],)).fetchone()
        if not memory or memory["status"] != "active" or int(memory["revision"]) != citation["revision"]:
            reasons.append({"id": citation["id"], "reason": "source_changed_or_inactive"})
        elif memory["valid_until"] and _date(memory["valid_until"]) <= datetime.now(timezone.utc):
            reasons.append({"id": citation["id"], "reason": "source_expired"})
    if result.get("stale"):
        reasons.append({"reason": "attached_file_changed"})
    result["stale"] = bool(reasons)
    result["stale_reasons"] = reasons
    result["label"] = "inference" if result.get("inference", True) else "evidence_summary"
    return result


def _reflect(conn: sqlite3.Connection, args: dict) -> dict:
    action = args.get("action", "prepare")
    space = _space(conn, args.get("space", "global"))
    if action == "list":
        rows = conn.execute("SELECT * FROM cm_summaries WHERE space=? ORDER BY updated_at DESC", (space,)).fetchall() if _table(conn, "cm_summaries") else []
        return {"summaries": [_summary_view(conn, row) for row in rows]}
    topic = _text(args.get("topic"), "topic")
    if action=="prepare":
        from codex_memory_core import search
        rows = search(conn, topic, limit=20, space=space, token_budget=int(args.get("token_budget", 4000)))
        return {"topic": topic, "space": space, "evidence": [_evidence_row(dict(row)) for row in rows], "instruction": "Codex should synthesize only supported claims, label inferences, name missing evidence, and save with exact id/revision citations. No model is invoked by this tool."}
    if not _table(conn,"cm_summaries"):
        return {"summary":None} if action=="get" else {"error":"summary store is not initialized; create a summary to initialize it"}
    row = conn.execute("SELECT * FROM cm_summaries WHERE space=? AND topic=?", (space, topic)).fetchone()
    if action == "get":
        return {"summary": _summary_view(conn, row) if row else None}
    if action != "save":
        raise ValueError("reflect action must be prepare, save, get or list")
    version = _version(row, args.get("expected_version"))
    citations = args.get("citations", [])
    if not isinstance(citations, list) or not citations:
        raise ValueError("summary requires id/revision citations")
    normalized = []
    seen = set()
    for citation in citations:
        if not isinstance(citation, dict) or "id" not in citation or "revision" not in citation:
            raise ValueError("each citation needs id and revision")
        source = _memory(conn, int(citation["id"]))
        revision = int(citation["revision"])
        if source.get("revision", 1) != revision:
            raise ValueError(f"stale citation for memory {source['id']}")
        if source.get("space", "global") not in {space, "global"}:
            raise ValueError("citation is outside this memory space")
        if source.get("valid_until") and _date(source["valid_until"]) <= datetime.now(timezone.utc):
            raise ValueError("citation has expired")
        if source["id"] not in seen:
            normalized.append({"id": source["id"], "revision": revision})
            seen.add(source["id"])
    payload = {"conclusion": _text(args.get("conclusion"), "conclusion"), "citations": normalized, "inference": bool(args.get("inference", True))}
    conn.execute("INSERT INTO cm_summaries(space,topic,payload,version,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(space,topic) DO UPDATE SET payload=excluded.payload,version=excluded.version,stale=0,updated_at=excluded.updated_at", (space, topic, _json(payload), version, _now()))
    return {**_reflect(conn, {"action": "get", "topic": topic, "space": space}), "operation": "updated" if row else "created", "version": version}


def _fingerprint(path: Path) -> dict:
    try:
        before = path.stat()
        if not path.is_file():
            return {"state": "not_file", "sha256": ""}
        if before.st_size > 100 * 1024 * 1024:
            raise ValueError("attached files are limited to 100 MiB")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
            raise ValueError("file changed while hashing; retry when stable")
        return {"state": "present", "sha256": digest.hexdigest(), "size": after.st_size, "mtime_ns": after.st_mtime_ns}
    except FileNotFoundError:
        return {"state": "missing", "sha256": ""}


def _file_view(row: sqlite3.Row) -> dict:
    result = dict(row)
    result.update(_load(result.pop("payload"), {}))
    return result


def _file(conn: sqlite3.Connection, args: dict) -> dict:
    action = args.get("action", "list")
    if action == "list":
        rows = conn.execute("SELECT * FROM cm_files ORDER BY updated_at DESC").fetchall() if _table(conn, "cm_files") else []
        return {"files": [_file_view(row) for row in rows]}
    raw_path = Path(_text(args.get("path"), "path")).expanduser()
    if not raw_path.is_absolute():
        raise ValueError("file attachment path must be absolute")
    path = str(raw_path.resolve())
    row = conn.execute("SELECT * FROM cm_files WHERE path=?", (path,)).fetchone()
    if action not in {"attach", "check"}:
        raise ValueError("file action must be attach, check or list")
    if action == "check" and not row:
        raise ValueError("file must be attached before checking")
    version = _version(row, args.get("expected_version"))
    current = _fingerprint(Path(path))
    old = _load(row["payload"], {}) if row else {}
    if action == "attach":
        ids = sorted({int(value) for value in args.get("memory_ids", [])})
        if not ids:
            raise ValueError("attach requires memory_ids")
        for memory_id in ids:
            _memory(conn, memory_id)
        if current["state"] != "present":
            raise ValueError("attach requires an existing regular file")
        baseline = current
        changed = False
    else:
        ids = old["memory_ids"]
        baseline = old["baseline"]
        changed = current["sha256"] != baseline["sha256"] or current["state"] != baseline["state"]
    payload = {"memory_ids": ids, "baseline": baseline, "current": current, "changed": changed, "checked_at": _now()}
    if changed:
        for memory_id in ids:
            conn.execute("UPDATE cm_procedures SET stale=1 WHERE memory_id=?", (memory_id,))
        for summary in conn.execute("SELECT space,topic,payload FROM cm_summaries").fetchall():
            references = _load(summary["payload"], {}).get("citations", [])
            if any(citation["id"] in ids for citation in references):
                conn.execute("UPDATE cm_summaries SET stale=1 WHERE space=? AND topic=?", (summary["space"], summary["topic"]))
        _event(conn, "file_changed", path, {"memory_ids": ids, "state": current["state"]})
    conn.execute("INSERT INTO cm_files(path,payload,version,updated_at) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET payload=excluded.payload,version=excluded.version,updated_at=excluded.updated_at", (path, _json(payload), version, _now()))
    return {"file": _file_view(conn.execute("SELECT * FROM cm_files WHERE path=?", (path,)).fetchone()), "version": version}


def _feedback(conn: sqlite3.Connection, args: dict) -> dict:
    memory_id = int(args.get("memory_id") or 0)
    memory = _memory(conn, memory_id)
    outcome = args.get("outcome")
    if outcome not in {"useful", "irrelevant", "incorrect"}:
        raise ValueError("feedback outcome must be useful, irrelevant or incorrect")
    scope = _space(conn, args.get("scope", "global"))
    correction = str(args.get("correction", "")).strip()
    if correction and outcome != "incorrect":
        raise ValueError("correction is only supported with incorrect feedback")
    cursor = conn.execute("INSERT INTO cm_feedback(memory_id,memory_revision,outcome,context,correction,scope,created_at) VALUES(?,?,?,?,?,?,?)", (memory_id, memory.get("revision", 1), outcome, str(args.get("context", "")), correction, scope, _now()))
    return {"feedback_id": cursor.lastrowid, "memory_id": memory_id, "outcome": outcome, "scope": scope, "correction_status": "pending_confirmation" if correction else None, "memory_changed": False}


def _graph(conn: sqlite3.Connection, args: dict) -> dict:
    space = _space(conn, args.get("space", "global"))
    limit = max(1, min(1000, int(args.get("limit", 100))))
    memory_id = int(args.get("memory_id") or 0)
    rows = [dict(row) for row in conn.execute("SELECT * FROM memories WHERE status='active' AND space IN (?, 'global') ORDER BY importance DESC,id", (space,))]
    allowed = {row["id"] for row in rows}
    edges = []
    if _table(conn, "memory_edges"):
        for row in conn.execute("SELECT * FROM memory_edges ORDER BY strength DESC"):
            item = dict(row)
            if item["memory_a_id"] in allowed and item["memory_b_id"] in allowed:
                edges.append({"source": item["memory_a_id"], "target": item["memory_b_id"], "type": item["relation_type"], "strength": item["strength"], "evidence": item.get("evidence", "")})
    if memory_id:
        selected = {memory_id} if memory_id in allowed else set()
        for edge in edges:
            if memory_id in {edge["source"], edge["target"]} and len(selected) < limit:
                selected.update({edge["source"], edge["target"]})
        rows = sorted((row for row in rows if row["id"] in selected), key=lambda row: row["id"] != memory_id)[:limit]
    else:
        rows = rows[:limit]
    included = {row["id"] for row in rows}
    return {"nodes": [{key: row.get(key) for key in ("id", "title", "kind", "space", "status", "importance", "activity", "revision")} for row in rows], "edges": [edge for edge in edges if edge["source"] in included and edge["target"] in included], "truncated": len(allowed) > len(rows)}


def _health(conn: sqlite3.Connection, args: dict) -> dict:
    space = _space(conn, args.get("space", "global"))
    rows = [dict(row) for row in conn.execute("SELECT * FROM memories WHERE status='active' AND space IN (?, 'global')", (space,))]
    issues = []
    duplicate_groups = {}
    key_groups = {}
    for row in rows:
        duplicate_groups.setdefault((row["space"], _normal(row["content"])), []).append(row["id"])
        if row.get("memory_key"):
            key_groups.setdefault((row["space"], row["memory_key"]), []).append(row)
        if row.get("valid_until") and _date(row["valid_until"]) <= datetime.now(timezone.utc):
            issues.append({"type": "expired", "severity": "warning", "ids": [row["id"]], "message": "Memory validity has ended."})
        if row.get("needs_review"):
            issues.append({"type": "legacy_scope_review", "severity": "info", "ids": [row["id"]], "message": "Review the migrated applicability scope and provenance before relying on it as a task instruction."})
    for ids in duplicate_groups.values():
        if len(ids) > 1:
            issues.append({"type": "duplicate", "severity": "warning", "ids": ids, "message": "Identical normalized content in this space; inspect before merging."})
    for group in key_groups.values():
        if len({_normal(item["content"]) for item in group}) > 1:
            issues.append({"type": "possible_conflict", "severity": "warning", "ids": [item["id"] for item in group], "message": "Active records have the same key and different content; Codex should assess scope and time."})
    graph = _graph(conn, {"space": space, "limit": 1000})
    connected = {node for edge in graph["edges"] for node in (edge["source"], edge["target"])}
    for row in rows:
        if row["id"] not in connected:
            issues.append({"type": "orphan", "severity": "info", "ids": [row["id"]], "message": "No relation to another active memory in the selected space."})
    for edge in graph["edges"]:
        if edge["type"] == "contradicts":
            issues.append({"type": "declared_conflict", "severity": "warning", "ids": [edge["source"], edge["target"]], "message": "Explicit contradiction relation requires review."})
    for procedure in _procedures(conn, space):
        if procedure["stale"] or not procedure.get("verified_at"):
            issues.append({"type": "stale_procedure" if procedure["stale"] else "unverified_procedure", "severity": "warning", "ids": [procedure["memory_id"]], "message": "Procedure needs validation before reuse."})
    for summary in _reflect(conn, {"action": "list", "space": space})["summaries"]:
        if summary["stale"]:
            issues.append({"type": "stale_summary", "severity": "warning", "ids": [item["id"] for item in summary["citations"]], "message": f"Rebuild summary: {summary['topic']}"})
    if _table(conn, "cm_feedback"):
        allowed = {row["id"] for row in rows}
        for item in conn.execute("SELECT f.memory_id,MAX(f.id) AS feedback_id FROM cm_feedback f JOIN memories m ON m.id=f.memory_id AND m.revision=f.memory_revision WHERE f.outcome='incorrect' AND f.scope IN (?, 'global') GROUP BY f.memory_id", (space,)):
            if item["memory_id"] in allowed:
                issues.append({"type": "reported_incorrect", "severity": "warning", "ids": [item["memory_id"]], "message": "Incorrect feedback is pending review; confirm and replace the fact when appropriate.", "feedback_id": item["feedback_id"]})
    counts = {"active_memories": len(rows), "issues": len(issues), "warnings": sum(item["severity"] == "warning" for item in issues)}
    return {"space": space, "issues": issues, "counts": counts, "semantic_review_required": True}


def _packet(conn: sqlite3.Connection, args: dict) -> dict:
    from codex_memory_core import search
    space = _space(conn, args.get("space", "global"))
    budget = max(256, min(32000, int(args.get("token_budget", 4000))))
    query = str(args.get("query", ""))
    memories = search(conn, query, limit=int(args.get("limit", 8)), space=space, scenarios=args.get("scenarios", []), token_budget=max(128, int(budget * 0.65)))
    ids = {item["id"] for item in memories}
    procedures = [item for item in _procedures(conn, space) if item["memory_id"] in ids and not item["stale"] and item.get("verified_at")]
    tasks = [item for item in _task(conn, {"action": "list", "space": space})["tasks"] if not item["expired"] and item["status"] in {"active", "blocked", "paused"}]
    summaries = [item for item in _reflect(conn, {"action": "list", "space": space})["summaries"] if not item["stale"] and any(citation["id"] in ids for citation in item["citations"])]
    result = {"space": space, "query": query, "memories": memories, "procedures": [], "tasks": [], "summaries": [], "budget_tokens": budget, "truncated": False}
    # Conservative UTF-8 byte/3 estimate prevents unbounded derived payloads.
    for name, items in (("procedures", procedures), ("tasks", tasks), ("summaries", summaries)):
        for item in items:
            result[name].append(item)
            if len(_json(result).encode("utf-8")) > budget * 3:
                result[name].pop()
                result["truncated"] = True
    return result


def _maintenance(conn: sqlite3.Connection, args: dict) -> dict:
    space = args.get("space", "global")
    result = _health(conn, {"space": space})
    result["tasks_needing_review"] = [item["key"] for item in _task(conn, {"action": "list", "space": space})["tasks"] if item["expired"] and item["status"] not in {"completed", "cancelled"}]
    if _table(conn, "cm_events"):
        result["recent_events"] = [{**dict(row), "details": _load(row["details"], {})} for row in conn.execute("SELECT * FROM cm_events ORDER BY id DESC LIMIT 20")]
    else:
        result["recent_events"] = []
    result["mutated"] = False
    return result


_HANDLERS = {"spaces": _spaces, "procedure": _procedure, "task": _task, "profile": _profile, "packet": _packet, "reflect": _reflect, "file": _file, "feedback": _feedback, "health": _health, "graph": _graph, "maintenance": _maintenance}
READ_ONLY_TOOLS = {"codex_memory_profile", "codex_memory_packet", "codex_memory_health", "codex_memory_graph", "codex_memory_maintenance"}
_READ_ACTIONS = {"spaces": {"list", "get"}, "procedure": {"list", "get", "skill_draft"}, "task": {"list", "get"}, "reflect": {"prepare", "get", "list"}, "file": {"list"}}
_DEFAULT_ACTIONS = {"spaces": "list", "procedure": "list", "task": "list", "reflect": "prepare", "file": "list"}


def is_read_only(name: str, args: dict | None = None) -> bool:
    short = name.removeprefix("codex_memory_")
    return name in READ_ONLY_TOOLS or (args or {}).get("action", _DEFAULT_ACTIONS.get(short)) in _READ_ACTIONS.get(short, set())


def dispatch(conn: sqlite3.Connection, name: str, args: dict | None = None) -> dict:
    args = dict(args or {})
    short = name.removeprefix("codex_memory_")
    if short not in _HANDLERS:
        raise ValueError(f"unknown feature tool: {name}")
    if is_read_only(name, args):
        return _HANDLERS[short](conn, args)
    request_id = str(args.get("request_id", "")).strip()
    fingerprint = hashlib.sha256(_json({"name": name, "args": {key: value for key, value in args.items() if key != "request_id"}}).encode("utf-8")).hexdigest()
    with _atomic(conn):
        if request_id:
            previous = conn.execute("SELECT fingerprint,result FROM cm_requests WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("request_id was already used with different arguments")
                return _load(previous["result"], {})
        result = _HANDLERS[short](conn, args)
        if request_id:
            conn.execute("INSERT INTO cm_requests(request_id,fingerprint,result,created_at) VALUES(?,?,?,?)", (request_id, fingerprint, _json(result), _now()))
        return result


def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"name": "codex_memory_" + name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}


S = {"type": "string"}
I = {"type": "integer", "minimum": 1}
L = {"type": "array", "items": S}
IDS = {"type": "array", "items": I}
V = {"expected_version": {"type": "integer", "minimum": 0}, "request_id": S}
SPACE = {"type": "string", "default": "global"}
def _action(*values: str) -> dict:
    return {"type": "string", "enum": list(values), "default": values[0]}


TOOLS = [
    _schema("spaces", "Create/update named local project spaces, or read their metadata. Updates require expected_version; global is inherited by project retrieval.", {"action": _action("list", "get", "create"), "key": S, "title": S, "description": S, **V}),
    _schema("procedure", "Store complete procedural or failure playbooks as one long-term memory; record verified execution results; generate a Skill draft after two successful reports. No workflow or application is executed. Updates need expected_version and expected_revision.", {"action": _action("list", "get", "save", "feedback", "skill_draft"), "memory_id": I, "space": SPACE, "title": S, "content": S, "memory_key": S, "procedure_type": {"type": "string", "enum": ["procedure", "failure"]}, "steps": L, "prerequisites": L, "success_criteria": L, "environment": {"type": "object"}, "verified_at": S, "evidence": L, "importance": {"type": "integer", "minimum": 1, "maximum": 100}, "expected_revision": I, "outcome": {"type": "string", "enum": ["success", "failure"]}, "notes": S, **V}),
    _schema("task", "Read or maintain task resume cards separately from the 1000 long-term memories. Cards retain expired/completed history; active packets omit expired cards.", {"action": _action("list", "get", "save", "close"), "key": S, "space": SPACE, "goal": S, "completed": L, "next_steps": L, "files": L, "questions": L, "status": {"type": "string", "enum": ["active", "blocked", "paused", "completed", "cancelled"]}, "ttl_hours": {"type": "number", "minimum": 1, "maximum": 8760, "default": 168}, **V}),
    _schema("profile", "Read a derived structured profile using exact memory keys, titles or aliases. Returns known/ambiguous/unknown plus evidence, never invents missing fields or stores duplicate facts.", {"fields": L, "space": SPACE}, ["fields"]),
    _schema("packet", "Read a bounded task packet combining scoped memory, relevant verified procedures, open task cards and current cited summaries.", {"query": S, "space": SPACE, "scenarios": L, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 8}, "token_budget": {"type": "integer", "minimum": 256, "maximum": 32000, "default": 4000}}, ["query"]),
    _schema("reflect", "Prepare evidence for Codex analysis, then save or retrieve a cited topic summary. Citations require current memory IDs/revisions; inferences stay labelled. This tool never invokes an external model.", {"action": _action("prepare", "save", "get", "list"), "topic": S, "space": SPACE, "conclusion": S, "citations": {"type": "array", "items": {"type": "object", "properties": {"id": I, "revision": I}, "required": ["id", "revision"], "additionalProperties": False}}, "inference": {"type": "boolean", "default": True}, "token_budget": {"type": "integer", "minimum": 256, "maximum": 32000, "default": 4000}, **V}),
    _schema("file", "Attach a local file fingerprint to existing facts, list attachments, or explicitly check for changes and flag affected procedures/summaries stale. Hashes only; no file contents are stored. Check/reattach require expected_version.", {"action": _action("list", "attach", "check"), "path": S, "memory_ids": IDS, **V}),
    _schema("feedback", "Record scoped useful/irrelevant/incorrect feedback. Proposed corrections are pending confirmation; they do not silently overwrite facts.", {"memory_id": I, "outcome": {"type": "string", "enum": ["useful", "irrelevant", "incorrect"]}, "context": S, "correction": S, "scope": SPACE, "request_id": S}, ["memory_id", "outcome"]),
    _schema("health", "Read deterministic duplicate/conflict candidates, expired sources, stale procedures/summaries and orphaned memories. Semantic conflicts still require Codex review.", {"space": SPACE}),
    _schema("graph", "Read local memory nodes and typed, weighted relation edges for a space or a chosen memory's neighbors.", {"space": SPACE, "memory_id": I, "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}}),
    _schema("maintenance", "Read a maintenance report with health issues, expired open tasks and recent local feature events; performs no maintenance writes.", {"space": SPACE}),
]
