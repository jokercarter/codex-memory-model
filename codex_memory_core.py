"""Shared local storage layer for the Codex memory integration.

This module intentionally uses only Python's standard library so the MCP server
and Codex lifecycle hooks can run without installing extra packages.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


MAX_MEMORIES = 1000
DECAY_INTERVAL_DAYS = 3
IMPORTANCE_MIN = 1
IMPORTANCE_MAX = 100
IMPORTANT_MIN = 67
NORMAL_MIN = 34
RELATION_MIN = 1
RELATION_MAX = 100
RELATION_SEED_LIMIT = 12
RELATION_EXPANSION_LIMIT = 32
CATEGORIES = ["通用", "项目", "技术", "决策", "流程", "偏好", "人物", "其他"]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CodexMemoryVault" / "memory.db"
    return Path.home() / ".codex_memory_vault" / "memory.db"


def connect(path: Path | None = None, read_only: bool = False) -> sqlite3.Connection | None:
    target = path or database_path()
    if read_only:
        if not target.exists():
            return None
        # Open SQLite in URI read-only mode before enabling query_only. This
        # prevents retrieval from creating journals, schema objects, or other
        # database-side write artifacts.
        connection = sqlite3.connect(
            f"{target.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA query_only = ON")
        return connection
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '通用',
            importance INTEGER NOT NULL DEFAULT 50 CHECK (importance BETWEEN 1 AND 100),
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            memory_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            confidence REAL NOT NULL DEFAULT 0.8,
            source_session TEXT NOT NULL DEFAULT '',
            last_reviewed_at TEXT NOT NULL DEFAULT '',
            use_count INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(memories)").fetchall()
    }
    migrations = {
        "memory_key": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "confidence": "REAL NOT NULL DEFAULT 0.8",
        "source_session": "TEXT NOT NULL DEFAULT ''",
        "last_reviewed_at": "TEXT NOT NULL DEFAULT ''",
        "use_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in migrations.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
    _migrate_importance_scale(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_relations (
            memory_a_id INTEGER NOT NULL,
            memory_b_id INTEGER NOT NULL,
            strength INTEGER NOT NULL DEFAULT 20 CHECK (strength BETWEEN 1 AND 100),
            evidence_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_observed_at TEXT NOT NULL,
            PRIMARY KEY (memory_a_id, memory_b_id),
            FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
            CHECK (memory_a_id < memory_b_id)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_relations_a
            ON memory_relations(memory_a_id, strength DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_relations_b
            ON memory_relations(memory_b_id, strength DESC);
        CREATE TABLE IF NOT EXISTS memory_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    _ensure_fts(connection)
    marker = connection.execute(
        "SELECT value FROM memory_metadata WHERE key = 'relations_backfilled_v1'"
    ).fetchone()
    if not marker:
        _backfill_relations(connection)
        connection.execute(
            "INSERT OR REPLACE INTO memory_metadata(key, value) VALUES ('relations_backfilled_v1', '1')"
        )
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_active_updated
            ON memories(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_key
            ON memories(memory_key, status);
        CREATE INDEX IF NOT EXISTS idx_memories_importance
            ON memories(importance DESC, updated_at DESC);
        """
    )
    connection.commit()


