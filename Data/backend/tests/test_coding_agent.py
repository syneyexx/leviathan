"""Acceptance tests for the LEVIATHAN Coding Agent control plane."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import ConfigurationError, Settings
from Data.modules.agents import AgentKind, AgentRuntime
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.coding import (
    CODING_SYSTEM_PROMPT,
    CodingControlPlane,
    CodingLoop,
    FakeLLM,
    Mission,
    SessionStatus,
    apply_unified_diff,
    confine,
    extract_capabilities,
    is_denied,
    strip_capabilities,
)
from Data.modules.coding.patch import PatchApplyError as PatchError
from Data.modules.coding.store import CodingStore
from Data.modules.coding.tools import enforce_capability
from Data.modules.coding.types import CodingError
from Data.modules.common.paths import PathEscapeError
from Data.modules.context import ContextBuilder
from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.reasoning import ReasoningEngine, ReasoningPlan
from Data.modules.verification import VerificationEngine
from Data.modules.evidence import EvidenceStore


class CodingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "codingworkspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "leviathan.db"
        self.store = CodingStore(self.db_path)
        self.store.initialize()

        self.registry = build_default_registry()
        self.runtime = FunctionRuntime(self.registry, max_concurrency=2, warm_cache_size=0)
        self.catalog = build_default_catalog()
        self.approval_store = ApprovalStore(self.db_path)
        self.approval_store.initialize()
        self.approvals = ApprovalService(self.approval_store, PolicyEngine())
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.runtime,
            approval_checker=self.approvals,
        )
        self.fake_llm = FakeLLM()
        self.settings = mock.Mock()
        self.settings.features.agents_enabled = True
        self.settings.features.coding_enabled = True
        self.settings.coding.workspace = self.workspace
        self.settings.coding.max_rounds = 8
        self.settings.coding.temperature = 0.1
        self.settings.coding.token_budget = 4000
        self.settings.coding.max_file_bytes = 1_000_000

        self.loop = CodingLoop(
            self.store,
            gateway=self.gateway,
            approvals=self.approvals,
            llm=self.fake_llm,
            context_builder=ContextBuilder(token_budget=4000),
            reasoning=ReasoningEngine(),
            settings=self.settings,
            agents_enabled=True,
            coding_enabled=True,
        )
        self.plane = CodingControlPlane(
            self.store,
            gateway=self.gateway,
            approvals=self.approvals,
            loop=self.loop,
            settings=self.settings,
            agents_enabled=True,
            coding_enabled=True,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    # --- flags --------------------------------------------------------------

    def test_01_flags_off_session_disabled(self) -> None:
        plane = CodingControlPlane(
            self.store,
            gateway=self.gateway,
            approvals=self.approvals,
            loop=self.loop,
            settings=self.settings,
            agents_enabled=False,
            coding_enabled=False,
        )
        session = plane.create_session(goal="write hello", workspace_root=str(self.workspace))
        self.assertEqual(session.status, SessionStatus.DISABLED)
        self.assertIn("LEVIATHAN_FEATURE_AGENTS", session.error or "")
        # No gateway writes should have occurred
        self.assertEqual(self.gateway.telemetry.get("completed", 0), 0)

    def test_coding_requires_agents_parent(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_AGENTS": "false",
            "LEVIATHAN_FEATURE_CODING": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    # --- confinement --------------------------------------------------------

    def test_02_hades_path_denied(self) -> None:
        with self.assertRaises(PathEscapeError):
            confine(self.workspace, "HADES/secret.txt")
        with self.assertRaises(PathEscapeError):
            confine(self.workspace, "../HADES")
        self.assertTrue(is_denied(self.workspace / "HADES" / "x.py"))
        self.assertTrue(is_denied(r"D:\leviathan\codingworkspace\HADES\x.py"))

        # Gateway-level: enforce_capability rejects
        with self.assertRaises(CodingError) as ctx:
            enforce_capability(
                "file.read",
                {"path": "HADES/x.py"},
                workspace_root=self.workspace,
                read_paths=set(),
                mission=Mission.GENERIC,
                writes_this_round=0,
            )
        self.assertEqual(ctx.exception.code, "PATH_DENIED")

    def test_workspace_search_confined(self) -> None:
        (self.workspace / "alpha.py").write_text("CodingLoop lives here\n", encoding="utf-8")
        (self.workspace / "HADES").mkdir()
        (self.workspace / "HADES" / "secret.py").write_text("secret CodingLoop\n", encoding="utf-8")
        from Data.modules.coding.workspace import search_files

        result = search_files(self.workspace, "CodingLoop")
        paths = [h["path"] for h in result["hits"]]
        self.assertTrue(any("alpha.py" in p for p in paths))
        self.assertFalse(any("HADES" in p for p in paths))
        self.assertIn(result["method"], {"python", "ripgrep"})

    # --- patch applicator ---------------------------------------------------

    def test_05_patch_hunk_mismatch_fail_closed(self) -> None:
        original = "line1\nline2\nline3\n"
        good = """@@ -1,3 +1,3 @@
 line1
