"""Phase 5 — custom capability optimistic concurrency + protected metadata."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.custom_store import (
    PROTECTED_CUSTOM_METADATA_KEYS,
    CustomCapabilityStore,
)
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect
from Data.modules.plugins import PluginRegistry


class CustomCapabilityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CustomCapabilityStore(Path(self.tmp.name) / "c.db")
        self.store.initialize()
        self.catalog = CapabilityCatalog()
        self.catalog.register(
            CapabilityDefinition(
                id="base.read",
                name="Base",
                description="base",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.INTERNAL,
                provider_ref="x",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_protected_metadata_keys_stripped(self) -> None:
        record = self.store.create(
            name="Wrap",
            description="d",
            wraps_capability_id="base.read",
            capability_id="custom.wrap",
            metadata={
                "origin": "evil",
                "tags": ["ok"],
                "owner": "attacker",
                "provider_kind": "MCP",
                "side_effects": ["DELETE"],
                "execution_class": "INLINE_SAFE",
                "trust": "verified",
            },
        )
        self.assertNotIn("origin", record.metadata)
        self.assertNotIn("owner", record.metadata)
        self.assertNotIn("provider_kind", record.metadata)
        self.assertNotIn("side_effects", record.metadata)
        self.assertNotIn("execution_class", record.metadata)
        self.assertNotIn("trust", record.metadata)
        self.assertEqual(record.metadata.get("tags"), ["ok"])
        self.assertTrue("origin" in PROTECTED_CUSTOM_METADATA_KEYS)

    def test_hydrate_metadata_cannot_weaken_security_fields(self) -> None:
        record = self.store.create(
            name="Wrap",
            description="d",
            wraps_capability_id="base.read",
            capability_id="custom.sec",
            metadata={
                "provider_kind": "EXTERNAL",
                "side_effects": ["DELETE", "EXECUTE"],
                "execution_class": "INLINE_SAFE",
                "label": "display-only",
            },
        )
        self.store.hydrate_into_catalog(self.catalog)
        definition = self.catalog.get("custom.sec")
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.provider_kind, CapabilityProviderKind.INTERNAL)
        self.assertEqual(definition.side_effects, (SideEffect.READ,))
        self.assertEqual(definition.metadata.get("label"), "display-only")
        self.assertNotEqual(definition.metadata.get("provider_kind"), "EXTERNAL")

    def test_atomic_revision_update(self) -> None:
        record = self.store.create(
            name="Wrap",
            description="d",
            wraps_capability_id="base.read",
            capability_id="custom.rev",
        )
        updated = self.store.update(
            "custom.rev",
            name="Wrap2",
            expected_revision=record.revision,
        )
        self.assertEqual(updated.revision, record.revision + 1)
        with self.assertRaises(ValueError):
            self.store.update("custom.rev", name="stale", expected_revision=record.revision)

    def test_catalog_unregister_on_delete_path(self) -> None:
        record = self.store.create(
            name="Wrap",
            description="d",
            wraps_capability_id="base.read",
            capability_id="custom.del",
        )
        self.store.hydrate_into_catalog(self.catalog)
        self.assertIn("custom.del", self.catalog)
        self.store.delete(record.capability_id)
        self.assertTrue(self.catalog.unregister("custom.del"))
        self.assertNotIn("custom.del", self.catalog)

    def test_plugin_unregister_removes_durable_binding(self) -> None:
        registry = PluginRegistry(self.catalog)
        stub = registry.register_echo_mcp_stub()
        self.assertIsNotNone(registry.get(stub.plugin_id))
        self.assertTrue(registry.unregister(stub.plugin_id))
        self.assertIsNone(registry.get(stub.plugin_id))


if __name__ == "__main__":
    unittest.main()
