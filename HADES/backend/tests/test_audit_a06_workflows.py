"""A06 — Workflows / Agent Factory executable via real runtimes."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import ArtifactService
from build_agent import BuildAgentService
from coding_agent import CodingAgentService
from gen2.services import Gen2Services
from gen2.store import Gen2Store
from gen2.workflow_adapters import PRODUCT_ACTIONS, resolve_bindings, workflow_definition_hash
from gen2.workflows import (
    create_from_template,
    create_workflow,
    dry_run,
    promote_workflow,
    sandbox_run,
)
from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService, ResearchRunner, WebResearchService


class _FakePlatformDb(PlatformDatabase):
    """Minimal platform DB rooted in a temp directory."""


class A06WorkflowAdaptersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "gen2.db"))
        self.platform_db = PlatformDatabase(str(self.root / "platform.db"))
        self.platform_db.initialize()
        self.artifact_service = ArtifactService(self.platform_db, self.root)
        self.build = BuildAgentService(self.root, self.artifact_service)
        self.coding = CodingAgentService(self.build)
        self.knowledge = KnowledgeService(self.platform_db, self.root)
        self.web = WebResearchService(self.knowledge)

        async def _resolver(_model):
            return "local-test", {"temperature": 0.2, "max_tokens": 500}

        class _Client:
            async def chat(self, payload):
                return {
                    "choices": [{"message": {"content": "Synthese uit lokale fixtures."}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
                }

        self.research = ResearchRunner(
            self.platform_db,
            self.knowledge,
            self.web,
            _resolver,
            lambda: _Client(),
            lambda model_id, profile, messages: {
                "model": model_id,
                "messages": messages,
                **profile,
            },
            lambda: "block",
            lambda: {},
        )
        self.svc = Gen2Services(self.store, data_root=self.root, artifact_service=self.artifact_service)
        self.svc.set_workflow_runtime(
            coding_agent=self.coding,
            research_runner=self.research,
            plugin_manager=None,
            platform_db=self.platform_db,
            chat_fn=None,
            approval_service=None,
            artifact_service=self.artifact_service,
            data_root=self.root,
        )
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.svc.record = _record  # type: ignore[method-assign]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _buggy_repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir(exist_ok=True)
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        return repo

    def _research_fixture(self) -> Path:
        folder = self.root / "research_src"
        folder.mkdir(exist_ok=True)
        (folder / "notes.md").write_text(
            "# Local research fixture\n\nHADES offline research provenance test.\n"
            "Claim A: widgets are blue.\nClaim B: widgets are not blue under water.\n",
            encoding="utf-8",
        )
        return folder

    def test_product_actions_registered(self) -> None:
        self.assertIn("coding_agent", PRODUCT_ACTIONS)
        self.assertIn("research_runner", PRODUCT_ACTIONS)
        self.assertIn("plugin_invoke", PRODUCT_ACTIONS)
        self.assertIn("model_chat", PRODUCT_ACTIONS)
        self.assertIn("artifact_persist", PRODUCT_ACTIONS)

    def test_bindings_pass_typed_upstream_outputs(self) -> None:
        ctx = {"steps": {"repair": {"outputs": {"status": "verified", "ok": True}}}}
        resolved = resolve_bindings(
            {"goal": "{{inputs.goal}}", "ok": "{{steps.repair.outputs.ok}}"},
            ctx=ctx,
            run_inputs={"goal": "fix add"},
        )
        self.assertEqual(resolved["goal"], "fix add")
        self.assertIs(resolved["ok"], True)

    def test_sandbox_refuses_product_actions_and_no_fake_tokens(self) -> None:
        row = create_from_template(self.store, self.svc.record, "coding")
        sand = sandbox_run(self.store, self.svc.record, row["id"])
        self.assertFalse(sand["live_execution"])
        self.assertFalse(sand.get("product_ready"))
        self.assertFalse(sand["passed"])
        details = [s.get("detail") for s in sand.get("step_results") or []]
        self.assertTrue(any(d == "product_action_requires_product_mode" for d in details), details)
        self.assertIsNone((sand.get("metrics") or {}).get("cost_tokens"))
        # Sandbox must not promote product coding to Ready.
        with self.assertRaises(ValueError) as ctx:
            promote_workflow(self.store, self.svc.record, row["id"], target="tested")
        self.assertIn("product-run", str(ctx.exception).lower())

    def test_heritage_demo_sandbox_still_works_without_product_ready(self) -> None:
        row = create_from_template(self.store, self.svc.record, "coding_demo")
        sand = sandbox_run(self.store, self.svc.record, row["id"])
        self.assertTrue(sand["passed"])
        self.assertFalse(sand.get("product_ready"))
        self.assertFalse(sand["live_execution"])
        promote_workflow(self.store, self.svc.record, row["id"], target="tested")
        refreshed = self.store.get_workflow(row["id"])
        self.assertEqual(refreshed["status"], "tested")

    def test_coding_product_workflow_repairs_isolated_repo(self) -> None:
        repo = self._buggy_repo()
        row = create_from_template(self.store, self.svc.record, "coding")
        result = self.svc.product_run_workflow(
            row["id"],
            run_inputs={
                "goal": "Repareer de fout in add",
                "source_repo": str(repo),
                "test_args": ["test_app.py"],
                "preapproved": True,
            },
            async_mode=False,
            blocking=True,
        )
        self.assertTrue(result.get("live_execution"))
        self.assertTrue(result.get("passed"), result)
        self.assertTrue(result.get("product_ready"))
        self.assertEqual(result.get("mode"), "product")
        # Source untouched; worktree fixed.
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))
        repair = next(s for s in result["step_results"] if s.get("action") == "coding_agent")
        work = Path(str((repair.get("outputs") or {}).get("work_root")))
        self.assertTrue(work.is_dir())
        self.assertIn("return a + b", (work / "app.py").read_text(encoding="utf-8"))
        # Independent verification: re-run tests in worktree.
        import subprocess
        import sys

        (work / "__init__.py").write_text("", encoding="utf-8")
        probe = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(work), "-p", "test_*.py"],
            cwd=str(work),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stdout + "\n" + probe.stderr)
        # Durable artifact persisted.
        self.assertTrue(result.get("artifacts"))
        # Honest tokens — not +8/step fiction.
        usage = (result.get("metrics") or {}).get("usage") or {}
        self.assertIn(usage.get("source"), {"not_measured", "measured"})
        if usage.get("source") == "not_measured":
            self.assertIsNone(usage.get("total_tokens"))

    def test_research_product_workflow_local_fixtures_and_provenance(self) -> None:
        fixture = self._research_fixture()
        row = create_from_template(self.store, self.svc.record, "research")
        result = self.svc.product_run_workflow(
            row["id"],
            run_inputs={
                "topic": "widgets HADES offline research provenance",
                "source_inputs": [str(fixture)],
                "depth": "quick",
                "preapproved": True,
            },
            async_mode=False,
            blocking=True,
        )
        self.assertTrue(result.get("live_execution"), result)
        self.assertTrue(result.get("passed"), result)
        self.assertTrue(result.get("product_ready"))
        research_step = next(s for s in result["step_results"] if s.get("action") == "research_runner")
        outputs = research_step.get("outputs") or {}
        self.assertTrue(outputs.get("project_id"))
        self.assertTrue(str(outputs.get("report") or "").strip())
        arts = result.get("artifacts") or []
        self.assertTrue(arts)
        # Provenance present on durable artifact metadata path.
        self.assertTrue(any(a.get("kind") == "research_report" or a.get("provenance") for a in arts) or arts)
        project = self.platform_db.get_research_project(str(outputs["project_id"]))
        self.assertIsNotNone(project)
        self.assertTrue(str(project.get("report") or "").strip())

    def test_step_failure_stops_execution(self) -> None:
        definition = {
            "name": "fail-fast-coding",
            "fixture_kind": "product",
            "pattern_tags": ["coding", "product"],
            "permissions": {"network": "deny", "filesystem": "allow"},
            "offline_safe": True,
            "success_checks": ["all_steps_passed"],
            "steps": [
                {
                    "id": "plan",
                    "type": "action",
                    "action": "echo",
                    "inputs": {"message": "go"},
                    "depends_on": [],
                },
                {
                    "id": "repair",
                    "type": "action",
                    "action": "coding_agent",
                    "inputs": {
                        "goal": "fix missing",
                        "source_repo": str(self.root / "does_not_exist"),
                    },
                    "depends_on": ["plan"],
                },
                {
                    "id": "after",
                    "type": "action",
                    "action": "echo",
                    "inputs": {"message": "should not run"},
                    "depends_on": ["repair"],
                },
            ],
        }
        row = create_workflow(self.store, self.svc.record, definition)
        result = self.svc.product_run_workflow(
            row["id"],
            run_inputs={"preapproved": True},
            async_mode=False,
            blocking=True,
        )
        self.assertFalse(result.get("passed"))
        self.assertEqual(result.get("failed_step_id"), "repair")
        actions = [s.get("action") or s.get("id") for s in result.get("step_results") or []]
        self.assertNotIn("should not run", str(result.get("step_results")))
        self.assertTrue(any(s.get("id") == "repair" for s in result["step_results"]))
        self.assertFalse(any(s.get("id") == "after" and s.get("executed") for s in result["step_results"]))

    def test_product_promotion_hash_bound(self) -> None:
        repo = self._buggy_repo()
        row = create_from_template(self.store, self.svc.record, "coding")
        result = self.svc.product_run_workflow(
            row["id"],
            run_inputs={
                "goal": "Repareer de fout in add",
                "source_repo": str(repo),
                "test_args": ["test_app.py"],
                "preapproved": True,
            },
            async_mode=False,
            blocking=True,
        )
        self.assertTrue(result.get("passed"), result)
        before_hash = workflow_definition_hash(row.get("definition") or {})
        tested = promote_workflow(self.store, self.svc.record, row["id"], target="tested")
        self.assertEqual(tested["status"], "tested")
        evidence = (tested.get("definition") or {}).get("test_evidence") or {}
        self.assertEqual(evidence.get("last_product_definition_hash"), before_hash)
        # Mutate definition → hash mismatch blocks promote to promoted until re-run.
        mutated = dict(tested.get("definition") or {})
        mutated["description"] = "changed after test"
        self.store.update_workflow(row["id"], definition=mutated, status="tested")
        with self.assertRaises(ValueError):
            promote_workflow(
                self.store, self.svc.record, row["id"], human_approved=True, target="promoted"
            )

    def test_async_product_run_returns_immediately(self) -> None:
        repo = self._buggy_repo()
        row = create_from_template(self.store, self.svc.record, "coding")
        accepted = self.svc.product_run_workflow(
            row["id"],
            run_inputs={
                "goal": "Repareer de fout in add",
                "source_repo": str(repo),
                "test_args": ["test_app.py"],
                "preapproved": True,
            },
            async_mode=True,
            blocking=False,
        )
        self.assertIn(accepted.get("status"), {"queued", "running"})
        self.assertTrue(accepted.get("run_id"))
        run_id = accepted["run_id"]
        terminal = None
        for _ in range(60):
            snap = self.store.get_workflow_run(run_id)
            assert snap is not None
            if str(snap.get("status")) in {"passed", "failed", "cancelled", "timeout", "awaiting_human"}:
                terminal = snap
                break
            time.sleep(0.25)
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal["status"], "passed", terminal)

    def test_dry_run_labels_product_adapters(self) -> None:
        row = create_from_template(self.store, self.svc.record, "coding")
        dry = dry_run(self.store, self.svc.record, row["id"])
        self.assertFalse(dry["live_execution"])
        self.assertTrue(dry.get("product_workflow"))
        product_steps = [s for s in dry["plan"]["steps"] if s.get("product_adapter")]
        self.assertTrue(product_steps)


if __name__ == "__main__":
    unittest.main()
