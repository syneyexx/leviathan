"""Tools control-plane read model / receipt / custom wrapper tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.custom_store import CustomCapabilityStore
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.metadata import normalize_capability_metadata
from Data.modules.execution.overview import build_tools_library, build_tools_overview
from Data.modules.execution.presentation import category_label, resolve_origin
from Data.modules.execution.receipts import (
    CapabilityCallReceipt,
    CapabilityReceiptStore,
    build_receipt_from_result,
)
from Data.modules.execution.types import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from Data.modules.function_runtime.types import SideEffect
from Data.modules.plugins.registry import PluginRegistry
from Data.modules.plugins.types import AdapterKind, PluginCapabilityBinding


class ToolsControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "control.db"
        self.catalog = build_default_catalog()
        self.receipts = CapabilityReceiptStore(self.db)
        self.receipts.initialize()
        self.custom = CustomCapabilityStore(self.db)
        self.custom.initialize()
        self.plugins = PluginRegistry(self.catalog)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_metadata_origin_and_version(self) -> None:
        meta = normalize_capability_metadata(
            {"origin": "custom", "version": "2.1.0", "domains": ["web"], "schema_version": 9},
            capability_id="custom.demo",
            name="Demo",
            description="d",
        )
        self.assertEqual(meta["origin"], "custom")
        self.assertEqual(meta["version"], "2.1.0")
        self.assertEqual(meta["schema_version"], 9)
        self.assertNotEqual(meta["version"], str(meta["schema_version"]))

    def test_resolve_origin_priority(self) -> None:
        self.assertEqual(resolve_origin({"origin": "custom"}, provider_kind="mcp"), "custom")
        self.assertEqual(resolve_origin({}, provider_kind="mcp"), "mcp")
        self.assertEqual(
            resolve_origin({}, provider_kind="module", in_plugin_bindings=True),
            "plugin",
        )
        self.assertEqual(resolve_origin({}, provider_kind="builtin"), "core")

    def test_category_label_unknown(self) -> None:
        self.assertEqual(category_label("web"), "Web")
        self.assertEqual(category_label("overig"), "Overig")
        self.assertEqual(category_label(""), "Overig")

    def test_receipt_requested_by_persisted(self) -> None:
        result = CapabilityResult(
            request_id="req-1",
            capability_id="file.read",
            status=CapabilityStatus.COMPLETED,
            output={"ok": True},
            provider_kind="function",
            provider_ref="text_file_read",
            telemetry={"duration_ms": 12.5},
        )
        request = CapabilityRequest(
            capability_id="file.read",
            arguments={"path": "x"},
            requested_by="tools-ui:operator",
        )
        receipt = build_receipt_from_result(
            result=result,
            request=request,
            authority_decision="allowed",
        )
        self.receipts.record(receipt)
        loaded = self.receipts.get(receipt.receipt_id)
        assert loaded is not None
        self.assertEqual(loaded.requested_by, "tools-ui:operator")
        self.assertEqual(loaded.latency_ms, 12.5)

    def test_receipt_aggregations(self) -> None:
        for i, status in enumerate(
            ["COMPLETED", "COMPLETED", "FAILED", "REJECTED", "TIMEOUT", "CANCELLED"]
        ):
            self.receipts.record(
                CapabilityCallReceipt(
                    receipt_id=f"r-{i}",
                    request_id=f"q-{i}",
                    capability_id="file.read",
                    provider_kind="function",
                    provider_ref="text_file_read",
                    status=status,
                    authority_decision="allowed",
                    side_effects=("READ",),
                    latency_ms=10.0 + i,
                    requested_by="agent-a" if i % 2 == 0 else None,
                )
            )
        usage = self.receipts.aggregate_for_capability("file.read")
        self.assertEqual(usage["completed"], 2)
        self.assertEqual(usage["failed"], 1)
        self.assertEqual(usage["timeout"], 1)
        self.assertEqual(usage["rejected"], 1)
        self.assertEqual(usage["cancelled"], 1)
        # COMPLETED / (COMPLETED+FAILED+TIMEOUT) = 2/4
        self.assertAlmostEqual(usage["success_ratio"], 0.5)
        latest = self.receipts.latest_by_capability(["file.read"])
        self.assertIn("file.read", latest)
        recent = self.receipts.recent_for_capability("file.read", limit=3)
        self.assertEqual(len(recent), 3)
        periods = self.receipts.success_ratio_periods(days=7)
        self.assertFalse(periods["unmeasured"])

    def test_legacy_receipt_without_requested_by(self) -> None:
        self.receipts.record(
            CapabilityCallReceipt(
                receipt_id="legacy-1",
                request_id="q",
                capability_id="file.read",
                provider_kind="function",
                provider_ref="text_file_read",
                status="COMPLETED",
                authority_decision="allowed",
                side_effects=("READ",),
                latency_ms=1.0,
                requested_by=None,
            )
        )
        row = self.receipts.get("legacy-1")
        assert row is not None
        self.assertIsNone(row.requested_by)

    def test_overview_counts_plugin_and_custom_explicitly(self) -> None:
        # Register a capability then bind via plugin.
        cap = CapabilityDefinition(
            id="plugin.demo.tool",
            name="Demo Plugin Tool",
            description="demo",
            side_effects=(SideEffect.READ,),
            provider_kind=CapabilityProviderKind.MODULE,
            provider_ref="demo",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            metadata={"domains": ["trading"], "tags": ["demo"]},
        )
        self.catalog.register(cap)
        self.plugins.register(
            name="demo-plugin",
            kind=AdapterKind.DECLARATIVE,
            bindings=[PluginCapabilityBinding(external_name="demo", capability_id="plugin.demo.tool")],
            version="1.2.3",
            plugin_id="demo-plugin",
        )
        record = self.custom.create(
            name="My Read",
            description="wrapper",
            wraps_capability_id="file.read",
            capability_id="custom.my_read",
            version="1.0.0",
        )
        self.custom.hydrate_into_catalog(self.catalog)
        overview = build_tools_overview(
            capability_catalog=self.catalog,
            capability_receipts=self.receipts,
            plugin_registry=self.plugins,
            mcp_bridge=None,
        )
        self.assertGreaterEqual(overview["total_capabilities"], 1)
        self.assertEqual(overview["plugin_tool_count"], 1)
        self.assertEqual(overview["custom_tool_count"], 1)
        self.assertTrue(overview["success_ratio_unmeasured"])
        self.assertEqual(overview["success_ratio_pct"], None)
        self.assertEqual(record.origin if hasattr(record, "origin") else "custom", "custom")

    def test_library_filters_and_last_used(self) -> None:
        self.receipts.record(
            CapabilityCallReceipt(
                receipt_id="lu-1",
                request_id="q",
                capability_id="file.read",
                provider_kind="function",
                provider_ref="text_file_read",
                status="COMPLETED",
                authority_decision="allowed",
                side_effects=("READ",),
                latency_ms=3.0,
                recorded_at="2025-05-25T14:00:00+00:00",
            )
        )
        lib = build_tools_library(
            capability_catalog=self.catalog,
            capability_receipts=self.receipts,
            plugin_registry=self.plugins,
            q="file.read",
            limit=50,
        )
        self.assertGreaterEqual(lib["total"], 1)
        row = next(r for r in lib["tools"] if r["id"] == "file.read")
        self.assertEqual(row["last_used_at"], "2025-05-25T14:00:00+00:00")
        self.assertEqual(row["status_label"], "Actief")

    def test_custom_wrapper_hydrates_and_deletes(self) -> None:
        self.custom.create(
            name="Wrapped Read",
            description="safe wrap",
            wraps_capability_id="file.read",
            capability_id="custom.wrap_read",
        )
        n = self.custom.hydrate_into_catalog(self.catalog)
        self.assertEqual(n, 1)
        item = self.catalog.get("custom.wrap_read")
        assert item is not None
        self.assertEqual(item.normalized_metadata()["origin"], "custom")
        self.assertEqual(item.provider_kind, CapabilityProviderKind.FUNCTION)
        self.custom.delete("custom.wrap_read")
        self.assertIsNone(self.custom.get("custom.wrap_read"))

    def test_gateway_records_requested_by(self) -> None:
        from Data.modules.function_runtime.types import FunctionCallStatus, FunctionResult

        class _Fn:
            def execute(self, function_id: str, arguments: dict | None = None) -> FunctionResult:
                return FunctionResult(
                    call_id="c1",
                    function_id=function_id,
                    status=FunctionCallStatus.COMPLETED,
                    output={"ok": True, "arguments": arguments or {}},
                    duration_ms=1.0,
                )

        catalog = CapabilityCatalog()
        catalog.register(
            CapabilityDefinition(
                id="echo.ping",
                name="Ping",
                description="ping",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.FUNCTION,
                provider_ref="echo_ping",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
                metadata={"domains": ["system"], "origin": "core"},
            )
        )
        gw = ExecutionGateway(
            catalog=catalog,
            function_runtime=_Fn(),  # type: ignore[arg-type]
            receipt_store=self.receipts,
        )
        result = gw.execute(
            CapabilityRequest(
                capability_id="echo.ping",
                arguments={},
                requested_by="Research Agent",
                idempotency_key="tools-test-1",
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        recent = self.receipts.recent_for_capability("echo.ping", limit=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].requested_by, "Research Agent")


if __name__ == "__main__":
    unittest.main()
