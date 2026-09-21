"""Focused capability-suite regressions: artifacts, approvals, MCP, memory, schedule, build, search."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from approvals import ApprovalService, arguments_fingerprint
from artifacts import ArtifactService, can_generate_format
from build_agent import BuildAgentService, FileEdit
from database import Database
from global_search import GlobalSearchService
from inbox import InboxService
from platform_db import PlatformDatabase
from schedules import ScheduleService, compute_next_run, preview_occurrences


class CapabilitySuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "hades.db"
        self.database = Database(str(self.db_path))
        self.database.initialize()
        self.platform = PlatformDatabase(str(self.db_path))
        self.platform.initialize()
        self.inbox = InboxService(self.platform)
        self.artifacts = ArtifactService(self.platform, self.root)
        self.approvals = ApprovalService(self.platform, self.inbox)
        self.schedules = ScheduleService(self.platform, self.inbox)
        self.search = GlobalSearchService(self.database, self.platform)
        self.build = BuildAgentService(self.root, self.artifacts)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_artifact_json_csv_checksum_and_restart(self) -> None:
        json_art = self.artifacts.create_text_result(
            name="result.json",
            text='{"ok": true, "n": 2}',
            mime_type="application/json",
            conversation_id="c1",
        )
        csv_art = self.artifacts.create_text_result(
            name="result.csv",
            text="a,b\n1,2\n",
            mime_type="text/csv",
            conversation_id="c1",
        )
        self.assertEqual(json_art["status"], "ready")
        self.assertEqual(csv_art["status"], "ready")
        verify = self.artifacts.verify_ready(json_art["id"])
        self.assertTrue(verify["checks"]["ok"])
        # Restart simulation: new service on same DB/files
        again = ArtifactService(PlatformDatabase(str(self.db_path)), self.root)
        loaded = again.get(json_art["id"])
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["checksum_sha256"], json_art["checksum_sha256"])
        _item, data = again.read_bytes(csv_art["id"])
        self.assertIn(b"1,2", data)
        ok, reason = can_generate_format("report.pdf")
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            self.artifacts.create_text_result(name="fake.pdf", text="%PDF", mime_type="application/pdf")
        failed = self.platform.list_artifacts(kind="generated")
        self.assertTrue(any(item["status"] == "failed" and item["name"] == "fake.pdf" for item in failed))

    def test_approval_atomic_and_argument_binding(self) -> None:
        req = self.approvals.create_tool_approval(
            plugin_id="demo",
            tool_name="write_file",
            arguments={"path": "a.txt", "content": "x"},
            expected_effect="Schrijf a.txt",
            schema_version="1",
            scope={"project": "p1"},
        )
        first = self.approvals.decide(req["id"], approve=True)
        second = self.approvals.decide(req["id"], approve=True)
        self.assertEqual(first["status"], "approved")
        self.assertEqual(second["decision_at"], first["decision_at"])
        with self.assertRaises(PermissionError):
            self.approvals.assert_reusable(
                req["id"],
                tool_name="write_file",
                arguments={"path": "a.txt", "content": "CHANGED"},
                schema_version="1",
                scope={"project": "p1"},
            )
        # Block policy cannot be satisfied by an approval button path
        blocked = self.approvals.create_tool_approval(
            plugin_id="demo",
            tool_name="net",
            arguments={"url": "http://example"},
            expected_effect="net",
        )
        with self.assertRaises(PermissionError):
            self.approvals.decide(blocked["id"], approve=True, current_permissions={"network_policy": "block"})

    def test_client_request_dedup_and_branch_isolation(self) -> None:
        conversation = self.database.create_conversation("Dedup")
        self.database.store_deduped_response(conversation["id"], "req-1", {"ok": True, "n": 1})
        self.assertEqual(self.database.get_deduped_response(conversation["id"], "req-1")["n"], 1)
        m1 = self.database.add_message(conversation["id"], "user", "Vraag A")
        a1 = self.database.add_message(conversation["id"], "assistant", "Antwoord A")
        branch = self.database.create_branch(conversation["id"], m1["id"], title="Alt")
        self.database.deactivate_messages_after(conversation["id"], m1["id"])
        with self.database.connection() as db:
            db.execute("UPDATE messages SET is_active=1, branch_id=? WHERE id=?", (branch["id"], m1["id"]))
        m2 = self.database.add_message(conversation["id"], "user", "Vraag B", branch_id=branch["id"])
        active = self.database.list_messages(conversation["id"], branch_id=branch["id"])
        ids = {item["id"] for item in active}
        self.assertIn(m1["id"], ids)
        self.assertIn(m2["id"], ids)
        self.assertNotIn(a1["id"], ids)

    def test_activate_branch_restores_lineage(self) -> None:
        conversation = self.database.create_conversation("Switch")
        m1 = self.database.add_message(conversation["id"], "user", "Vraag A")
        a1 = self.database.add_message(conversation["id"], "assistant", "Antwoord A")
        branch = self.database.create_branch(conversation["id"], m1["id"], title="Alt")
        self.database.deactivate_messages_after(conversation["id"], m1["id"])
        with self.database.connection() as db:
            db.execute("UPDATE messages SET is_active=1, branch_id=? WHERE id=?", (branch["id"], m1["id"]))
        a2 = self.database.add_message(conversation["id"], "assistant", "Antwoord B", branch_id=branch["id"])
        activated = self.database.activate_branch(conversation["id"], branch["id"])
        self.assertTrue(activated["is_active"])
        visible = self.database.list_messages(conversation["id"], branch_id=branch["id"])
        visible_ids = {item["id"] for item in visible}
        self.assertIn(m1["id"], visible_ids)
        self.assertIn(a2["id"], visible_ids)
        self.assertNotIn(a1["id"], visible_ids)
        conv = self.database.get_conversation(conversation["id"])
        self.assertEqual(conv["active_branch_id"], branch["id"])

    def test_memory_proposal_correction_and_forget_derived(self) -> None:
        proposal = self.database.create_memory_proposal(
            {
                "title": "Voorkeursthema",
                "content": "Gebruiker houdt van donker thema",
                "summary": "donker",
                "origin_kind": "model_inference",
                "source_conversation_id": "c1",
            }
        )
        accepted = self.database.decide_memory_proposal(
            proposal["id"],
            action="edit",
            edited={"content": "Gebruiker houdt van licht thema", "title": "Voorkeursthema"},
        )
        memory = accepted["memory"]
        self.assertIn("licht", memory["content"])
        corrected = self.database.supersede_memory(
            memory["id"],
            {
                "title": "Voorkeursthema",
                "content": "Gebruiker houdt van licht thema met hoog contrast",
                "summary": "licht/contrast",
                "collection": "Voorkeuren",
                "tags": ["ui"],
                "source": "Correctie",
                "origin_kind": "user_fact",
            },
        )
        history = self.database.memory_history(corrected["id"])
        self.assertGreaterEqual(len(history), 2)
        conversation = self.database.create_conversation("Forget me")
        self.database.add_message(conversation["id"], "user", "geheim geheimwoord-xyz")
        self.platform.upsert_knowledge_source(
            title="Gesprek",
            source_type="conversation",
            uri=f"conversation:{conversation['id']}",
            metadata={"conversation_id": conversation["id"]},
        )
        self.platform.replace_knowledge_chunks(
            self.platform.list_knowledge_sources()[0]["id"],
            "Gesprek",
            [{"text": "geheim geheimwoord-xyz", "ordinal": 0}],
        )
        self.database.forget_memory(corrected["id"])
        self.assertEqual(self.database.get_memory(corrected["id"])["status"], "forgotten")
        active = self.database.list_memories(query="licht")
        self.assertEqual(active, [])
        self.platform.mark_knowledge_forgotten(f"conversation:{conversation['id']}")
        hits = self.platform.search_knowledge("geheimwoord-xyz", limit=5)
        self.assertEqual(hits, [])

    def test_schedule_occurrence_dedup_overlap_and_disabled(self) -> None:
        clock = {"now": datetime(2026, 3, 28, 10, 0, tzinfo=UTC)}
        svc = ScheduleService(self.platform, self.inbox, clock=lambda: clock["now"])
        task = self.database.create_task("Daily", "doe werk", "executor", "normal", None)
        schedule = svc.attach_schedule(
            task["id"],
            frequency="daily",
            timezone="UTC",
            time_of_day="09:00",
            enabled=True,
        )
        self.assertTrue(schedule["next_run_at"] <= "2026-03-29T09:00:00+00:00")
        # Move past due
        clock["now"] = datetime(2026, 3, 29, 9, 5, tzinfo=UTC)
        due = svc.due_schedules()
        self.assertEqual(len(due), 1)
        first = svc.claim_occurrence(due[0])
        self.assertIsNotNone(first)
        second = svc.claim_occurrence(self.platform.get_task_schedule(schedule["id"]))
        self.assertIsNone(second)
        # Disabled does not fire
        other = self.database.create_task("Once", "x", "executor", "low", None)
        disabled = svc.attach_schedule(
            other["id"],
            frequency="once",
            timezone="UTC",
            run_at="2026-03-29T08:00:00+00:00",
            enabled=False,
        )
        self.assertEqual(svc.due_schedules(), [])
        # DST-safe weekly preview still returns wall-clock times
        preview = preview_occurrences(frequency="weekly", timezone="Europe/Amsterdam", time_of_day="09:30", weekday=0, count=3)
        self.assertEqual(len(preview), 3)

    def test_build_agent_patch_and_conflict(self) -> None:
        repo = self.root / "fixture_repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3), 5)\n",
            encoding="utf-8",
        )
        result = self.build.run_repair_loop(
            repo,
            [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a + b\n")],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=1,
        )
        self.assertEqual(result.status, "verified")
        self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")
        # Mutate source then apply -> conflict
        (repo / "app.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
        conflicts = self.build.check_apply_conflicts(result.run_id)
        self.assertTrue(conflicts)
        applied = self.build.apply_to_source(result.run_id, approved=True)
        self.assertEqual(applied["status"], "conflict")

    def test_global_search_groups_and_commands(self) -> None:
        conversation = self.database.create_conversation("Zoekalpha project")
        self.database.add_message(conversation["id"], "user", "bericht met zoekalpha token")
        self.database.save_memory(
            {
                "title": "Memory zoekalpha",
                "content": "inhoud zoekalpha",
                "summary": "zoekalpha",
                "collection": "Tests",
                "tags": ["zoekalpha"],
                "source": "test",
                "origin_kind": "user_fact",
            }
        )
        task = self.database.create_task("Taak zoekalpha", "prompt", "executor", "normal", None)
        art = self.artifacts.create_text_result(name="zoekalpha.txt", text="hello", mime_type="text/plain")
        result = self.search.search("zoekalpha")
        self.assertIn("conversations", result["groups"])
        self.assertIn("messages", result["groups"])
        self.assertIn("memories", result["groups"])
        self.assertIn("tasks", result["groups"])
        self.assertIn("artifacts", result["groups"])
        self.assertTrue(any(cmd["id"] == "new_chat" for cmd in result["commands"]))
        # Forgotten memory excluded
        self.database.forget_memory(self.database.list_memories(query="zoekalpha")[0]["id"])
        again = self.search.search("zoekalpha")
        self.assertNotIn("memories", again["groups"])

    def test_mcp_bridge_notification_pagination_and_is_error(self) -> None:
        fixture = self.root / "mcp_fixture_server.py"
        fixture.write_text(
            r'''
import json, sys
tools_page1 = [{"name": "alpha", "description": "A", "inputSchema": {"type": "object"}}, {"name": "beta", "description": "B", "inputSchema": {"type": "object"}}]
tools_page2 = [{"name": "gamma", "description": "C", "inputSchema": {"type": "object"}}]
def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
# notification before any response
send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "hello"}})
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    req_id = req.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fixture", "version": "1"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        cursor = (req.get("params") or {}).get("cursor")
        if not cursor:
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_page1, "nextCursor": "p2"}})
        else:
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_page2}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "boom"}], "isError": True}})
    else:
        send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown"}})
''',
            encoding="utf-8",
        )
        bridge = Path(__file__).resolve().parents[2] / "plugins" / "_shared" / "mcp_bridge.py"
        list_proc = subprocess.run(
            [sys.executable, str(bridge), "--action", "list_tools", "--", sys.executable, str(fixture)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        listed = json.loads(list_proc.stdout)
        names = {tool["name"] for tool in listed["tools"]}
        self.assertEqual(names, {"alpha", "beta", "gamma"})
        self.assertTrue(any(n.get("method") == "notifications/message" for n in listed.get("notifications") or []))
        call_proc = subprocess.run(
            [
                sys.executable,
                str(bridge),
                "--action",
                "call_tool",
                "--tool",
                "alpha",
                "--arguments",
                "{}",
                "--",
                sys.executable,
                str(fixture),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(call_proc.returncode, 1, call_proc.stdout)
        called = json.loads(call_proc.stdout)
        self.assertTrue(called.get("isError"))

    def test_migration_preserves_existing_user_rows(self) -> None:
        # Simulate older DB then re-initialize
        older = self.root / "legacy.db"
        import sqlite3

        conn = sqlite3.connect(older)
        conn.executescript(
            """
            CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT, model_id TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE messages(id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, created_at TEXT);
            CREATE TABLE memories(id TEXT PRIMARY KEY, title TEXT, content TEXT, summary TEXT, collection TEXT, tags TEXT, source TEXT, created_at TEXT, updated_at TEXT);
            INSERT INTO conversations VALUES('c_old','Oud','m','2020-01-01','2020-01-01');
            INSERT INTO messages VALUES('m_old','c_old','user','hello','2020-01-01');
            INSERT INTO memories VALUES('mem_old','T','C','S','A','[]','src','2020-01-01','2020-01-01');
            """
        )
        conn.commit()
        conn.close()
        db = Database(str(older))
        db.initialize()
        platform = PlatformDatabase(str(older))
        platform.initialize()
        self.assertEqual(db.get_conversation("c_old")["title"], "Oud")
        self.assertEqual(db.list_messages("c_old")[0]["content"], "hello")
        self.assertTrue(hasattr(platform, "insert_artifact"))


if __name__ == "__main__":
    unittest.main()
