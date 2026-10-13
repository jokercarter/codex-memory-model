import os
import tempfile
import unittest
from pathlib import Path

import codex_memory_core as core
import codex_memory_mcp as mcp


class McpPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.previous=os.environ.get("CODEX_MEMORY_DB")
        os.environ["CODEX_MEMORY_DB"]=str(Path(self.temp.name)/"memory.db")

    def tearDown(self):
        if self.previous is None:os.environ.pop("CODEX_MEMORY_DB",None)
        else:os.environ["CODEX_MEMORY_DB"]=self.previous
        self.temp.cleanup()

    def test_feature_tool_commits_schema_and_write_before_connection_close(self):
        result=mcp.call_tool("codex_memory_spaces",{"action":"create","key":"project-a","title":"Project A"})
        self.assertFalse(result["isError"])
        read=core.connect(read_only=True)
        try:
            self.assertIsNotNone(read.execute("SELECT 1 FROM cm_spaces WHERE key='project-a'").fetchone())
        finally:read.close()

    def test_empty_store_stats_and_uninitialized_read_tools_are_read_only(self):
        stats=mcp.call_tool("codex_memory_stats",{})
        self.assertFalse(stats["isError"])
        self.assertEqual(stats["structuredContent"]["active"],0)
        read=mcp.call_tool("codex_memory_spaces",{"action":"get","key":"missing"})
        self.assertFalse(read["isError"])
        self.assertFalse(read["structuredContent"]["initialized"])
        self.assertFalse(Path(os.environ["CODEX_MEMORY_DB"]).exists())

    def test_mcp_commit_then_read_reopens_full_versioned_memory(self):
        saved=mcp.call_tool("codex_memory_commit",{
            "title":"Verified workflow","content":"Run migration then inspect its status",
            "importance":72,"kind":"procedure","scope":"scenario","scenarios":["coding"],
            "memory_key":"migration-status","request_id":"mcp-write-1"})
        self.assertFalse(saved["isError"])
        memory_id=saved["structuredContent"]["id"]
        read=mcp.call_tool("codex_memory_get",{"memory_id":memory_id})
        self.assertEqual(read["structuredContent"]["memory"]["content"],"Run migration then inspect its status")
        self.assertEqual(read["structuredContent"]["memory"]["revision"],1)

    def test_typed_relation_is_persisted_and_can_be_reweighted(self):
        left=mcp.call_tool("codex_memory_commit",{"title":"A","content":"A","memory_key":"a","request_id":"a"})["structuredContent"]["id"]
        right=mcp.call_tool("codex_memory_commit",{"title":"B","content":"B","memory_key":"b","request_id":"b"})["structuredContent"]["id"]
        first=mcp.call_tool("codex_memory_relation",{"a":left,"b":right,"relation_type":"prerequisite","strength":80,"evidence":"reviewed","request_id":"edge-1"})
        self.assertFalse(first["isError"])
        again=mcp.call_tool("codex_memory_relation",{"a":left,"b":right,"relation_type":"prerequisite","strength":25,"evidence":"updated review","request_id":"edge-2"})
        self.assertFalse(again["isError"])
        conn=core.connect(read_only=True)
        try:
            edge=conn.execute("SELECT strength,evidence_count FROM memory_edges WHERE relation_type='prerequisite'").fetchone()
            self.assertEqual((edge["strength"],edge["evidence_count"]),(25,2))
        finally:conn.close()


if __name__=="__main__":unittest.main()
