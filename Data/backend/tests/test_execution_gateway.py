from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore


class ExecutionGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "test.db"
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(
            self.db_path,
            data_root=self.root / "corpus",
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        (self.root / "corpus").mkdir(parents=True, exist_ok=True)
        self.retriever = HybridRetriever(self.knowledge)
        self.registry = build_default_registry()
        self.runtime = FunctionRuntime(self.registry, max_concurrency=2, warm_cache_size=1)
        self.catalog = build_default_catalog()
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.runtime,
            knowledge_retriever=self.retriever,
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def test_catalog_builtins(self) -> None:
        ids = {item.id for item in self.catalog.list()}
        self.assertIn("file.read", ids)
        self.assertIn("file.inspect_csv", ids)
        self.assertIn("file.parse_pdf", ids)
        self.assertIn("knowledge.search", ids)
        self.assertIn("artifact.create_text", ids)

    def test_file_read_via_gateway(self) -> None:
        path = self.root / "note.txt"
        path.write_text("gateway-hello", encoding="utf-8")
        result = self.gateway.execute(
            CapabilityRequest(capability_id="file.read", arguments={"path": str(path)})
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        assert result.output is not None
        self.assertIn("gateway-hello", result.output["content"])
        self.assertEqual(result.provider_kind, "function")
        self.assertEqual(len(self.gateway.effect_ledger), 1)
        self.assertEqual(self.gateway.effect_ledger[0].capability_id, "file.read")

    def test_unknown_capability_rejected(self) -> None:
        result = self.gateway.execute(CapabilityRequest(capability_id="no.such.cap"))
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertIn("Unknown capability", result.error or "")
        self.assertEqual(result.telemetry.get("reason"), "unknown_capability")

    def test_validation_rejects_missing_args(self) -> None:
        result = self.gateway.execute(CapabilityRequest(capability_id="file.read", arguments={}))
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertIn("Missing required argument", result.error or "")

    def test_write_capability_requires_approval(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "x", "filename": "out.txt"},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertEqual(result.telemetry.get("reason"), "approval_required")
        self.assertGreaterEqual(self.gateway.telemetry["approval_required"], 1)

    def test_write_capability_with_verified_approval(self) -> None:
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
        )
        approved = self.approvals.approve(pending.approval_id, decided_by="operator")
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "approved text", "filename": "out.txt"},
                approval_id=approved.approval_id,
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        assert result.output is not None
        self.assertEqual(result.output["type"], "text")
        self.assertTrue(result.telemetry.get("approval_consumed"))
        consumed = self.approvals.get(approved.approval_id)
        assert consumed is not None
        self.assertEqual(consumed.status.value, "CONSUMED")

    def test_placeholder_approval_id_is_denied(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "x", "filename": "out.txt"},
                approval_id="phase9-placeholder",
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertEqual(result.telemetry.get("reason"), "approval_denied")

    def test_knowledge_search_capability(self) -> None:
        self.knowledge.upsert_document(
            title="Gateway Doc",
            content="leviathan capability broker search target",
            source="test",
            document_id="doc-gw-1",
        )
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="knowledge.search",
                arguments={"query": "capability broker", "limit": 3},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        assert result.output is not None
        self.assertGreaterEqual(result.output["count"], 1)


if __name__ == "__main__":
    unittest.main()
