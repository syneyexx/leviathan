"""Phase 6/7 — schema validation, path semantics, catalog generation, release truth."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.execution import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
)
from Data.modules.execution.catalog_generation import (
    SCOPE_CUSTOM,
    CatalogGenerationStore,
    CatalogProjectionTracker,
)
from Data.modules.execution.catalog_reconcile import reconcile_dynamic_catalog
from Data.modules.execution.custom_store import CustomCapabilityStore
from Data.modules.execution.path_params import (
    normalize_path_argument,
    resolve_path_argument_keys,
    strip_file_url,
)
from Data.modules.execution.schema_validation import (
    SUPPORTED_JSON_SCHEMA_DRAFT_NAME,
    SchemaValidationError,
    clear_validator_cache,
    reject_pathological_schema,
    validate_args_against_schema,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.release import (
    GateCheck,
    GateMeasurement,
    GateSeverity,
    ReleaseGateRunner,
    evaluation_relevance_gate,
    is_shipable,
    measurement_blocks_release,
)


class JsonSchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_validator_cache()

    def test_supported_draft_is_2020_12(self) -> None:
        self.assertIn("2020-12", SUPPORTED_JSON_SCHEMA_DRAFT_NAME)

    def test_nested_required_enum_and_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "required": ["query", "options"],
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "options": {
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"type": "string", "enum": ["fast", "thorough"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            },
        }
        validate_args_against_schema(
            schema,
            {"query": "abc", "options": {"mode": "fast", "limit": 3}, "tags": ["a"]},
        )
        with self.assertRaises(SchemaValidationError):
            validate_args_against_schema(schema, {"query": "abc", "options": {"mode": "nope"}})
        with self.assertRaises(SchemaValidationError):
            validate_args_against_schema(
                schema, {"query": "abc", "options": {"mode": "fast"}, "extra": 1}
            )

    def test_oneof_const_nested_mcp_shaped(self) -> None:
        # Nested MCP-like tool schema.
        schema = {
            "type": "object",
            "required": ["path", "options"],
            "properties": {
                "path": {"type": "string", "x-leviathan-path": True},
                "options": {
                    "oneOf": [
                        {
                            "type": "object",
                            "required": ["mode"],
                            "properties": {"mode": {"const": "read"}},
                        },
                        {
                            "type": "object",
                            "required": ["mode", "content"],
                            "properties": {
                                "mode": {"const": "write"},
                                "content": {"type": "string", "minLength": 1},
                            },
                        },
                    ]
                },
            },
        }
        validate_args_against_schema(schema, {"path": "/tmp/a", "options": {"mode": "read"}})
        validate_args_against_schema(
            schema, {"path": "/tmp/a", "options": {"mode": "write", "content": "x"}}
        )
        with self.assertRaises(SchemaValidationError):
            validate_args_against_schema(
                schema, {"path": "/tmp/a", "options": {"mode": "write"}}
            )

    def test_pathological_schema_rejected(self) -> None:
        deep: dict = {"type": "object", "properties": {}}
        cursor = deep
        for i in range(40):
            nxt = {"type": "object", "properties": {}}
            cursor["properties"][f"n{i}"] = nxt
            cursor = nxt
        with self.assertRaises(SchemaValidationError):
            reject_pathological_schema(deep)

    def test_gateway_uses_real_schema_validation(self) -> None:
        catalog = build_default_catalog()
        catalog.upsert(
            CapabilityDefinition(
                id="test.nested_schema",
                name="Nested",
                description="d",
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.INTERNAL,
                provider_ref="noop",
                input_schema={
                    "type": "object",
                    "required": ["cfg"],
                    "properties": {
                        "cfg": {
                            "type": "object",
                            "required": ["kind"],
                            "properties": {
                                "kind": {"const": "ok"},
                                "n": {"type": "number", "exclusiveMinimum": 0},
                            },
                        }
                    },
                },
                output_schema={"type": "object"},
            )
        )
        gateway = ExecutionGateway(catalog=catalog)
        bad = gateway.execute(
            CapabilityRequest(
                capability_id="test.nested_schema",
                arguments={"cfg": {"kind": "ok", "n": 0}},
            )
        )
        self.assertEqual(bad.status, CapabilityStatus.REJECTED)
        self.assertEqual(bad.telemetry.get("reason"), "validation")


class TypedPathParameterTests(unittest.TestCase):
    def test_file_url_normalization(self) -> None:
        stripped = strip_file_url("file:///tmp/x")
        self.assertIn("tmp", stripped.replace("\\", "/"))
        self.assertEqual(
            normalize_path_argument("file:///workspace/a.txt").replace("\\", "/").split("/")[-1],
            "a.txt",
        )

    def test_schema_and_metadata_path_keys(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "src": {"type": "string", "x-leviathan-path": True},
                "note": {"type": "string"},
                "outdir": {"type": "string", "format": "leviathan-path"},
            },
        }
        keys = resolve_path_argument_keys(
            input_schema=schema,
            metadata={"path_parameters": ["custom_path"]},
            arguments={"path": "/y"},
        )
        self.assertIn("src", keys)
        self.assertIn("outdir", keys)
        self.assertIn("custom_path", keys)
        self.assertIn("path", keys)

    def test_gateway_confines_alternate_field_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.txt").write_text("hi", encoding="utf-8")
            catalog = build_default_catalog()
            catalog.upsert(
                CapabilityDefinition(
                    id="test.path_alt",
                    name="Alt path",
                    description="d",
                    side_effects=(SideEffect.READ,),
                    provider_kind=CapabilityProviderKind.FUNCTION,
                    provider_ref="text_file_read",
                    input_schema={
                        "type": "object",
                        "required": ["source_file"],
                        "properties": {
                            "source_file": {
                                "type": "string",
                                "x-leviathan-path": True,
                                "x-leviathan-path-role": "source",
                            }
                        },
                    },
                    output_schema={"type": "object"},
                    metadata={"path_parameters": ["source_file"]},
                )
            )
            runtime = FunctionRuntime(build_default_registry(), max_concurrency=1)
            try:
                gateway = ExecutionGateway(
                    catalog=catalog,
                    function_runtime=runtime,
                    filesystem_root=root,
                )
                escaped = gateway.execute(
                    CapabilityRequest(
                        capability_id="test.path_alt",
                        arguments={"source_file": str(root / ".." / "etc" / "passwd")},
                    )
                )
                self.assertEqual(escaped.status, CapabilityStatus.REJECTED)
                self.assertEqual(escaped.telemetry.get("reason"), "path_escape")
            finally:
                runtime.shutdown()

    def test_builtin_file_read_has_typed_path_semantics(self) -> None:
        catalog = build_default_catalog()
        item = catalog.require("file.read")
        prop = (item.input_schema.get("properties") or {}).get("path") or {}
        self.assertTrue(prop.get("x-leviathan-path"))
        self.assertIn("path", item.normalized_metadata().get("path_parameters") or [])


class CatalogGenerationConsistencyTests(unittest.TestCase):
    def test_custom_crud_bumps_generation_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            store = CustomCapabilityStore(db)
            store.initialize()
            before = store.get_catalog_generation()
            store.create(
                name="Wrap",
                description="d",
                wraps_capability_id="base.read",
                capability_id="custom.wrap",
            )
            after = store.get_catalog_generation()
            self.assertGreater(after, before)

            catalog_b = build_default_catalog()
            catalog_b.register(
                CapabilityDefinition(
                    id="base.read",
                    name="Base",
                    description="b",
                    side_effects=(SideEffect.READ,),
                    provider_kind=CapabilityProviderKind.INTERNAL,
                    provider_ref="x",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            )
            tracker = CatalogProjectionTracker()
            result = reconcile_dynamic_catalog(
                catalog_b, custom_store=store, tracker=tracker, force=False
            )
            self.assertIn("custom.wrap", catalog_b)
            self.assertEqual(result["catalog_generations"][SCOPE_CUSTOM], after)
            again = reconcile_dynamic_catalog(
                catalog_b, custom_store=store, tracker=tracker, force=False
            )
            self.assertEqual(again["actions"], [])

    def test_migration_creates_generation_table(self) -> None:
        from Data.backend.migrations import MigrationRunner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite"
            applied = MigrationRunner(path).apply_all()
            self.assertIn(68, applied)
            gen = CatalogGenerationStore(path)
            gen.initialize()
            self.assertEqual(gen.get_generation(SCOPE_CUSTOM), 0)


class ReleaseReadinessTruthTests(unittest.TestCase):
    def test_block_unmeasured_blocks_ready(self) -> None:
        self.assertTrue(
            measurement_blocks_release(GateMeasurement.UNMEASURED, severity="BLOCK")
        )
        self.assertFalse(
            measurement_blocks_release(GateMeasurement.NOT_APPLICABLE, severity="BLOCK")
        )
        runner = ReleaseGateRunner(
            checks=[
                lambda: GateCheck(
                    "core", "core", GateSeverity.BLOCK, True, "ok",
                    measurement=GateMeasurement.PASS,
                ),
                lambda: GateCheck(
                    "probe", "probe", GateSeverity.BLOCK, True, "not run",
                    measurement=GateMeasurement.UNMEASURED,
                ),
            ]
        )
        report = runner.run()
        self.assertFalse(report.ready)
        self.assertFalse(is_shipable(report, ci_release=False))
        self.assertFalse(is_shipable(report, ci_release=True))

    def test_soft_unmeasured_is_not_passed(self) -> None:
        gate = evaluation_relevance_gate(
            {"recorded": True, "measurement": "UNMEASURED", "promotable": False, "detail": "soft"},
            require_pass=False,
            severity=GateSeverity.WARN,
        )
        self.assertFalse(gate.passed)
        self.assertEqual(gate.measurement, GateMeasurement.UNMEASURED)

    def test_not_applicable_block_does_not_block_ready(self) -> None:
        runner = ReleaseGateRunner(
            checks=[
                lambda: GateCheck(
                    "core", "core", GateSeverity.BLOCK, True, "ok",
                    measurement=GateMeasurement.PASS,
                ),
                lambda: GateCheck(
                    "na", "na", GateSeverity.BLOCK, True, "out of scope",
                    measurement=GateMeasurement.NOT_APPLICABLE,
                ),
            ]
        )
        report = runner.run()
        self.assertTrue(report.ready)
        self.assertTrue(is_shipable(report, ci_release=True))


if __name__ == "__main__":
    unittest.main()
