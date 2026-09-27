"""WAVES 23–25 — trusted DB paths, SSRF endpoint identity, schema/serving authority, commit truth."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from Data.backend.db_upgrade import (
    WAVE3_CANONICAL_DDL,
    WAVE3_PRODUCT_TABLES,
    _ensure_runtime_bootstrap_schema,
    apply_wave3_canonical_ddl,
    wave3_canonical_ddl,
)
from Data.modules.common.database_domains import (
    knowledge_path_from_settings,
    resolve_knowledge_database_path,
    resolve_market_database_path,
)
from Data.modules.common.process import pid_fingerprint
from Data.modules.db_commit.handlers.dataset import _commit_index_batch
from Data.modules.db_commit.types import CommitIntent, CommitReceiptStatus
from Data.modules.model_runtime.serving import ServingSupervisor, WorkerState
from Data.modules.provider_io.private_host_authority import (
    endpoint_identity,
    redirect_target_private_hosts_allowed,
    resolve_allow_private_hosts_for_url,
)


class Wave23TrustedDbPathsTests(unittest.TestCase):
    def test_market_stream_ignores_payload_db_path(self) -> None:
        from Data.modules.provider_io.adapters import market_stream as ms
        import inspect

        src = inspect.getsource(ms.MarketStreamAdapter._execute_stream)
        self.assertNotIn('payload.get("market_db_path")', src)
        self.assertNotIn('payload.get("db_path")', src)
        self.assertIn("resolve_market_database_path", src)

    def test_executor_does_not_honor_payload_market_db_path(self) -> None:
        from Data.modules.provider_io import executor as ex
        import inspect

        src = inspect.getsource(ex.ProviderIoExecutor.execute_job)
        self.assertNotIn('request.payload.get("market_db_path")', src)
        self.assertIn("resolve_market_database_path()", src)

    def test_knowledge_never_falls_back_to_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control.db"
            knowledge = Path(tmp) / "knowledge.db"
            settings = SimpleNamespace(
                database_path=control,
                knowledge_database_path=knowledge,
            )
            self.assertEqual(knowledge_path_from_settings(settings), knowledge)
            # Missing knowledge attr → resolve_knowledge, not control.
            bare = SimpleNamespace(database_path=control)
            resolved = knowledge_path_from_settings(bare)
            self.assertNotEqual(resolved, control)
            self.assertEqual(resolved, resolve_knowledge_database_path())

    def test_research_worker_context_no_control_fallback(self) -> None:
        import inspect
        from Data.modules.research import worker_context as wc

        src = inspect.getsource(wc.build_research_worker_context)
        self.assertNotIn("fallback=db_path", src)
        self.assertIn("knowledge_path_from_settings", src)


class Wave23SsrfEndpointIdentityTests(unittest.TestCase):
    def test_configured_endpoint_does_not_authorize_wrong_port(self) -> None:
        settings = mock.Mock(spec=["model", "managed_serving", "llm_base_url"])
        settings.model = mock.Mock(spec=["base_url"])
        settings.model.base_url = "http://127.0.0.1:11434"
        settings.managed_serving = mock.Mock(spec=["base_url"])
        settings.managed_serving.base_url = ""
        settings.llm_base_url = "http://127.0.0.1:11434"
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            self.assertTrue(
                resolve_allow_private_hosts_for_url(
                    "http://127.0.0.1:11434/v1/chat",
                    settings=settings,
                    trust_model_endpoints=True,
                )
            )
            self.assertFalse(
                resolve_allow_private_hosts_for_url(
                    "http://127.0.0.1:5432/secret",
                    settings=settings,
                    trust_model_endpoints=True,
                )
            )
            self.assertFalse(
                resolve_allow_private_hosts_for_url(
                    "https://127.0.0.1:11434/v1/chat",
                    settings=settings,
                    trust_model_endpoints=True,
                )
            )

    def test_generic_http_does_not_inherit_model_trust(self) -> None:
        settings = mock.Mock(spec=["model", "managed_serving", "llm_base_url"])
        settings.model = mock.Mock(spec=["base_url"])
        settings.model.base_url = "http://127.0.0.1:11434"
        settings.managed_serving = mock.Mock(spec=["base_url"])
        settings.managed_serving.base_url = ""
        settings.llm_base_url = "http://127.0.0.1:11434"
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            self.assertFalse(
                resolve_allow_private_hosts_for_url(
                    "http://127.0.0.1:11434/v1/chat",
                    settings=settings,
                    trust_model_endpoints=False,
                )
            )

    def test_forged_allow_private_hosts_still_ignored(self) -> None:
        from Data.modules.provider_io.executor import _request_from_job_args

        # Isolate from other tests that may set the operator env override.
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            req = _request_from_job_args(
                {
                    "capability": "http",
                    "provider": "generic",
                    "allow_private_hosts": True,
                    "payload": {
                        "url": "http://127.0.0.1:9/x",
                        "allow_private_hosts": True,
                    },
                },
                job_id="j1",
            )
            self.assertFalse(req.allow_private_hosts)
            self.assertNotIn("allow_private_hosts", req.payload)

    def test_redirect_target_wrong_port_blocked(self) -> None:
        settings = mock.Mock(spec=["model", "managed_serving", "llm_base_url"])
        settings.model = mock.Mock(spec=["base_url"])
        settings.model.base_url = "http://127.0.0.1:11434"
        settings.managed_serving = mock.Mock(spec=["base_url"])
        settings.managed_serving.base_url = ""
        settings.llm_base_url = "http://127.0.0.1:11434"
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST": "",
                "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS": "",
            },
            clear=False,
        ):
            self.assertFalse(
                redirect_target_private_hosts_allowed(
                    "http://127.0.0.1:5432/redirected",
                    settings=settings,
                    trust_model_endpoints=True,
                )
            )
            self.assertTrue(
                redirect_target_private_hosts_allowed(
                    "http://127.0.0.1:11434/ok",
                    settings=settings,
                    trust_model_endpoints=True,
                )
            )

    def test_endpoint_identity_normalizes_default_ports(self) -> None:
        self.assertEqual(
            endpoint_identity("http://127.0.0.1/v1"),
            ("http", "127.0.0.1", 80),
        )
        self.assertEqual(
            endpoint_identity("https://127.0.0.1/v1"),
            ("https", "127.0.0.1", 443),
        )


class Wave24SchemaAuthorityTests(unittest.TestCase):
    def test_handlers_reuse_canonical_ddl(self) -> None:
        from Data.modules.db_commit.handlers import dataset, market_sim, source_ingestion
        from Data.modules.provider_io import stream_store
        from Data.modules.knowledge.pipeline import committer
        from Data.modules.intelligence import assimilation
        import inspect

        for mod in (dataset, market_sim, source_ingestion, stream_store, committer, assimilation):
            src = inspect.getsource(mod)
            self.assertIn("apply_wave3_canonical_ddl", src, mod.__name__)
            # No duplicated CREATE TABLE strings for wave3 product tables.
            for table in WAVE3_PRODUCT_TABLES:
                # Generic CREATE TABLE IF NOT EXISTS {table} in generic.py is ok elsewhere;
                # these modules must not embed full wave3 DDL literals.
                if f"CREATE TABLE IF NOT EXISTS {table}" in src:
                    self.fail(f"{mod.__name__} still embeds DDL for {table}")

    def test_bootstrap_uses_canonical_source(self) -> None:
        import inspect
        from Data.backend import db_upgrade

        src = inspect.getsource(db_upgrade._ensure_runtime_bootstrap_schema)
        self.assertIn("apply_wave3_canonical_ddl", src)
        self.assertNotIn("Canonical ProviderStreamStore schema", src)

    def test_wave3_ddl_helper_stable(self) -> None:
        self.assertEqual(
            set(WAVE3_CANONICAL_DDL),
            set(WAVE3_PRODUCT_TABLES),
        )
        conn = sqlite3.connect(":memory:")
        apply_wave3_canonical_ddl(conn)
        for table in WAVE3_PRODUCT_TABLES:
            cols = {
                row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            self.assertTrue(cols, table)
            self.assertIn(table, wave3_canonical_ddl(table))


class Wave24ServingSingleOwnerTests(unittest.TestCase):
    def test_control_plane_delegates_reconcile(self) -> None:
        import inspect
        from Data.modules.models import control_plane as cp

        src = inspect.getsource(cp.ModelControlPlane.reconcile_persisted_serving_workers)
        self.assertIn("reconcile_persisted_orphans", src)
        self.assertIn("ServingSupervisor", src)
        self.assertIn("kill_skipped", src)

    def test_ready_requires_health_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "reg.json"
            sup = ServingSupervisor(registry_path=reg)
            # sleep 0 command that stays alive briefly — no ready_check → STARTING not READY
            worker = sup.start_subprocess(
                provider_id="p",
                model_id="m",
                backend_kind="vllm_class",
                command=["/bin/sleep", "30"],
                endpoint="http://127.0.0.1:9/v1",
                ready_check=None,
                ready_timeout_seconds=2.0,
            )
            try:
                self.assertEqual(worker.state, WorkerState.STARTING)
                self.assertNotEqual(worker.state, WorkerState.READY)
            finally:
                try:
                    sup.stop(worker.worker_id, drain=False)
                except Exception:  # noqa: BLE001
                    pass

    def test_pid_fingerprint_windows_safe_api(self) -> None:
        fp = pid_fingerprint(os.getpid())
        self.assertTrue(fp.startswith(f"{os.getpid()}:"))
        # Must not be empty starttime-only failure for live self.
        self.assertNotEqual(fp, f"{os.getpid()}:")


class Wave25CommitReceiptTruthTests(unittest.TestCase):
    def test_rollback_on_in_txn_aux_failure_is_rejected_without_durable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            intent = CommitIntent(
                commit_id="c-rollback",
                idempotency_key="k-rollback",
                domain="dataset",
                operation="dataset.commit_index_batch",
                payload_hash="h",
            )
            receipt = _commit_index_batch(
                intent,
                {
                    "dataset_id": "d1",
                    "rows": [{"row_id": "r1"}],
                    "_fail_aux_in_transaction": True,
                },
                db,
                settings=SimpleNamespace(max_batch_rows=1000),
            )
            self.assertEqual(receipt.status, CommitReceiptStatus.REJECTED.value)
            self.assertTrue(receipt.result.get("rolled_back"))
            con = sqlite3.connect(db)
            try:
                tables = {
                    r[0]
                    for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "dataset_commit_index_rows" in tables:
                    n = con.execute(
                        "SELECT COUNT(*) FROM dataset_commit_index_rows"
                    ).fetchone()[0]
                    self.assertEqual(n, 0)
            finally:
                con.close()

    def test_partial_after_durable_primary_never_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            intent = CommitIntent(
                commit_id="c-partial",
                idempotency_key="k-partial",
                domain="dataset",
                operation="dataset.commit_index_batch",
                payload_hash="h",
            )
            receipt = _commit_index_batch(
                intent,
                {
                    "dataset_id": "d1",
                    "rows": [{"row_id": "r1"}, {"row_id": "r2"}],
                    "_fail_aux_after_primary_commit": True,
                },
                db,
                settings=SimpleNamespace(max_batch_rows=1000),
            )
            self.assertEqual(
                receipt.status, CommitReceiptStatus.FAILED_AFTER_PARTIAL_COMMIT.value
            )
            self.assertNotEqual(receipt.status, CommitReceiptStatus.REJECTED.value)
            self.assertEqual(receipt.record_count, 2)
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM dataset_commit_index_rows WHERE dataset_id='d1'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 2)

    def test_applied_success_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            intent = CommitIntent(
                commit_id="c-ok",
                idempotency_key="k-ok",
                domain="dataset",
                operation="dataset.commit_index_batch",
                payload_hash="h",
            )
            receipt = _commit_index_batch(
                intent,
                {"dataset_id": "d1", "rows": [{"row_id": "r1"}]},
                db,
                settings=SimpleNamespace(max_batch_rows=1000),
            )
            self.assertEqual(receipt.status, CommitReceiptStatus.APPLIED.value)


if __name__ == "__main__":
    unittest.main()