def _migrate_importance_scale(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
    ).fetchone()
    schema = str(row[0] or "") if row else ""
    if "BETWEEN 1 AND 5" not in schema:
        return
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(
        """
        CREATE TABLE memories_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '通用',
            importance INTEGER NOT NULL DEFAULT 50 CHECK (importance BETWEEN 1 AND 100),
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            memory_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            confidence REAL NOT NULL DEFAULT 0.8,
            source_session TEXT NOT NULL DEFAULT '',
            last_reviewed_at TEXT NOT NULL DEFAULT '',
            use_count INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.execute(
        """
        INSERT INTO memories_v2
            (id, title, content, tags, category, importance, source,
             created_at, updated_at, memory_key, status, confidence,
             source_session, last_reviewed_at, use_count)
        SELECT id, title, content, tags, category,
               CASE
                   WHEN importance <= 1 THEN 1
                   WHEN importance >= 5 THEN 100
                   ELSE ((importance - 1) * 25) + 1
               END,
               source, created_at, updated_at, memory_key, status, confidence,
               source_session, last_reviewed_at, use_count
          FROM memories
        """
    )
    connection.execute("DROP TABLE memories")
    connection.execute("ALTER TABLE memories_v2 RENAME TO memories")
    connection.execute("PRAGMA foreign_keys = ON")


def _ensure_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
            USING fts5(memory_id UNINDEXED, title, content, tags, source)
            """
        )
        connection.execute("DELETE FROM memory_fts")
        connection.execute(
            """
            INSERT INTO memory_fts(memory_id, title, content, tags, source)
            SELECT CAST(id AS TEXT), title, content, tags, source
              FROM memories
             WHERE status = 'active'
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def _refresh_fts_row(connection: sqlite3.Connection, memory_id: int) -> None:
    try:
        connection.execute(
            "DELETE FROM memory_fts WHERE memory_id = ?", (str(int(memory_id)),)
        )
        connection.execute(
            """
            INSERT INTO memory_fts(memory_id, title, content, tags, source)
            SELECT CAST(id AS TEXT), title, content, tags, source
              FROM memories
             WHERE id = ? AND status = 'active'
            """,
            (int(memory_id),),
        )
    except sqlite3.OperationalError:
        return


def active_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS total FROM memories WHERE status = 'active'"
    ).fetchone()
    return int(row["total"])


def table_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(memories)").fetchall()
    }


def apply_decay(connection: sqlite3.Connection, now: datetime | None = None) -> int:
    """Lower stale memories one point per 3 days without retrieval.

    The last review timestamp is moved forward when a decay step is applied,
    so repeated hook calls do not subtract the same step over and over.
    """
    current = now or datetime.now()
    rows = connection.execute(
        """
        SELECT id, importance, created_at, updated_at, last_reviewed_at
          FROM memories
         WHERE status = 'active' AND importance > 1
        """
    ).fetchall()
    updates: list[tuple[int, str, int]] = []
    for row in rows:
        stamp = str(row["last_reviewed_at"] or row["updated_at"] or row["created_at"] or "")
        try:
            last_seen = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        days = max(0, (current - last_seen).days)
        steps = days // DECAY_INTERVAL_DAYS
        if steps <= 0:
            continue
        new_importance = max(1, int(row["importance"]) - steps)
        if new_importance != int(row["importance"]):
            updates.append((new_importance, current.strftime("%Y-%m-%d %H:%M:%S"), int(row["id"])))
    if updates:
        with connection:
            connection.executemany(
                "UPDATE memories SET importance = ?, last_reviewed_at = ? WHERE id = ? AND status = 'active'",
                updates,
            )
    return len(updates)


def stats(connection: sqlite3.Connection | None, mutate: bool = True) -> dict[str, int]:
    if connection is None:
        return {
            "active": 0,
            "obsolete": 0,
            "capacity": MAX_MEMORIES,
            "remaining": MAX_MEMORIES,
            "decay_interval_days": DECAY_INTERVAL_DAYS,
            "important": 0,
            "normal": 0,
            "unimportant": 0,
        }
    columns = table_columns(connection)
    if not columns:
        return {
            "active": 0,
            "obsolete": 0,
            "capacity": MAX_MEMORIES,
            "remaining": MAX_MEMORIES,
            "decay_interval_days": DECAY_INTERVAL_DAYS,
            "important": 0,
            "normal": 0,
            "unimportant": 0,
        }
    extended = "status" in columns
    if mutate and extended:
        apply_decay(connection)
    if extended:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS total FROM memories GROUP BY status"
        ).fetchall()
        counts = {str(row["status"]): int(row["total"]) for row in rows}
    else:
        total = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        counts = {"active": total, "obsolete": 0}
    counts.setdefault("active", 0)
    counts.setdefault("obsolete", 0)
    counts["capacity"] = MAX_MEMORIES
    counts["remaining"] = max(0, MAX_MEMORIES - counts["active"])
    counts["decay_interval_days"] = DECAY_INTERVAL_DAYS
    def count_where(condition: str) -> int:
        prefix = "status = 'active' AND " if extended else ""
        row = connection.execute(
            f"SELECT COUNT(*) FROM memories WHERE {prefix}{condition}"
        ).fetchone()
        return int(row[0])

    counts["important"] = count_where(f"importance >= {IMPORTANT_MIN}")
    counts["normal"] = count_where(
        f"importance >= {NORMAL_MIN} AND importance < {IMPORTANT_MIN}"
    )
    counts["unimportant"] = count_where(f"importance < {NORMAL_MIN}")
    return counts


def normalize_key(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    cleaned = re.sub(r"[^\w\u4e00-\u9fff .:/-]", "", cleaned)
    return cleaned[:160]


def fallback_key(title: str, content: str) -> str:
    title_key = normalize_key(title)
    if title_key:
        return title_key
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
    return f"memory-{digest}"


def _terms(query: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_./:-]{2,}|[\u4e00-\u9fff]{2,}", query.lower())
    terms: list[str] = []
    for value in raw:
        if value not in terms:
            terms.append(value)
    if not terms and query.strip():
        terms.append(query.strip().lower())
    return terms[:16]


def _fts_seed_ids(
    connection: sqlite3.Connection,
    terms: list[str],
    limit: int,
) -> list[int]:
    if not terms:
        return []
    expression = " OR ".join(
        '"' + term.replace('"', '""') + '"' for term in terms
    )
    try:
        rows = connection.execute(
            """
            SELECT CAST(memory_id AS INTEGER) AS id
              FROM memory_fts
             WHERE memory_fts MATCH ?
             LIMIT ?
            """,
            (expression, max(1, int(limit))),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [int(row["id"]) for row in rows]


def _relation_neighbors(
    connection: sqlite3.Connection,
    memory_ids: Iterable[int],
    limit: int,
) -> dict[int, int]:
    ids = sorted({int(value) for value in memory_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = connection.execute(
            f"""
            SELECT CASE
                       WHEN memory_a_id IN ({placeholders}) THEN memory_b_id
                       ELSE memory_a_id
                   END AS neighbor_id,
                   MAX(strength) AS strength
              FROM memory_relations
             WHERE memory_a_id IN ({placeholders})
                OR memory_b_id IN ({placeholders})
             GROUP BY neighbor_id
             ORDER BY strength DESC, neighbor_id
             LIMIT ?
            """,
            [*ids, *ids, *ids, int(max(1, limit))],
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {int(row["neighbor_id"]): int(row["strength"]) for row in rows}


def _upsert_relation(
    connection: sqlite3.Connection,
    first_id: int,
    second_id: int,
    strength: int,
    *,
    evidence_increment: int = 1,
    timestamp: str | None = None,
) -> None:
    if first_id == second_id:
        return
    memory_a_id, memory_b_id = sorted((int(first_id), int(second_id)))
    strength = max(RELATION_MIN, min(RELATION_MAX, int(strength)))
    stamp = timestamp or now_text()
    connection.execute(
        """
        INSERT INTO memory_relations
            (memory_a_id, memory_b_id, strength, evidence_count,
             created_at, updated_at, last_observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_a_id, memory_b_id) DO UPDATE SET
            strength = MIN(100, MAX(memory_relations.strength, excluded.strength)),
            evidence_count = memory_relations.evidence_count + excluded.evidence_count,
            updated_at = excluded.updated_at,
            last_observed_at = excluded.last_observed_at
        """,
        (
            memory_a_id,
            memory_b_id,
            strength,
            max(1, int(evidence_increment)),
            stamp,
            stamp,
            stamp,
        ),
    )


def _link_new_memory(
    connection: sqlite3.Connection,
    memory_id: int,
    *,
    category: str,
    tags: str,
    title: str,
    content: str,
    timestamp: str,
) -> None:
    terms = set(_terms(f"{title} {content} {tags}"))
    rows = connection.execute(
        """
        SELECT id, category, tags, title, content
          FROM memories
         WHERE status = 'active' AND id <> ?
         ORDER BY updated_at DESC, id DESC
         LIMIT 200
        """,
        (int(memory_id),),
    ).fetchall()
    candidates: list[tuple[int, int]] = []
    new_tags = {value.strip().lower() for value in tags.split(",") if value.strip()}
    for row in rows:
        other_terms = set(_terms(f"{row['title']} {row['content']} {row['tags']}"))
        shared_terms = len(terms & other_terms)
        other_tags = {
            value.strip().lower()
            for value in str(row["tags"]).split(",")
            if value.strip()
        }
        strength = (20 if str(row["category"]) == category else 0)
        strength += min(30, len(new_tags & other_tags) * 15)
        strength += min(30, shared_terms * 10)
        if strength >= 20:
            candidates.append((strength, int(row["id"])))
    for strength, other_id in sorted(candidates, reverse=True)[:8]:
        _upsert_relation(connection, memory_id, other_id, strength, timestamp=timestamp)


def _backfill_relations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT id, category, tags, title, content
          FROM memories
         WHERE status = 'active'
         ORDER BY id
        """
    ).fetchall()
    for row in rows:
        _link_new_memory(
            connection,
            int(row["id"]),
            category=str(row["category"]),
            tags=str(row["tags"]),
            title=str(row["title"]),
            content=str(row["content"]),
            timestamp=now_text(),
        )


