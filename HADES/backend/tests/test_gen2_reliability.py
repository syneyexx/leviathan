"""Regression tests for Gen2 reliability defects reproduced on 6896fc3."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from artifacts import ArtifactService
from database import Database
from gen2 import Gen2Services, Gen2Store
from gen2.services import _path_is_within
from platform_db import PlatformDatabase


class FakeLmStudio:
    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


def _mission_deliverables(arts: ArtifactService, *, task_id: str) -> list[dict]:
    report = arts.create_text_result(
        name="mission_report.md",
        text="# report\nverified\n",
        mime_type="text/markdown",
        kind="generated",
        task_id=task_id,
    )
    index = arts.create_text_result(
        name="evidence_index.json",
        text='{"ok": true}',
        mime_type="application/json",
        kind="generated",
        task_id=task_id,
    )
    return [report, index]


class Gen2ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "gen2.db"))
        db_path = str(self.root / "arts.db")
        Database(db_path).initialize()
        pdb = PlatformDatabase(db_path)
        pdb.initialize()
        self.arts = ArtifactService(pdb, self.root)
        self.svc = Gen2Services(self.store, data_root=self.root, artifact_service=self.arts)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _approve_all(self, mission_id: str) -> None:
        mission = self.store.get_mission(mission_id)
        assert mission
        for gate in mission.get("gates") or []:
            if gate.get("required") and gate.get("status") != "approved":
                self.svc.decide_mission_gate(mission_id, gate["id"], approve=True)

    def test_mission_without_task_bridge_is_blocked(self) -> None:
        mission = self.svc.compile_mission("Doe een volledige intelligence-analyse van NVIDIA.")
        self._approve_all(mission["id"])
        started = self.svc.start_mission(mission["id"], create_task=None)
        self.assertEqual(started["status"], "blocked")
        self.assertIsNone(started.get("task_id"))
        self.assertIn("task_bridge", str(started.get("error") or ""))

    def test_mission_start_idempotent_and_retry_new_execution(self) -> None:
        mission = self.svc.compile_mission("Refactor codebase tests carefully.")
        self._approve_all(mission["id"])
        calls: list[str] = []

        def create_task(_mission: dict) -> dict:
            tid = f"task_{len(calls) + 1}"
            calls.append(tid)
            return {"id": tid}

        first = self.svc.start_mission(mission["id"], create_task=create_task)
        second = self.svc.start_mission(mission["id"], create_task=create_task)
        self.assertEqual(first["status"], "dispatched")
        self.assertEqual(first["task_id"], "task_1")
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(second["task_id"], "task_1")
        self.assertEqual(calls, ["task_1"])

        retry = self.svc.start_mission(mission["id"], create_task=create_task, force_retry=True)
        self.assertEqual(retry["task_id"], "task_2")
        self.assertNotEqual(retry["execution_id"], first["execution_id"])
        self.assertEqual(len(retry.get("executions") or []), 2)

    def test_mission_concurrent_start_single_task(self) -> None:
        mission = self.svc.compile_mission("Research market analogues carefully.")
        self._approve_all(mission["id"])
        calls: list[str] = []
        lock = threading.Lock()

        def create_task(_mission: dict) -> dict:
            with lock:
                tid = f"task_{len(calls) + 1}"
                calls.append(tid)
                return {"id": tid}

        results: list[dict] = []

        def worker() -> None:
            results.append(self.svc.start_mission(mission["id"], create_task=create_task))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        task_ids = {r.get("task_id") for r in results if r.get("task_id")}
        self.assertEqual(task_ids, {"task_1"})
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(r.get("task_id") == "task_1" or r.get("idempotent") for r in results))

    def test_rejected_gate_cannot_become_ready_via_start(self) -> None:
        mission = self.svc.compile_mission("Doe een volledige intelligence-analyse van NVIDIA.")
        started = self.svc.start_mission(mission["id"])
        self.assertEqual(started["status"], "awaiting_approval")
        gate_id = started["gates"][0]["id"]
        failed = self.svc.decide_mission_gate(mission["id"], gate_id, approve=False, note="no")
        self.assertEqual(failed["status"], "failed")
        with self.assertRaises(ValueError):
            self.svc.start_mission(mission["id"], create_task=lambda m: {"id": "x"})

    def test_unknown_compute_job_fails(self) -> None:
        job = self.svc.dispatch_job(payload={"op": "totally_unknown_xyz", "data": 1})
        self.assertEqual(job["status"], "failed")
        self.assertIn("unsupported_job_type", str(job.get("error") or ""))

    def test_inspect_compute_job_labeled(self) -> None:
        job = self.svc.dispatch_job(payload={"op": "ping"})
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["mode"], "inspect")

    def test_sandbox_prefix_sibling_denied(self) -> None:
        allowed = self.root / "plugin-outputs" / "foo"
        sibling = self.root / "plugin-outputs" / "foo_evil"
        allowed.mkdir(parents=True)
        sibling.mkdir(parents=True)
        self.assertTrue(str(sibling.resolve()).startswith(str(allowed.resolve())))
        self.assertFalse(_path_is_within(sibling / "x.txt", allowed))
        env = self.svc.default_envelope("foo", permissions=["filesystem", "subprocess"])
        self.store.upsert_envelope(
            "foo",
            1,
            {
                **env["envelope"],
                "filesystem_writes": [str(allowed)],
                "filesystem_reads": [str(allowed)],
            },
        )
        denied = self.svc.enforce_envelope(
            "foo",
            action="write",
            path=str(sibling / "x.txt"),
            approved=True,
        )
        self.assertFalse(denied["ok"])
        self.assertTrue(any("path_outside_envelope" in v for v in denied["violations"]))

    def test_sandbox_traversal_and_missing_params(self) -> None:
        jail = self.root / "jail"
        jail.mkdir()
        env = self.svc.default_envelope("bar", permissions=["filesystem", "subprocess"])
        self.store.upsert_envelope(
            "bar",
            1,
            {**env["envelope"], "filesystem_reads": [str(jail)], "filesystem_writes": [str(jail)], "network_domains": []},
        )
        traversal = self.svc.enforce_envelope(
            "bar",
            action="read",
            path=str(jail / ".." / "outside.txt"),
            approved=True,
        )
        self.assertFalse(traversal["ok"])
        missing_path = self.svc.enforce_envelope("bar", action="write", approved=True)
        self.assertFalse(missing_path["ok"])
        self.assertIn("path_required", missing_path["violations"])
        missing_host = self.svc.enforce_envelope("bar", action="network", approved=True)
        self.assertFalse(missing_host["ok"])
        self.assertIn("network_host_required", missing_host["violations"])
        empty_net = self.svc.enforce_envelope("bar", action="network", network_host="evil.test", approved=True)
        self.assertFalse(empty_net["ok"])
        # Default envelopes deny network when permission absent; empty allowlist is the ask-path check.
        self.assertTrue(
            any(v in empty_net["violations"] for v in ("network_denied", "empty_network_allowlist"))
        )
        ask_env = {
            **env["envelope"],
            "filesystem_reads": [str(jail)],
            "filesystem_writes": [str(jail)],
            "network_policy": "ask",
            "network_domains": [],
            "approval_required": False,
        }
        self.store.upsert_envelope("bar-ask", 1, ask_env)
        empty_ask = self.svc.enforce_envelope(
            "bar-ask", action="network", network_host="evil.test", approved=True, check_approval=False
        )
        self.assertFalse(empty_ask["ok"])
        self.assertIn("empty_network_allowlist", empty_ask["violations"])

    def test_unavailable_tier_does_not_claim_isolation(self) -> None:
        env = self.svc.default_envelope("hard", permissions=["subprocess"])
        # Request a tier that no host advertises (Job Objects may make tier 2
        # available on Windows CI; 99 must always fail closed).
        fantasy_tier = 99
        self.store.upsert_envelope(
            "hard",
            fantasy_tier,
            {**env["envelope"], "tier": fantasy_tier, "execution_mode": "unavailable_fantasy_tier"},
        )
        result = self.svc.enforce_envelope("hard", action="inspect", approved=True)
        self.assertFalse(result["ok"])
        self.assertIn("tier_unavailable", result["violations"])
        self.assertEqual(result["requested_tier"], fantasy_tier)
        self.assertIsNone(result["effective_tier"])
        # Tiers 0/1 are always present. Higher tiers are host-detected only.
        available = result["available_enforcement"]
        self.assertIn(0, available)
        self.assertIn(1, available)
        self.assertNotIn(fantasy_tier, available)

    def test_context_dedupe_uses_full_content(self) -> None:
        prefix = ("SAME INTRO WORD " * 200).strip()
        self.assertGreater(len(prefix), 2000)
        items = [
            {
                "item_id": "1",
                "content": f"{prefix} UNIQUE PART ALPHA about cats",
                "usefulness": 0.9,
                "reliability": 0.9,
                "source": "s1",
            },
            {
                "item_id": "2",
                "content": f"{prefix} UNIQUE PART BETA about dogs entirely different",
                "usefulness": 0.9,
                "reliability": 0.9,
                "source": "s2",
            },
        ]
        pack = self.svc.compile_context(goal="test", items=items, max_tokens=5000, persist=False)
        kept = {i["item_id"] for i in pack["kept"]}
        self.assertEqual(kept, {"1", "2"})

    def test_context_zero_reliability_preserved(self) -> None:
        pack = self.svc.compile_context(
            goal="test",
            items=[
                {
                    "item_id": "z",
                    "content": "untrusted rumor text for scoring comparison pad",
                    "reliability": 0.0,
                    "freshness": 0.0,
                    "usefulness": 0.8,
                    "source": "rumor",
                },
                {
                    "item_id": "t",
                    "content": "trusted rumor text for scoring comparison pad",
                    "reliability": 0.9,
                    "freshness": 0.0,
                    "usefulness": 0.8,
                    "source": "trusted",
                },
            ],
            max_tokens=200,
            persist=False,
        )
        by_id = {i["item_id"]: i for i in pack["kept"]}
        self.assertIn("z", by_id)
        self.assertIn("t", by_id)
        self.assertLess(by_id["z"]["utility_per_token"], by_id["t"]["utility_per_token"])


class Gen2EnvelopeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api.db"))
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        self.client_patch = patch.object(main, "lm_client", return_value=FakeLmStudio())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_blocked_envelope_never_reaches_executor(self) -> None:
        ensure = main.ensure_platform_services
        ensure()
        pm = main.plugin_manager
        invoked = {"count": 0}
        original_run = pm._run_command

        def guard(*args, **kwargs):
            invoked["count"] += 1
            return original_run(*args, **kwargs)

        pm._run_command = guard  # type: ignore[method-assign]
        # Synthetic gate that always blocks write paths before executor.
        def deny_gate(plugin, tool, validated, **kwargs):
            return {
                "ok": False,
                "violations": ["path_outside_envelope:/evil"],
                "requested_tier": 1,
                "effective_tier": None,
            }

        pm.set_envelope_gate(deny_gate)
        # Import a tiny ready plugin if none — use record path via invoke on missing plugin → KeyError
        # Instead call invoke internals with a fake ready plugin via gate short-circuit:
        call = pm._finish_invocation  # noqa: F841 — ensure API available
        # Direct gate unit: blocked result must not call _run_command.
        result = {
            "ok": False,
            "violations": ["path_outside_envelope:/evil"],
        }
        self.assertFalse(result["ok"])
        # Exercise PluginManager.invoke gate path with a patched get_plugin/tool.
        plugin = {
            "id": "p_test",
            "enabled": True,
            "status": "ready",
            "trust": "manual",
            "health": "prepared",
            "manifest": {},
            "capabilities": {},
            "failure_state": None,
        }
        tool = {
            "name": "write_file",
            "enabled": True,
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            "command": ["python", "-c", "print(1)"],
            "metadata": {"action": "write"},
        }
        with patch.object(pm.db, "get_plugin", return_value=plugin), patch.object(
            pm.db, "plugin_tools", return_value=[tool]
        ), patch.object(pm.db, "create_tool_call", return_value="call_1"), patch.object(
            pm.db, "finish_tool_call", side_effect=lambda *a, **k: {"id": "call_1", "status": k.get("status") or a[1] if False else k.get("status", "blocked")}
        ) as finish, patch.object(pm.db, "set_plugin_state"), patch.object(pm.db, "add_plugin_event"):
            def _finish(call_id, plugin, tool, **kwargs):
                return {"id": call_id, "status": kwargs.get("status"), "error": kwargs.get("error")}

            with patch.object(pm, "_finish_invocation", side_effect=_finish):
                out = pm.invoke("p_test", "write_file", {"path": "/evil"}, approved_by_user=True)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(invoked["count"], 0)


class HarvestUnlimitedTests(unittest.TestCase):
    def test_null_harvest_defaults_preserved(self) -> None:
        from chat_commands import detect_harvest_intent, detect_slash_command

        settings = {
            "research_harvest_max_documents": None,
            "research_harvest_max_pages": None,
            "research_harvest_max_depth": None,
            "research_harvest_clamp_documents": None,
            "research_harvest_clamp_pages": None,
            "research_harvest_clamp_depth": None,
        }
        nl = detect_harvest_intent("Download docs from https://example.com/library", settings=settings)
        assert nl is not None
        self.assertIsNone(nl["max_documents"])
        self.assertIsNone(nl["max_pages"])
        self.assertIsNone(nl["max_depth"])
        slash = detect_slash_command("/harvest https://example.com/x", settings=settings)
        assert slash is not None
        self.assertIsNone(slash["max_documents"])


class MissionBridgeAndMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "gen2.db"))
        self.svc = Gen2Services(self.store, data_root=self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validate_mission_ir_detects_cycles_and_dupes(self) -> None:
        cyclic = {
            "execution_waves": [
                {
                    "wave": 0,
                    "steps": [
                        {"id": "a", "title": "A", "agent": "x", "depends_on": ["b"]},
                        {"id": "b", "title": "B", "agent": "x", "depends_on": ["a"]},
                    ],
                }
            ]
        }
        errors = Gen2Services.validate_mission_ir(cyclic)
        self.assertTrue(any("cycle" in e for e in errors), errors)
        duped = {
            "execution_waves": [
                {
                    "wave": 0,
                    "steps": [
                        {"id": "a", "title": "A", "agent": "x", "depends_on": []},
                        {"id": "a", "title": "dup", "agent": "x", "depends_on": []},
                    ],
                }
            ]
        }
        errors2 = Gen2Services.validate_mission_ir(duped)
        self.assertTrue(any("duplicate" in e for e in errors2), errors2)

    def test_best_model_latency_lower_is_better(self) -> None:
        now = "2026-09-08T00:00:00+00:00"
        with self.store.connection() as db:
            for model_id, score in (("fast-m", 10.0), ("slow-m", 200.0)):
                db.execute(
                    """INSERT INTO gen2_model_matrix_v2(
                          model_id,task_type,metric,quality_layer,suite,mode,config_hash,
                          score,samples,reliable,provenance_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        model_id,
                        "chat",
                        "latency_ms",
                        "live_quality",
                        "latency_probe",
                        "live_model",
                        "",
                        score,
                        3,
                        1,
                        "{}",
                        now,
                    ),
                )
        best = self.store.best_model_for("chat", metric="latency_ms")
        assert best is not None
        self.assertEqual(best["model_id"], "fast-m")
        self.assertEqual(best["sort"], "lower_better")

    def test_eval_lab_marks_software_not_model_quality(self) -> None:
        report = self.svc.run_eval_lab(model_id="unit-model")
        self.assertTrue((report.get("summary") or {}).get("not_model_quality"))
        self.assertFalse((report.get("summary") or {}).get("model_invoked"))
        rec = self.svc.recommend_model("verification")
        self.assertIn(rec.get("source"), {"software_suite_fallback", "empirical_matrix", "no_empirical_data"})

    def test_benchmark_requires_workflow_not_just_suite(self) -> None:
        skill = self.svc.extract_skill_candidate(
            name="broken-skill",
            workflow=["todo", "broken"],
            pattern_source="test",
        )
        bench = self.svc.benchmark_skill(skill["id"])
        self.assertEqual(bench["status"], "failed_benchmark")


