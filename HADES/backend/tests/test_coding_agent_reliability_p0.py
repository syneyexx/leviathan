"""Production hardening — Coding Agent reliability (adversarial false-success + honesty).

Asserts rejection of false success shapes:
- poll timeout ≠ completion
- started process ≠ healthy
- reviewer suggestion ≠ proof
- LSP regex fallback ≠ language_server success
- Browser actions without Ready plugin ≠ success
- Independent eval suite does not claim all-green without evidence
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_job_control import interpret_job_poll
from coding_jobs import reset_coding_job_store_for_tests
from coding_reviewer import review_coding_result
from evals.independent_tasks import (
    INDEPENDENT_TASKS,
    run_independent_eval_honesty_suite,
    run_independent_eval_suite,
)
from language_servers import find_definition_scoped, find_references_scoped, probe_language_servers, read_diagnostics
from preview_runtime import BrowserAdapter, PreviewManager


class LanguageServerHonestyTests(unittest.TestCase):
    def test_regex_fallback_never_claims_lsp_success(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        with patch("language_servers.shutil.which", return_value=None):
            with patch("language_servers._try_jedi_definitions", return_value=None):
                result = find_definition_scoped(root, "alpha")
        self.assertTrue(result.get("degraded") or result.get("fallback"))
        self.assertFalse(result.get("lsp_success"))
        self.assertNotEqual(result.get("method"), "language_server")
        self.assertNotIn("language_server", str(result.get("method") or "").lower())

    def test_installed_pyright_without_defs_still_degraded(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "mod.py").write_text("def beta():\n    return 2\n", encoding="utf-8")

        def fake_which(name: str):  # noqa: ANN001
            if name in {"pyright", "pyright-langserver"}:
                return "/usr/bin/pyright"
            return None

        with patch("language_servers.shutil.which", side_effect=fake_which):
            with patch("language_servers._try_jedi_definitions", return_value=None):
                result = find_definition_scoped(root, "beta")
        self.assertFalse(result.get("lsp_success"))
        self.assertTrue(result.get("degraded"))
        self.assertTrue(result.get("fallback"))
        self.assertNotEqual(result.get("method"), "language_server")
        self.assertTrue(result.get("lsp_installed") or "pyright" in str(result.get("reason") or ""))

    def test_jedi_success_marks_lsp_success_when_available(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "mod.py").write_text("def gamma():\n    return 3\n", encoding="utf-8")
        fake_ls = {
            "definitions": [{"name": "gamma", "path": "mod.py", "line": 1, "kind": "function", "snippet": "def gamma"}],
            "method": "jedi",
            "lsp_success": True,
            "degraded": False,
            "reason": None,
        }
        with patch("language_servers._try_jedi_definitions", return_value=fake_ls):
            result = find_definition_scoped(root, "gamma")
        self.assertTrue(result.get("lsp_success"))
        self.assertFalse(result.get("degraded"))
        self.assertEqual(result.get("method"), "jedi")

    def test_references_fallback_honest(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "a.py").write_text("x = 1\nprint(x)\n", encoding="utf-8")
        with patch("language_servers._try_jedi_references", return_value=None):
            with patch("language_servers.shutil.which", return_value=None):
                result = find_references_scoped(root, "x")
        self.assertFalse(result.get("lsp_success"))
        self.assertTrue(result.get("degraded"))

    def test_diagnostics_without_ls_not_lsp_success(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "bad.py").write_text("def (\n", encoding="utf-8")
        with patch("language_servers.shutil.which", return_value=None):
            result = read_diagnostics(root, paths=["bad.py"])
        self.assertFalse(result.get("lsp_success"))
        self.assertTrue(result.get("degraded"))


class BrowserAdapterPolicyTests(unittest.TestCase):
    def _ready_pm(self, *, tools: list[str] | None = None, invoke_result: Any = None) -> MagicMock:
        pm = MagicMock()
        pm.db.get_plugin.return_value = {"id": "puppeteer", "enabled": True, "status": "ready", "failure_state": None}
        tool_rows = [{"name": n, "enabled": True} for n in (tools or ["fetch", "screenshot"])]
        pm.db.plugin_tools.return_value = tool_rows
        if invoke_result is not None:
            pm.invoke.return_value = invoke_result
        else:
            pm.invoke.return_value = {"status": "completed", "stdout": "{}"}
        return pm

    def test_capabilities_false_when_plugin_not_ready(self) -> None:
        pm = MagicMock()
        pm.db.get_plugin.return_value = {"id": "puppeteer", "enabled": True, "status": "error", "failure_state": "dependency_failed"}
        pm.db.plugin_tools.return_value = []
        caps = BrowserAdapter(plugin_manager=pm).capabilities()
        self.assertFalse(caps["open_page"])
        self.assertFalse(caps["screenshot"])
        self.assertFalse(caps["fill"])
        self.assertFalse(caps["click"])
        self.assertFalse(caps["executable_now"])

    def test_open_fill_click_screenshot_fail_when_not_ready(self) -> None:
        pm = MagicMock()
        pm.db.get_plugin.return_value = {"id": "puppeteer", "enabled": False, "status": "installed"}
        adapter = BrowserAdapter(plugin_manager=pm)
        for res in (
            adapter.open_page("http://127.0.0.1:9/"),
            adapter.fill("#email", "a@b.com"),
            adapter.click("#go"),
            adapter.screenshot("http://127.0.0.1:9/"),
        ):
            self.assertFalse(res.get("ok"), res)
            self.assertIn(res.get("status"), {"unavailable", "failed", "not_started"})

    def test_fill_click_go_through_plugin_manager_policy(self) -> None:
        pm = self._ready_pm(tools=["fetch", "screenshot"])  # no fill/click in manifest
        adapter = BrowserAdapter(plugin_manager=pm)
        filled = adapter.fill("#x", "1")
        clicked = adapter.click("#y")
        self.assertFalse(filled["ok"])
        self.assertFalse(clicked["ok"])
        self.assertIn("tool_not_in_plugin_manifest", str(filled.get("reason") or ""))
        self.assertTrue(pm.record_rejected_call.called)
        # open/screenshot use declared tools → invoke
        opened = adapter.open_page("http://example.invalid/")
        self.assertTrue(opened["ok"])
        self.assertTrue(pm.invoke.called)
        shot = adapter.screenshot("http://example.invalid/", out_path=str(Path(tempfile.mkdtemp()) / "s.png"))
        # invoke ok but file missing → not live host pass
        self.assertFalse(shot.get("live_host_pass"))

    def test_ready_fill_invokes_when_manifest_has_tool(self) -> None:
        pm = self._ready_pm(tools=["fetch", "screenshot", "fill", "click"])
        adapter = BrowserAdapter(plugin_manager=pm)
        filled = adapter.fill("#email", "a@b.com", url="http://127.0.0.1:9/")
        self.assertTrue(filled["ok"])
        pm.invoke.assert_called()
        args = pm.invoke.call_args
        self.assertEqual(args[0][0], "puppeteer")
        self.assertEqual(args[0][1], "fill")


class AdversarialFalseSuccessTests(unittest.TestCase):
    def test_poll_timeout_is_not_completion(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        gate = threading.Event()

        def runner(params):  # noqa: ANN001
            gate.wait(timeout=5)
            return {"status": "verified", "id": "late"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        snap = store.get(job["id"])
        # Adversary: treat observation timeout as "klaar"
        interpreted = interpret_job_poll(snap, timed_out=True, poll_error="observation_timeout")
        self.assertFalse(interpreted["complete"])
        self.assertTrue(interpreted["continue_observing"])
        self.assertTrue(interpreted["false_success_rejected"])
        self.assertNotIn(snap["status"], {"verified", "completed", "failed", "cancelled"})
        gate.set()
        deadline = time.time() + 15.0
        final = store.get(job["id"])
        while time.time() < deadline:
            final = store.get(job["id"])
            if str(final.get("status") or "") in {"verified", "completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        # Only terminal store status may complete.
        done = interpret_job_poll(final, timed_out=False)
        self.assertTrue(
            done["complete"],
            f"expected terminal job after runner release, got status={final.get('status')!r} error={final.get('error')!r}",
        )

    def test_started_process_not_healthy(self) -> None:
        mgr = PreviewManager()
        # Simulate a started process without healthcheck success.
        class DummyProc:
            pid = 4242

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):  # noqa: ANN001
                return 0

            def kill(self):
                return None

        run_id = "adv-health"
        mgr._procs[run_id] = {
            "proc": DummyProc(),
            "plan": {"healthcheck": "http://127.0.0.1:9/", "kind": "npm_dev"},
            "started_at": time.time(),
        }
        health = mgr.check_health(run_id, timeout=0.2)
        status = mgr.status(run_id)
        self.assertTrue(status["running"])
        self.assertFalse(health.get("healthy"))
        self.assertFalse(status.get("healthy"))
        # Adversary claim: started ⇒ healthy — must be rejected.
        started_implies_healthy = bool(status["running"]) and bool(status.get("healthy"))
        self.assertFalse(started_implies_healthy)
        mgr.stop_preview(run_id)

    def test_reviewer_suggestion_is_not_proof(self) -> None:
        review = review_coding_result(
            goal="Fix async race in worker",
            diff_text="+ def worker():\n+   return 1\n",
            changed_files=["worker.py"],
            test_result={"status": "passed"},
            suggest_extra_checks=True,
        )
        self.assertTrue(review.get("extra_checks"))
        self.assertTrue(review.get("suggestions_are_not_proof"))
        self.assertTrue(all(c.get("status") == "suggested_not_proven" for c in review["extra_checks"]))
        # Adversary: elevate suggestion ids into defects — reviewer must not treat as proven.
        self.assertFalse(any(d.get("code") == "edge_async_race" for d in review.get("defects") or []))
        self.assertNotEqual(review.get("status"), "reject")
        # Also reject forged from_suggestion defects if re-filtered via contract fields.
        self.assertTrue(all(c.get("status") == "suggested_not_proven" for c in review["extra_checks"]))


class IndependentEvalHonestyTests(unittest.TestCase):
    def test_suite_lists_e01_to_e08(self) -> None:
        ids = [t["id"] for t in INDEPENDENT_TASKS]
        self.assertEqual(len(ids), 8)
        for i in range(1, 9):
            self.assertTrue(any(x.startswith(f"E0{i}_") for x in ids), ids)

    def test_honesty_suite_runnable_and_not_all_green_claim(self) -> None:
        report = run_independent_eval_honesty_suite()
        self.assertEqual(report["total"], 8)
        self.assertTrue(report["all_fixtures_honest"], report["scores"])
        self.assertFalse(report["claimed_all_green"])
        for row in report["scores"]:
            self.assertTrue(row["honest"], row)
            self.assertFalse(row["baseline_tests_passed"])
            self.assertFalse(row["solution_prebaked"])
            self.assertIn("evidence", row)

    def test_rejects_all_green_without_evidence(self) -> None:
        # Simulate a dishonest report shape and ensure our suite API does not emit it
        # when fixtures are merely honest (no agent pass).
        report = run_independent_eval_honesty_suite(limit=8)
        self.assertFalse(report.get("all_green", False))
        self.assertEqual(report.get("claimed_all_green"), False)
        # Attempted false success: treating honesty suite as agent all-green.
        false_success = report["all_fixtures_honest"] and report["claimed_all_green"]
        self.assertFalse(false_success)

    def test_agent_solution_suite_e01_e08_evidence_backed(self) -> None:
        """E01–E08 remain runnable regression fixtures; without a model they are not quality proof.

        Fixture-specific heuristic oracles were removed from coding_agent (F02). Without a live
        model, the suite must not claim all-green / independent quality success.
        """
        report = run_independent_eval_suite(strategies=["investigate"])
        self.assertEqual(report["total"], 8)
        self.assertFalse(report.get("quality_proof", True))
        self.assertEqual(report.get("fixture_kind"), "known_regression_fixtures")
        # Honesty: never claim all-green without evidence_backed passes.
        if report["all_green"]:
            self.assertEqual(report["evidence_backed_passed"], 8)
            for row in report["scores"]:
                self.assertTrue(row["passed"], row)
                self.assertTrue((row.get("evidence") or {}).get("evidence_backed"), row)
                self.assertFalse(row.get("claimed_without_evidence"))
        else:
            # Expected path after F02: heuristics no longer bake E01–E08 solutions.
            self.assertFalse(report["claimed_all_green"])
            self.assertLess(report["passed"], 8)
            for row in report["scores"]:
                self.assertFalse(row.get("claimed_without_evidence"))
                self.assertTrue((row.get("evidence") or {}).get("baseline_failed"), row)


if __name__ == "__main__":
    unittest.main()