def search(
    connection: sqlite3.Connection | None,
    query: str = "",
    limit: int = 8,
    category: str = "",
    min_importance: int = 0,
    track_usage: bool = True,
    mutate: bool = True,
) -> list[sqlite3.Row]:
    if connection is None:
        return []
    columns = table_columns(connection)
    if not columns:
        return []
    extended = "status" in columns
    if mutate and extended:
        apply_decay(connection)
    limit = max(1, min(int(limit), 30))
    clauses = ["status = 'active'"] if extended else []
    params: list[object] = []
    if category and category in CATEGORIES:
        clauses.append("category = ?")
        params.append(category)
    if min_importance:
        clauses.append("importance >= ?")
        params.append(max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(min_importance))))
    extra_columns = (
        "memory_key, confidence, use_count"
        if extended
        else "'' AS memory_key, 0.8 AS confidence, 0 AS use_count"
    )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query_lower = query.strip().lower()
    terms = _terms(query_lower)
    seed_limit = max(RELATION_SEED_LIMIT, limit * 2)
    if query_lower:
        seed_ids = _fts_seed_ids(connection, terms, seed_limit)
        if not seed_ids:
            like_clauses: list[str] = []
            like_params: list[object] = []
            for term in terms[:8]:
                like = f"%{term}%"
                like_clauses.append(
                    "(title LIKE ? OR content LIKE ? OR tags LIKE ? OR source LIKE ?)"
                )
                like_params.extend([like, like, like, like])
            fallback_where = [*clauses, f"({' OR '.join(like_clauses)})"]
            fallback_rows = connection.execute(
                f"""
                SELECT id
                  FROM memories
                 WHERE {' AND '.join(fallback_where)}
                 ORDER BY importance DESC, updated_at DESC, id DESC
                 LIMIT ?
                """,
                [*params, *like_params, seed_limit],
            ).fetchall()
            seed_ids = [int(row["id"]) for row in fallback_rows]
    else:
        seed_rows = connection.execute(
            f"""
            SELECT id
              FROM memories
             {where}
             ORDER BY importance DESC, updated_at DESC, id DESC
             LIMIT ?
            """,
            [*params, seed_limit],
        ).fetchall()
        seed_ids = [int(row["id"]) for row in seed_rows]
    relation_strengths = _relation_neighbors(
        connection, seed_ids, RELATION_EXPANSION_LIMIT
    )
    candidate_ids = list(dict.fromkeys([*seed_ids, *relation_strengths]))
    if not candidate_ids:
        return []
    id_placeholders = ",".join("?" for _ in candidate_ids)
    candidate_clauses = [f"id IN ({id_placeholders})"]
    candidate_params: list[object] = [*candidate_ids]
    if extended:
        candidate_clauses.append("status = 'active'")
    if category and category in CATEGORIES:
        candidate_clauses.append("category = ?")
        candidate_params.append(category)
    if min_importance:
        candidate_clauses.append("importance >= ?")
        candidate_params.append(max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(min_importance))))
    rows = connection.execute(
        f"""
        SELECT id, title, content, tags, category, importance, source,
               created_at, updated_at, {extra_columns}
          FROM memories
         WHERE {' AND '.join(candidate_clauses)}
        """,
        candidate_params,
    ).fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        title = str(row["title"]).lower()
        content = str(row["content"]).lower()
        tags = str(row["tags"]).lower()
        source = str(row["source"]).lower()
        row_id = int(row["id"])
        score = float(row["importance"]) * 0.6 + float(row["confidence"] or 0.0) * 10.0
        if row_id in relation_strengths:
            score += float(relation_strengths[row_id]) * 0.5
        if not query_lower:
            score += min(float(row["use_count"] or 0), 10.0) * 0.03
        else:
            if query_lower in title:
                score += 20
            if query_lower in content:
                score += 8
            if query_lower in tags:
                score += 10
            for term in terms:
                if term in title:
                    score += 7
                if term in content:
                    score += 2
                if term in tags:
                    score += 4
                if term in source:
                    score += 1
        scored.append((score, row))
    scored.sort(key=lambda item: (item[0], item[1]["updated_at"], item[1]["id"]), reverse=True)
    chosen = [row for _score, row in scored[:limit]]
    if chosen and track_usage and mutate:
        timestamp = now_text()
        with connection:
            connection.executemany(
                """
                UPDATE memories
                   SET use_count = use_count + 1,
                       importance = CASE
                           WHEN ((use_count + 1) % 3 = 0 AND importance < 100)
                           THEN importance + 1
                           ELSE importance
                       END,
                       last_reviewed_at = ?
                 WHERE id = ? AND status = 'active'
                """,
                [(timestamp, int(row["id"])) for row in chosen],
            )
            refreshed = connection.execute(
                f"SELECT id, title, content, tags, category, importance, source, created_at, updated_at, memory_key, confidence, use_count FROM memories WHERE id IN ({','.join('?' for _ in chosen)}) AND status = 'active'",
                [int(row["id"]) for row in chosen],
            ).fetchall()
        by_id = {int(row["id"]): row for row in refreshed}
        chosen = [by_id[int(row["id"])] for row in chosen if int(row["id"]) in by_id]
    return chosen


