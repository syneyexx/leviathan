"""Architecture regressions for evaluation / DB maintenance / assurance externalization."""

from __future__ import annotations

import ast
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.backup.service import BackupService, _sha256_file
from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.security.deep_scan import run_dependency_audit, run_repo_scan
from Data.modules.sqlite_manager.heavy import (
    classify_checkpoint_mode,
    classify_integrity_kind,
    classify_operator_query,
)
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability

EVAL_CAPS = (
    "evaluation.run",
    "evaluation.benchmark",
    "evaluation.regression",
    "evaluation.ablation",
    "evaluation.scorecard",
    "evaluation.release.validate",
    "evaluation.verify_tests",
    "evaluation.statistics",
    "evaluation.soak",
    "evaluation.chaos",
)

SQLITE_OPS_CAPS = (
    "sqlite_ops.query",
    "sqlite_ops.scan",
    "sqlite_ops.search",
    "sqlite_ops.analytics",
    "sqlite_ops.export",
)

MAINT_CAPS = (
    "maintenance.reconcile",
    "maintenance.db.integrity",
    "maintenance.db.vacuum",
    "maintenance.db.analyze",
    "maintenance.db.checkpoint",
    "maintenance.backup.restore",
    "maintenance.artifacts.cleanup",
    "maintenance.cache.cleanup",
)

BACKUP_CAPS = ("backup.create", "backup.verify")

SECURITY_CAPS = (
    "security.audit.deep",
    "security.repo.scan",
    "security.dependencies.audit",
    "security.integrity.audit",
)

TELEMETRY_CAPS = (
    "telemetry.sample",
    "telemetry.hardware_window",
    "diagnostics.collect",
    "diagnostics.process_window",
)


def _attr_calls(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                out.add(func.attr)
            elif isinstance(func, ast.Name):
                out.add(func.id)
    return out


def _route_source(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "routes" / name).read_text(encoding="utf-8")


class PoolTopologyTests(unittest.TestCase):
    def test_evaluation_pool_bounded(self) -> None:
        pool = POOL_CATALOG["evaluation"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 2)

    def test_sqlite_ops_pool(self) -> None:
        pool = POOL_CATALOG["sqlite_ops"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)
        self.assertIn("IO_HEAVY", pool.resource_classes)

    def test_security_pool(self) -> None:
        pool = POOL_CATALOG["security"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)

    def test_maintenance_singleton(self) -> None:
        pool = POOL_CATALOG["maintenance"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)
        self.assertIn("MAINTENANCE_EXCLUSIVE", pool.resource_classes)

    def test_backup_singleton(self) -> None:
        pool = POOL_CATALOG["backup"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)

    def test_capability_routing(self) -> None:
        for cap in EVAL_CAPS:
            self.assertEqual(pool_for_capability(cap), "evaluation", msg=cap)
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)
        for cap in SQLITE_OPS_CAPS:
            self.assertEqual(pool_for_capability(cap), "sqlite_ops", msg=cap)
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
        for cap in MAINT_CAPS:
            self.assertEqual(pool_for_capability(cap), "maintenance", msg=cap)
        for cap in BACKUP_CAPS:
            self.assertEqual(pool_for_capability(cap), "backup", msg=cap)
        for cap in SECURITY_CAPS:
            self.assertEqual(pool_for_capability(cap), "security", msg=cap)
        for cap in TELEMETRY_CAPS:
            self.assertEqual(pool_for_capability(cap), "telemetry", msg=cap)

    def test_catalog_registers_new_caps(self) -> None:
        catalog = build_default_catalog()
        for cap in (
            *EVAL_CAPS,
            *SQLITE_OPS_CAPS,
            *MAINT_CAPS,
            *BACKUP_CAPS,
            *SECURITY_CAPS,
            *TELEMETRY_CAPS,
        ):
            self.assertIsNotNone(catalog.get(cap), msg=cap)


class RouteAstGuards(unittest.TestCase):
    def test_evaluation_routes_no_inline_run(self) -> None:
        tree = ast.parse(_route_source("evaluation.py"))
        calls = _attr_calls(tree)
        for forbidden in {
            "run_foundation",
            "run_regression_corpus",
            "run_ablations",
            "run_assistant_benchmark",
            "run_paired_evaluation",
            "run_suite",
        }:
            self.assertNotIn(forbidden, calls, msg=forbidden)

    def test_backup_routes_no_inline_create_restore(self) -> None:
        src = _route_source("platform.py")
        tree = ast.parse(src)
        # Within create_backup / restore_backup functions, BackupService methods
        # must not be invoked — only enqueue.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {
                "create_backup",
                "restore_backup",
                "verify_backup",
            }:
                calls = _attr_calls(node)
                self.assertNotIn("create", calls - {"enqueue"}, msg=node.name)
                self.assertNotIn("restore", calls, msg=node.name)
                self.assertIn("enqueue", calls, msg=node.name)

    def test_sqlite_routes_enqueue_heavy_ops(self) -> None:
        src = _route_source("sqlite_manager.py")
        self.assertIn("maintenance.db.vacuum", src)
        self.assertIn("maintenance.db.integrity", src)
        self.assertIn("sqlite_ops", src)
        self.assertIn("classify_operator_query", src)


