"""Characterization + honesty tests for Gen2 sandbox extraction."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from gen2.sandbox import (
    available_sandbox_tiers,
    detect_host_sandbox_capabilities,
    path_is_within,
    try_assign_job_object,
)
from gen2.store import Gen2Store
from gen2.services import Gen2Services


class SandboxModuleTests(unittest.TestCase):
    def test_path_jail_relative_to(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            inside = root / "a" / "b.txt"
            inside.parent.mkdir(parents=True)
            inside.write_text("x", encoding="utf-8")
            self.assertTrue(path_is_within(inside, root))
            self.assertFalse(path_is_within(Path(tmp) / "evil.txt", root))

    def test_host_capabilities_honest_on_linux(self) -> None:
        caps = detect_host_sandbox_capabilities()
        self.assertIn(0, caps["available_tiers"])
        self.assertIn(1, caps["available_tiers"])
        self.assertFalse(caps["quality_evaluated"])
        self.assertFalse(caps["operationally_tested"])
        self.assertFalse(caps.get("os_isolation_enforced"))
        if os.name != "nt":
            self.assertFalse(caps["job_objects"])
            self.assertNotIn(2, caps["available_tiers"])
            self.assertEqual(caps.get("verification_status"), "UNVERIFIED_ON_HOST")
            probe = try_assign_job_object(os.getpid())
            self.assertFalse(probe["ok"])
            self.assertEqual(probe["reason"], "not_windows")
            self.assertFalse(probe.get("operationally_tested"))

    def test_tier2_selftest_unverified_off_windows(self) -> None:
        from gen2.sandbox_job import run_tier2_selftest, WindowsJobSandbox
        from gen2.sandbox import spawn_in_job_object

        report = run_tier2_selftest()
        self.assertTrue(report["implemented"])
        if os.name != "nt":
            self.assertFalse(report["available_on_host"])
            self.assertFalse(report["operationally_tested"])
            self.assertEqual(report["status"], "UNVERIFIED_ON_HOST")
            spawned = spawn_in_job_object([sys.executable, "-c", "print(1)"])
            self.assertFalse(spawned["ok"])
            self.assertFalse(spawned["operationally_tested"])
            sandbox = WindowsJobSandbox()
            self.assertFalse(sandbox.available())

    def test_api_presence_does_not_imply_operational(self) -> None:
        caps = detect_host_sandbox_capabilities()
        # Even if someone stubs job_objects True later, operationally_tested stays False here.
        self.assertFalse(caps["operationally_tested"])
        env_tier, env = __import__("gen2.sandbox", fromlist=["build_default_envelope"]).build_default_envelope(
            "third.party", permissions=["subprocess", "filesystem"]
        )
        self.assertFalse(env.get("os_isolation_enforced"))
        if os.name != "nt":
            self.assertNotEqual(env.get("execution_mode"), "windows_job_object")
            self.assertIn(env_tier, {0, 1})

    def test_enforce_fail_closed_unavailable_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            svc = Gen2Services(store, data_root=Path(tmp))
            env = svc.default_envelope("third-party-x", permissions=["subprocess", "filesystem"])
            # Force tier 3 into store even if host lacks it.
            store.upsert_envelope("third-party-x", 3, {**env["envelope"], "tier": 3})
            denied = svc.enforce_envelope("third-party-x", action="inspect", approved=True)
            if 3 not in available_sandbox_tiers():
                self.assertFalse(denied["ok"])
                self.assertIn("tier_unavailable", denied["violations"])
                self.assertEqual(denied["execution_mode"], "blocked")

    def test_path_block_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            svc = Gen2Services(store, data_root=Path(tmp))
            env = svc.default_envelope("third-party-x", permissions=["subprocess", "filesystem"])
            self.assertIn(env["tier"], {1, 2})
            denied = svc.enforce_envelope(
                "third-party-x",
                action="write",
                path="/tmp/evil",
                approved=True,
            )
            self.assertFalse(denied["ok"])
            self.assertTrue(any("path_outside_envelope" in v for v in denied["violations"]))

    def test_envelope_deny_paths_network_subprocess_env_secret(self) -> None:
        from gen2.policy_profiles import envelope_for_profile

        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "g.db"))
            svc = Gen2Services(store, data_root=Path(tmp))
            strict = envelope_for_profile("deny.plugin", "strict")
            store.upsert_envelope("deny.plugin", int(strict["tier"]), strict["envelope"])

            net = svc.enforce_envelope(
                "deny.plugin", action="network", network_host="evil.example", approved=True
            )
            self.assertFalse(net["ok"])
            self.assertIn("network_denied", net["violations"])
            self.assertIn("honesty", net)

            sub = svc.enforce_envelope("deny.plugin", action="subprocess", approved=True)
            self.assertFalse(sub["ok"])
            self.assertIn("subprocess_denied", sub["violations"])

            # Research profile: network ask without approval must deny.
            research = envelope_for_profile("ask.plugin", "research")
            store.upsert_envelope("ask.plugin", int(research["tier"]), research["envelope"])
            ask = svc.enforce_envelope(
                "ask.plugin", action="network", network_host="news.example", approved=False
            )
            self.assertFalse(ask["ok"])
            self.assertTrue(
                any(v in ask["violations"] for v in ("network_ask_requires_approval", "approval_required"))
            )

            env_denied = svc.enforce_envelope(
                "deny.plugin", action="env", path="AWS_SECRET_ACCESS_KEY", approved=True
            )
            self.assertFalse(env_denied["ok"])
            self.assertIn("empty_env_allowlist", env_denied["violations"])

            secret_denied = svc.enforce_envelope(
                "deny.plugin", action="secret", path="broker_api_key", approved=True
            )
            self.assertFalse(secret_denied["ok"])
            self.assertIn("empty_secrets_allowlist", secret_denied["violations"])

    def test_honesty_labels_on_linux(self) -> None:
        from gen2.sandbox import sandbox_honesty_labels

        labels = sandbox_honesty_labels()
        self.assertEqual(labels["os_isolation_enforced"], False)
        self.assertTrue(any(b["id"] == "os_isolation" for b in labels["ui_badges"]))
        with tempfile.TemporaryDirectory() as tmp:
            svc = Gen2Services(Gen2Store(str(Path(tmp) / "h.db")), data_root=Path(tmp))
            caps = svc.sandbox_host_capabilities()
            self.assertIn("honesty", caps)
            if os.name != "nt":
                self.assertEqual(caps["verification_status"], "UNVERIFIED_ON_HOST")
                self.assertEqual(caps["honesty"]["tier2_label"], "UNVERIFIED_ON_HOST")
                report = svc.sandbox_tier2_selftest()
                self.assertEqual(report["status"], "UNVERIFIED_ON_HOST")
                self.assertFalse(report["operationally_tested"])


class JobSandboxFailClosedPortableTests(unittest.TestCase):
    """Linux-runnable unit tests for fail-closed helpers (no Win32 required)."""

    def test_fail_closed_result_never_ok(self) -> None:
        from gen2.sandbox_job import (
            REASON_ASSIGN_FAILED,
            REASON_CREATE_SUSPENDED_FAILED,
            REASON_RESUME_FAILED,
            fail_closed_result,
        )

        for reason in (
            REASON_CREATE_SUSPENDED_FAILED,
            REASON_ASSIGN_FAILED,
            REASON_RESUME_FAILED,
        ):
            row = fail_closed_result(reason=reason, pid=42, killed=True)
            self.assertFalse(row.ok)
            self.assertEqual(row.reason, reason)
            self.assertFalse(row.operationally_tested)
            self.assertTrue(row.killed_on_close)

    def test_kill_process_tree_best_effort_calls_hooks(self) -> None:
        from gen2.sandbox_job import kill_process_tree_best_effort

        class FakeProc:
            def __init__(self) -> None:
                self.killed = False
                self.returncode = None

            def poll(self):
                return None if not self.killed else 1

            def kill(self) -> None:
                self.killed = True
                self.returncode = 9

            def wait(self, timeout=None):
                return self.returncode

        job_calls: list[str] = []
        proc = FakeProc()
        evidence = kill_process_tree_best_effort(
            proc,
            terminate_job=lambda: job_calls.append("terminate"),
        )
        self.assertEqual(job_calls, ["terminate"])
        self.assertTrue(proc.killed)
        self.assertTrue(evidence.get("cleanup_attempted"))
        self.assertTrue(evidence.get("terminate_job"))
        self.assertTrue(evidence.get("proc_kill"))

    def test_selftest_timeout_alone_is_not_pass(self) -> None:
        from gen2.sandbox_job import REASON_TIMEOUT, decide_selftest_status

        alone = decide_selftest_status(
            on_windows=True,
            result_ok=False,
            result_reason=REASON_TIMEOUT,
            cleanup_verified=False,
            explicitly_testing_timeout=True,
        )
        self.assertEqual(alone["status"], "FAIL")
        self.assertEqual(alone["failure_reason"], "timeout_without_cleanup_evidence")

        with_cleanup = decide_selftest_status(
            on_windows=True,
            result_ok=False,
            result_reason=REASON_TIMEOUT,
            cleanup_verified=True,
            explicitly_testing_timeout=True,
        )
        self.assertEqual(with_cleanup["status"], "PASS")

        accidental = decide_selftest_status(
            on_windows=True,
            result_ok=False,
            result_reason=REASON_TIMEOUT,
            cleanup_verified=True,
            explicitly_testing_timeout=False,
        )
        self.assertEqual(accidental["status"], "FAIL")

    def test_selftest_linux_unverified(self) -> None:
        from gen2.sandbox_job import decide_selftest_status, run_tier2_selftest

        verdict = decide_selftest_status(
            on_windows=False,
            result_ok=False,
            result_reason="not_windows",
            cleanup_verified=False,
        )
        self.assertEqual(verdict["status"], "UNVERIFIED_ON_HOST")
        if os.name != "nt":
            report = run_tier2_selftest()
            self.assertEqual(report["status"], "UNVERIFIED_ON_HOST")
            self.assertIn("Not full FS/network isolation", report["evidence"]["isolation_scope"])

    def test_configure_ctypes_signatures_defined(self) -> None:
        """Documented binding helper exists and is callable with a fake kernel32."""
        from gen2.sandbox_job import configure_job_object_ctypes

        class FakeFn:
            def __init__(self) -> None:
                self.argtypes = None
                self.restype = None

        class FakeK32:
            CreateJobObjectW = FakeFn()
            SetInformationJobObject = FakeFn()
            AssignProcessToJobObject = FakeFn()
            OpenProcess = FakeFn()
            CloseHandle = FakeFn()
            TerminateJobObject = FakeFn()
            ResumeThread = FakeFn()

        class FakeNt:
            NtResumeProcess = FakeFn()

        k32 = FakeK32()
        nt = FakeNt()
        configure_job_object_ctypes(k32, nt)
        self.assertIsNotNone(k32.CreateJobObjectW.argtypes)
        self.assertIsNotNone(k32.AssignProcessToJobObject.restype)
        self.assertIsNotNone(k32.OpenProcess.argtypes)
        self.assertIsNotNone(k32.CloseHandle.restype)
        self.assertIsNotNone(k32.TerminateJobObject.argtypes)
        self.assertIsNotNone(k32.ResumeThread.restype)
        self.assertIsNotNone(nt.NtResumeProcess.argtypes)

    def test_tier_label_documents_not_full_isolation(self) -> None:
        from gen2.sandbox import TIER_LABELS

        self.assertIn("not full fs/network isolation", TIER_LABELS[2].lower())

    def test_lifecycle_fail_closed_create_assign_resume(self) -> None:
        from gen2.sandbox_job import (
            REASON_ASSIGN_FAILED,
            REASON_CREATE_SUSPENDED_FAILED,
            REASON_RESUME_FAILED,
            run_lifecycle_fail_closed,
        )

        create_fail = run_lifecycle_fail_closed(
            create_suspended_ok=False, assign_ok=True, resume_ok=True
        )
        self.assertFalse(create_fail.ok)
        self.assertEqual(create_fail.reason, REASON_CREATE_SUSPENDED_FAILED)
        self.assertFalse((create_fail.evidence or {}).get("unconstrained_spawn"))

        kills: list[str] = []
        assign_fail = run_lifecycle_fail_closed(
            create_suspended_ok=True,
            assign_ok=False,
            resume_ok=True,
            terminate_job=lambda: kills.append("job"),
            kill_child=lambda: kills.append("child"),
        )
        self.assertFalse(assign_fail.ok)
        self.assertEqual(assign_fail.reason, REASON_ASSIGN_FAILED)
        self.assertTrue(assign_fail.killed_on_close)
        self.assertIn("job", kills)
        self.assertIn("child", kills)

        resume_kills: list[str] = []
        resume_fail = run_lifecycle_fail_closed(
            create_suspended_ok=True,
            assign_ok=True,
            resume_ok=False,
            terminate_job=lambda: resume_kills.append("job"),
            kill_child=lambda: resume_kills.append("child"),
        )
        self.assertFalse(resume_fail.ok)
        self.assertEqual(resume_fail.reason, REASON_RESUME_FAILED)
        self.assertEqual(resume_kills, ["job", "child"])
        # Resume errors must surface in evidence — never silently swallowed.
        self.assertIn("resume", str((resume_fail.evidence or {}).get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
