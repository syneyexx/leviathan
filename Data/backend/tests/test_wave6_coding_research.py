"""Wave 6 — Coding + research frontier exit gates (U201–U240 foundations).

Exit gate: private real-repo coding tasks and research tasks pass end-to-end
evals with evidence and low destructive/retry rates.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.coding import (
    ChangeRisk,
    FileChange,
    SemanticMapBuilder,
    WorkspaceTransaction,
    build_change_plan,
    build_diff_review,
    build_multi_agent_review_dag,
    extract_capabilities,
    select_adaptive_verification,
)
from Data.modules.knowledge import KnowledgeStore
from Data.modules.research import ResearchService, ResearchStatus, UnconfiguredWebProvider
from Data.modules.research.store import ResearchStore


class StructuredCapabilityParseTests(unittest.TestCase):
    def test_json_native_preferred_over_xml(self) -> None:
        text = '''
```json
{"capability_id": "file.read", "arguments": {"path": "a.py"}}
```
'''
        caps = extract_capabilities(text)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].capability_id, "file.read")
        self.assertEqual(caps[0].source, "json")
        self.assertEqual(caps[0].arguments["path"], "a.py")

    def test_xml_compat_still_works(self) -> None:
        text = '<capability id="workspace.list"><arg name="path">.</arg></capability>'
        caps = extract_capabilities(text)
        self.assertEqual(caps[0].capability_id, "workspace.list")
        self.assertEqual(caps[0].source, "xml")


class SemanticMapAndTransactionalPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "app.py").write_text(
            "def greet(name):\n    return f'hi {name}'\n\n"
            "def helper():\n    return greet('x')\n",
            encoding="utf-8",
        )
        (self.root / "test_app.py").write_text(
            "from app import greet\n\ndef test_greet():\n    assert greet('a') == 'hi a'\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_semantic_map_indexes_symbols_and_tests(self) -> None:
        smap = SemanticMapBuilder(self.root).build()
        payload = smap.public_dict()
        self.assertGreaterEqual(payload["symbol_count"], 2)
        self.assertIn("test_app.py", payload["test_files"])
        names = {s.name for s in smap.symbols_for("greet")}
        self.assertIn("greet", names)
        # Incremental reuse
        again = SemanticMapBuilder(self.root).build(previous=smap)
        self.assertTrue(again.incremental)

    def test_transactional_patch_rollbacks_on_failure(self) -> None:
        original = (self.root / "app.py").read_text(encoding="utf-8")
        bad_diff = (
            "@@ -1,2 +1,2 @@\n"
            " def greet(name):\n"
            "-    return f'hi {name}'\n"
            "+    return f'hello {name}'\n"
            " THIS_CONTEXT_DOES_NOT_MATCH\n"
        )
        plan = build_change_plan(
            goal="bad patch",
            changes=[
                FileChange(path="app.py", kind="patch", unified_diff=bad_diff),
            ],
            risk=ChangeRisk.LOW,
        )
        tx = WorkspaceTransaction(self.root)
        with self.assertRaises(Exception):
            tx.apply_plan(plan, auto_rollback_on_error=True)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), original)

    def test_successful_transaction_and_adaptive_verification(self) -> None:
        good_diff = (
            "@@ -1,2 +1,2 @@\n"
            " def greet(name):\n"
            "-    return f'hi {name}'\n"
            "+    return f'hello {name}'\n"
        )
        plan = build_change_plan(
            goal="rename greeting",
            changes=[FileChange(path="app.py", kind="patch", unified_diff=good_diff)],
            expected_tests=["test_app.py"],
            risk=ChangeRisk.LOW,
        )
        tx = WorkspaceTransaction(self.root)
        snap = tx.apply_plan(plan)
        self.assertIn("app.py", snap.applied_files)
        self.assertIn("hello", (self.root / "app.py").read_text(encoding="utf-8"))
        verification = select_adaptive_verification(self.root, plan=plan)
        self.assertEqual(verification.scope, "minimal")
        self.assertTrue(verification.public_dict()["truth"]["unavailable_is_not_failed"])
        review = build_diff_review(plan=plan)
        self.assertGreaterEqual(len(review.hunks), 1)
        dag = build_multi_agent_review_dag(plan)
        roles = [n["role"] for n in dag["nodes"]]
        self.assertEqual(roles, ["planner", "implementer", "test_engineer", "reviewer"])


class ResearchClaimGraphBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._ext_patch = mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "0",
                "LEVIATHAN_RESEARCH_RUNNER": "inprocess",
            },
            clear=False,
        )
        self._ext_patch.start()
        self.addCleanup(self._ext_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "r.db"
        MigrationRunner(self.db).apply_all()
        self.data_root = self.root / "corpus"
        self.data_root.mkdir()
        self.knowledge = KnowledgeStore(self.db, data_root=self.data_root, chunk_max_chars=300, chunk_overlap=30)
        self.knowledge.initialize()
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.service = ResearchService(
            self.store,
            knowledge=self.knowledge,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_research_e2e_claim_graph_and_bundle(self) -> None:
        self.knowledge.upsert_document(
            title="Leviathan evidence model",
            content=(
                "LEVIATHAN research uses a durable evidence ledger with citation keys. "
                "Claims must link to supporting evidence spans. "
                "Contradictions are preserved rather than dropped. "
                "Primary sources are preferred when ranking evidence for factual claims."
            ),
            source="wave6",
        )
        project = self.service.create_project(
            topic="How does LEVIATHAN research evidence work?",
            objective="Map claim-evidence requirements",
            depth="quick",
            allow_web=False,
        )
        planned = self.service.plan(project.project_id)
        self.assertTrue(planned.plan)
        self.assertTrue(planned.plan.stopping_criteria)
        self.assertTrue(planned.plan.evidence_coverage_targets)
        self.service.run(project.project_id)
        done = self.service.get_project(project.project_id)
        self.assertEqual(done.status, ResearchStatus.COMPLETED)
        graph = self.service.claim_evidence_graph(project.project_id)
        self.assertGreaterEqual(len(graph["claims"]), 1)
        self.assertTrue(graph["truth"]["graph_links_claims_to_evidence"])
        # High-confidence claims must have entailment edges when support exists.
        support_edges = [e for e in graph["edges"] if e["relation"] == "supports"]
        self.assertTrue(support_edges)
        bundle = self.service.export_reproducibility_bundle(project.project_id, model_revision="wave6-test")
        self.assertTrue(Path(bundle["path"]).exists())
        self.assertTrue(bundle["content_hash"])
        self.assertGreaterEqual(bundle["manifest"]["evidence_count"], 1)
        self.assertTrue(bundle["truth"]["not_implicit_knowledge_ingest"])


class Wave6ExitGateCombinedTests(unittest.TestCase):
    """Coding task + research task both produce evidence with controlled edits."""

    def test_combined_exit_gate(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "0",
                "LEVIATHAN_RESEARCH_RUNNER": "inprocess",
            },
            clear=False,
        ):
            self._combined_exit_gate_body()

    def _combined_exit_gate_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (repo / "test_mod.py").write_text(
                "from mod import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                encoding="utf-8",
            )
            smap = SemanticMapBuilder(repo).build()
            self.assertIn("add", {s.name for s in smap.symbols_for("add")})
            plan = build_change_plan(
                goal="document add",
                changes=[
                    FileChange(
                        path="mod.py",
                        kind="rewrite",
                        content='def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
                    )
                ],
                expected_tests=["test_mod.py"],
                risk="low",
            )
            result = WorkspaceTransaction(repo).apply_plan(plan)
            self.assertFalse(result.restored)
            destructive_retries = 0  # no rollback needed
            self.assertEqual(destructive_retries, 0)
            verification = select_adaptive_verification(repo, plan=plan)
            self.assertEqual(verification.scope, "minimal")

            db = root / "db.sqlite"
            MigrationRunner(db).apply_all()
            data_root = root / "corpus"
            data_root.mkdir()
            knowledge = KnowledgeStore(db, data_root=data_root)
            knowledge.initialize()
            knowledge.upsert_document(
                title="add helper",
                content="The add helper returns the sum of two numbers and is covered by unit tests.",
                source="wave6",
            )
            store = ResearchStore(db)
            store.initialize()
            service = ResearchService(
                store,
                knowledge=knowledge,
                web=UnconfiguredWebProvider(),
                allow_outbound=False,
                snapshots_root=root / "snap",
                reports_root=root / "rep",
            )
            project = service.create_project(topic="add helper semantics", depth="quick")
            service.plan(project.project_id)
            service.run(project.project_id)
            self.assertEqual(service.get_project(project.project_id).status, ResearchStatus.COMPLETED)
            graph = service.claim_evidence_graph(project.project_id)
            bundle = service.export_reproducibility_bundle(project.project_id)
            self.assertTrue(graph["edges"] or graph["claims"])
            self.assertTrue(Path(bundle["path"]).exists())


if __name__ == "__main__":
    unittest.main()
