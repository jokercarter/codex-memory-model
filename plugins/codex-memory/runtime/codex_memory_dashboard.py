"""Local Codex Memory workbench. Importing this module has no side effects.

Browsing uses read-only SQLite connections. Explicit desktop actions delegate
all writes to the same versioned APIs as the MCP server.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import codex_memory_core as core


def decode_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        result = json.loads(str(value))
        if isinstance(result, list):
            return result
    except (TypeError, ValueError):
        pass
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def record(value: Any) -> dict:
    row = dict(value) if value is not None else {}
    for key in ("scenarios", "aliases", "evidence"):
        if key in row:
            row[key] = decode_list(row[key])
    return row


def parse_field(kind: str, text: str) -> Any:
    text = text.strip()
    if kind == "optional_int":
        return int(text) if text else None
    if kind in {"int", "float"}:
        return int(text) if kind == "int" else float(text)
    if kind in {"list", "ids"}:
        values = [v.strip() for v in text.splitlines() if v.strip()]
        return [int(v) for v in values] if kind == "ids" else values
    if kind == "pairs":
        result = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            key, sep, value = line.partition("=")
            if not sep or not key.strip():
                raise ValueError("每行请填写 名称=值，例如 Python=3.12")
            result[key.strip()] = value.strip()
        return result
    if kind == "citations":
        result = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.strip().split(":")
            if len(parts) != 2 or any(not part.isdigit() or int(part) < 1 for part in parts):
                raise ValueError("依据每行填写 记忆编号:版本，例如 12:3")
            result.append({"id": int(parts[0]), "revision": int(parts[1])})
        return result
    if kind == "bool":
        return text.lower() in {"true", "1", "yes", "是"}
    if kind == "json_list":
        value = json.loads(text or "[]")
        if not isinstance(value, list):
            raise ValueError("证据须为 JSON 数组")
        return value
    return text


def private_destination(path: Path) -> Path:
    target = path.expanduser().resolve()
    code = Path(__file__).resolve().parent
    if target == code or code in target.parents:
        raise ValueError("请将记忆数据导出到代码目录之外。")
    if any((parent / ".git").exists() for parent in target.parents):
        raise ValueError("不能将记忆数据导出到 Git 仓库。请选择本地私有目录。")
    return target


LABELS = {
    "title": "标题", "content": "内容", "id": "记忆编号", "memory_id": "记忆编号",
    "revision": "记忆版本", "version": "版本", "space": "空间", "scope": "读取规则",
    "kind": "类型", "importance": "长期重要度", "activity": "近期活跃度", "confidence": "可信度",
    "source": "来源", "updated_at": "更新时间", "created_at": "创建时间", "status": "状态",
    "goal": "目标", "completed": "已完成", "next_steps": "下一步", "files": "文件", "questions": "待确认",
    "steps": "步骤", "prerequisites": "前提", "success_criteria": "成功标准", "environment": "环境",
    "verified_at": "验证时间", "stale": "需要复核", "evidence": "证据", "field": "资料字段", "fields": "资料视图",
    "records": "依据记忆", "issues": "待处理事项", "counts": "统计", "message": "说明", "severity": "程度",
    "type": "类型", "conclusion": "结论", "inference": "包含推断", "citations": "引用依据", "topic": "主题",
    "path": "路径", "operation": "操作", "reason": "原因", "description": "说明", "label": "名称",
    "expires_at": "到期时间", "expired": "已到期", "success_count": "成功次数", "failure_count": "失败次数",
}


def readable(value: Any, depth: int = 0) -> str:
    indent = "  " * depth
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            label = LABELS.get(str(key), str(key))
            result.append(f"{indent}{label}：" + ("\n" + readable(item, depth + 1) if isinstance(item, (list, dict)) else readable(item)))
        return "\n".join(result)
    if isinstance(value, (list, tuple)):
        return "\n\n".join(f"{indent}{i + 1}. {readable(item, depth + 1).lstrip()}" for i, item in enumerate(value)) or indent + "（无）"
    if value is None:
        return "（未提供）"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


class MemoryRepository:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else core.database_path()

    @contextmanager
    def connection(self, write=False):
        conn = core.connect(self.path, read_only=not write)
        try:
            if write and conn is not None:
                from codex_memory_features import ensure_schema
                ensure_schema(conn)
                # Finish migrations before a backup can be requested. SQLite
                # backup must not run on an uncommitted writer transaction.
                conn.commit()
            yield conn
            if write and conn is not None:
                conn.commit()
        except BaseException:
            if write and conn is not None:
                conn.rollback()
            raise
        finally:
            if conn is not None:
                conn.close()

    def initialize(self):
        with self.connection(write=True):
            pass

    def memories(self, query="", space="", scope="", kind="", status="active") -> list[dict]:
        with self.connection() as conn:
            if conn is None:
                return []
            columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
            clauses, params = [], []
            for name, value in (("space", space), ("scope", scope), ("kind", kind), ("status", status)):
                if value and name in columns:
                    clauses.append(f"{name} = ?")
                    params.append(value)
            if query.strip():
                names = [name for name in ("title", "content", "tags", "aliases", "source", "memory_key") if name in columns]
                clauses.append("(" + " OR ".join(f"{name} LIKE ? ESCAPE '\\'" for name in names) + ")")
                escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params.extend([f"%{escaped}%"] * len(names))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            return [record(row) for row in conn.execute("SELECT * FROM memories" + where + " ORDER BY updated_at DESC,id DESC", params)]

    def get(self, memory_id):
        with self.connection() as conn:
            return record(core.get(conn, int(memory_id))) if conn is not None else {}

    @staticmethod
    def validate(values):
        allowed = {"title", "content", "category", "importance", "tags", "source", "memory_key", "confidence", "always_apply", "source_session", "space", "kind", "scope", "scenarios", "aliases", "evidence", "valid_from", "valid_until"}
        result = {key: value for key, value in values.items() if key in allowed}
        for field in ("title", "content"):
            result[field] = str(result.get(field, "")).strip()
            if not result[field]:
                raise ValueError(f"{LABELS[field]}不能为空")
        for field in ("scenarios", "aliases", "evidence"):
            if field in result:
                result[field] = decode_list(result[field])
        if result.get("scope", "on_demand") not in {"global", "scenario", "on_demand"}:
            raise ValueError("读取规则应为 global、scenario 或 on_demand")
        if result.get("scope") == "scenario" and not result.get("scenarios"):
            raise ValueError("场景必读记忆至少需要一个适用场景")
        if "importance" in result:
            result["importance"] = int(result["importance"])
            if not 1 <= result["importance"] <= 100:
                raise ValueError("长期重要度应为 1–100")
        if "confidence" in result:
            result["confidence"] = float(result["confidence"])
            if not 0 <= result["confidence"] <= 1:
                raise ValueError("可信度应为 0–1")
        return result

    def save(self, values, rows=()):
        args = self.validate(values)
        if rows:
            args["replace_ids"] = sorted(row["id"] for row in rows)
            args["expected_revisions"] = {row["id"]: row.get("revision", 1) for row in rows}
            args["expected_revision"] = args["expected_revisions"][min(args["replace_ids"])]
        with self.connection(write=True) as conn:
            return core.commit_memory(conn, **args, request_id=str(uuid.uuid4()))

    def retire(self, rows, reason):
        with self.connection(write=True) as conn:
            return core.retire(conn, [row["id"] for row in rows], reason=reason,
                               expected_revisions={row["id"]: row.get("revision", 1) for row in rows}, request_id=str(uuid.uuid4()))

    def history(self, memory_id):
        with self.connection() as conn:
            return core.history(conn, int(memory_id)) if conn is not None else []

    def restore_revision(self, memory_id, revision, expected_revision):
        with self.connection(write=True) as conn:
            return core.restore_revision(conn, int(memory_id), int(revision), expected_revision=expected_revision)

    def snapshots(self):
        with self.connection() as conn:
            return core.list_snapshots(conn) if conn is not None else []

    def snapshot(self, label):
        with self.connection(write=True) as conn:
            return core.snapshot(conn, label=label)

    def restore_snapshot(self, snapshot_id):
        with self.connection(write=True) as conn:
            return core.restore_snapshot(conn, snapshot_id)

    def relation(self, source, target, relation_type, strength, evidence):
        with self.connection(write=True) as conn:
            return core.set_relation(conn, int(source), int(target), relation_type, int(strength), evidence=evidence, request_id=str(uuid.uuid4()))

    def feature(self, name, args, write=False):
        from codex_memory_features import dispatch, is_read_only, ensure_schema
        mutates = not is_read_only("codex_memory_" + name, args)
        if mutates and not write:
            raise ValueError("此功能需要明确的保存操作，不能作为只读查询执行。")
        with self.connection(write=mutates) as conn:
            if conn is None:
                return {"message": "记忆库尚未创建。请先保存记忆或点击初始化。"}
            if mutates:
                ensure_schema(conn)
            return dispatch(conn, "codex_memory_" + name, args)

    def export_json(self, path):
        target = private_destination(Path(path))
        rows = self.memories(status="")
        spaces = self.feature("spaces", {"action": "list"}).get("spaces", [])
        target.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as stream:
                name = stream.name
                json.dump({"format": "codex-memory-export", "version": 2, "memories": rows, "spaces": spaces}, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(name, target)
        finally:
            if name and Path(name).exists():
                Path(name).unlink()
        return len(rows)

    def import_json(self, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        rows = payload.get("memories", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("导入文件必须是记忆数组或包含 memories 数组的导出文件")
        prepared = [self.validate(row) for row in rows if row.get("status", "active") == "active"]
        spaces = payload.get("spaces", []) if isinstance(payload, dict) else []
        if not isinstance(spaces, list) or any(not isinstance(space, dict) or not space.get("key") for space in spaces):
            raise ValueError("spaces 应是带 key 的空间数组")
        from codex_memory_features import dispatch
        with self.connection(write=True) as conn:
            backup = core.snapshot(conn, label="导入前自动快照")
            with core.atomic(conn):
                existing = {row["key"] for row in dispatch(conn, "codex_memory_spaces", {"action": "list"})["spaces"]}
                for space in spaces:
                    if space["key"] not in existing:
                        dispatch(conn, "codex_memory_spaces", {"action": "create", "key": space["key"], "title": space.get("title", space["key"]), "description": space.get("description", "")})
                        existing.add(space["key"])
                results = [core.commit_memory(conn, **values, request_id=str(uuid.uuid4())) for values in prepared]
        return {"imported": len(results), "skipped": len(rows) - len(prepared), "snapshot": backup}


# Fields are (API key, visible label, input type, initial value). Multi-value
# input uses one line per value; users never need to compose request JSON.
WORKSPACES = {
    "项目空间": ("spaces", [
        ("key", "空间标识", "text", ""), ("title", "显示名称", "text", ""),
        ("description", "说明", "lines", ""), ("expected_version", "当前版本（修改时填）", "optional_int", ""),
    ], [("列出", "list", False), ("读取", "get", False), ("保存", "create", True)]),
    "任务接续卡": ("task", [
        ("key", "任务标识", "text", ""), ("space", "空间", "text", "global"), ("goal", "目标", "lines", ""),
        ("completed", "已完成（每行一项）", "list", ""), ("next_steps", "下一步（每行一项）", "list", ""),
        ("files", "相关文件（每行一路径）", "list", ""), ("questions", "待确认（每行一项）", "list", ""),
        ("status", "任务状态", "choice:active,blocked,paused,completed,cancelled", "active"),
        ("ttl_hours", "保留小时数", "int", "168"), ("expected_version", "当前版本（修改时填）", "optional_int", ""),
    ], [("列出", "list", False), ("读取", "get", False), ("保存", "save", True), ("完成任务", "close", True)]),
    "流程与失败经验": ("procedure", [
        ("memory_id", "记忆编号（新建留空）", "optional_int", ""), ("space", "空间", "text", "global"),
        ("title", "标题", "text", ""), ("content", "适用场景与说明", "lines", ""),
        ("procedure_type", "类型", "choice:procedure,failure", "procedure"),
        ("prerequisites", "前提（每行一项）", "list", ""), ("steps", "执行或恢复步骤（每行一步）", "list", ""),
        ("success_criteria", "成功标准（每行一项）", "list", ""), ("environment", "环境（每行 名称=值）", "pairs", ""),
        ("verified_at", "验证时间（未验证留空）", "text", ""), ("evidence", "证据（每行一项）", "list", ""),
        ("expected_version", "流程当前版本", "optional_int", ""), ("expected_revision", "记忆当前版本", "optional_int", ""),
    ], [("列出", "list", False), ("读取", "get", False), ("保存", "save", True), ("生成 Skill 草稿", "skill_draft", False)]),
    "个人资料视图": ("profile", [
        ("space", "空间", "text", "global"), ("fields", "资料字段（每行一个，例如 毕业时间）", "list", ""),
    ], [("读取资料", None, False)]),
    "任务记忆包": ("packet", [
        ("query", "当前任务", "lines", ""), ("space", "项目空间（留空跨空间）", "text", ""),
        ("scenarios", "场景（每行一项）", "list", ""), ("limit", "候选数量", "int", "12"),
        ("token_budget", "上下文预算", "int", "4000"),
    ], [("读取记忆包", None, False)]),
    "有依据的主题摘要": ("reflect", [
        ("topic", "主题", "text", ""), ("space", "空间", "text", "global"),
        ("conclusion", "已核对的综合结论", "lines", ""), ("citations", "引用（每行 记忆编号:版本）", "citations", ""),
        ("inference", "结论包含推断", "bool", "true"), ("expected_version", "摘要当前版本", "optional_int", ""),
    ], [("列出摘要", "list", False), ("查找依据", "prepare", False), ("读取摘要", "get", False), ("保存摘要", "save", True)]),
    "文件与版本": ("file", [
        ("path", "文件路径", "path", ""), ("memory_ids", "关联记忆编号（每行一个）", "ids", ""),
        ("expected_version", "登记当前版本", "optional_int", ""),
    ], [("列出文件", "list", False), ("登记版本", "attach", True), ("检查并更新状态", "check", True)]),
    "使用反馈": ("feedback", [
        ("memory_id", "记忆编号", "int", ""), ("outcome", "使用结果", "choice:useful,irrelevant,incorrect", "useful"),
        ("context", "本次使用场景", "lines", ""), ("correction", "纠正说明", "lines", ""),
        ("scope", "反馈适用空间（或 global）", "text", "global"),
    ], [("保存反馈", None, True)]),
    "流程结果反馈": ("procedure", [
        ("memory_id", "流程记忆编号", "int", ""), ("outcome", "执行结果", "choice:success,failure", "success"),
        ("notes", "实际观察到的结果和证据", "lines", ""), ("expected_version", "流程当前版本", "optional_int", ""),
    ], [("读取流程版本", "get", False), ("记录执行结果", "feedback", True)]),
}

MEMORY_FIELDS = [
    ("title", "标题", "text", ""), ("memory_key", "稳定标识", "text", ""),
    ("space", "空间", "text", "global"), ("kind", "类型", "choice:fact,preference,procedure,failure,decision,event,profile", "fact"),
    ("scope", "读取规则", "choice:global,scenario,on_demand", "on_demand"), ("category", "分类", "text", "通用"),
    ("importance", "长期重要度 1–100", "int", "50"), ("confidence", "可信度 0–1", "float", "0.8"),
    ("tags", "标签", "text", ""), ("source", "来源", "text", ""),
    ("scenarios", "适用场景（每行一项）", "list", ""), ("aliases", "别名（每行一项）", "list", ""),
    ("valid_from", "生效时间", "text", ""), ("valid_until", "失效时间", "text", ""),
    ("content", "完整内容与适用条件", "lines", ""),
    ("evidence", "证据数组（高级，可保持默认）", "json_list", "[]"),
]


def build_dashboard(root, repository=None):
    """Build widgets on a caller-owned root, permitting withdrawn smoke tests."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    class Dashboard:
        def __init__(self):
            self.root = root
            self.repo = repository or MemoryRepository()
            self.rows, self.edit_rows, self.history_rows = {}, [], {}
            self.status = tk.StringVar(value=f"数据位置：{self.repo.path}")
            root.title("Codex Memory · 本地记忆工作台")
            root.geometry("1250x830")
            root.minsize(950, 650)
            bar = ttk.Frame(root, padding=7)
            bar.pack(fill="x")
            for label, fn in (("刷新", self.refresh), ("初始化", self.initialize), ("导入 JSON", self.import_data), ("导出 JSON", self.export_data)):
                self.button(bar, label, fn).pack(side="left", padx=3)
            ttk.Label(bar, text="浏览只读；保存、恢复、反馈等操作会更新本地数据。").pack(side="left", padx=14)
            self.tabs = ttk.Notebook(root)
            self.tabs.pack(fill="both", expand=True, padx=8)
            self.build_memories()
            self.build_workspace()
            self.build_history()
            self.build_health()
            self.build_graph()
            ttk.Label(root, textvariable=self.status, padding=8).pack(fill="x")

        def run(self, fn):
            try:
                return fn()
            except Exception as error:
                self.status.set(f"操作未完成：{error}")
                messagebox.showerror("Codex Memory", f"{type(error).__name__}: {error}\n\n若提示版本冲突，请重新读取最新记录后再编辑。", parent=root)

        def button(self, parent, label, fn):
            return ttk.Button(parent, text=label, command=lambda: self.run(fn))

        def text_box(self, parent, height=8):
            frame = ttk.Frame(parent)
            widget = tk.Text(frame, wrap="word", height=height, padx=8, pady=6, undo=True)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
            widget.configure(yscrollcommand=scroll.set)
            widget.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            return frame, widget

        def display(self, widget, value):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", readable(value))
            widget.configure(state="disabled")

        def scrolled_form(self, parent):
            canvas = tk.Canvas(parent, highlightthickness=0)
            scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            frame = ttk.Frame(canvas, padding=5)
            window = canvas.create_window((0, 0), window=frame, anchor="nw")
            frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
            return frame

        def form(self, parent, fields):
            controls = {}
            for key, label, kind, default in fields:
                block = ttk.Frame(parent, padding=(3, 3))
                block.pack(fill="x")
                ttk.Label(block, text=label).pack(anchor="w")
                if kind in {"lines", "list", "pairs", "citations", "ids", "json_list"}:
                    frame, widget = self.text_box(block, 5 if key == "content" else 3)
                    frame.pack(fill="x")
                    widget.insert("1.0", default)
                else:
                    widget = tk.StringVar(value=default)
                    if kind.startswith("choice:") or kind == "bool":
                        values = kind.split(":", 1)[1].split(",") if ":" in kind else ["false", "true"]
                        control = ttk.Combobox(block, textvariable=widget, values=values, state="readonly")
                    else:
                        control = ttk.Entry(block, textvariable=widget)
                    control.pack(fill="x")
                    if kind == "path":
                        def browse(var=widget):
                            name = filedialog.askopenfilename(parent=root)
                            if name:
                                var.set(name)
                        self.button(block, "选择文件", browse).pack(anchor="e")
                controls[key] = (kind, widget)
            return controls

        def form_values(self, controls, allowed=None):
            result = {}
            for key, (kind, widget) in controls.items():
                if allowed is not None and key not in allowed:
                    continue
                raw = widget.get("1.0", "end-1c") if isinstance(widget, tk.Text) else widget.get()
                value = parse_field(kind, raw)
                if value is not None:
                    result[key] = value
            return result

        def fill_form(self, controls, row):
            for key, (kind, widget) in controls.items():
                name = {"expected_version": "version", "expected_revision": "revision"}.get(key, key)
                if name not in row:
                    continue
                value = row[name]
                if kind == "json_list":
                    text = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, list) else str(value)
                elif kind == "pairs" and isinstance(value, dict):
                    text = "\n".join(f"{k}={v}" for k, v in value.items())
                elif kind == "citations" and isinstance(value, list):
                    text = "\n".join(f"{v['id']}:{v['revision']}" for v in value)
                elif isinstance(value, list):
                    text = "\n".join(map(str, value))
                elif isinstance(value, bool):
                    text = str(value).lower()
                else:
                    text = str(value) if value is not None else ""
                if isinstance(widget, tk.Text):
                    widget.delete("1.0", "end")
                    widget.insert("1.0", text)
                else:
                    widget.set(text)

        def build_memories(self):
            page = ttk.Frame(self.tabs)
            self.tabs.add(page, text="记忆与编辑")
            bar = ttk.Frame(page, padding=6)
            bar.pack(fill="x")
            self.filters = {}
            for key, label, default in (("query", "搜索", ""), ("space", "空间", ""), ("scope", "规则", ""), ("kind", "类型", ""), ("status", "状态", "active")):
                ttk.Label(bar, text=label).pack(side="left", padx=(5, 2))
                var = tk.StringVar(value=default)
                self.filters[key] = var
                entry = ttk.Entry(bar, textvariable=var, width=16 if key == "query" else 12)
                entry.pack(side="left")
                entry.bind("<Return>", lambda event: self.run(self.refresh))
            self.button(bar, "筛选", self.refresh).pack(side="left", padx=6)
            split = ttk.Panedwindow(page, orient="horizontal")
            split.pack(fill="both", expand=True)
            left, right = ttk.Frame(split), ttk.Frame(split)
            split.add(left, weight=3)
            split.add(right, weight=2)
            columns = ("id", "title", "space", "scope", "importance", "activity", "revision")
            self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="extended")
            for key in columns:
                self.tree.heading(key, text=LABELS.get(key, key))
                self.tree.column(key, width=200 if key == "title" else 75, minwidth=40)
            scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.tree.bind("<<TreeviewSelect>>", lambda event: self.run(self.select_memory))
            buttons = ttk.Frame(right, padding=4)
            buttons.pack(fill="x")
            for label, fn in (("新建", self.new_memory), ("保存", self.save_memory), ("合并", self.merge), ("淘汰", self.retire), ("历史", self.show_history)):
                self.button(buttons, label, fn).pack(side="left", padx=2)
            form_parent = ttk.Frame(right)
            form_parent.pack(fill="both", expand=True)
            self.memory_form = self.form(self.scrolled_form(form_parent), MEMORY_FIELDS)

        def initialize(self):
            self.repo.initialize()
            self.refresh()

        def refresh(self):
            rows = self.repo.memories(**{key: var.get() for key, var in self.filters.items()})
            self.tree.delete(*self.tree.get_children())
            self.rows = {row["id"]: row for row in rows}
            for row in rows:
                self.tree.insert("", "end", iid=str(row["id"]), values=[row.get(key, "") for key in self.tree["columns"]])
            self.status.set(f"显示 {len(rows)} 条记录 · {self.repo.path}")

        def new_memory(self):
            self.edit_rows = []
            self.fill_form(self.memory_form, {key: default for key, label, kind, default in MEMORY_FIELDS})

        def select_memory(self):
            selected = self.tree.selection()
            if len(selected) != 1:
                return
            row = self.repo.get(int(selected[0]))
            if row:
                self.edit_rows = [row]
                self.fill_form(self.memory_form, row)
                self.status.set(f"#{row['id']} · 版本 {row.get('revision', 1)} · 完整内容")

        def save_memory(self):
            values = self.form_values(self.memory_form)
            result = self.repo.save(values, self.edit_rows)
            self.refresh()
            if str(result["id"]) in self.tree.get_children():
                self.tree.selection_set(str(result["id"]))
                self.tree.see(str(result["id"]))
            self.status.set(f"已保存记忆 #{result['id']} · 版本 {result.get('revision', '')}")

        def merge(self):
            selected = self.tree.selection()
            if len(selected) < 2:
                raise ValueError("请按住 Ctrl 选择至少两条记忆")
            self.edit_rows = [self.rows[int(key)] for key in sorted(selected, key=int)]
            values = dict(self.edit_rows[0])
            values["content"] = "\n\n".join(row["content"] for row in self.edit_rows)
            self.fill_form(self.memory_form, values)
            self.status.set("请整理成一个独立信息单元后保存。旧版本会保留。")

        def retire(self):
            rows = [self.rows[int(key)] for key in self.tree.selection()]
            if not rows:
                raise ValueError("请先选中记忆")
            reason = simpledialog.askstring("淘汰记忆", "错误、过期或重复的原因：", parent=root)
            if reason is not None:
                count = self.repo.retire(rows, reason)
                self.refresh()
                self.status.set(f"已淘汰 {count} 条，可通过历史恢复")

        def import_data(self):
            name = filedialog.askopenfilename(parent=root, filetypes=[("JSON", "*.json")])
            if name:
                result = self.repo.import_json(name)
                self.refresh()
                messagebox.showinfo("导入完成", readable(result), parent=root)

        def export_data(self):
            name = filedialog.asksaveasfilename(parent=root, initialdir=str(self.repo.path.parent), initialfile="memory-export.json", defaultextension=".json", filetypes=[("JSON", "*.json")])
            if name:
                count = self.repo.export_json(name)
                self.status.set(f"已导出 {count} 条记忆到 {name}")

        def build_workspace(self):
            page = ttk.Frame(self.tabs, padding=6)
            self.tabs.add(page, text="项目、流程与知识")
            self.workspace = tk.StringVar(value=next(iter(WORKSPACES)))
            selector = ttk.Combobox(page, textvariable=self.workspace, values=list(WORKSPACES), state="readonly", width=30)
            selector.pack(anchor="w", pady=5)
            selector.bind("<<ComboboxSelected>>", lambda event: self.render_workspace())
            split = ttk.Panedwindow(page, orient="horizontal")
            split.pack(fill="both", expand=True)
            left, right = ttk.Frame(split), ttk.Frame(split)
            split.add(left, weight=1)
            split.add(right, weight=1)
            self.work_form_parent = self.scrolled_form(left)
            frame, self.work_result = self.text_box(right)
            frame.pack(fill="both", expand=True)
            self.display(self.work_result, "读取已有记录后，字段和版本会自动填入。\n综合结论须由 Codex 或使用者核对后保存；资料缺失会明确显示。")
            self.render_workspace()

        def render_workspace(self):
            for child in self.work_form_parent.winfo_children():
                child.destroy()
            name, fields, actions = WORKSPACES[self.workspace.get()]
            self.work_form = self.form(self.work_form_parent, fields)
            bar = ttk.Frame(self.work_form_parent, padding=5)
            bar.pack(fill="x")
            for label, action, write in actions:
                self.button(bar, label, lambda a=action, w=write: self.execute_workspace(a, w)).pack(side="left", padx=3, pady=5)

        def execute_workspace(self, action, write):
            name = WORKSPACES[self.workspace.get()][0]
            allowed = None
            if not write and action in {"list", "get", "prepare", "skill_draft"}:
                allowed = {"space", "key", "memory_id", "topic", "path"}
            if action == "close":
                allowed = {"key", "expected_version"}
            args = self.form_values(self.work_form, allowed)
            args = {key: value for key, value in args.items() if value != ""}
            if action:
                args["action"] = action
            if write:
                args["request_id"] = str(uuid.uuid4())
            result = self.repo.feature(name, args, write=write)
            self.display(self.work_result, result)
            if action in {"get", "create", "save", "close", "attach", "check", "feedback"}:
                key = {"spaces": "space", "task": "task", "procedure": "procedure", "reflect": "summary", "file": "file"}.get(name)
                row = result.get(key, {}) if key else {}
                if isinstance(row, dict):
                    self.fill_form(self.work_form, row)
            self.status.set("已保存本地数据" if write else "已完成只读查询")
            return result

        def build_history(self):
            self.history_page = ttk.Frame(self.tabs, padding=7)
            self.tabs.add(self.history_page, text="历史与恢复")
            bar = ttk.Frame(self.history_page)
            bar.pack(fill="x")
            self.history_id = tk.StringVar()
            ttk.Label(bar, text="记忆编号").pack(side="left")
            ttk.Entry(bar, textvariable=self.history_id, width=10).pack(side="left", padx=4)
            for label, fn in (("读取版本", self.load_history), ("恢复版本", self.restore_revision), ("列出快照", self.load_snapshots), ("创建快照", self.create_snapshot), ("恢复快照", self.restore_snapshot)):
                self.button(bar, label, fn).pack(side="left", padx=3)
            split = ttk.Panedwindow(self.history_page, orient="vertical")
            split.pack(fill="both", expand=True, pady=7)
            self.history_tree = ttk.Treeview(split, columns=("version", "date", "label"), show="headings")
            for key, title in (("version", "版本或快照编号"), ("date", "记录时间"), ("label", "说明")):
                self.history_tree.heading(key, text=title)
            split.add(self.history_tree, weight=1)
            frame, self.history_text = self.text_box(split)
            split.add(frame, weight=2)
            self.history_tree.bind("<<TreeviewSelect>>", lambda event: self.history_selection())
            self.history_mode = "revision"

        def show_history(self):
            if not self.edit_rows:
                raise ValueError("请先选中一条记忆")
            self.history_id.set(str(self.edit_rows[0]["id"]))
            self.tabs.select(self.history_page)
            self.load_history()

        def load_history(self):
            memory_id = int(self.history_id.get())
            self.history_current = self.repo.get(memory_id)
            self.history_mode = "revision"
            self.populate_history(self.repo.history(memory_id))
            self.display(self.history_text, "选择历史版本可查看完整内容。恢复将创建新版本，保留已有历史。")

        def populate_history(self, rows):
            self.history_tree.delete(*self.history_tree.get_children())
            self.history_rows = {}
            for index, row in enumerate(rows):
                self.history_rows[str(index)] = row
                self.history_tree.insert("", "end", iid=str(index), values=(row.get("revision", row.get("id", "")), row.get("recorded_at", row.get("created_at", "")), row.get("reason", row.get("label", ""))))

        def history_selection(self):
            selected = self.history_tree.selection()
            if selected:
                self.display(self.history_text, self.history_rows[selected[0]])

        def restore_revision(self):
            selected = self.history_tree.selection()
            if self.history_mode != "revision" or not selected:
                raise ValueError("请先读取并选中一个历史版本")
            row = self.history_rows[selected[0]]
            result = self.repo.restore_revision(int(self.history_id.get()), row["revision"], self.history_current.get("revision", 1))
            self.load_history()
            self.refresh()
            self.display(self.history_text, result)

        def load_snapshots(self):
            self.history_mode = "snapshot"
            self.populate_history(self.repo.snapshots())
            self.display(self.history_text, "快照只保存在本地。恢复整个记忆库之前，会自动保存当前状态。")

        def create_snapshot(self):
            label = simpledialog.askstring("创建本地快照", "快照说明：", parent=root)
            if label is not None:
                result = self.repo.snapshot(label)
                self.load_snapshots()
                self.display(self.history_text, result)

        def restore_snapshot(self):
            selected = self.history_tree.selection()
            if self.history_mode != "snapshot" or not selected:
                raise ValueError("请先列出并选择一个快照")
            row = self.history_rows[selected[0]]
            if messagebox.askyesno("恢复整个记忆库", f"恢复快照 {row['id']}？\n当前状态将先保存为安全快照。", parent=root):
                result = self.repo.restore_snapshot(row["id"])
                self.load_snapshots()
                self.refresh()
                self.display(self.history_text, result)

        def build_health(self):
            page = ttk.Frame(self.tabs, padding=7)
            self.tabs.add(page, text="健康检查")
            bar = ttk.Frame(page)
            bar.pack(fill="x")
            ttk.Label(bar, text="空间（留空全部）").pack(side="left")
            self.health_space = tk.StringVar()
            ttk.Entry(bar, textvariable=self.health_space).pack(side="left", padx=6)
            self.button(bar, "只读检查", self.load_health).pack(side="left", padx=4)
            self.button(bar, "维护报告", self.maintain).pack(side="left", padx=4)
            frame, self.health_text = self.text_box(page)
            frame.pack(fill="both", expand=True, pady=7)
            self.display(self.health_text, "检查冲突、重复、缺少来源、过期流程、失效引用和文件变化。\n只读检查不增加使用次数或改变重要度。")

        def load_health(self):
            args = {"space": self.health_space.get()} if self.health_space.get() else {}
            self.display(self.health_text, self.repo.feature("health", args))

        def maintain(self):
            result = self.repo.feature("maintenance", {})
            self.display(self.health_text, result)
            self.refresh()

        def build_graph(self):
            page = ttk.Frame(self.tabs, padding=7)
            self.tabs.add(page, text="关系图")
            bar = ttk.Frame(page)
            bar.pack(fill="x")
            self.graph_space, self.graph_id = tk.StringVar(), tk.StringVar()
            ttk.Label(bar, text="空间").pack(side="left")
            ttk.Entry(bar, textvariable=self.graph_space, width=16).pack(side="left", padx=4)
            ttk.Label(bar, text="中心记忆编号（可留空）").pack(side="left")
            ttk.Entry(bar, textvariable=self.graph_id, width=9).pack(side="left", padx=4)
            self.button(bar, "读取关系图", self.load_graph).pack(side="left", padx=4)
            ttk.Label(bar, text="点击节点查看全文；最多显示 40 个节点。").pack(side="left", padx=8)
            self.graph_canvas = tk.Canvas(page, background="#f5f7fb", highlightthickness=0)
            self.graph_canvas.pack(fill="both", expand=True, pady=7)
            self.graph_data = {}
            self.graph_canvas.bind("<Configure>", lambda event: self.draw_graph())
            edit = ttk.LabelFrame(page, text="维护已确认的关系", padding=7)
            edit.pack(fill="x")
            self.edge_fields = {}
            for key, label, default in (("source", "来源编号", ""), ("target", "目标编号", ""), ("relation_type", "关系类型", "related"), ("strength", "相关度 1–100", "50"), ("evidence", "依据", "")):
                ttk.Label(edit, text=label).pack(side="left", padx=(5, 2))
                var = tk.StringVar(value=default)
                self.edge_fields[key] = var
                if key == "relation_type":
                    control = ttk.Combobox(edit, textvariable=var, values=sorted(core.EDGE_TYPES), state="readonly", width=13)
                else:
                    control = ttk.Entry(edit, textvariable=var, width=25 if key == "evidence" else 8)
                control.pack(side="left")
            self.button(edit, "保存关系", self.save_relation).pack(side="left", padx=8)

        def save_relation(self):
            args = {key: value.get() for key, value in self.edge_fields.items()}
            if not 1 <= int(args["strength"]) <= 100:
                raise ValueError("相关度应为 1–100")
            self.repo.relation(**args)
            self.load_graph()
            self.status.set("已保存关系与依据")

        def load_graph(self):
            args = {"limit": 40}
            if self.graph_space.get():
                args["space"] = self.graph_space.get()
            if self.graph_id.get():
                args["memory_id"] = int(self.graph_id.get())
            self.graph_data = self.repo.feature("graph", args)
            self.draw_graph()

        def draw_graph(self):
            canvas = self.graph_canvas
            canvas.delete("all")
            nodes = self.graph_data.get("nodes", [])
            if not nodes:
                canvas.create_text(30, 30, anchor="nw", text="选择空间或中心记忆后读取关系图。", fill="#4b5f75")
                return
            width, height = max(canvas.winfo_width(), 400), max(canvas.winfo_height(), 300)
            radius = max(60, min(width, height) / 2 - 95)
            positions = {node["id"]: (width / 2 + radius * math.cos(i * math.tau / len(nodes) - math.pi / 2), height / 2 + radius * math.sin(i * math.tau / len(nodes) - math.pi / 2)) for i, node in enumerate(nodes)}
            for edge in self.graph_data.get("edges", []):
                a, b = positions.get(edge["source"]), positions.get(edge["target"])
                if a and b:
                    canvas.create_line(*a, *b, fill="#a4b5c9", width=1 + float(edge.get("strength", 1)) / 40, arrow="last")
                    canvas.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, text=f"{edge.get('type', '')} {edge.get('strength', '')}", fill="#62748a", font=("TkDefaultFont", 8))
            for node in nodes:
                x, y = positions[node["id"]]
                tag = f"memory-{node['id']}"
                canvas.create_oval(x - 19, y - 19, x + 19, y + 19, fill="#265e94", outline="white", width=2, tags=tag)
                canvas.create_text(x, y, text=str(node["id"]), fill="white", tags=tag)
                canvas.create_text(x, y + 32, text=str(node.get("title", ""))[:20], width=145, fill="#213d56", tags=tag)
                canvas.tag_bind(tag, "<Button-1>", lambda event, memory_id=node["id"]: self.run(lambda: self.show_graph_memory(memory_id)))

        def show_graph_memory(self, memory_id):
            row = self.repo.get(memory_id)
            dialog = tk.Toplevel(root)
            dialog.title(f"记忆 #{memory_id} · {row.get('title', '')}")
            dialog.geometry("680x570")
            frame, widget = self.text_box(dialog)
            frame.pack(fill="both", expand=True, padx=8, pady=8)
            self.display(widget, row)

    return Dashboard()


def launch(path=None):
    import tkinter as tk
    root = tk.Tk()
    app = build_dashboard(root, MemoryRepository(path))
    app.run(app.refresh)
    root.mainloop()


if __name__ == "__main__":
    launch()
