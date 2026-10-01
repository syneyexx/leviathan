"""Phase 2 MCP hardening: secrets, ArtifactStore spill, async 202 tool calls."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MIGRATIONS, MigrationRunner
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import CapabilityStatus, build_default_catalog
from Data.modules.mcp import McpBridge, McpProvider, McpStore
from Data.modules.mcp.errors import McpError
from Data.modules.mcp.limits import McpLimits
from Data.modules.mcp.secrets import (
    build_process_env,
    is_secret_env_name,
    scrub_legacy_public_env_row,
    scrub_mcp_server_secrets,
    validate_public_env,
)
from Data.modules.mcp.session import McpServerSession
from Data.modules.mcp.types import McpServerConfig, McpSourceKind, McpTransportKind


FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def _python() -> str:
    return sys.executable


class McpSecretHandlingTests(unittest.TestCase):
    def test_secret_name_classification_covers_required_tokens(self) -> None:
        for name in (
            "API_KEY",
            "OPENAI_API_KEY",
            "HF_TOKEN",
            "PASSWORD",
            "DB_PASSWORD",
            "AUTHORIZATION",
            "COOKIE",
            "SESSION_COOKIE",
            "MY_SECRET",
            "PRIVATE_KEY",
        ):
            self.assertTrue(is_secret_env_name(name), name)
        self.assertFalse(is_secret_env_name("LOG_LEVEL"))
        self.assertFalse(is_secret_env_name("NODE_ENV"))

    def test_custom_configured_sensitive_names(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_MCP_SENSITIVE_ENV_KEYS": "CORP_CRED,VAULT_SLOT"}):
            self.assertTrue(is_secret_env_name("CORP_CRED"))
            self.assertTrue(is_secret_env_name("APP_VAULT_SLOT_X"))
            self.assertFalse(is_secret_env_name("LOG_LEVEL"))

    def test_validate_public_env_rejects_sensitive_keys(self) -> None:
        with self.assertRaises(McpError) as ctx:
            validate_public_env({"API_KEY": "sk-live-should-not-persist", "LOG_LEVEL": "info"})
        self.assertEqual(ctx.exception.code, "MCP_PLAINTEXT_SECRET_REJECTED")
        self.assertIn("API_KEY", ctx.exception.details["rejected_keys"])

    def test_validate_public_env_rejects_token_password_authorization_cookie(self) -> None:
        for key in ("TOKEN", "PASSWORD", "AUTHORIZATION", "COOKIE"):
            with self.assertRaises(McpError) as ctx:
                validate_public_env({key: "plaintext-value"})
            self.assertEqual(ctx.exception.code, "MCP_PLAINTEXT_SECRET_REJECTED")
            self.assertIn(key, ctx.exception.details["rejected_keys"])

    def test_bridge_register_rejects_plaintext_secret_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = McpStore(root / "c.db")
            store.initialize()
            bridge = McpBridge(store=store, catalog=build_default_catalog(), enabled=True)
            bridge.initialize()
            with self.assertRaises(McpError) as ctx:
                bridge.register_server(
                    display_name="bad",
                    transport="stdio",
                    command="true",
                    env={"API_KEY": "sk-abc12345678901234", "LOG_LEVEL": "info"},
                )
            self.assertEqual(ctx.exception.code, "MCP_PLAINTEXT_SECRET_REJECTED")

    def test_bridge_accepts_secret_refs_not_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = McpStore(root / "c.db")
            store.initialize()
            bridge = McpBridge(store=store, catalog=build_default_catalog(), enabled=True)
            bridge.initialize()
            cfg = bridge.register_server(
                display_name="ok",
                transport="stdio",
                command="true",
                env={"LOG_LEVEL": "info"},
                secret_refs={"API_KEY": "secret:TEST_API_KEY", "TOKEN": "env:HOST_TOKEN"},
            )
            public = bridge.get_server_public(cfg.server_id)
            blob = json.dumps(public)
            self.assertNotIn("sk-", blob)
            self.assertIn("secret:TEST_API_KEY", blob)
            self.assertEqual(public["env"].get("LOG_LEVEL"), "info")
            self.assertNotIn("API_KEY", public["env"])

    def test_build_process_env_resolves_only_at_creation(self) -> None:
        os.environ["TEST_MCP_RESOLVE_KEY"] = "resolved-secret-value-xyz"
        try:
            env, secrets = build_process_env(
                env_public={"LOG_LEVEL": "debug"},
                secret_refs={"API_KEY": "env:TEST_MCP_RESOLVE_KEY"},
            )
            self.assertEqual(env["API_KEY"], "resolved-secret-value-xyz")
            self.assertEqual(env["LOG_LEVEL"], "debug")
            self.assertIn("resolved-secret-value-xyz", secrets)
            # Legacy sensitive public key must not be injected.
            env2, _ = build_process_env(
                env_public={"API_KEY": "should-be-ignored", "FOO": "bar"},
                secret_refs={},
            )
            self.assertNotIn("API_KEY", env2)
            self.assertEqual(env2["FOO"], "bar")
        finally:
            os.environ.pop("TEST_MCP_RESOLVE_KEY", None)

    def test_scrub_legacy_row_moves_keys_without_keeping_plaintext(self) -> None:
        public, refs, scrubbed = scrub_legacy_public_env_row(
            {"API_KEY": "sk-should-vanish", "LOG_LEVEL": "info", "COOKIE": "sess=abc"},
            {},
        )
        self.assertEqual(public, {"LOG_LEVEL": "info"})
        self.assertIn("API_KEY", scrubbed)
        self.assertIn("COOKIE", scrubbed)
        self.assertEqual(refs["API_KEY"], "env:API_KEY")
        self.assertNotIn("sk-should-vanish", json.dumps(public))
        self.assertNotIn("sk-should-vanish", json.dumps(refs))
        self.assertNotIn("sess=abc", json.dumps(refs))

    def test_migration_scrubs_without_printing_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.db"
            # Seed a pre-migration mcp_servers row with plaintext secrets.
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE mcp_servers (
                    server_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'manual',
                    source_key TEXT NOT NULL DEFAULT '',
                    transport TEXT NOT NULL DEFAULT 'stdio',
                    command TEXT,
                    args_json TEXT NOT NULL DEFAULT '[]',
                    url TEXT,
                    cwd TEXT,
                    env_public_json TEXT NOT NULL DEFAULT '{}',
                    secret_refs_json TEXT NOT NULL DEFAULT '{}',
                    timeout_seconds REAL NOT NULL DEFAULT 30,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    trust TEXT NOT NULL DEFAULT 'untrusted',
                    requested_isolation TEXT NOT NULL DEFAULT 'subprocess',
                    max_concurrent_calls INTEGER NOT NULL DEFAULT 4,
                    owner_module_id TEXT,
                    eager_connect INTEGER NOT NULL DEFAULT 0,
                    expand_tools INTEGER NOT NULL DEFAULT 1,
                    semantic_effects_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL DEFAULT 'DISCONNECTED',
                    catalog_generation INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                "INSERT INTO mcp_servers(server_id, display_name, env_public_json, secret_refs_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    "srv-legacy",
                    "legacy",
                    json.dumps({"API_KEY": "sk-legacy-plaintext-NEVER-REPORT", "LOG_LEVEL": "info"}),
                    "{}",
                ),
            )
            conn.commit()
            report = scrub_mcp_server_secrets(conn)
            conn.commit()
            self.assertEqual(report["servers_scrubbed"], 1)
            self.assertIn("API_KEY", report["scrubbed_key_names"])
            report_blob = json.dumps(report)
            self.assertNotIn("sk-legacy-plaintext-NEVER-REPORT", report_blob)
            row = conn.execute(
                "SELECT env_public_json, secret_refs_json FROM mcp_servers WHERE server_id = ?",
                ("srv-legacy",),
            ).fetchone()
            env_public = json.loads(row["env_public_json"])
            refs = json.loads(row["secret_refs_json"])
            self.assertEqual(env_public.get("LOG_LEVEL"), "info")
            self.assertNotIn("API_KEY", env_public)
            self.assertEqual(refs.get("API_KEY"), "env:API_KEY")
            self.assertNotIn("sk-legacy", json.dumps(env_public) + json.dumps(refs))
            conn.close()

    def test_migration_runner_head_includes_scrub(self) -> None:
        self.assertEqual(MIGRATIONS[-1].version, 67)
        self.assertEqual(MIGRATIONS[-1].name, "mcp_scrub_plaintext_secrets")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "full.db"
            applied = MigrationRunner(path).apply_all()
            self.assertIn(67, applied)


class McpArtifactStoreSpillTests(unittest.TestCase):
    def test_spill_uses_injected_artifact_store_not_sidecar_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "control.db"
            artifacts = ArtifactStore(db, root / "artifacts")
            artifacts.initialize()
            config = McpServerConfig(
                server_id="spill-srv",
                display_name="spill",
                source_kind=McpSourceKind.MANUAL,
                source_key="spill",
                transport=McpTransportKind.STDIO,
                command=_python(),
                args=(str(FAKE_SERVER),),
                enabled=True,
            )
            session = McpServerSession(
                config=config,
                limits=McpLimits(max_tool_result_bytes=64),
                artifact_store=artifacts,
            )
            raw = b'{"big":"' + (b"x" * 200) + b'"}'
            artifact_id = session._spill_tool_result(raw)
            self.assertIsNotNone(artifact_id)
            # No fourth product DB under mcp_tool_results.
            self.assertFalse((root / "mcp_tool_results" / "artifacts.db").exists())
            # Durable in CONTROL ArtifactStore.
            record = artifacts.get(artifact_id)  # type: ignore[arg-type]
            self.assertIsNotNone(record)
            self.assertEqual(getattr(record, "artifact_type", None), "mcp_tool_result")
            path = Path(getattr(record, "path"))
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), raw)

    def test_spill_without_store_returns_none(self) -> None:
        config = McpServerConfig(
            server_id="no-store",
            display_name="n",
            source_kind=McpSourceKind.MANUAL,
            source_key="n",
            transport=McpTransportKind.STDIO,
            command="true",
            enabled=True,
        )
        session = McpServerSession(config=config, limits=McpLimits())
        self.assertIsNone(session._spill_tool_result(b"{}"))


class McpAsyncCallContractTests(unittest.TestCase):
    def test_provider_enqueues_without_polling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = McpStore(root / "c.db")
            store.initialize()
            catalog = build_default_catalog()
            bridge = McpBridge(store=store, catalog=catalog, enabled=True)
            bridge.initialize()
            cfg = bridge.register_server(
                display_name="async",
                transport="stdio",
                command=_python(),
                args=[str(FAKE_SERVER)],
                enabled=True,
                expand_tools=False,
            )
            # Seed a tool row without live connect.
            from Data.modules.mcp.types import McpToolAvailability, McpToolRecord, mcp_capability_id, stable_schema_hash
            from Data.modules.mcp.store import utc_now

            schema = {"type": "object", "properties": {"text": {"type": "string"}}}
            cap = mcp_capability_id(cfg.server_id, "echo")
            store.upsert_tool(
                McpToolRecord(
                    server_id=cfg.server_id,
                    external_name="echo",
                    capability_id=cap,
                    description="echo",
                    input_schema=schema,
                    schema_hash=stable_schema_hash(schema),
                    semantic_effects=("READ",),
                    availability=McpToolAvailability.AVAILABLE,
                    first_seen_at=utc_now(),
                    last_seen_at=utc_now(),
                )
            )

            enqueued: list[dict] = []

            class _Jobs:
                def enqueue(self, **kwargs):
                    enqueued.append(kwargs)
                    return type("J", (), {"job_id": "job-async-1", "timeout_seconds": 60.0})()

                def get(self, job_id):  # pragma: no cover — must not be polled
                    raise AssertionError(f"Control plane must not poll job {job_id}")

            provider = McpProvider(bridge, job_runtime=_Jobs())
            with mock.patch.object(provider, "_externalize_execution", return_value=True):
                with mock.patch.object(provider, "_mcp_workers_ready", return_value=True):
                    result = provider.execute_capability(
                        cap,
                        {"text": "hi"},
                        request_id="req-1",
                    )
            self.assertEqual(result.status, CapabilityStatus.QUEUED)
            self.assertTrue(result.output["queued"])
            self.assertEqual(result.output["job_id"], "job-async-1")
            self.assertEqual(len(enqueued), 1)
            self.assertEqual(enqueued[0]["capability_id"], "mcp.call")

    def test_call_route_returns_202_when_queued(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from Data.backend.routes.mcp import build_mcp_router
        from Data.modules.execution.types import CapabilityResult

        class _Bridge:
            enabled = True
            telemetry = {}
            store = type("S", (), {"get_tool": lambda self, cid: None})()

            def health_summary(self):
                return type("H", (), {"public_dict": lambda self: {}})()

        class _Gateway:
            def execute(self, request):
                return CapabilityResult(
                    request_id="r1",
                    capability_id=request.capability_id,
                    status=CapabilityStatus.QUEUED,
                    output={"queued": True, "job_id": "job-call-9"},
                    telemetry={"job_id": "job-call-9"},
                )

        app = FastAPI()
        app.include_router(build_mcp_router(_Bridge(), _Gateway(), job_runtime=None))
        client = TestClient(app)
        resp = client.post("/api/mcp/call", json={"capability_id": "mcp:x:echo", "arguments": {}})
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertTrue(body.get("queued"))
        self.assertEqual(body.get("job_id"), "job-call-9")


class WorkerLoopArtifactStoreTests(unittest.TestCase):
    def test_loop_source_uses_control_db_not_artifacts_sidecar(self) -> None:
        source = Path("Data/modules/workers/loop.py").read_text(encoding="utf-8")
        self.assertIn("ArtifactStore(settings.database_path", source)
        self.assertNotIn('db_parent / "artifacts.db"', source)
        session_src = Path("Data/modules/mcp/session.py").read_text(encoding="utf-8")
        self.assertIn("artifact_store", session_src)
        self.assertNotIn('root / "artifacts.db"', session_src)
        self.assertNotIn("mcp_tool_results", session_src)


if __name__ == "__main__":
    unittest.main()
