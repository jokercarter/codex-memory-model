"""Feature acceptance tests use fabricated records and temporary databases only."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import codex_memory_core as core
import codex_memory_features as features


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        self.conn = core.connect(self.path)
        features.ensure_schema(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def call(self, name, **args):
        return features.dispatch(self.conn, "codex_memory_" + name, args)

    def fact(self, title="Example fact", content="Fictional example", **args):
        return core.commit_memory(self.conn, title=title, content=content, **args)

    def procedure(self):
        return self.call("procedure", action="save", title="Synthetic document rendering", content="Render a fabricated input using an explicitly supplied tool.", steps=["Read supplied input", "Run the selected renderer", "Inspect the output"], prerequisites=["Input exists"], success_criteria=["Output matches supplied input"], environment={"renderer": "example-v1"}, verified_at="2026-01-01T00:00:00Z", evidence=["Synthetic fixture validation"], request_id="procedure-create")

    def test_project_versions_and_idempotency(self):
        first = self.call("spaces", action="create", key="example", title="Example project", request_id="space-first")
        again = self.call("spaces", action="create", key="example", title="Example project", request_id="space-first")
        self.assertEqual(first, again)
        with self.assertRaises(ValueError):
            self.call("spaces", action="create", key="example", title="Wrong request reuse", request_id="space-first")
        with self.assertRaises(ValueError):
            self.call("spaces", action="create", key="example", title="No version supplied")
        revised = self.call("spaces", action="create", key="example", title="Updated project", expected_version=1)
        self.assertEqual(revised["version"], 2)

    def test_tasks_have_separate_capacity_expiry_and_concurrency(self):
        before = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        task = self.call("task", action="save", key="example-card", goal="Finish a fictional report", completed=["Outline"], next_steps=["Draft"], files=["example.txt"], questions=["Audience?"], ttl_hours=1)
        self.assertEqual(task["task"]["next_steps"], ["Draft"])
        self.assertEqual(before, self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        with self.assertRaises(ValueError):
            self.call("task", action="close", key="example-card", expected_version=9)
        payload = json.loads(self.conn.execute("SELECT payload FROM cm_tasks WHERE key='example-card'").fetchone()[0])
        payload["expires_at"] = "2020-01-01T00:00:00Z"
        self.conn.execute("UPDATE cm_tasks SET payload=? WHERE key='example-card'", (json.dumps(payload),))
        self.conn.commit()
        self.assertTrue(self.call("task", action="get", key="example-card")["task"]["expired"])
        packet = self.call("packet", query="fictional report")
        self.assertEqual(packet["tasks"], [])
        closed = self.call("task", action="close", key="example-card", expected_version=1)
        self.assertEqual(closed["task"]["status"], "completed")

    def test_derived_profile_reports_unknown_and_preserves_count(self):
        self.fact(title="Preferred response language", content="Example user prefers English.", memory_key="response.language", aliases=["language"])
        before = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        view = self.call("profile", fields=["language", "missing-field"])
        self.assertEqual([field["status"] for field in view["fields"]], ["known", "unknown"])
        self.assertEqual(before, self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def test_summary_citation_versions_inference_and_staleness(self):
        fact = self.fact(memory_key="example.current", aliases=["example"])
        memory = dict(core.get(self.conn, fact["id"]))
        summary = self.call("reflect", action="save", topic="Example", conclusion="An interpretation of the synthetic example.", citations=[{"id": memory["id"], "revision": memory["revision"]}])
        self.assertEqual(summary["summary"]["label"], "inference")
        self.assertFalse(summary["summary"]["stale"])
        self.fact(content="Updated synthetic example", memory_key="example.current", replace_ids=[memory["id"]], expected_revision=memory["revision"])
        self.assertTrue(self.call("reflect", action="get", topic="Example")["summary"]["stale"])
        with self.assertRaises(ValueError):
            self.call("reflect", action="save", topic="Wrong", conclusion="Stale assertion", citations=[{"id": memory["id"], "revision": memory["revision"]}])

    def test_procedure_validation_feedback_and_skill_draft(self):
        result = self.procedure()
        memory_id = result["procedure"]["memory_id"]
        with self.assertRaises(ValueError):
            self.call("procedure", action="skill_draft", memory_id=memory_id)
        for version in (1, 2):
            self.call("procedure", action="feedback", memory_id=memory_id, outcome="success", notes=f"Synthetic validation run {version}", expected_version=version, request_id=f"execution-{version}")
        draft = self.call("procedure", action="skill_draft", memory_id=memory_id)
        self.assertIn("## Success criteria", draft["skill_draft"])
        self.assertFalse(draft["installed"])
        self.call("procedure", action="feedback", memory_id=memory_id, outcome="failure", notes="Synthetic failure", expected_version=3)
        with self.assertRaises(ValueError):
            self.call("procedure", action="skill_draft", memory_id=memory_id)

    def test_file_change_flags_derived_sources_and_detects_missing(self):
        result = self.procedure()
        memory_id = result["procedure"]["memory_id"]
        memory = dict(core.get(self.conn, memory_id))
        self.call("reflect", action="save", topic="File linked example", conclusion="Synthetic linked source", citations=[{"id": memory_id, "revision": memory["revision"]}], inference=False)
        path = Path(self.temp.name) / "input.txt"
        path.write_text("version one", encoding="utf-8")
        attached = self.call("file", action="attach", path=str(path), memory_ids=[memory_id])
        self.assertFalse(attached["file"]["changed"])
        path.write_text("version two", encoding="utf-8")
        checked = self.call("file", action="check", path=str(path), expected_version=1)
        self.assertTrue(checked["file"]["changed"])
        self.assertTrue(self.call("procedure", action="get", memory_id=memory_id)["procedure"]["stale"])
        self.assertTrue(self.call("reflect", action="get", topic="File linked example")["summary"]["stale"])
        path.unlink()
        missing = self.call("file", action="check", path=str(path), expected_version=2)
        self.assertEqual(missing["file"]["current"]["state"], "missing")

    def test_feedback_is_scoped_and_does_not_overwrite_fact(self):
        item = self.fact()
        self.call("spaces", action="create", key="course", title="Fictional course")
        before = dict(core.get(self.conn, item["id"]))
        result = self.call("feedback", memory_id=item["id"], outcome="incorrect", scope="course", context="Only in this fictional course", correction="Proposed replacement", request_id="feedback-example")
        self.assertEqual(result["correction_status"], "pending_confirmation")
        self.assertEqual(before, dict(core.get(self.conn, item["id"])))
        self.assertFalse(any(issue["type"] == "reported_incorrect" for issue in self.call("health")["issues"]))
        self.assertTrue(any(issue["type"] == "reported_incorrect" for issue in self.call("health", space="course")["issues"]))

    def test_read_tools_are_query_only_and_health_graph_work(self):
        first = self.fact(title="First fictional fact", memory_key="first")
        second = self.fact(title="Second fictional fact", content="Other synthetic content", memory_key="second")
        core.set_relation(self.conn, first["id"], second["id"], "supports", 70)
        self.conn.commit()
        readonly = core.connect(self.path, read_only=True)
        try:
            for name, args in [("spaces", {}), ("profile", {"fields": ["first"]}), ("health", {}), ("graph", {}), ("maintenance", {}), ("packet", {"query": "fictional"}), ("reflect", {"topic": "fictional"})]:
                self.assertTrue(features.is_read_only("codex_memory_" + name, args))
                features.dispatch(readonly, "codex_memory_" + name, args)
            graph = features.dispatch(readonly, "codex_memory_graph", {})
            self.assertTrue(any(edge["type"] == "supports" for edge in graph["edges"]))
            with self.assertRaises(sqlite3.OperationalError):
                features.dispatch(readonly, "codex_memory_task", {"action": "save", "key": "forbidden-write", "goal": "Should fail"})
        finally:
            readonly.close()

    def test_validation_failure_rolls_back_feature_and_core_writes(self):
        before = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        with self.assertRaises(ValueError):
            self.call("procedure", action="save", title="Invalid", content="Invalid fixture", steps=["one"], success_criteria=[])
        self.assertEqual(before, self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cm_procedures").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
