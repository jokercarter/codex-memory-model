"""Dashboard checks use synthetic temporary stores, never the user's vault."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_memory_core as core
import codex_memory_dashboard as dashboard


class FormTests(unittest.TestCase):
    def test_parse_human_fields(self):
        self.assertEqual(dashboard.parse_field("pairs", "Python=3.12\nOS=Windows"), {"Python": "3.12", "OS": "Windows"})
        self.assertEqual(dashboard.parse_field("citations", "12:3\n4:1"), [{"id": 12, "revision": 3}, {"id": 4, "revision": 1}])
        self.assertEqual(dashboard.parse_field("list", "第一步\n\n第二步"), ["第一步", "第二步"])
        self.assertEqual(dashboard.parse_field("optional_int", ""), None)
        with self.assertRaises(ValueError):
            dashboard.parse_field("citations", "12")
        with self.assertRaises(ValueError):
            dashboard.parse_field("pairs", "no separator")

    def test_private_export_rejects_code_and_any_git_repository(self):
        with self.assertRaises(ValueError):
            dashboard.private_destination(Path(dashboard.__file__).parent / "memories.json")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".git").mkdir()
            with self.assertRaises(ValueError):
                dashboard.private_destination(root / "nested" / "memories.json")

    def test_readable_evidence_is_complete(self):
        content = "适用条件与详细步骤" * 500
        output = dashboard.readable({"content": content, "citations": [{"id": 7, "revision": 2}], "inference": True})
        self.assertIn(content, output)
        self.assertIn("引用依据", output)
        self.assertIn("包含推断：是", output)

    def test_invalid_import_fields_fail_before_write(self):
        with self.assertRaises(ValueError):
            dashboard.MemoryRepository.validate({"title": "x", "content": "y", "scope": "scenario", "scenarios": []})
        with self.assertRaises(ValueError):
            dashboard.MemoryRepository.validate({"title": "x", "content": "y", "importance": 101})


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.repo = dashboard.MemoryRepository(self.folder / "data" / "memory.db")

    def save(self, title="示例偏好", content="在示例项目中使用中文说明。", **extra):
        return self.repo.save({"title": title, "content": content, "memory_key": title, **extra})

    def test_browsing_missing_vault_does_not_create_any_file(self):
        self.assertEqual(self.repo.memories(), [])
        self.assertEqual(self.repo.get(1), {})
        self.assertEqual(self.repo.history(1), [])
        self.assertEqual(self.repo.snapshots(), [])
        self.assertIn("message", self.repo.feature("health", {}))
        self.assertFalse(self.repo.path.parent.exists())

    def test_read_only_browsing_does_not_change_rows(self):
        result = self.save()
        before = self.repo.get(result["id"])
        self.repo.memories(query="中文")
        self.repo.history(result["id"])
        self.repo.feature("health", {})
        self.repo.feature("maintenance", {})
        after = self.repo.get(result["id"])
        self.assertEqual(before, after)

    def test_editor_rejects_stale_update(self):
        result = self.save()
        stale = self.repo.get(result["id"])
        self.repo.save({**stale, "content": "其他会话的新信息"}, [stale])
        with self.assertRaises((RuntimeError, ValueError)):
            self.repo.save({**stale, "content": "旧编辑器内容"}, [stale])
        self.assertEqual(self.repo.get(result["id"])["content"], "其他会话的新信息")

    def test_merge_preserves_history_and_retire_is_versioned(self):
        first = self.save("示例原子事实甲", "示例项目先检查环境")
        second = self.save("示例原子事实乙", "示例项目需要相同环境")
        rows = [self.repo.get(first["id"]), self.repo.get(second["id"])]
        merged = self.repo.save({**rows[0], "content": "在示例项目中，先检查运行环境是否一致。"}, rows)
        self.assertEqual(len(self.repo.memories()), 1)
        self.assertGreater(len(self.repo.history(merged["id"])), 1)
        current = self.repo.get(merged["id"])
        self.repo.retire([current], "示例项目已经结束")
        self.assertEqual(self.repo.get(merged["id"])["status"], "obsolete")
        self.assertGreater(self.repo.get(merged["id"])["revision"], current["revision"])

    def test_full_text_literal_filter_and_export_roundtrip(self):
        content = "100% 的示例流程_需要保存完整上下文。" * 300
        self.save(content=content)
        self.assertEqual(len(self.repo.memories(query="100%")), 1)
        target = self.folder / "export.json"
        self.assertEqual(self.repo.export_json(target), 1)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["memories"][0]["content"], content)
        other = dashboard.MemoryRepository(self.folder / "other" / "memory.db")
        result = other.import_json(target)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(other.memories()[0]["content"], content)

    def test_import_is_atomic_if_a_later_record_fails(self):
        self.save()
        target = self.folder / "import.json"
        target.write_text(json.dumps([{"title": "first", "content": "new value"}, {"title": "second", "content": "new value", "kind": "not-a-kind"}]), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.repo.import_json(target)
        self.assertEqual(len(self.repo.memories()), 1)
        self.assertGreaterEqual(len(self.repo.snapshots()), 1)

    def test_workspace_updates_require_explicit_write(self):
        self.repo.initialize()
        with self.assertRaises(ValueError):
            self.repo.feature("spaces", {"action": "create", "key": "demo", "title": "Demo"})
        result = self.repo.feature("spaces", {"action": "create", "key": "demo", "title": "Demo"}, write=True)
        self.assertEqual(result["space"]["key"], "demo")

    def test_export_import_keeps_project_spaces(self):
        self.repo.initialize()
        self.repo.feature("spaces", {"action": "create", "key": "synthetic-project", "title": "Synthetic Project"}, write=True)
        self.save(space="synthetic-project")
        target = self.folder / "spaces.json"
        self.repo.export_json(target)
        other = dashboard.MemoryRepository(self.folder / "other" / "memory.db")
        other.import_json(target)
        spaces = other.feature("spaces", {"action": "list"})["spaces"]
        self.assertIn("synthetic-project", {space["key"] for space in spaces})
        self.assertEqual(other.memories()[0]["space"], "synthetic-project")

    def test_relation_editor_sets_exact_strength(self):
        first = self.save("示例前提", "示例运行环境已经准备好")
        second = self.save("示例流程", "在示例环境里运行流程")
        self.repo.relation(first["id"], second["id"], "related", 85, "verified example")
        self.repo.relation(first["id"], second["id"], "related", 25, "relationship is weaker after review")
        graph = self.repo.feature("graph", {})
        matching = [edge for edge in graph["edges"] if {edge["source"], edge["target"]} == {first["id"], second["id"]} and edge["type"] == "related"]
        self.assertEqual(matching[0]["strength"], 25)

    def test_snapshot_restore_and_revision_restore(self):
        result = self.save()
        old = self.repo.get(result["id"])
        snapshot = self.repo.snapshot("synthetic test")
        self.repo.save({**old, "content": "changed"}, [old])
        current = self.repo.get(result["id"])
        self.repo.restore_revision(result["id"], old["revision"], current["revision"])
        self.assertEqual(self.repo.get(result["id"])["content"], old["content"])
        self.save("additional", "another fact")
        self.repo.restore_snapshot(snapshot["id"])
        self.assertEqual(len(self.repo.memories()), 1)


class HiddenWidgetTests(unittest.TestCase):
    def hidden_root(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.addCleanup(root.destroy)
        return root

    def test_workbench_can_render_all_forms_while_withdrawn(self):
        root = self.hidden_root()
        with tempfile.TemporaryDirectory() as folder:
            repo = dashboard.MemoryRepository(Path(folder) / "absent.db")
            with patch("tkinter.messagebox.showerror", side_effect=AssertionError("unexpected GUI error")):
                app = dashboard.build_dashboard(root, repo)
                app.refresh()
                for workspace in dashboard.WORKSPACES:
                    app.workspace.set(workspace)
                    app.render_workspace()
                app.draw_graph()
                root.update_idletasks()
            self.assertEqual(root.state(), "withdrawn")
            self.assertFalse(repo.path.exists())

    def test_workspace_forms_complete_synthetic_workflow(self):
        root = self.hidden_root()
        with tempfile.TemporaryDirectory() as folder:
            repo = dashboard.MemoryRepository(Path(folder) / "vault" / "memory.db")
            repo.initialize()
            with patch("tkinter.messagebox.showerror", side_effect=AssertionError("unexpected GUI error")):
                app = dashboard.build_dashboard(root, repo)

                def workspace(name, values):
                    app.workspace.set(name)
                    app.render_workspace()
                    app.fill_form(app.work_form, values)

                workspace("项目空间", {"key": "demo", "title": "Synthetic workspace"})
                app.execute_workspace("create", True)
                self.assertEqual(repo.feature("spaces", {"action": "get", "key": "demo"})["space"]["title"], "Synthetic workspace")

                workspace("任务接续卡", {"key": "demo-task", "space": "demo", "goal": "Verify a synthetic workflow", "next_steps": ["Run example"], "files": ["example.txt"]})
                task = app.execute_workspace("save", True)["task"]
                self.assertEqual(task["next_steps"], ["Run example"])
                closed = app.execute_workspace("close", True)["task"]
                self.assertEqual(closed["status"], "completed")

                workspace("流程与失败经验", {"space": "demo", "title": "Synthetic workflow", "content": "Use this example only in a test environment.", "steps": ["Open the fixture", "Read the result"], "prerequisites": ["Fixture exists"], "success_criteria": ["Result matches fixture"], "environment": {"runtime": "Python"}})
                procedure = app.execute_workspace("save", True)["procedure"]
                memory_id = procedure["memory_id"]
                self.assertEqual(procedure["steps"], ["Open the fixture", "Read the result"])

                workspace("流程结果反馈", {"memory_id": memory_id, "notes": "Synthetic execution matched the success criteria."})
                app.execute_workspace("get", False)
                app.execute_workspace("feedback", True)
                verified = app.execute_workspace("feedback", True)["procedure"]
                self.assertEqual(verified["success_count"], 2)
                workspace("流程与失败经验", {"memory_id": memory_id})
                draft = app.execute_workspace("skill_draft", False)
                self.assertIn("## Steps", draft["skill_draft"])
                self.assertFalse(draft["installed"])

                workspace("有依据的主题摘要", {"space": "demo", "topic": "Synthetic workflow", "conclusion": "This synthetic workflow was verified twice.", "citations": [{"id": memory_id, "revision": verified["revision"]}], "inference": False})
                summary = app.execute_workspace("save", True)["summary"]
                self.assertFalse(summary["inference"])

                fixture = Path(folder) / "fixture.txt"
                fixture.write_text("synthetic initial value", encoding="utf-8")
                workspace("文件与版本", {"path": str(fixture), "memory_ids": [memory_id]})
                app.execute_workspace("attach", True)
                fixture.write_text("synthetic changed value", encoding="utf-8")
                changed = app.execute_workspace("check", True)["file"]
                self.assertTrue(changed["changed"])

                workspace("使用反馈", {"memory_id": memory_id, "outcome": "useful", "context": "Synthetic fixture task", "scope": "demo"})
                self.assertFalse(app.execute_workspace(None, True)["memory_changed"])
                workspace("个人资料视图", {"space": "demo", "fields": ["Synthetic workflow", "Unknown example field"]})
                profile = app.execute_workspace(None, False)
                self.assertEqual(profile["fields"][1]["status"], "unknown")
                workspace("任务记忆包", {"space": "demo", "query": "Synthetic workflow"})
                packet = app.execute_workspace(None, False)
                self.assertIsInstance(packet, dict)
                app.graph_space.set("demo")
                app.load_graph()
                app.load_health()
                app.maintain()
                root.update_idletasks()
            self.assertEqual(root.state(), "withdrawn")


if __name__ == "__main__":
    unittest.main()
