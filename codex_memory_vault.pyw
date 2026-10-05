"""Codex 记忆库

一个只依赖 Python 标准库的本地桌面记忆库。数据保存在 SQLite 中，
默认位置为 %LOCALAPPDATA%\\CodexMemoryVault\\memory.db。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from codex_memory_core import apply_decay as core_apply_decay
from codex_memory_core import ensure_schema as ensure_core_schema


MAX_MEMORIES = 1000
DECAY_INTERVAL_DAYS = 3
IMPORTANCE_MIN = 1
IMPORTANCE_MAX = 100
IMPORTANT_MIN = 67
NORMAL_MIN = 34
APP_TITLE = "Codex 记忆库"
CATEGORIES = ["通用", "项目", "技术", "决策", "流程", "偏好", "人物", "其他"]
IMPORTANCE_VALUES = [str(value) for value in range(100, 0, -1)]
IMPORTANCE_FILTER_VALUES = ["全部", "重要", "普通", "不重要", *IMPORTANCE_VALUES]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def importance_level(value: int) -> str:
    value = int(value)
    if value >= IMPORTANT_MIN:
        return "重要"
    if value < NORMAL_MIN:
        return "不重要"
    return "普通"


def data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CodexMemoryVault"
    return Path.home() / ".codex_memory_vault"


class MemoryDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        ensure_core_schema(self.connection)
        self.connection.commit()
        self.apply_decay()

    def apply_decay(self) -> int:
        return core_apply_decay(self.connection)

    def count(self) -> int:
        self.apply_decay()
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM memories WHERE status = 'active'"
        ).fetchone()
        return int(row["total"])

    def list_memories(
        self,
        query: str = "",
        category: str = "全部",
        importance: str = "全部",
    ) -> list[sqlite3.Row]:
        self.apply_decay()
        clauses: list[str] = ["status = 'active'"]
        params: list[object] = []
        if query.strip():
            like = f"%{query.strip()}%"
            clauses.append(
                "(title LIKE ? OR content LIKE ? OR tags LIKE ? OR source LIKE ?)"
            )
            params.extend([like, like, like, like])
        if category and category != "全部":
            clauses.append("category = ?")
            params.append(category)
        if importance and importance != "全部":
            if importance == "重要":
                clauses.append(f"importance >= {IMPORTANT_MIN}")
            elif importance == "普通":
                clauses.append(f"importance >= {NORMAL_MIN} AND importance < {IMPORTANT_MIN}")
            elif importance == "不重要":
                clauses.append(f"importance < {NORMAL_MIN}")
            else:
                clauses.append("importance = ?")
                params.append(int(importance))
        where = f"WHERE {' AND '.join(clauses)}"
        return self.connection.execute(
            f"""
            SELECT id, title, content, tags, category, importance, source,
                   created_at, updated_at, use_count
              FROM memories
              {where}
             ORDER BY importance DESC, updated_at DESC, id DESC
            """,
            params,
        ).fetchall()

    def get(self, memory_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    def add(self, values: dict[str, object]) -> int:
        if self.count() >= MAX_MEMORIES:
            raise ValueError(f"记忆库已达到 {MAX_MEMORIES} 条上限")
        timestamp = now_text()
        memory_key = str(values.get("memory_key", values["title"])).strip()
        cursor = self.connection.execute(
            """
            INSERT INTO memories
                (title, content, tags, category, importance, source, created_at, updated_at,
                 memory_key, status, confidence, source_session, last_reviewed_at, use_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, 0)
            """,
            (
                values["title"],
                values["content"],
                values.get("tags", ""),
                values.get("category", "通用"),
                max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(values.get("importance", 50)))),
                values.get("source", ""),
                timestamp,
                timestamp,
                memory_key,
                float(values.get("confidence", 0.8)),
                str(values.get("source_session", "")),
                timestamp,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update(self, memory_id: int, values: dict[str, object]) -> None:
        self.connection.execute(
            """
            UPDATE memories
               SET title = ?, content = ?, tags = ?, category = ?, importance = ?,
                   source = ?, updated_at = ?, memory_key = ?, status = 'active',
                   confidence = ?, source_session = ?, last_reviewed_at = ?
             WHERE id = ?
            """,
            (
                values["title"],
                values["content"],
                values.get("tags", ""),
                values.get("category", "通用"),
                max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(values.get("importance", 50)))),
                values.get("source", ""),
                now_text(),
                str(values.get("memory_key", values["title"])).strip(),
                float(values.get("confidence", 0.8)),
                str(values.get("source_session", "")),
                now_text(),
                memory_id,
            ),
        )
        self.connection.commit()

    def delete(self, memory_id: int) -> None:
        self.connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.connection.commit()

    def export_json(self, path: Path) -> int:
        rows = self.connection.execute(
            """
            SELECT id, title, content, tags, category, importance, source,
                   created_at, updated_at, memory_key, confidence,
                   source_session, last_reviewed_at
              FROM memories
             WHERE status = 'active'
             ORDER BY importance DESC, updated_at DESC, id DESC
            """
        ).fetchall()
        relation_rows = self.connection.execute(
            """
            SELECT memory_a_id, memory_b_id, strength, evidence_count,
                   created_at, updated_at, last_observed_at
              FROM memory_relations
             ORDER BY memory_a_id, memory_b_id
            """
        ).fetchall()
        payload = {
            "format": "codex-memory-v2",
            "exported_at": now_text(),
            "max_memories": MAX_MEMORIES,
            "memories": [dict(row) for row in rows],
            "relations": [dict(row) for row in relation_rows],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)

    def import_json(self, path: Path) -> tuple[int, int, int]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            source_items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("memories"), list):
            source_items = payload["memories"]
        else:
            raise ValueError("JSON 格式不正确：需要数组，或包含 memories 数组的对象")

        existing = {
            (row["title"].strip(), row["content"].strip()): int(row["id"])
            for row in self.connection.execute(
                "SELECT id, title, content FROM memories WHERE status = 'active'"
            )
        }
        source_relations = (
            payload.get("relations", [])
            if isinstance(payload, dict) and isinstance(payload.get("relations"), list)
            else []
        )
        id_map: dict[int, int] = {}
        added = skipped = invalid = 0
        remaining = max(0, MAX_MEMORIES - self.count())
        timestamp = now_text()
        with self.connection:
            for item in source_items:
                if not isinstance(item, dict):
                    invalid += 1
                    continue
                title = str(item.get("title", "")).strip()
                content = str(item.get("content", "")).strip()
                if not title or not content:
                    invalid += 1
                    continue
                identity = (title, content)
                if identity in existing:
                    try:
                        id_map[int(item.get("id"))] = existing[identity]
                    except (TypeError, ValueError):
                        pass
                    skipped += 1
                    continue
                if added >= remaining:
                    skipped += 1
                    continue
                try:
                    importance = max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(item.get("importance", 50))))
                except (TypeError, ValueError):
                    importance = 50
                category = str(item.get("category", "通用")).strip() or "通用"
                if category not in CATEGORIES:
                    category = "其他"
                try:
                    confidence = max(0.0, min(1.0, float(item.get("confidence", 0.8))))
                except (TypeError, ValueError):
                    confidence = 0.8
                cursor = self.connection.execute(
                    """
                    INSERT INTO memories
                        (title, content, tags, category, importance, source, created_at, updated_at,
                         memory_key, status, confidence, source_session, last_reviewed_at, use_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, 0)
                    """,
                    (
                        title,
                        content,
                        str(item.get("tags", "")).strip(),
                        category,
                        importance,
                        str(item.get("source", "")).strip(),
                        str(item.get("created_at", timestamp)),
                        str(item.get("updated_at", timestamp)),
                        str(item.get("memory_key", item.get("title", ""))).strip(),
                        confidence,
                        str(item.get("source_session", "")).strip(),
                        str(item.get("last_reviewed_at", timestamp)),
                    ),
                )
                new_id = int(cursor.lastrowid)
                existing[identity] = new_id
                try:
                    id_map[int(item.get("id"))] = new_id
                except (TypeError, ValueError):
                    pass
                added += 1
            for item in source_relations:
                if not isinstance(item, dict):
                    continue
                try:
                    first_id = id_map[int(item["memory_a_id"])]
                    second_id = id_map[int(item["memory_b_id"])]
                    strength = max(1, min(100, int(item.get("strength", 20))))
                    evidence = max(1, int(item.get("evidence_count", 1)))
                except (KeyError, TypeError, ValueError):
                    continue
                if first_id == second_id:
                    continue
                first_id, second_id = sorted((first_id, second_id))
                stamp = str(item.get("updated_at", timestamp))
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO memory_relations
                        (memory_a_id, memory_b_id, strength, evidence_count,
                         created_at, updated_at, last_observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        first_id,
                        second_id,
                        strength,
                        evidence,
                        str(item.get("created_at", stamp)),
                        stamp,
                        str(item.get("last_observed_at", stamp)),
                    ),
                )
        return added, skipped, invalid

    def close(self) -> None:
        self.connection.close()


class MemoryApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} · 1000 条本地记忆")
        self.root.geometry("1180x760")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.db = MemoryDB(data_directory() / "memory.db")
        self.current_id: int | None = None
        self._build_style()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.refresh_list()
        self.new_memory()

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Subtitle.TLabel", foreground="#5f6368")
        style.configure("Count.TLabel", foreground="#1a73e8", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="新建记忆", command=self.new_memory, accelerator="Ctrl+N")
        file_menu.add_command(label="保存记忆", command=self.save_memory, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="导入 JSON…", command=self.import_json)
        file_menu.add_command(label="导出 JSON…", command=self.export_json)
        file_menu.add_command(label="打开数据文件夹", command=self.open_data_directory)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.close)
        menu.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="关于", command=self.show_about)
        menu.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menu)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(18, 14, 18, 12))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Codex 记忆库", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="把重要信息整理成可检索、可维护的长期记忆",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(5, 0))
        self.count_label = ttk.Label(header, style="Count.TLabel")
        self.count_label.pack(side="right", pady=(5, 0))

        filters = ttk.LabelFrame(outer, text="检索与筛选", padding=(10, 8))
        filters.pack(fill="x", pady=(0, 12))
        ttk.Label(filters, text="关键词").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(filters, textvariable=self.search_var, width=34)
        search_entry.pack(side="left", padx=(6, 12))
        search_entry.bind("<Return>", lambda _event: self.refresh_list())
        ttk.Label(filters, text="分类").pack(side="left")
        self.category_filter = ttk.Combobox(
            filters, values=["全部", *CATEGORIES], state="readonly", width=10
        )
        self.category_filter.set("全部")
        self.category_filter.pack(side="left", padx=(6, 12))
        ttk.Label(filters, text="重要度").pack(side="left")
        self.importance_filter = ttk.Combobox(
            filters, values=IMPORTANCE_FILTER_VALUES, state="readonly", width=9
        )
        self.importance_filter.set("全部")
        self.importance_filter.pack(side="left", padx=(6, 12))
        ttk.Button(filters, text="搜索", command=self.refresh_list).pack(side="left")
        ttk.Button(filters, text="清空筛选", command=self.clear_filters).pack(side="left", padx=(6, 0))
        ttk.Button(filters, text="导入 JSON", command=self.import_json).pack(side="right")
        ttk.Button(filters, text="导出 JSON", command=self.export_json).pack(side="right", padx=(0, 6))

        splitter = ttk.Panedwindow(outer, orient="horizontal")
        splitter.pack(fill="both", expand=True)

        left = ttk.Frame(splitter, padding=(0, 0, 10, 0))
        right = ttk.Frame(splitter, padding=(10, 0, 0, 0))
        splitter.add(left, weight=5)
        splitter.add(right, weight=6)

        list_header = ttk.Frame(left)
        list_header.pack(fill="x", pady=(0, 6))
        ttk.Label(list_header, text="记忆列表", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(list_header, text="可多选后合并", style="Subtitle.TLabel").pack(side="right")

        table_frame = ttk.Frame(left)
        table_frame.pack(fill="both", expand=True)
        columns = ("id", "title", "category", "importance", "uses", "updated")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {"id": "编号", "title": "标题", "category": "分类", "importance": "重要度", "uses": "使用次数", "updated": "更新时间"}
        widths = {"id": 55, "title": 210, "category": 75, "importance": 110, "uses": 75, "updated": 145}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center" if column != "title" else "w")
        self.tree.column("title", stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        list_buttons = ttk.Frame(left)
        list_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(list_buttons, text="新建", command=self.new_memory).pack(side="left")
        ttk.Button(list_buttons, text="合并选中", command=self.merge_selected).pack(side="left", padx=(6, 0))
        ttk.Button(list_buttons, text="删除选中", command=self.delete_selected).pack(side="right")

        editor_title = ttk.Frame(right)
        editor_title.pack(fill="x", pady=(0, 6))
        ttk.Label(editor_title, text="记忆编辑器", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.mode_label = ttk.Label(editor_title, style="Subtitle.TLabel")
        self.mode_label.pack(side="right")

        form = ttk.Frame(right)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="标题 *").grid(row=0, column=0, sticky="w", pady=(3, 7))
        self.title_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.title_var).grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 7))
        ttk.Label(form, text="分类").grid(row=1, column=0, sticky="w", pady=(0, 7))
        self.category_var = tk.StringVar(value="通用")
        ttk.Combobox(form, textvariable=self.category_var, values=CATEGORIES, state="readonly", width=12).grid(
            row=1, column=1, sticky="w", pady=(0, 7)
        )
        ttk.Label(form, text="重要度（1-100）").grid(row=1, column=2, sticky="w", padx=(18, 0), pady=(0, 7))
        self.importance_var = tk.StringVar(value="50")
        ttk.Combobox(form, textvariable=self.importance_var, values=IMPORTANCE_VALUES, state="readonly", width=8).grid(
            row=1, column=3, sticky="w", pady=(0, 7)
        )
        ttk.Label(form, text="标签").grid(row=2, column=0, sticky="w", pady=(0, 7))
        self.tags_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tags_var).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(0, 7))
        ttk.Label(form, text="来源").grid(row=3, column=0, sticky="w", pady=(0, 7))
        self.source_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.source_var).grid(row=3, column=1, columnspan=3, sticky="ew", pady=(0, 7))
        ttk.Label(form, text="整合后的内容 *").grid(row=4, column=0, sticky="nw", pady=(3, 5))
        self.content_text = tk.Text(
            form,
            height=16,
            wrap="word",
            undo=True,
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=8,
        )
        self.content_text.grid(row=4, column=1, columnspan=3, sticky="nsew", pady=(0, 7))
        content_scrollbar = ttk.Scrollbar(form, orient="vertical", command=self.content_text.yview)
        content_scrollbar.grid(row=4, column=4, sticky="ns", pady=(0, 7))
        self.content_text.configure(yscrollcommand=content_scrollbar.set)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=1)
        form.columnconfigure(3, weight=1)
        form.rowconfigure(4, weight=1)

        editor_buttons = ttk.Frame(right)
        editor_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(editor_buttons, text="保存记忆", style="Primary.TButton", command=self.save_memory).pack(side="left")
        ttk.Button(editor_buttons, text="清空编辑器", command=self.new_memory).pack(side="left", padx=(7, 0))
        self.status_var = tk.StringVar(value=f"数据文件：{self.db.path}")
        ttk.Label(right, textvariable=self.status_var, style="Subtitle.TLabel").pack(fill="x", pady=(10, 0))

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-n>", lambda _event: self.new_memory())
        self.root.bind("<Control-s>", lambda _event: self.save_memory())
        self.root.bind("<Control-f>", lambda _event: self.focus_search())

    def focus_search(self) -> None:
        for child in self.root.winfo_children():
            self._focus_search_in(child)

    def _focus_search_in(self, widget: tk.Misc) -> bool:
        if isinstance(widget, ttk.Entry) and str(widget.cget("textvariable")) == str(self.search_var):
            widget.focus_set()
            widget.selection_range(0, "end")
            return True
        for child in widget.winfo_children():
            if self._focus_search_in(child):
                return True
        return False

    def refresh_count(self) -> None:
        total = self.db.count()
        tier_rows = self.db.connection.execute(
            """
            SELECT
                SUM(CASE WHEN importance >= 67 THEN 1 ELSE 0 END) AS important,
                SUM(CASE WHEN importance >= 34 AND importance < 67 THEN 1 ELSE 0 END) AS normal,
                SUM(CASE WHEN importance < 34 THEN 1 ELSE 0 END) AS unimportant
              FROM memories
             WHERE status = 'active'
            """
        ).fetchone()
        self.count_label.configure(
            text=(
                f"{total} / {MAX_MEMORIES} 条 · 重要 {int(tier_rows['important'] or 0)} · "
                f"普通 {int(tier_rows['normal'] or 0)} · 不重要 {int(tier_rows['unimportant'] or 0)}"
            )
        )

    def refresh_list(self, _event: object | None = None) -> None:
        selected_id = self.current_id
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = self.db.list_memories(
            self.search_var.get(), self.category_filter.get(), self.importance_filter.get()
        )
        for row in rows:
            title = row["title"]
            if len(title) > 42:
                title = title[:41] + "…"
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    title,
                    row["category"],
                    f"{importance_level(row['importance'])} · {row['importance']}/100",
                    row["use_count"],
                    row["updated_at"],
                ),
            )
        self.refresh_count()
        if selected_id is not None and self.tree.exists(str(selected_id)):
            self.tree.selection_set(str(selected_id))
            self.tree.see(str(selected_id))
        elif rows:
            self.tree.selection_set(str(rows[0]["id"]))
            self.tree.see(str(rows[0]["id"]))
        else:
            self.current_id = None
            self.mode_label.configure(text="没有匹配的记忆")

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.category_filter.set("全部")
        self.importance_filter.set("全部")
        self.refresh_list()

    def on_tree_select(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if len(selected) != 1:
            if len(selected) > 1:
                self.mode_label.configure(text=f"已选 {len(selected)} 条，可合并")
            return
        try:
            memory_id = int(selected[0])
        except ValueError:
            return
        row = self.db.get(memory_id)
        if row:
            self.load_row(row)

    def load_row(self, row: sqlite3.Row) -> None:
        self.current_id = int(row["id"])
        self.title_var.set(row["title"])
        self.category_var.set(row["category"] if row["category"] in CATEGORIES else "其他")
        self.importance_var.set(str(row["importance"]))
        self.tags_var.set(row["tags"])
        self.source_var.set(row["source"])
        self.content_text.delete("1.0", "end")
        self.content_text.insert("1.0", row["content"])
        self.mode_label.configure(text=f"编辑 #{row['id']} · 更新于 {row['updated_at']}")
        self.status_var.set(f"数据文件：{self.db.path}")

    def new_memory(self) -> None:
        self.current_id = None
        self.tree.selection_remove(self.tree.selection())
        self.title_var.set("")
        self.category_var.set("通用")
        self.importance_var.set("50")
        self.tags_var.set("")
        self.source_var.set("")
        self.content_text.delete("1.0", "end")
        self.mode_label.configure(text="新建记忆")
        self.status_var.set("请把一条已经整理好的重要信息保存为记忆")

    def form_values(self) -> dict[str, object] | None:
        title = self.title_var.get().strip()
        content = self.content_text.get("1.0", "end-1c").strip()
        if not title:
            messagebox.showwarning(APP_TITLE, "请填写标题。", parent=self.root)
            return None
        if not content:
            messagebox.showwarning(APP_TITLE, "请填写整合后的内容。", parent=self.root)
            return None
        try:
            importance = max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(self.importance_var.get())))
        except ValueError:
            importance = 50
        category = self.category_var.get() if self.category_var.get() in CATEGORIES else "其他"
        return {
            "title": title,
            "content": content,
            "tags": self.tags_var.get().strip(),
            "category": category,
            "importance": importance,
            "source": self.source_var.get().strip(),
        }

    def save_memory(self) -> None:
        values = self.form_values()
        if values is None:
            return
        try:
            if self.current_id is None:
                memory_id = self.db.add(values)
                self.current_id = memory_id
                message = f"已保存新记忆 #{memory_id}"
            else:
                self.db.update(self.current_id, values)
                message = f"已更新记忆 #{self.current_id}"
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self.root)
            return
        self.refresh_list()
        self.status_var.set(message)

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "请先在左侧选择要删除的记忆。", parent=self.root)
            return
        ids = [int(item) for item in selected]
        prompt = f"确定删除选中的 {len(ids)} 条记忆吗？此操作不能撤销。"
        if not messagebox.askyesno(APP_TITLE, prompt, parent=self.root):
            return
        for memory_id in ids:
            self.db.delete(memory_id)
        self.new_memory()
        self.refresh_list()
        self.status_var.set(f"已删除 {len(ids)} 条记忆")

    def merge_selected(self) -> None:
        selected = self.tree.selection()
        if len(selected) < 2:
            messagebox.showinfo(APP_TITLE, "请至少选择 2 条记忆后再合并。", parent=self.root)
            return
        if self.db.count() >= MAX_MEMORIES:
            messagebox.showwarning(APP_TITLE, f"记忆库已达到 {MAX_MEMORIES} 条上限，请先删除或导出旧记录。", parent=self.root)
            return
        rows = [self.db.get(int(item)) for item in selected]
        rows = [row for row in rows if row is not None]
        if len(rows) < 2:
            return
        default_title = "整合：" + "、".join(row["title"] for row in rows[:3])
        if len(rows) > 3:
            default_title += "等"
        title = simpledialog.askstring(
            "合并记忆",
            "为整合后的记忆命名：",
            initialvalue=default_title,
            parent=self.root,
        )
        if title is None:
            return
        title = title.strip()
        if not title:
            messagebox.showwarning(APP_TITLE, "整合记忆需要标题。", parent=self.root)
            return
        paragraphs: list[str] = []
        seen: set[str] = set()
        for row in rows:
            block = f"【{row['title']}】\n{row['content'].strip()}"
            normalized = " ".join(block.split())
            if normalized not in seen:
                paragraphs.append(block)
                seen.add(normalized)
        tags: list[str] = []
        for row in rows:
            for tag in row["tags"].replace("，", ",").split(","):
                tag = tag.strip()
                if tag and tag not in tags:
                    tags.append(tag)
        category = rows[0]["category"] if all(row["category"] == rows[0]["category"] for row in rows) else "通用"
        values = {
            "title": title,
            "content": "\n\n".join(paragraphs),
            "tags": ", ".join(tags),
            "category": category,
            "importance": max(int(row["importance"]) for row in rows),
            "source": "合并自：" + ", ".join(str(row["id"]) for row in rows),
        }
        try:
            new_id = self.db.add(values)
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self.root)
            return
        self.current_id = new_id
        self.refresh_list()
        self.status_var.set(f"已创建整合记忆 #{new_id}；原记忆仍保留")

    def import_json(self) -> None:
        path_string = filedialog.askopenfilename(
            parent=self.root,
            title="导入 Codex 记忆 JSON",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path_string:
            return
        try:
            added, skipped, invalid = self.db.import_json(Path(path_string))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror(APP_TITLE, f"导入失败：{exc}", parent=self.root)
            return
        self.refresh_list()
        messagebox.showinfo(
            APP_TITLE,
            f"导入完成\n新增：{added} 条\n跳过：{skipped} 条（重复或达到上限）\n无效：{invalid} 条",
            parent=self.root,
        )

    def export_json(self) -> None:
        path_string = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出 Codex 记忆 JSON",
            defaultextension=".json",
            initialfile=f"codex-memories-{datetime.now():%Y%m%d-%H%M%S}.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path_string:
            return
        try:
            count = self.db.export_json(Path(path_string))
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"导出失败：{exc}", parent=self.root)
            return
        self.status_var.set(f"已导出 {count} 条记忆：{path_string}")

    def open_data_directory(self) -> None:
        directory = self.db.path.parent
        try:
            if os.name == "nt":
                os.startfile(str(directory))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"无法打开数据目录：{exc}", parent=self.root)

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于 Codex 记忆库",
            "本地、轻量的 Codex 长期记忆工具\n\n"
            f"容量：最多 {MAX_MEMORIES} 条\n"
            "重要度：1–33 不重要，34–66 普通，67–100 重要；连续 3 天不用会降低 1 点\n"
            "存储：SQLite（本机）\n"
            "功能：搜索、分类、重要度、JSON 导入导出、记忆合并",
            parent=self.root,
        )

    def close(self) -> None:
        self.db.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    MemoryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
