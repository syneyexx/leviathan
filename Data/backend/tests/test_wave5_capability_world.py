"""Wave 5 — Capability world interface exit gates (U161–U200 foundations).

Exit gate: one run moves between API / MCP / browser actions without leaving
the shared Run / Job / Gateway / Evidence / receipt trace.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.browser import BrowserAction, BrowserWorker
from Data.modules.cognition import CapabilityBroker
from Data.modules.common.correlation import new_id
from Data.modules.evidence import EvidenceService, EvidenceStore
from Data.modules.execution import (
    CapabilityProviderKind,
    CapabilityReceiptStore,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.function_runtime.types import SideEffect
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.mcp import McpBridge, McpProvider, McpStore
from Data.modules.mcp.limits import McpLimits
from Data.modules.observations import ObservationStore
from Data.modules.plugins import PluginRegistry
from Data.modules.run import RunStore
from Data.modules.security import SecretsBroker


FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


class CapabilityMetadataTests(unittest.TestCase):
    def test_normalized_metadata_and_schema_hash(self) -> None:
        catalog = build_default_catalog()
        nav = catalog.require("browser.navigate")
        self.assertEqual(nav.provider_kind, CapabilityProviderKind.BROWSER)
        meta = nav.normalized_metadata()
        self.assertIn("browser", meta["tags"])
        self.assertIn("browser", meta["domains"])
        self.assertTrue(meta["truth"]["metadata_is_not_authorization"])
        self.assertTrue(nav.resolved_schema_hash())
        public = nav.public_dict()
        self.assertEqual(public["metadata"]["schema_version"], meta["schema_version"])


class SemanticShortlistTests(unittest.TestCase):
    def test_broker_shortlists_browser_by_alias(self) -> None:
        catalog = build_default_catalog()
        broker = CapabilityBroker(catalog)
        short = broker.search("open page navigate web", limit=8)
        self.assertIn("browser.navigate", short.capability_ids)
        self.assertTrue(short.inspected)
        self.assertTrue(
            any("Semantic shortlist" in note for note in short.notes)
        )


class SecretsBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "sec.db"
        self.broker = SecretsBroker(
            self.db,
            overrides={"secret:wave5_token": "SUPER_SECRET_WAVE5_TOKEN"},
            default_ttl_seconds=120,
        )
        self.broker.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lease_hides_plaintext_and_redacts(self) -> None:
        lease = self.broker.issue(
            "secret:wave5_token",
            scope="browser.auth",
            issued_to="worker:browser",
            run_id="run-1",
        )
        public = lease.public_dict()
        self.assertNotIn("SUPER_SECRET", str(public))
        self.assertTrue(public["truth"]["raw_tokens_never_in_model_prompts"])
        plain = self.broker.resolve_lease(lease.lease_id, issued_to="worker:browser")
        self.assertEqual(plain, "SUPER_SECRET_WAVE5_TOKEN")
        redacted = self.broker.redact_for_prompt(f"token={plain}")
        self.assertNotIn("SUPER_SECRET_WAVE5_TOKEN", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)


class FixtureBrowserWorkerTests(unittest.TestCase):
    def test_navigate_extract_screenshot_fixture(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            artifacts = ArtifactStore(root / "a.db", root / "artifacts")
            artifacts.initialize()
            worker = BrowserWorker(artifact_store=artifacts)
            nav = worker.execute(
                action=BrowserAction.NAVIGATE,
                arguments={"url": "https://example.com/wave5"},
                run_id="run-browser",
            )
            self.assertEqual(nav["status"], "COMPLETED")
            self.assertEqual(nav["backend"], "fixture")
            session_id = nav["session_id"]
            text = worker.execute(
                action=BrowserAction.EXTRACT_TEXT,
                arguments={"session_id": session_id},
                run_id="run-browser",
            )
            self.assertIn("Fixture page", text["observation"]["dom_text"])
            shot = worker.execute(
                action=BrowserAction.SCREENSHOT,
                arguments={"session_id": session_id},
                run_id="run-browser",
            )
            self.assertTrue(shot.get("artifact_id"))
            # Session isolation across runs
            with self.assertRaises(PermissionError):
                worker.execute(
                    action=BrowserAction.EXTRACT_TEXT,
                    arguments={"session_id": session_id},
                    run_id="other-run",
                )
        finally:
            tmp.cleanup()


class CapabilityWorldExitGateTests(unittest.TestCase):
    """One shared run/trace across API + MCP + browser via Gateway/Jobs/Evidence."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "wave5.db"
        MigrationRunner(self.db).apply_all()

        self.runs = RunStore(self.db)
        self.runs.initialize()
        self.artifacts = ArtifactStore(self.db, self.root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(
            self.db, data_root=self.root / "corp", chunk_max_chars=200, chunk_overlap=20
        )
        self.knowledge.initialize()
        (self.root / "corp").mkdir(parents=True, exist_ok=True)
        self.knowledge.upsert_document(
            title="Wave5",
            content="Capability world interface shares Run Job Gateway Evidence.",
            source="wave5",
        )
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.catalog = build_default_catalog()
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.obs = ObservationStore(self.db)
        self.obs.initialize()
        self.receipts = CapabilityReceiptStore(self.db)
        self.receipts.initialize()
        self.evidence_store = EvidenceStore(self.db)
        self.evidence_store.initialize()
        self.evidence = EvidenceService(
            self.evidence_store, artifacts=self.artifacts, observations=self.obs
        )

        self.plugins = PluginRegistry(self.catalog)
        self.mcp_store = McpStore(self.db)
        self.mcp_store.initialize()
        self.bridge = McpBridge(
            store=self.mcp_store,
            catalog=self.catalog,
            plugin_registry=self.plugins,
            enabled=True,
            stdio_enabled=True,
            http_enabled=False,
            auto_expand_modules=False,
            allow_outbound=False,
            limits=McpLimits(
                max_restart_attempts=2,
                restart_window_seconds=60.0,
                circuit_open_seconds=1.0,
                startup_timeout_seconds=10.0,
            ),
        )
        self.bridge.initialize()
        self.mcp_provider = McpProvider(self.bridge)
        self.browser = BrowserWorker(artifact_store=self.artifacts)

        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            knowledge_store=self.knowledge,
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=self.obs,
            mcp_executor=self.mcp_provider,
            browser_executor=self.browser,
            receipt_store=self.receipts,
        )
        self.jobs = JobRuntime(JobStore(self.db), self.gateway, ResourceManager(2))
        self.jobs.store.initialize()

    def tearDown(self) -> None:
        self.bridge.shutdown()
        self.fn.shutdown()
        self.tmp.cleanup()

    def _approve(self, capability_id: str, *, run_id: str) -> str:
        defn = self.catalog.require(capability_id)
        rec = self.approvals.request(
            capability_id=capability_id,
            side_effects=defn.side_effects,
            requested_by="wave5-test",
            run_id=run_id,
            reason="wave5 exit gate",
        )
        self.approvals.approve(rec.approval_id, decided_by="operator")
        return rec.approval_id

    def test_shared_trace_across_api_mcp_browser(self) -> None:
        run = self.runs.create_run(user_request="wave5 capability world exit gate")
        trace_id = run.trace_id or new_id("tr_")
        run_id = run.run_id

        # 1) API/function capability via Gateway
        note = self.root / "note.txt"
        note.write_text("api-leg", encoding="utf-8")
        api_result = self.gateway.execute(
            CapabilityRequest(
                capability_id="file.read",
                arguments={"path": str(note)},
                run_id=run_id,
                trace_id=trace_id,
                requested_by="wave5-api",
            )
        )
        self.assertEqual(api_result.status, CapabilityStatus.COMPLETED)

        # 2) MCP capability via same Gateway
        cfg = self.bridge.register_server(
            display_name="wave5-fake",
            transport="stdio",
            source_kind="manual",
            source_key="wave5-fake",
            command=sys.executable,
            args=[str(FAKE_SERVER), "--mode=normal"],
            enabled=True,
            trust="manual",
            semantic_effects={"echo": ["READ"], "add": ["READ"]},
            requested_isolation="subprocess",
            expand_tools=True,
        )
        self.bridge.connect(cfg.server_id)
        tools = self.bridge.list_tools(server_id=cfg.server_id)
        echo = next(t for t in tools if t.external_name == "echo")
        mcp_result = self.gateway.execute(
            CapabilityRequest(
                capability_id=echo.capability_id,
                arguments={"text": "mcp-leg"},
                run_id=run_id,
                trace_id=trace_id,
                requested_by="wave5-mcp",
            )
        )
        self.assertEqual(mcp_result.status, CapabilityStatus.COMPLETED)

        # 3) Browser via Job → Gateway (fixture, no Chromium)
        approval_id = self._approve("browser.navigate", run_id=run_id)
        job = self.jobs.enqueue(
            capability_id="browser.navigate",
            arguments={"url": "https://example.com/wave5-exit"},
            run_id=run_id,
            approval_id=approval_id,
            requested_by="wave5-browser",
            trace_id=trace_id,
            idempotency_key=f"browser-nav-{run_id}",
        )
        processed = self.jobs.process_next()
        self.assertIsNotNone(processed)
        final = self.jobs.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state.value, "COMPLETED")
        output = (final.result or {}).get("output") or {}
        session_id = output.get("session_id")
        self.assertTrue(session_id)

        extract = self.gateway.execute(
            CapabilityRequest(
                capability_id="browser.extract_text",
                arguments={"session_id": session_id},
                run_id=run_id,
                trace_id=trace_id,
                requested_by="wave5-browser",
            )
        )
        self.assertEqual(extract.status, CapabilityStatus.COMPLETED)
        self.assertIn("Fixture page", (extract.output or {}).get("observation", {}).get("dom_text", ""))

        # Shared receipts / observations / evidence lineage
        receipts = self.receipts.list_for_run(run_id)
        self.assertGreaterEqual(len(receipts), 3)
        receipt_caps = {r.capability_id for r in receipts}
        self.assertIn("file.read", receipt_caps)
        self.assertTrue(any(c.startswith("mcp.") for c in receipt_caps) or echo.capability_id in receipt_caps)
        self.assertIn("browser.navigate", receipt_caps)
        for receipt in receipts:
            self.assertEqual(receipt.run_id, run_id)
            self.assertEqual(receipt.trace_id, trace_id)
            self.assertTrue(receipt.public_dict()["truth"]["receipt_is_immutable_audit"])

        by_trace = self.receipts.list_for_trace(trace_id)
        self.assertGreaterEqual(len(by_trace), 3)

        obs_ids = [r.observation_id for r in receipts if r.observation_id]
        self.assertTrue(obs_ids)
        evidence = self.evidence.claim_observation_ref(
            observation_id=obs_ids[0],
            claim="Wave5 observation exists on shared run",
            run_id=run_id,
            job_id=job.job_id,
        )
        self.assertEqual(evidence.run_id, run_id)
        self.assertTrue(evidence.public_dict()["evidence_id"])


if __name__ == "__main__":
    unittest.main()