class TerminalTimeoutSemanticsTests(unittest.TestCase):
    def test_configured_null_timeout_is_unlimited(self) -> None:
        from terminal_tool import PolicyTerminalService
        from unittest.mock import MagicMock, patch

        artifacts = MagicMock()
        artifacts.create_text_result.return_value = {"id": "art"}
        svc = PolicyTerminalService(artifacts, Path(tempfile.gettempdir()))
        isolated = MagicMock(
            stdout="ok",
            stderr="",
            exit_code=0,
            reason=None,
            mode="trusted",
            isolation_enforced=False,
            fs_isolation=False,
            network_isolation=False,
            adapter="native",
            env_filtered=False,
            evidence={},
        )
        with patch("terminal_tool.run_isolated", return_value=isolated) as run:
            svc.run(
                ["echo", "hi"],
                settings={
                    "terminal_timeout_seconds": None,
                    "terminal_max_timeout_seconds": None,
                    "terminal_allowlist": ["echo"],
                    "terminal_output_max_chars": 1000,
                    "terminal_execution_mode": "trusted",
                },
            )
            self.assertIsNone(run.call_args.kwargs.get("timeout_seconds"))


class PhaseContinuationReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "gen2.db"))
        db_path = str(self.root / "arts.db")
        Database(db_path).initialize()
        pdb = PlatformDatabase(db_path)
        pdb.initialize()
        self.arts = ArtifactService(pdb, self.root)
        self.svc = Gen2Services(self.store, data_root=self.root, artifact_service=self.arts)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pending_gates_for_mid_wave(self) -> None:
        mission = {
            "gates": [
                {"id": "g0", "required": True, "status": "approved", "before_wave": 0},
                {"id": "g1", "required": True, "status": "approved", "before_wave": 1},
                {"id": "g2", "required": True, "status": "pending", "before_wave": 2},
            ]
        }
        pending = self.svc.pending_gates_for_wave(mission, before_wave=2)
        self.assertEqual([g["id"] for g in pending], ["g2"])
        self.assertEqual(self.svc.pending_gates_for_wave(mission, before_wave=1), [])

    def test_sync_mission_rejects_completed_with_failed_steps(self) -> None:
        mission = self.svc.compile_mission("Betrouwbare sync test")
        self.store.update_mission(
            mission["id"],
            status="running",
            task_id="task_sync_1",
            verification={"required": True, "status": "passed"},
        )
        updated = self.svc.sync_mission_from_task(
            "task_sync_1",
            status="completed",
            verification={"status": "passed"},
            step_summary={"total": 3, "completed": 2, "failed": 1},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "failed")
        acceptance = (updated.get("verification") or {}).get("acceptance") or {}
        self.assertFalse(acceptance.get("passed"))
        self.assertTrue(acceptance.get("evidence_based"))

    def test_sync_mission_completed_when_evidence_ok(self) -> None:
        mission = self.svc.compile_mission("Betrouwbare sync ok")
        self.store.update_mission(
            mission["id"],
            status="running",
            task_id="task_sync_2",
        )
        arts = _mission_deliverables(self.arts, task_id="task_sync_2")
        updated = self.svc.sync_mission_from_task(
            "task_sync_2",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "work_runtime",
                "criteria_checklist": [{"criterion": "ok", "met": True}],
                "evidence_refs": ["step:1", "step:2", arts[0]["id"], arts[1]["id"]],
                "artifacts": arts,
                "task_id": "task_sync_2",
            },
            step_summary={"total": 2, "completed": 2, "failed": 0, "pending": 0},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "completed")
        self.assertTrue((updated.get("verification") or {}).get("acceptance", {}).get("passed"))

    def test_mid_wave_gate_approve_resumes_running(self) -> None:
        mission = self.svc.compile_mission("Gate resume")
        gates = list(mission["gates"])
        for g in gates:
            if int(g.get("before_wave", 0) or 0) <= 1:
                g["status"] = "approved"
        gates.append(
            {"id": "g_wave2", "required": True, "status": "pending", "before_wave": 2, "label": "wave2"}
        )
        self.store.update_mission(
            mission["id"],
            gates=gates,
            status="awaiting_approval",
            task_id="task_gate_1",
        )
        updated = self.svc.decide_mission_gate(mission["id"], "g_wave2", approve=True, note="ok")
        self.assertEqual(updated["status"], "running")

    def test_shared_budget_ledger_blocks_overspend(self) -> None:
        mission = self.svc.compile_mission("Budget ledger")
        self.store.update_mission(mission["id"], budgets={"max_tool_calls": 3, "ledger": {"reserved": {}, "consumed": {}, "entries": []}})
        reserved = self.svc.reserve_mission_budget(mission["id"], key="max_tool_calls", amount=2, step_id="s1")
        rid = reserved["reservation_id"]
        with self.assertRaises(ValueError):
            self.svc.reserve_mission_budget(mission["id"], key="max_tool_calls", amount=2, step_id="s2")
        ledger = self.svc.mission_budget_ledger(mission["id"])
        self.assertEqual(ledger["ledger"]["reserved"]["max_tool_calls"], 2.0)
        self.svc.consume_mission_budget(
            mission["id"], key="max_tool_calls", amount=1, step_id="s1", reservation_id=rid
        )
        ledger2 = self.svc.mission_budget_ledger(mission["id"])
        self.assertEqual(ledger2["ledger"]["consumed"]["max_tool_calls"], 1.0)

    def test_live_model_eval_blocked_without_client(self) -> None:
        import asyncio

        report = asyncio.run(self.svc.run_model_eval(model_id="local-test", chat_fn=None))
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["mode"], "live_model")
        self.assertFalse((report.get("summary") or {}).get("model_invoked"))
        self.assertEqual((report.get("summary") or {}).get("reason"), "lm_client_unavailable")
        self.assertEqual(report.get("scores") or [], [])

    def test_live_model_eval_with_simulated_lm(self) -> None:
        import asyncio

        async def chat_fn(payload):
            text = " ".join(str((m or {}).get("content") or "") for m in (payload.get("messages") or [])).lower()
            content = "OK" if "exactly: ok" in text else "honest"
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}

        report = asyncio.run(self.svc.run_model_eval(model_id="sim-model", chat_fn=chat_fn))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["mode"], "live_model")
        self.assertTrue((report.get("summary") or {}).get("model_invoked"))
        self.assertEqual((report.get("summary") or {}).get("passed"), 2)
        self.assertTrue(all(score.get("measurement_method") == "live_lm_studio" for score in report["scores"]))
        # Default live prompts are infrastructure_smoke — must NOT promote into routing.
        self.assertEqual((report.get("summary") or {}).get("quality_layer"), "infrastructure_smoke")
        self.assertTrue((report.get("summary") or {}).get("not_model_quality"))
        best = self.store.best_model_for("chat", metric="pass")
        self.assertIsNone(best)
        matrix = [r for r in self.store.capability_matrix() if r.get("model_id") == "sim-model"]
        self.assertTrue(matrix)
        self.assertTrue(all(r.get("quality_layer") == "infrastructure_smoke" for r in matrix))
        self.assertTrue(all(not r.get("reliable") for r in matrix))

    def test_select_promoted_skill_by_name(self) -> None:
        skill = self.svc.extract_skill_candidate(
            name="nvidia-earnings-deepdive",
            workflow=["scope", "retrieve", "synthesize"],
            pattern_source="unit",
        )
        # Force promoted without full promote path (hash bind tested elsewhere).
        self.store.update_skill(skill["id"], status="promoted")
        matched = self.svc.select_promoted_skill("Please run nvidia-earnings-deepdive analysis")
        assert matched is not None
        self.assertEqual(matched["id"], skill["id"])
        self.assertEqual(matched["match_reason"], "name_in_prompt")

    def test_committee_consensus_from_position_results(self) -> None:
        session = self.svc.run_committee(
            "NVIDIA earnings outlook",
            domain="research",
            evidence=["NVIDIA earnings beat estimates", "Guidance raised for datacenter"],
        )
        consensus = session.get("consensus") or {}
        self.assertEqual(consensus.get("basis"), "position_results_plus_external_evidence")
        self.assertIn("evidence_checks", consensus)
        self.assertEqual(consensus.get("mode"), "heuristic_isolated")
        self.assertIn("support_ratio", consensus)
        self.assertGreaterEqual(consensus.get("position_count") or 0, 2)

    def test_committee_live_falls_back_without_client(self) -> None:
        import asyncio

        session = asyncio.run(
            self.svc.run_committee_live(
                "NVIDIA outlook",
                evidence=["NVIDIA earnings beat"],
                chat_fn=None,
            )
        )
        consensus = session.get("consensus") or {}
        self.assertTrue(consensus.get("live_requested"))
        self.assertEqual(consensus.get("live_blocked_reason"), "lm_client_unavailable")
        self.assertEqual(consensus.get("mode"), "heuristic_isolated")

    def test_finance_content_hash_dedupes(self) -> None:
        first = self.store.save_market_event(
            {
                "event_type": "news",
                "title": "Acme raises guidance",
                "summary": "Acme Corp raised FY guidance after strong demand.",
                "entities": ["ACME"],
                "source_count": 1,
                "confidence": 0.6,
                "novelty": 0.5,
                "likely_horizon": "days",
                "supporting_evidence": ["src-a"],
            }
        )
        second = self.store.save_market_event(
            {
                "event_type": "news",
                "title": "Acme raises guidance",
                "summary": "Acme Corp raised FY guidance after strong demand.",
                "entities": ["ACME", "NASDAQ"],
                "source_count": 1,
                "confidence": 0.8,
                "novelty": 0.5,
                "likely_horizon": "days",
                "supporting_evidence": ["src-b"],
            }
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["source_count"], 2)
        self.assertIn("NASDAQ", second["entities"])
        self.assertEqual(first.get("content_hash"), second.get("content_hash"))

    def test_context_full_request_budget_and_explain(self) -> None:
        pack = self.svc.compile_context(
            goal="budget explain",
            items=[
                {"content": "alpha evidence " * 40, "kind": "evidence", "reliability": 0.9, "source": "a"},
                {"content": "beta noise " * 40, "kind": "other", "reliability": 0.4, "source": "b"},
            ],
            max_tokens=2000,
            request_budget_tokens=1000,
            system_reserve_tokens=100,
            response_reserve_tokens=200,
            persist=False,
        )
        self.assertEqual(pack["budget_reserve"]["mode"], "full_request_budget")
        self.assertEqual(pack["max_tokens"], 700)
        self.assertIn("kept_ids", pack["selection_explain"])
        self.assertIn("drop_reasons", pack["selection_explain"])

    def test_flight_recorder_diagnostics_enrichment(self) -> None:
        event = self.svc.record(
            "run_diag_1",
            "TOOL_RESULT",
            {"tool_name": "echo"},
            component="tests",
            severity="warning",
            duration_ms=12.5,
            correlation_id="corr-1",
        )
        diag = (event.get("payload") or {}).get("_diagnostics") or {}
        self.assertEqual(diag.get("severity"), "warning")
        self.assertEqual(diag.get("duration_ms"), 12.5)
        self.assertEqual(diag.get("correlation_id"), "corr-1")


if __name__ == "__main__":
    unittest.main()
