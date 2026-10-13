import os
import tempfile
import unittest
from pathlib import Path

import codex_memory_core as core


class CoreV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "memory.db"
        self.conn = core.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def add(self, title, content, **kwargs):
        return core.commit_memory(self.conn, title=title, content=content,
                                  importance=kwargs.pop("importance", 40), **kwargs)

    def test_importance_stays_durable_while_activity_changes_on_actual_use(self):
        record = self.add("Durable preference", "Use Python for this project")
        core.mark_used(self.conn, [record["id"]], request_id="turn-1")
        row = core.get(self.conn, record["id"])
        self.assertEqual(row["importance"], 40)
        self.assertEqual(row["activity"], 75)
        self.assertEqual(row["use_count"], 1)

    def test_scenario_memories_are_scoped_and_global_rules_are_inherited(self):
        global_rule = self.add("Language", "Answer in Chinese", scope="global")
        job_rule = self.add("Resume rule", "Use the confirmed resume", scope="scenario",
                            scenarios=["jobs"])
        study_rule = self.add("Homework rule", "Show complete derivations", scope="scenario",
                              scenarios=["study"])
        result = core.search(self.conn, "unrelated wording", space="global",
                             scenarios=["jobs"], limit=10)
        ids = {item["id"] for item in result}
        self.assertIn(global_rule["id"], ids)
        self.assertIn(job_rule["id"], ids)
        self.assertNotIn(study_rule["id"], ids)

    def test_replacement_keeps_previous_revision_and_rejects_stale_writer(self):
        old = self.add("Graduation date", "May 2028", memory_key="graduation-date")
        updated = self.add("Graduation date", "December 2028", memory_key="graduation-date",
                           replace_ids=[old["id"]], expected_revision=1)
        self.assertEqual(updated["revision"], 2)
        versions = core.history(self.conn, old["id"])
        self.assertEqual([item["revision"] for item in versions], [1, 2])
        self.assertEqual(versions[0]["snapshot"]["content"], "May 2028")
        with self.assertRaisesRegex(RuntimeError, "revision_conflict"):
            self.add("Graduation date", "January 2029", memory_key="graduation-date",
                     replace_ids=[old["id"]], expected_revision=1)

    def test_chinese_subphrase_retrieval_and_token_budget(self):
        self.add("LaTeX PDF workflow", "Use XeLaTeX to compile the PDF without intermediate files",
                 aliases=["Tex 编译流程"])
        results = core.search(self.conn, "编译生成 PDF", aliases=["XeLaTeX"], limit=8,
                              token_budget=256)
        self.assertTrue(results)
        self.assertIn("revision", results[0]["citation"])
        self.assertLessEqual(len(core.format_context(results, token_budget=256)), 1600)

    def test_snapshot_restore_creates_safety_snapshot(self):
        first = self.add("Snapshot fact", "before")
        snapshot = core.snapshot(self.conn, "test")
        self.add("Snapshot fact", "after", memory_key="snapshot-fact", replace_ids=[first["id"]], expected_revision=1)
        result = core.restore_snapshot(self.conn, snapshot["id"])
        self.assertEqual(result["restored_snapshot_id"], snapshot["id"])
        self.assertTrue(Path(core.list_snapshots(self.conn)[0]["path"]).exists())

    def test_request_id_cannot_be_reused_for_different_memory_content(self):
        self.add("One fact", "first", request_id="once")
        with self.assertRaisesRegex(ValueError, "different operation"):
            self.add("One fact", "different", request_id="once")

    def test_legacy_migration_keeps_local_backup_and_routes_topics(self):
        self.conn.close()
        legacy = Path(self.temp.name) / "legacy.db"
        raw = __import__("sqlite3").connect(legacy)
        raw.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY,title TEXT,content TEXT,tags TEXT,category TEXT,importance INTEGER,source TEXT,created_at TEXT,updated_at TEXT,memory_key TEXT,status TEXT,confidence REAL,source_session TEXT,last_reviewed_at TEXT,use_count INTEGER,always_apply INTEGER)")
        raw.execute("INSERT INTO memories VALUES(1,'Handshake resume','Use the confirmed resume','Handshake,resume','流程',80,'verified','2026-01-01','2026-01-01','resume','active',1,'','2026-01-01',3,1)")
        raw.commit();raw.close()
        migrated=core.connect(legacy)
        row=core.get(migrated,1)
        self.assertEqual(row["scope"],"scenario")
        self.assertIn("jobs",row["scenarios"])
        self.assertTrue(row["always_apply"])
        self.assertTrue(row["needs_review"])
        self.assertTrue(row["needs_review"])
        backups=list((Path(self.temp.name)/"backups").glob("pre-v2-migration-*.sqlite"))
        self.assertEqual(len(backups),1)
        old=__import__("sqlite3").connect(backups[0])
        self.assertEqual(old.execute("SELECT content FROM memories WHERE id=1").fetchone()[0],"Use the confirmed resume")
        old.close();migrated.close();self.conn=core.connect(self.path)


if __name__ == "__main__":
    unittest.main()
