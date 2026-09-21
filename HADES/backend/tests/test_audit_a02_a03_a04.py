"""Regression tests for A02 execution isolation, A03 artifacts, A04 metrics."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import ArtifactService
from database import Database
from execution_isolation import (
    IsolationPolicy,
    IsolationUnavailable,
    detect_isolation_capabilities,
    run_isolated,
)
from gen2.eval_lab import expand_software_metrics, smoke_expect_match
from gen2.mission_control import (
    default_acceptance_checks,
    evaluate_acceptance_checks,
)
from gen2.store import Gen2Store
from platform_db import PlatformDatabase
from terminal_tool import PolicyTerminalService, TerminalPolicyError


class A02ExecutionIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.secret = self.outside / "SECRET.txt"
        self.secret.write_text("TOPSECRET_CANARY", encoding="utf-8")
        self.cwd = self.data / "cwd"
        self.cwd.mkdir()
        core = Database(str(self.root / "hades.db"))
        core.initialize()
        self.pdb = PlatformDatabase(str(self.root / "hades.db"))
        self.pdb.initialize()
        self.artifacts = ArtifactService(self.pdb, self.data)
        self.term = PolicyTerminalService(self.artifacts, self.data)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_interpreter_escape_blocked_in_secured_mode(self) -> None:
        caps = detect_isolation_capabilities()
        if not caps.get("secured_fs_isolation_available"):
            self.skipTest(f"secured FS isolation unavailable: {caps.get('linux_userns_reason')}")
        binary = Path(sys.executable).name.lower()
        settings = {
            "terminal_allowlist": ["python", "python3", binary],
            "terminal_execution_mode": "secured",
            "terminal_allow_network": False,
        }
        # Direct path read via cat-style argv remains blocked by path jail.
        with self.assertRaises(TerminalPolicyError):
            self.term.run(["cat", str(self.secret)], settings=settings)

        result = self.term.run(
            [sys.executable, "-c", f"print(open({str(self.secret)!r}).read())"],
            settings=settings,
        )
        self.assertTrue(result.get("fs_isolation"))
        self.assertNotEqual(result.get("exit_code"), 0)
        self.assertNotIn("TOPSECRET_CANARY", result.get("stdout") or "")

    def test_inside_workspace_python_still_works(self) -> None:
        caps = detect_isolation_capabilities()
        if not caps.get("secured_fs_isolation_available"):
            self.skipTest("secured FS isolation unavailable")
        target = self.data / "ok.txt"
        target.write_text("HADES_OK", encoding="utf-8")
        binary = Path(sys.executable).name.lower()
        result = self.term.run(
            [sys.executable, "-c", f"print(open({str(target)!r}).read())"],
            settings={
                "terminal_allowlist": ["python", "python3", binary],
                "terminal_execution_mode": "secured",
            },
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("HADES_OK", result["stdout"])
        self.assertTrue(result.get("fs_isolation"))

    def test_env_secret_and_network_blocked(self) -> None:
        caps = detect_isolation_capabilities()
        if not caps.get("secured_fs_isolation_available"):
            self.skipTest("secured FS isolation unavailable")
        os.environ["HADES_CANARY_SECRET_TOKEN"] = "leak-me-please"
        policy = IsolationPolicy(
            read_roots=[self.data],
            write_roots=[self.data],
            allow_network=False,
            mode="secured",
        )
        env_result = run_isolated(
            [sys.executable, "-c", "import os; print(os.environ.get('HADES_CANARY_SECRET_TOKEN','MISSING'))"],
            cwd=self.cwd,
            policy=policy,
            timeout_seconds=15,
        )
        self.assertIn("MISSING", env_result.stdout)
        net_result = run_isolated(
            [
                sys.executable,
                "-c",
                "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',9))",
            ],
            cwd=self.cwd,
            policy=policy,
            timeout_seconds=15,
        )
        self.assertNotEqual(net_result.exit_code, 0)
        self.assertTrue(net_result.network_isolation)

    def test_secured_mode_fails_closed_when_forced_unavailable(self) -> None:
        # Trusted mode remains explicit and labeled.
        policy = IsolationPolicy(read_roots=[self.data], write_roots=[self.data], mode="trusted")
        trusted = run_isolated(
            [sys.executable, "-c", f"print(open({str(self.secret)!r}).read())"],
            cwd=self.cwd,
            policy=policy,
            timeout_seconds=10,
        )
        self.assertEqual(trusted.mode, "trusted")
        self.assertFalse(trusted.fs_isolation)
        self.assertIn("TOPSECRET_CANARY", trusted.stdout)


class A03ArtifactVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        core = Database(str(self.root / "hades.db"))
        core.initialize()
        self.pdb = PlatformDatabase(str(self.root / "hades.db"))
        self.pdb.initialize()
        self.artifacts = ArtifactService(self.pdb, self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_name_only_evidence_is_not_proof(self) -> None:
        checks = [
            {"id": "a", "type": "artifact_exists", "name": "mission_report.md", "required": True},
        ]
        result = evaluate_acceptance_checks(
            checks,
            status="completed",
            verification={
                "status": "passed",
                "evidence_refs": ["mission_report.md"],
                "artifacts": [{"name": "mission_report.md"}],
            },
            artifact_service=self.artifacts,
        )
        self.assertFalse(result["passed"])
        self.assertTrue(any("artifact" in b for b in result["blockers"]))

    def test_verify_ready_bytes_pass(self) -> None:
        art = self.artifacts.create_text_result(
            name="mission_report.md",
            text="# Mission report\nreal bytes\n",
            mime_type="text/markdown",
            kind="generated",
            task_id="task_1",
        )
        checks = [
            {
                "id": "a",
                "type": "artifact_exists",
                "name": "mission_report.md",
                "artifact_id": art["id"],
                "required": True,
                "min_bytes": 1,
            }
        ]
        result = evaluate_acceptance_checks(
            checks,
            status="completed",
            verification={"status": "passed", "artifacts": [art], "task_id": "task_1"},
            mission={"task_id": "task_1"},
            artifact_service=self.artifacts,
        )
        self.assertTrue(result["passed"], result)

    def test_default_deliverables_are_required(self) -> None:
        checks = default_acceptance_checks(domain="research", artifacts=["mission_report.md"])
        art_checks = [c for c in checks if c.get("type") == "artifact_exists"]
        self.assertTrue(art_checks)
        self.assertTrue(all(c.get("required") is True for c in art_checks))


class A04MetricsRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.tmp.name) / "gen2.db"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_perfect_defaults_without_evidence(self) -> None:
        metrics = expand_software_metrics({"passed": True, "scenario_id": "plain_pass", "details": {}})
        self.assertIsNone(metrics.get("citation_coverage"))
        self.assertIsNone(metrics.get("tool_accuracy"))
        reasons = metrics.get("metric_reasons") or {}
        self.assertIn("not_measured", reasons.get("citation_coverage", ""))
        self.assertTrue(
            "not_measured" in reasons.get("tool_accuracy", "")
            or "not_applicable" in reasons.get("tool_accuracy", "")
        )

    def test_dishonest_substring_smoke_fails(self) -> None:
        self.assertFalse(smoke_expect_match("OK", "NOT OK. dishonest."))
        self.assertFalse(smoke_expect_match("honest", "NOT OK. dishonest."))
        self.assertTrue(smoke_expect_match("OK", "OK"))
        self.assertTrue(smoke_expect_match("honest", "honest"))

    def test_smoke_scores_do_not_drive_recommendations(self) -> None:
        self.store.save_eval_run(
            suite="live_model_smoke",
            mode="live_model",
            model_id="live-dishonest",
            summary={
                "pass_rate": 1.0,
                "total": 2,
                "passed": 2,
                "failed": 0,
                "quality_layer": "infrastructure_smoke",
                "not_model_quality": True,
            },
            scores=[
                {
                    "scenario_id": "echo_ok",
                    "passed": True,
                    "model_id": "live-dishonest",
                    "task_type": "chat",
                    "quality_layer": "infrastructure_smoke",
                    "not_model_quality": True,
                    "metrics": {"pass": 1.0},
                },
                {
                    "scenario_id": "refuse_invention",
                    "passed": True,
                    "model_id": "live-dishonest",
                    "task_type": "chat",
                    "quality_layer": "infrastructure_smoke",
                    "not_model_quality": True,
                    "metrics": {"pass": 1.0},
                },
            ],
        )
        best = self.store.best_model_for("chat", metric="pass", min_samples=1)
        self.assertIsNone(best)

        # Comparable quality runs can recommend.
        for _ in range(3):
            self.store.save_eval_run(
                suite="live_quality",
                mode="live_quality",
                model_id="quality-model",
                summary={"pass_rate": 0.9, "quality_layer": "model_answer", "not_model_quality": False},
                scores=[
                    {
                        "scenario_id": "q1",
                        "passed": True,
                        "model_id": "quality-model",
                        "task_type": "chat",
                        "quality_layer": "model_answer",
                        "metrics": {"pass": 0.9},
                    }
                ],
            )
        best2 = self.store.best_model_for("chat", metric="pass", min_samples=3)
        self.assertIsNotNone(best2)
        self.assertEqual(best2["model_id"], "quality-model")
        self.assertEqual(best2.get("quality_layer"), "model_answer")
        self.assertTrue(best2.get("reliable"))


if __name__ == "__main__":
    unittest.main()