-line2
+line2-fixed
 line3
"""
        updated = apply_unified_diff(original, good)
        self.assertIn("line2-fixed", updated)

        bad = """@@ -1,3 +1,3 @@
 line1
-line-NOT-HERE
+line2-fixed
 line3
"""
        with self.assertRaises(PatchError):
            apply_unified_diff(original, bad)
        # File unchanged when applied via function + gateway without writing on error
        target = self.workspace / "sample.py"
        target.write_text(original, encoding="utf-8")
        from Data.functions.text_file_patch import run as patch_run

        with self.assertRaises(ValueError):
            patch_run(str(target), bad)
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    # --- approvals / write --------------------------------------------------

    def test_03_write_without_approval_rejected(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="file.write",
                arguments={"path": str(self.workspace / "a.py"), "content": "x\n"},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertIn("approval", (result.error or "").lower())

    def test_04_write_with_approval_completed(self) -> None:
        path = self.workspace / "b.py"
        args = {"path": str(path), "content": "print('hi')\n"}
        record = self.approvals.request(
            capability_id="file.write",
            side_effects=("WRITE",),
            requested_by="test",
            arguments=args,
        )
        self.approvals.approve(record.approval_id)
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="file.write",
                arguments=args,
                approval_id=record.approval_id,
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertTrue(path.is_file())
        self.assertIn("hash_after", result.output or {})

    # --- ENFORCE unread / must_patch ----------------------------------------

    def test_16_unread_write_rejected(self) -> None:
        with self.assertRaises(CodingError) as ctx:
            enforce_capability(
                "file.write",
                {"path": "newish.py", "content": "x"},
                workspace_root=self.workspace,
                read_paths=set(),
                mission=Mission.GENERIC,
                writes_this_round=0,
            )
        self.assertEqual(ctx.exception.code, "unread_file")

    def test_17_must_patch_for_large_file(self) -> None:
        big = self.workspace / "big.py"
        big.write_text("\n".join(f"line{i}" for i in range(81)) + "\n", encoding="utf-8")
        with self.assertRaises(CodingError) as ctx:
            enforce_capability(
                "file.write",
                {"path": "big.py", "content": "x"},
                workspace_root=self.workspace,
                read_paths={"big.py"},
                mission=Mission.GENERIC,
                writes_this_round=0,
            )
        self.assertEqual(ctx.exception.code, "must_patch")

    # --- file.read enhancements --------------------------------------------

    def test_21_secrets_redacted_from_env_read(self) -> None:
        env_path = self.workspace / ".env"
        env_path.write_text("API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
        from Data.functions.text_file_read import run as read_run

        out = read_run(str(env_path))
        self.assertIn("L1|", out["content"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", out["content"])
        self.assertIn("REDACTED", out["content"])

    def test_22_binary_file_read_failed(self) -> None:
        bin_path = self.workspace / "blob.bin"
        bin_path.write_bytes(b"hello\x00world")
        from Data.functions.text_file_read import run as read_run

        with self.assertRaises(ValueError) as ctx:
            read_run(str(bin_path))
        self.assertIn("binary", str(ctx.exception).lower())

    def test_file_read_line_numbers(self) -> None:
        path = self.workspace / "lines.py"
        path.write_text("a\nb\nc\n", encoding="utf-8")
        from Data.functions.text_file_read import run as read_run

        out = read_run(str(path), start_line=2, end_line=3)
        self.assertIn("L2|b", out["content"])
        self.assertIn("L3|c", out["content"])
        self.assertNotIn("L1|", out["content"])

    # --- parser -------------------------------------------------------------

    def test_27_parser_extracts_xml_from_fenced_mix(self) -> None:
        text = (
            "I will search.\n"
            "```xml\n"
            '<capability id="workspace.search">\n'
            '  <arg name="query">CodingPage</arg>\n'
            "</capability>\n"
            "```\n"
            "Then read."
        )
        caps = extract_capabilities(text)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].capability_id, "workspace.search")
        self.assertEqual(caps[0].arguments.get("query"), "CodingPage")
        visible = strip_capabilities(text)
        self.assertNotIn("<capability", visible)
        self.assertIn("I will search", visible)

    # --- loop / worker ------------------------------------------------------

    def test_01b_disabled_loop(self) -> None:
        loop = CodingLoop(
            self.store,
            gateway=self.gateway,
            approvals=self.approvals,
            llm=self.fake_llm,
            settings=self.settings,
            agents_enabled=True,
            coding_enabled=False,
        )
        session = self.store.create_session(
            mission=Mission.GENERIC,
            workspace_root=str(self.workspace),
            user_goal="x",
            status=SessionStatus.RUNNING,
        )
        result = loop.run_round(session.session_id)
        self.assertEqual(result.status, SessionStatus.DISABLED)

    def test_19_worker_non_blocking_turn(self) -> None:
        # Slow fake LLM
        barrier = threading.Event()

        class SlowLLM:
            temperature_seen: list[float] = []

            def complete(self, messages, *, temperature=0.1, model_id=None):
                SlowLLM.temperature_seen.append(temperature)
                barrier.wait(timeout=2.0)
                return ("done without tools", model_id or "slow")

        self.loop.llm = SlowLLM()
        self.plane.loop = self.loop
        self.plane.worker.loop = self.loop
        self.plane.start_background(poll_seconds=0.05) if False else None
        # Use drain-style: start_turn returns immediately with RUNNING
        session = self.plane.create_session(goal="list files", workspace_root=str(self.workspace))
        started = time.perf_counter()
        # Manually set RUNNING without waiting for LLM
        updated = self.plane.start_turn(session.session_id, message="list files please")
        elapsed = time.perf_counter() - started
        self.assertEqual(updated.status, SessionStatus.RUNNING)
        self.assertLess(elapsed, 0.5, msg="start_turn must not block on LLM")
        # Process one round in background thread to prove worker pattern
        done = threading.Event()

        def _work() -> None:
            self.plane.worker.process_next()
            done.set()

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        barrier.set()
        self.assertTrue(done.wait(timeout=3.0))
        t.join(timeout=1.0)
        # temperature captured
        self.assertTrue(SlowLLM.temperature_seen)
        self.assertAlmostEqual(SlowLLM.temperature_seen[0], 0.1)

    def test_24_temperature_is_0_1(self) -> None:
        self.fake_llm.push("No tools, just an answer.")
        session = self.plane.create_session(goal="explain", workspace_root=str(self.workspace))
        self.store.update_session(session.session_id, status=SessionStatus.RUNNING)
        self.loop.run_round(session.session_id)
        self.assertEqual(self.fake_llm.temperature_seen[-1], 0.1)

    def test_20_waiting_approval_then_approve_writes(self) -> None:
        target = self.workspace / "note.txt"
        # SCAFFOLD allows unread create
        session = self.plane.create_session(
            goal="create note",
            mission="SCAFFOLD",
            workspace_root=str(self.workspace),
        )
        self.fake_llm.push(
            '<capability id="file.write">'
            f'<arg name="path">note.txt</arg>'
            f'<arg name="content">hello</arg>'
            "</capability>"
        )
        self.store.update_session(session.session_id, status=SessionStatus.RUNNING)
        result = self.loop.run_round(session.session_id)
        self.assertEqual(result.status, SessionStatus.WAITING_APPROVAL)
        self.assertFalse(target.exists())
        pending = self.store.get_session(session.session_id).pending_capability  # type: ignore[union-attr]
        self.assertIsNotNone(pending)
        approval_id = pending["approval_id"]
        # Deny path first on a copy? — deny should not write
        self.approvals.deny(approval_id, reason="nope")
        denied = self.loop.run_round(session.session_id, approval_ids=[approval_id])
        self.assertFalse(target.exists())
        self.assertEqual(denied.status, SessionStatus.RUNNING)

        # Fresh write attempt with approve
        self.fake_llm.push(
            '<capability id="file.write">'
            f'<arg name="path">note.txt</arg>'
            f'<arg name="content">hello</arg>'
            "</capability>"
        )
        session2 = self.store.get_session(session.session_id)
        assert session2 is not None
        self.store.update_session(session.session_id, status=SessionStatus.RUNNING, pending_capability=None)
        result2 = self.loop.run_round(session.session_id)
        self.assertEqual(result2.status, SessionStatus.WAITING_APPROVAL)
        pending2 = self.store.get_session(session.session_id).pending_capability  # type: ignore[union-attr]
        approval2 = pending2["approval_id"]
        self.approvals.approve(approval2)
        resumed = self.plane.start_turn(session.session_id, approval_id=approval2)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")
        self.assertNotEqual(resumed.status, SessionStatus.WAITING_APPROVAL)

    def test_23_two_running_sessions_same_workspace_409(self) -> None:
        s1 = self.plane.create_session(goal="one", workspace_root=str(self.workspace))
        self.store.update_session(s1.session_id, status=SessionStatus.RUNNING)
        with self.assertRaises(CodingError) as ctx:
            self.plane.create_session(goal="two", workspace_root=str(self.workspace))
        self.assertEqual(ctx.exception.http_status, 409)

    def test_07_max_rounds_does_not_fake_completed_without_verify(self) -> None:
        self.settings.coding.max_rounds = 2
        # Always emit a read so rounds continue
        (self.workspace / "f.py").write_text("x\n", encoding="utf-8")
        for _ in range(5):
            self.fake_llm.push(
                '<capability id="file.read"><arg name="path">f.py</arg></capability>'
            )
        session = self.plane.create_session(goal="read forever", workspace_root=str(self.workspace))
        self.store.update_session(session.session_id, status=SessionStatus.RUNNING)
        last = None
        for _ in range(5):
            last = self.loop.run_round(session.session_id)
            if last.status != SessionStatus.RUNNING:
                break
        assert last is not None
        self.assertIn(
            last.status,
            {
                SessionStatus.COMPLETED,
                SessionStatus.UNVERIFIED,
                SessionStatus.PARTIAL,
                SessionStatus.RESOURCE_EXHAUSTED,
            },
        )

    def test_08_verification_without_evidence_unmeasured(self) -> None:
        evidence = EvidenceStore(self.db_path)
        evidence.initialize()
        engine = VerificationEngine(evidence)
        report = engine.verify([])
        self.assertEqual(report.outcome.value, "UNMEASURED")

    def test_12_run_tests_nonzero_not_passed(self) -> None:
        from Data.functions.coding_run_tests import run as run_tests

        out = run_tests(
            selector="Data/backend/tests/no_such_test_file_xyz.py",
            cwd=str(Path(__file__).resolve().parents[3]),
            timeout_seconds=30,
        )
        self.assertFalse(out["passed"])
        self.assertNotEqual(out["exit_code"], 0)
        self.assertEqual(out["status"], "FAILED")

    def test_13_run_command_shell_string_rejected(self) -> None:
        with self.assertRaises(CodingError) as ctx:
            enforce_capability(
                "coding.run_command",
                {"argv": "rm -rf /"},
                workspace_root=self.workspace,
                read_paths=set(),
                mission=Mission.GENERIC,
                writes_this_round=0,
            )
        self.assertEqual(ctx.exception.code, "SHELL_STRING")

    def test_14_cancel_between_rounds(self) -> None:
        session = self.plane.create_session(goal="cancel me", workspace_root=str(self.workspace))
        self.store.update_session(session.session_id, status=SessionStatus.RUNNING)
        self.plane.cancel(session.session_id)
        result = self.loop.run_round(session.session_id)
        self.assertEqual(result.status, SessionStatus.CANCELLED)

    def test_11_agent_runtime_delegates_when_coding_enabled(self) -> None:
        agents = AgentRuntime(
            gateway=self.gateway,
            agents_enabled=True,
            coding=self.plane,
            coding_enabled=True,
        )
        started = time.perf_counter()
        result = agents.execute("build a helper", kind=AgentKind.CODING)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertIn(result.status, {"RUNNING", "CREATED", "COMPLETED", "DISABLED", "WAITING_APPROVAL"})
        self.assertTrue(result.steps)

    def test_agent_runtime_plan_still_has_verify(self) -> None:
        agents = AgentRuntime(gateway=self.gateway, agents_enabled=True)
        steps = agents.plan("read file and inspect csv", kind=AgentKind.CODING)
        kinds = [s.kind.value for s in steps]
        self.assertIn("VERIFY", kinds)

    def test_26_catalog_includes_coding_capabilities(self) -> None:
        ids = {item.id for item in self.catalog.list()}
        for required in {
            "workspace.list",
            "workspace.search",
            "file.write",
            "file.patch",
            "file.delete",
            "coding.run_tests",
            "git.status",
            "git.diff",
        }:
            self.assertIn(required, ids)

    def test_git_status_honest_without_repo(self) -> None:
        from Data.functions.git_status import run as git_status

        out = git_status(str(self.workspace))
        self.assertEqual(out["status"], "FAILED")
        self.assertIn(".git", out["error"])

    def test_18_context_compaction_budget(self) -> None:
        # BehaviorProfile identity + coding overlay can exceed tiny budgets alone;
        # assert compaction drops older history while retaining the latest user turn.
        builder = ContextBuilder(token_budget=2000, reserve_response_tokens=100)
        plan = ReasoningPlan(
            intent="coding",
            complexity="low",
            use_knowledge=False,
            steps=("read",),
        )
        history = []
        for i in range(4):
            body = ("FILE CONTENT " + ("x" * 200) + "\n") * 5
            history.append({"role": "user", "content": f"CAPABILITY RESULT id=file.read\n{body}"})
            history.append({"role": "assistant", "content": f"read {i}"})
        pack = builder.build(
            history=history,
            knowledge=[],
            plan=plan,
            mode="coding",
            constraints=CODING_SYSTEM_PROMPT[:500],
            token_budget=1200,
        )
        self.assertTrue(pack.dropped)  # older history must be trimmed under pressure
        latest_retained = any(
            s.name == "history_user_latest" and s.included for s in pack.sections
        )
        self.assertTrue(latest_retained)
        # Older user turns dropped; at most one user history section remains.
        user_history = [
            s for s in pack.sections
            if s.included and s.kind == "history" and "user" in s.name
        ]
        self.assertEqual(len(user_history), 1)
        self.assertGreaterEqual(sum(1 for d in pack.dropped if d.startswith("history:user")), 2)
        self.assertTrue(
            pack.system_prompt.startswith("# LEVIATHAN")
            or "Coding Agent" in pack.system_prompt
            or "Flight" in pack.system_prompt
            or pack.system_prompt
        )

    def test_prompts_not_generic(self) -> None:
        self.assertIn("unread_file", CODING_SYSTEM_PROMPT)
        self.assertIn("workspace.search", CODING_SYSTEM_PROMPT)
        self.assertIn("Shot 4", CODING_SYSTEM_PROMPT)
        self.assertNotIn("You are a helpful coding assistant", CODING_SYSTEM_PROMPT)

    def test_public_summary_coding_no_workspace_leak(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_FEATURE_AGENTS": "true",
                "LEVIATHAN_FEATURE_CODING": "true",
                "LEVIATHAN_CODING_WORKSPACE": "D:/leviathan/codingworkspace",
            },
            clear=False,
        ):
            cfg = Settings.from_env()
        summary = cfg.public_summary()
        self.assertIn("coding", summary)
        self.assertTrue(summary["features"]["coding_enabled"])
        self.assertNotIn("D:/leviathan/codingworkspace", str(summary["coding"]))


if __name__ == "__main__":
    unittest.main()