class HeavyQueryClassificationTests(unittest.TestCase):
    def test_limit_is_not_cost_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "big.db"
            db.write_bytes(b"0" * (70 * 1024 * 1024))
            decision = classify_operator_query(
                sql="SELECT COUNT(*) FROM huge",
                domain="CONTROL",
                db_path=db,
                limit=1,
            )
            self.assertTrue(decision.heavy)
            self.assertEqual(decision.capability, "sqlite_ops.analytics")

    def test_small_select_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "small.db"
            db.write_bytes(b"0" * 1024)
            decision = classify_operator_query(
                sql="SELECT 1",
                domain="CONTROL",
                db_path=db,
                limit=10,
            )
            self.assertFalse(decision.heavy)

    def test_full_integrity_external(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            db.write_bytes(b"0" * 100)
            decision = classify_integrity_kind("integrity_check", db_path=db)
            self.assertTrue(decision.heavy)
            self.assertEqual(decision.capability, "maintenance.db.integrity")

    def test_blocking_checkpoint_external(self) -> None:
        decision = classify_checkpoint_mode("TRUNCATE")
        self.assertTrue(decision.heavy)
        self.assertEqual(decision.capability, "maintenance.db.checkpoint")
        self.assertFalse(classify_checkpoint_mode("PASSIVE").heavy)


class BackupHashStreamingTests(unittest.TestCase):
    def test_no_read_bytes_in_service_hash_paths(self) -> None:
        src = Path(__file__).resolve().parents[2] / "modules" / "backup" / "service.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn(".read_bytes()", text)

    def test_streaming_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            data = b"leviathan-backup-hash-" * 10_000
            path.write_bytes(data)
            self.assertEqual(_sha256_file(path), hashlib.sha256(data).hexdigest())

    def test_verify_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "control.db"
            import sqlite3

            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE t(x)")
            conn.commit()
            conn.close()
            service = BackupService(
                database_path=db,
                artifacts_root=root / "artifacts",
                backup_root=root / "backups",
            )
            (root / "artifacts").mkdir()
            manifest = service.create(note="test")
            dest = root / "backups" / manifest.backup_id
            target = next(dest.glob("leviathan_*.db"), dest / "leviathan.db")
            raw = target.read_bytes()
            target.write_bytes(raw[:-1] + bytes([(raw[-1] ^ 0xFF)]))
            result = service.verify(manifest.backup_id, level="HASH_VERIFIED")
            self.assertEqual(result["status"], "FAIL")


class SecurityScanTests(unittest.TestCase):
    def test_excludes_hades_editor_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Data" / "HADES").mkdir(parents=True)
            (root / "Data" / "HADES" / "secret.txt").write_text(
                "AKIAIOSFODNN7EXAMPLE", encoding="utf-8"
            )
            (root / "editor").mkdir()
            (root / "editor" / "leak.txt").write_text(
                "AKIAIOSFODNN7EXAMPLE", encoding="utf-8"
            )
            safe = root / "Data" / "backend"
            safe.mkdir(parents=True)
            safe.joinpath("config.py").write_text(
                "api_key = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8"
            )
            report = run_repo_scan(root)
            paths = {f.path for f in report.findings}
            self.assertTrue(any("config.py" in p for p in paths))
            self.assertFalse(any("HADES" in p for p in paths))
            self.assertFalse(any(p.startswith("editor") for p in paths))
            for finding in report.findings:
                blob = finding.public_dict()
                self.assertTrue(blob["secretRedacted"])
                self.assertNotIn("AKIA", str(blob))

    def test_dependency_audit_no_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
            report = run_dependency_audit(root)
            self.assertEqual(report.scanner_status, "UNAVAILABLE")
            self.assertIn(report.measurement, {"UNMEASURED", "NOT_APPLICABLE"})


class DurableFenceTests(unittest.TestCase):
    def test_durable_fence_blocks_writes(self) -> None:
        from Data.modules.backup.maintenance import (
            MaintenanceError,
            assert_writes_allowed,
            durable_writes_fenced,
            register_process_coordinator,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register_process_coordinator(None)
            state = root / "maintenance_state.json"
            state.write_text(
                '{"state":"RESTORING","writesFenced":true}',
                encoding="utf-8",
            )
            self.assertTrue(durable_writes_fenced(root))
            with self.assertRaises(MaintenanceError):
                assert_writes_allowed(op="test", backup_root=root)


class MainGateAstGuards(unittest.TestCase):
    def test_main_gates_do_not_run_foundation(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        text = main_path.read_text(encoding="utf-8")
        # Extract the two gate functions and ensure run_foundation is absent.
        self.assertNotIn(
            "evaluation_platform.run_foundation(persist=True)",
            text,
        )
        # Serving fixture must not be production proof in evaluation worker.
        eval_ep = (
            Path(__file__).resolve().parents[2]
            / "modules"
            / "workers"
            / "entrypoints"
            / "evaluation.py"
        )
        eval_text = eval_ep.read_text(encoding="utf-8")
        self.assertIn("fixtureIsNotProductionProof", eval_text)
        self.assertNotIn("ManagedLocalServingAdapter", eval_text)


if __name__ == "__main__":
    unittest.main()
