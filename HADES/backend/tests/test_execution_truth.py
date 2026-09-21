"""Authoritative execution/persistence truth — LLM cannot fake success."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from execution_truth import (
    BackendExecutionState,
    PersistenceResult,
    ToolExecutionResult,
    build_execution_result_artifact_payload,
    collect_tool_executions,
    decide_route_completion,
    ground_assistant_message,
    make_persistence_result,
    message_claims_success,
    parse_model_action_proposal,
    resolve_sqlite_paths,
    strip_model_authority_fields,
    tool_execution_from_invoke,
    verify_rows_exist,
)
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService
from run_lifecycle import decide_work_task_completion


class ModelAuthorityStripTests(unittest.TestCase):
    def test_strips_success_fields_from_proposal(self) -> None:
        proposal = parse_model_action_proposal(
            {
                "tool": "newsfeeder",
                "args": {"topic": "ai"},
                "status": "completed",
                "knowledge_updated": True,
                "success": True,
            }
        )
        self.assertEqual(proposal.requested_tool, "newsfeeder")
        self.assertNotIn("knowledge_updated", proposal.raw)
        self.assertNotIn("success", proposal.raw)
        self.assertEqual(proposal.requested_next_state, "completed")

    def test_strip_nested(self) -> None:
        cleaned = strip_model_authority_fields({"a": 1, "status": "completed", "nested": {"saved": True, "x": 2}})
        self.assertEqual(cleaned, {"a": 1, "nested": {"x": 2}})


class FakeSuccessClaimTests(unittest.TestCase):
    def test_llm_knowledge_updated_without_tool_is_not_success(self) -> None:
        state = BackendExecutionState(request_id="req1")
        status, reason = decide_route_completion(
            verification_called=False,
            verification_allowed=None,
            tool_executions=[],
            persistence_results=[],
            required_tools=True,
            required_persistence=True,
        )
        self.assertEqual(status, "failed")
        self.assertIn("required_tool", reason)
        text, notes = ground_assistant_message(
            "Mijn kennis is geüpdatet. NewsFeeder is gebruikt. status: completed",
            state,
        )
        self.assertIn("runtime-waarheid", text.lower())
        self.assertIn("ungrounded_success_claims_stripped", notes)
        self.assertFalse(state.persistence_verified)
        self.assertEqual(state.saved_knowledge_count, 0)

    def test_status_completed_without_tool_cannot_complete_task(self) -> None:
        decision = decide_work_task_completion(
            checkpoint_state={"phase": "executed", "passed": True, "status": "completed", "knowledge_updated": True},
            steps=[{"status": "pending"}],
            required_tools_succeeded=False,
        )
        self.assertFalse(decision.may_complete)
        self.assertTrue(any("required_tools" in b or "pending" in b or "phase" in b for b in decision.blockers))


class ToolExecutionTruthTests(unittest.TestCase):
    def test_tool_failure_not_success(self) -> None:
        result = tool_execution_from_invoke(
            {"id": "tc1", "plugin_id": "news", "tool_name": "feed", "status": "failed", "exit_code": 1, "error": "boom"}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        state = BackendExecutionState(request_id="r", tool_executions=[result])
        state.emit("TOOL_FAILED", execution_id=result.execution_id)
        self.assertFalse(state.any_tool_succeeded)
        status, reason = decide_route_completion(
            verification_called=True,
            verification_allowed=True,
            tool_executions=[result],
            required_tools=True,
        )
        self.assertEqual(status, "failed")
        self.assertIn("tool", reason)

    def test_model_nested_success_false_forces_failed(self) -> None:
        from reasoning.tool_engine import normalize_tool_result_status

        row = normalize_tool_result_status(
            {"status": "completed", "exit_code": 0, "structured_output": {"success": False, "knowledge_updated": True}}
        )
        self.assertEqual(row["status"], "failed")
        self.assertNotIn("knowledge_updated", row.get("structured_output") or {})


class PersistenceFailureTests(unittest.TestCase):
    def test_insert_failure_blocks_success_claim(self) -> None:
        pers = make_persistence_result(
            entity_type="knowledge",
            requested_count=10,
            inserted_ids=[],
            verified_ids=[],
            error="disk full",
            error_type="PersistenceError",
        )
        self.assertFalse(pers.success)
        self.assertFalse(pers.verification_passed)
        state = BackendExecutionState(
            request_id="r",
            tool_executions=[
                ToolExecutionResult(
                    execution_id="e1",
                    tool_id="news/feed",
                    plugin_id="news",
                    tool_name="feed",
                    status="succeeded",
                    success=True,
                )
            ],
            persistence_results=[pers],
            required_persistence=True,
        )
        text, notes = ground_assistant_message("12 kennisitems zijn opgeslagen via NewsFeeder.", state)
        self.assertIn("0", text)  # truth block reports 0 verified
        self.assertIn("ungrounded_success_claims_stripped", notes)

    def test_readback_failure_not_completed(self) -> None:
        pers = make_persistence_result(
            entity_type="knowledge",
            requested_count=1,
            inserted_ids=["src_1"],
            verified_ids=[],
        )
        self.assertFalse(pers.verification_passed)
        self.assertFalse(pers.success)
        status, reason = decide_route_completion(
            verification_called=True,
            verification_allowed=True,
            tool_executions=[
                ToolExecutionResult(
                    execution_id="e1",
                    tool_id="t",
                    status="succeeded",
                    success=True,
                )
            ],
            persistence_results=[pers],
            required_tools=True,
            required_persistence=True,
        )
        self.assertEqual(status, "failed")
        self.assertIn("persistence", reason)


class VerifiedSuccessPathTests(unittest.TestCase):
    def test_tool_and_persistence_verified_allows_accurate_report(self) -> None:
        pers = make_persistence_result(
            entity_type="knowledge",
            requested_count=2,
            inserted_ids=["src_a", "src_b"],
            verified_ids=["src_a", "src_b"],
        )
        self.assertTrue(pers.success)
        self.assertTrue(pers.verification_passed)
        state = BackendExecutionState(
            request_id="r",
            tool_executions=[
                ToolExecutionResult(
                    execution_id="e1",
                    tool_id="news/feed",
                    plugin_id="news",
                    tool_name="feed",
                    status="succeeded",
                    success=True,
                )
            ],
            persistence_results=[pers],
            route_status="completed",
            verification_called=True,
            verification_passed=True,
        )
        text, notes = ground_assistant_message("2 kennisitems zijn opgeslagen via NewsFeeder.", state)
        self.assertNotIn("ungrounded_success_claims_stripped", notes)
        self.assertEqual(state.saved_knowledge_count, 2)
        self.assertIn("claims_aligned_with_execution_truth", notes)
        self.assertEqual(text, "2 kennisitems zijn opgeslagen via NewsFeeder.")

    def test_results_payload_from_backend_truth(self) -> None:
        state = BackendExecutionState(
            request_id="req",
            chat_id="c1",
            tool_executions=collect_tool_executions(
                [{"id": "tc1", "plugin_id": "p", "tool_name": "t", "status": "completed", "exit_code": 0}]
            ),
            persistence_results=[
                make_persistence_result(
                    entity_type="knowledge",
                    requested_count=1,
                    inserted_ids=["src_1"],
                    verified_ids=["src_1"],
                )
            ],
            route_status="completed",
        )
        payload = build_execution_result_artifact_payload(state)
        self.assertEqual(payload["schema"], "hades.execution_result.v1")
        self.assertEqual(payload["grounding"]["saved_knowledge_count"], 1)
        self.assertTrue(payload["grounding"]["tool_success"])


class KnowledgeRestartPersistenceTests(unittest.TestCase):
    def test_knowledge_survives_backend_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "hades.db")
            data_root = Path(tmp)
            db = PlatformDatabase(db_path)
            db.initialize()
            svc = KnowledgeService(db, data_root)
            result = svc.ingest_text(
                title="News batch",
                text="Item one about AI.\n\nItem two about robotics.",
                source_type="plugin",
                uri="plugin:newsfeeder:batch1",
                metadata={"plugin_id": "ultimate-news-feeder"},
            )
            self.assertTrue((result.get("persistence") or {}).get("verification_passed"))
            source_id = result["id"]
            # Close by dropping references and reopening — simulates restart.
            del svc
            del db
            db2 = PlatformDatabase(db_path)
            db2.initialize()
            svc2 = KnowledgeService(db2, data_root)
            again = db2.get_knowledge_source(source_id)
            self.assertIsNotNone(again)
            chunks = db2.list_knowledge_chunks(source_id, limit=100)
            self.assertGreaterEqual(len(chunks), 1)
            # Second connection must still see the same verified row.
            verified = verify_rows_exist(
                entity_type="knowledge",
                ids=[source_id],
                fetch_one=db2.get_knowledge_source,
                required_fields=["id", "uri", "status"],
            )
            self.assertTrue(verified.verification_passed)

    def test_memory_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "hades.db")
            core = Database(db_path)
            core.initialize()
            saved = core.save_memory(
                {
                    "title": "Besluit",
                    "content": "Gebruiker wil offline-first.",
                    "summary": "offline-first",
                    "collection": "Projectkennis",
                    "tags": ["test"],
                    "source": "unit",
                }
            )
            self.assertTrue((saved.get("persistence") or {}).get("verification_passed"))
            mem_id = saved["id"]
            del core
            core2 = Database(db_path)
            core2.initialize()
            again = core2.get_memory(mem_id)
            self.assertIsNotNone(again)
            self.assertIn("offline-first", again["content"])


class AssistantGroundingForcedFailureTests(unittest.TestCase):
    def test_failed_persistence_blocks_save_claim(self) -> None:
        state = BackendExecutionState(
            request_id="r",
            tool_executions=[
                ToolExecutionResult(
                    execution_id="e",
                    tool_id="news/feed",
                    status="succeeded",
                    success=True,
                    plugin_id="news",
                    tool_name="feed",
                )
            ],
            persistence_results=[
                PersistenceResult(
                    operation_id="p1",
                    entity_type="knowledge",
                    requested_count=5,
                    inserted_count=0,
                    inserted_ids=[],
                    verified_count=0,
                    success=False,
                    verification_passed=False,
                    error="commit_failed",
                )
            ],
            route_status="failed",
        )
        grounded, notes = ground_assistant_message("Mijn kennis is geüpdatet", state)
        self.assertIn("ungrounded_success_claims_stripped", notes)
        self.assertIn("geen geverifieerde kennispersistentie", grounded.lower())

    def test_verified_success_may_report_count(self) -> None:
        state = BackendExecutionState(
            request_id="r",
            persistence_results=[
                make_persistence_result(
                    entity_type="knowledge",
                    requested_count=12,
                    inserted_ids=[f"id{i}" for i in range(12)],
                    verified_ids=[f"id{i}" for i in range(12)],
                )
            ],
            tool_executions=[
                ToolExecutionResult(
                    execution_id="e",
                    tool_id="news/feed",
                    status="succeeded",
                    success=True,
                    plugin_id="news",
                    tool_name="feed",
                )
            ],
            route_status="completed",
        )
        grounded, notes = ground_assistant_message("12 kennisitems zijn opgeslagen via NewsFeeder.", state)
        self.assertIn("claims_aligned_with_execution_truth", notes)
        self.assertEqual(state.grounding_context()["saved_count"], 12)


class SqlitePathDiagnosticsTests(unittest.TestCase):
    def test_resolve_paths_are_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "data" / "hades.db")
            paths = resolve_sqlite_paths(database_path=db_path)
            self.assertTrue(Path(paths["sqlite_path"]).is_absolute())
            self.assertIn("hades.db", paths["sqlite_path"])


class ArtifactResultsApiTests(unittest.TestCase):
    def test_execution_artifact_listable(self) -> None:
        from artifacts import ArtifactService

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "hades.db")
            pdb = PlatformDatabase(db_path)
            pdb.initialize()
            arts = ArtifactService(pdb, Path(tmp))
            state = BackendExecutionState(
                request_id="req_art",
                chat_id="conv1",
                tool_executions=collect_tool_executions(
                    [{"id": "tc", "plugin_id": "p", "tool_name": "echo", "status": "completed", "exit_code": 0}]
                ),
                persistence_results=[
                    make_persistence_result(
                        entity_type="knowledge",
                        requested_count=1,
                        inserted_ids=["src"],
                        verified_ids=["src"],
                    )
                ],
                route_status="completed",
            )
            payload = build_execution_result_artifact_payload(state)
            item = arts.create_text_result(
                name="execution-req_art.json",
                text=json.dumps(payload),
                kind="generated",
                mime_type="application/json",
                conversation_id="conv1",
                metadata={"schema": "hades.execution_result.v1", "success": True, "persistence_verified": True},
            )
            listed = arts.list(conversation_id="conv1")
            self.assertTrue(any(row["id"] == item["id"] for row in listed))
            ready = arts.verify_ready(item["id"])
            self.assertTrue(ready["checks"]["ok"])


class MessageClaimDetectionTests(unittest.TestCase):
    def test_dutch_and_english_claims(self) -> None:
        self.assertTrue(message_claims_success("Mijn kennis is geüpdatet"))
        self.assertTrue(message_claims_success("NewsFeeder is gebruikt"))
        self.assertTrue(message_claims_success("knowledge_updated=true"))
        self.assertFalse(message_claims_success("Wat is de hoofdstad van Frankrijk?"))


if __name__ == "__main__":
    unittest.main()
