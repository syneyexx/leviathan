"""Wave 2 control-plane honesty: research block, empty workflow, call_id merge source."""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ResearchBlockedNetworkHonestyTests(unittest.TestCase):
    def test_send_message_stamps_research_blocked_network(self) -> None:
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("research_blocked_network", source)
        self.assertIn("needs_research", source)

    def test_research_intent_with_network_block_keeps_local_answer_honest(self) -> None:
        from reasoning.understanding import (
            build_request_spec,
            build_route_decision,
            extract_task_features,
        )

        text = "Zoek actuele informatie over Python 3.13 release notes"
        spec = build_request_spec(text)
        features = extract_task_features(spec)
        route = build_route_decision(
            spec,
            requested_profile="adaptive",
            network_policy="block",
            plugin_tools_enabled=True,
            features=features,
        )
        self.assertTrue(spec.needs_research)
        self.assertFalse(route.allow_web)
        self.assertNotEqual(route.target, "research")


class EmptyWorkflowCompletionTests(unittest.TestCase):
    def test_sandbox_empty_steps_fail_not_completed(self) -> None:
        from gen2.store import Gen2Store
        from gen2.workflow_executor import execute_sandbox

        tmp = tempfile.TemporaryDirectory()
        try:
            store = Gen2Store(str(Path(tmp.name) / "gen2.db"))
            store.initialize()
            wf = store.create_workflow(
                {
                    "name": "empty",
                    "definition": {"version": 1, "steps": [], "success_checks": []},
                }
            )
            record = mock.MagicMock()
            result = execute_sandbox(store, record, wf["id"])
            self.assertEqual(result.get("status"), "failed")
            self.assertFalse(result.get("passed"))
            # Empty IR is refused at validate OR empty_workflow gate — never "completed".
            note = str(result.get("note") or "")
            details = [s.get("detail") for s in (result.get("step_results") or [])]
            self.assertTrue(
                note == "empty_workflow"
                or "IR invalid" in note
                or "empty_workflow" in details
                or bool(result.get("validation_errors")),
                msg=f"unexpected empty-workflow failure shape: {result!r}",
            )
        finally:
            tmp.cleanup()

    def test_product_empty_steps_fail_not_completed(self) -> None:
        from gen2.store import Gen2Store
        from gen2.workflow_adapters import WorkflowServices
        from gen2.workflow_executor import _execute_product_body

        tmp = tempfile.TemporaryDirectory()
        try:
            store = Gen2Store(str(Path(tmp.name) / "gen2.db"))
            store.initialize()
            wf = store.create_workflow(
                {
                    "name": "empty-product",
                    "definition": {
                        "version": 1,
                        "fixture_kind": "product",
                        "steps": [],
                        "success_checks": [],
                    },
                }
            )
            run = store.create_workflow_run(
                workflow_id=wf["id"],
                version=1,
                mode="product",
                status="queued",
                result={},
            )
            result = _execute_product_body(
                store,
                mock.MagicMock(),
                wf["id"],
                run_id=run["id"],
                ir={
                    "version": 1,
                    "fixture_kind": "product",
                    "steps": [],
                    "success_checks": [],
                },
                run_inputs={},
                services=WorkflowServices(),
                timeout_seconds=5.0,
                definition_hash="empty",
            )
            self.assertEqual(result.get("status"), "failed")
            self.assertFalse(result.get("passed"))
            self.assertEqual(result.get("note"), "empty_workflow")
        finally:
            tmp.cleanup()


class ClassicChatCallIdMergeSourceTests(unittest.TestCase):
    def test_chat_page_uses_merge_helpers(self) -> None:
        page = Path(__file__).resolve().parents[2] / "components" / "hades" / "pages" / "chat-page.tsx"
        source = page.read_text(encoding="utf-8")
        self.assertIn("mergeChatToolCalls", source)
        self.assertIn("mergeLiveExecutionEvents", source)
        self.assertNotIn("...(current?.tools || []), ...progress.tools].slice(-30)", source)


if __name__ == "__main__":
    unittest.main()