def get(connection: sqlite3.Connection, memory_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM memories WHERE id = ?", (int(memory_id),)
    ).fetchone()


def related(
    connection: sqlite3.Connection | None,
    memory_id: int,
    limit: int = 10,
) -> list[sqlite3.Row]:
    if connection is None:
        return []
    try:
        return connection.execute(
            """
            SELECT CASE
                       WHEN r.memory_a_id = ? THEN r.memory_b_id
                       ELSE r.memory_a_id
                   END AS id,
                   m.title, m.content, m.tags, m.category, m.importance,
                   m.source, m.created_at, m.updated_at, m.memory_key,
                   m.confidence, m.use_count,
                   r.strength AS relation_strength,
                   r.evidence_count, r.last_observed_at
              FROM memory_relations AS r
              JOIN memories AS m
                ON m.id = CASE
                              WHEN r.memory_a_id = ? THEN r.memory_b_id
                              ELSE r.memory_a_id
                          END
             WHERE (r.memory_a_id = ? OR r.memory_b_id = ?)
               AND m.status = 'active'
             ORDER BY r.strength DESC, r.evidence_count DESC, m.id
             LIMIT ?
            """,
            (
                int(memory_id),
                int(memory_id),
                int(memory_id),
                int(memory_id),
                max(1, min(30, int(limit))),
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def mark_used(
    connection: sqlite3.Connection,
    memory_ids: Iterable[int],
    source_session: str = "",
) -> int:
    """Record deliberate post-turn use without involving any other app."""
    apply_decay(connection)
    ids = sorted({int(value) for value in memory_ids})
    if not ids:
        return 0
    timestamp = now_text()
    with connection:
        connection.executemany(
            """
            UPDATE memories
               SET use_count = use_count + 1,
                   importance = CASE
                       WHEN ((use_count + 1) % 3 = 0 AND importance < 100)
                       THEN importance + 1
                       ELSE importance
                   END,
                   last_reviewed_at = ?, source_session = ?
             WHERE id = ? AND status = 'active'
            """,
            [(timestamp, source_session, memory_id) for memory_id in ids],
        )
        row = connection.execute(
            f"SELECT COUNT(*) AS total FROM memories WHERE status = 'active' AND id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchone()
        for index, first_id in enumerate(ids):
            for second_id in ids[index + 1 :]:
                existing = connection.execute(
                    """
                    SELECT strength FROM memory_relations
                     WHERE memory_a_id = ? AND memory_b_id = ?
                    """,
                    tuple(sorted((first_id, second_id))),
                ).fetchone()
                current_strength = int(existing["strength"]) if existing else 15
                _upsert_relation(
                    connection,
                    first_id,
                    second_id,
                    min(RELATION_MAX, current_strength + 10),
                    evidence_increment=1,
                    timestamp=timestamp,
                )
    return int(row["total"])


def retire(
    connection: sqlite3.Connection,
    memory_ids: Iterable[int],
    reason: str = "",
    source_session: str = "",
) -> int:
    apply_decay(connection)
    ids = sorted({int(value) for value in memory_ids})
    if not ids:
        return 0
    timestamp = now_text()
    updated = 0
    with connection:
        for memory_id in ids:
            row = connection.execute(
                "SELECT id, content, source FROM memories WHERE id = ? AND status = 'active'",
                (memory_id,),
            ).fetchone()
            if not row:
                continue
            note = f"\n\n[已淘汰原因] {reason.strip()}" if reason.strip() else ""
            connection.execute(
                """
                UPDATE memories
                   SET status = 'obsolete', content = ?, updated_at = ?,
                       last_reviewed_at = ?, source_session = ?
                 WHERE id = ?
                """,
                (
                    str(row["content"]) + note,
                    timestamp,
                    timestamp,
                    source_session,
                    memory_id,
                ),
            )
            _refresh_fts_row(connection, memory_id)
            updated += 1
    return updated


def infer_importance(title: str, content: str, category: str, confidence: float) -> int:
    """Choose a reasonable initial level when the curator omits one.

    The Codex curation instructions ask the model to choose the level itself;
    this conservative heuristic is only a fallback for an omitted field.
    """
    score = 50
    if category in {"决策", "项目", "流程"}:
        score += 12
    durable_signals = ("必须", "始终", "长期", "约定", "规范", "架构", "安全", "接口")
    temporary_signals = ("临时", "待确认", "草稿", "猜测", "可能", "今天", "当前")
    if any(signal in title or signal in content for signal in durable_signals):
        score += 15
    if any(signal in title or signal in content for signal in temporary_signals):
        score -= 15
    if confidence < 0.65:
        score -= 10
    return max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, score))


def commit_memory(
    connection: sqlite3.Connection,
    *,
    title: str,
    content: str,
    category: str = "通用",
    importance: int | None = None,
    tags: str = "",
    source: str = "",
    memory_key: str = "",
    confidence: float = 0.8,
    replace_ids: Iterable[int] = (),
    obsolete_ids: Iterable[int] = (),
    source_session: str = "",
) -> dict[str, object]:
    title = str(title).strip()
    content = str(content).strip()
    if not title or not content:
        raise ValueError("title 和 content 不能为空")
    apply_decay(connection)
    category = category if category in CATEGORIES else "其他"
    importance_value = (
        None
        if importance is None
        else max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(importance)))
    )
    confidence = max(0.0, min(1.0, float(confidence)))
    tags = str(tags).strip()
    source = str(source).strip()
    memory_key = normalize_key(memory_key) or fallback_key(title, content)
    replace_list = sorted({int(value) for value in replace_ids})
    obsolete_list = sorted({int(value) for value in obsolete_ids})
    timestamp = now_text()

    with connection:
        for memory_id in obsolete_list:
            if memory_id not in replace_list:
                connection.execute(
                    """
                    UPDATE memories
                       SET status = 'obsolete', updated_at = ?, last_reviewed_at = ?,
                           source_session = ?
                     WHERE id = ? AND status = 'active'
                    """,
                    (timestamp, timestamp, source_session, memory_id),
                )

        target_id: int | None = None
        for memory_id in replace_list:
            row = connection.execute(
                "SELECT id FROM memories WHERE id = ? AND status = 'active'",
                (memory_id,),
            ).fetchone()
            if row:
                target_id = int(row["id"])
                break
        if target_id is None:
            row = connection.execute(
                "SELECT id FROM memories WHERE memory_key = ? AND status = 'active' ORDER BY id LIMIT 1",
                (memory_key,),
            ).fetchone()
            if row:
                target_id = int(row["id"])
        if target_id is None:
            row = connection.execute(
                "SELECT id FROM memories WHERE title = ? AND status = 'active' ORDER BY id LIMIT 1",
                (title,),
            ).fetchone()
            if row:
                target_id = int(row["id"])

        if target_id is not None:
            existing_row = connection.execute(
                "SELECT importance FROM memories WHERE id = ?",
                (target_id,),
            ).fetchone()
            update_importance = (
                importance_value
                if importance_value is not None
                else int(existing_row["importance"] if existing_row else 3)
            )
            connection.execute(
                """
                UPDATE memories
                   SET title = ?, content = ?, tags = ?, category = ?, importance = ?,
                       source = ?, updated_at = ?, memory_key = ?, status = 'active',
                       confidence = ?, source_session = ?, last_reviewed_at = ?
                 WHERE id = ?
                """,
                (
                    title,
                    content,
                    tags,
                    category,
                    update_importance,
                    source,
                    timestamp,
                    memory_key,
                    confidence,
                    source_session,
                    timestamp,
                    target_id,
                ),
            )
            _link_new_memory(
                connection,
                target_id,
                category=category,
                tags=tags,
                title=title,
                content=content,
                timestamp=timestamp,
            )
            _refresh_fts_row(connection, target_id)
            for memory_id in replace_list:
                if memory_id != target_id:
                    connection.execute(
                        "UPDATE memories SET status = 'obsolete', updated_at = ?, last_reviewed_at = ?, source_session = ? WHERE id = ? AND status = 'active'",
                        (timestamp, timestamp, source_session, memory_id),
                    )
            return {"operation": "updated", "id": target_id, "memory_key": memory_key}

        if active_count(connection) >= MAX_MEMORIES:
            raise ValueError(
                f"记忆库已达到 {MAX_MEMORIES} 条，请通过 replace_ids 或 obsolete_ids 替换低价值记录后再添加"
            )
        new_importance = importance_value if importance_value is not None else infer_importance(
            title, content, category, confidence
        )
        cursor = connection.execute(
            """
            INSERT INTO memories
                (title, content, tags, category, importance, source,
                 created_at, updated_at, memory_key, status, confidence,
                 source_session, last_reviewed_at, use_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, 0)
            """,
            (
                title,
                content,
                tags,
                category,
                new_importance,
                source,
                timestamp,
                timestamp,
                memory_key,
                confidence,
                source_session,
                timestamp,
            ),
        )
        new_id = int(cursor.lastrowid)
        _link_new_memory(
            connection,
            new_id,
            category=category,
            tags=tags,
            title=title,
            content=content,
            timestamp=timestamp,
        )
        _refresh_fts_row(connection, new_id)
        return {"operation": "created", "id": new_id, "memory_key": memory_key}


def format_context(rows: Iterable[sqlite3.Row], *, heading: str = "Codex 记忆库检索结果") -> str:
    rows = list(rows)
    if not rows:
        return (
            "Codex 记忆库已连接，但当前没有匹配的长期记忆。\n"
            "只在本轮产生已确认、长期可复用的信息时写入记忆。"
        )
    parts = [heading + "（仅作参考；若与当前用户明确要求冲突，以当前要求为准）："]
    for row in rows:
        content = str(row["content"]).strip()
        if len(content) > 900:
            content = content[:897] + "…"
        importance = int(row["importance"])
        level = (
            "重要"
            if importance >= IMPORTANT_MIN
            else ("不重要" if importance < NORMAL_MIN else "普通")
        )
        parts.append(
            f"- [记忆 #{row['id']}] {row['title']} | 分类={row['category']} | 重要度={level}（{importance}/100） | 使用次数={row['use_count']} | 置信度={float(row['confidence'] or 0):.2f}\n"
            f"  {content}\n"
            f"  标签：{row['tags'] or '无'}"
        )
    return "\n".join(parts)
