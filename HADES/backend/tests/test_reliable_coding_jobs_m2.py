"""Reliable coding-job control + investigate generalization (Milestone 2).

Asserts executable behavior — not merely stored flags.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_job_control import CodingJobCancelled, CodingJobPaused, validate_transition
from coding_jobs import reset_coding_job_store_for_tests
from coding_investigate import InteractiveCodingInvestigator
from investigate_selector import _heuristic_from_observations


class JobControlContractTests(unittest.TestCase):
    def test_invalid_transitions_rejected(self) -> None:
        bad = validate_transition("verified", "running")
        self.assertFalse(bad["ok"])
        ok = validate_transition("paused", "queued")
        self.assertTrue(ok["ok"])


class PauseResumeDispatchTests(unittest.TestCase):
    def test_pause_before_worker_start(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        ran = {"n": 0}
        delay = threading.Event()

        def runner(params):  # noqa: ANN001
            ran["n"] += 1
            return {"status": "verified", "id": "r1"}

        original_submit = store._executor.submit

        def delayed_submit(fn, *args, **kwargs):  # noqa: ANN001
            def wrapped():
                delay.wait(timeout=3)
                return fn(*args, **kwargs)

            return original_submit(wrapped)

        store._executor.submit = delayed_submit  # type: ignore[method-assign]
        try:
            job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
            store.request_pause(job["id"])
            delay.set()
            for _ in range(80):
                if store.get(job["id"])["status"] == "paused":
                    break
                time.sleep(0.05)
            snap = store.get(job["id"])
            self.assertEqual(snap["status"], "paused")
            self.assertEqual(ran["n"], 0)
            self.assertTrue(snap.get("checkpoint"))
            self.assertTrue(any(e["kind"] == "JOB_PAUSED" for e in snap.get("events") or []))
        finally:
            store._executor.submit = original_submit  # type: ignore[method-assign]

    def test_resume_dispatches_worker_exactly_once(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        ran = {"n": 0}
        gate = threading.Event()
        allow_start = threading.Event()

        def runner(params):  # noqa: ANN001
            ran["n"] += 1
            gate.wait(timeout=30)
            return {"status": "verified", "id": "r_resume"}

        original_submit = store._executor.submit

        def delayed_submit(fn, *args, **kwargs):  # noqa: ANN001
            def wrapped():
                allow_start.wait(timeout=5)
                return fn(*args, **kwargs)

            return original_submit(wrapped)

        store._executor.submit = delayed_submit  # type: ignore[method-assign]
        try:
            job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
            store.request_pause(job["id"])
            allow_start.set()
            for _ in range(120):
                if store.get(job["id"])["status"] == "paused":
                    break
                time.sleep(0.05)
            self.assertEqual(store.get(job["id"])["status"], "paused")
            self.assertEqual(ran["n"], 0)

            # Concurrent resume requests must not double-dispatch.
            results = []

            def do_resume():
                results.append(store.resume(job["id"]))

            t1 = threading.Thread(target=do_resume)
            t2 = threading.Thread(target=do_resume)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            gate.set()
            for _ in range(120):
                if store.get(job["id"])["status"] in {"verified", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            final = store.get(job["id"])
            self.assertEqual(final["status"], "verified")
            self.assertEqual(ran["n"], 1, "resume must run the job exactly once")
        finally:
            store._executor.submit = original_submit  # type: ignore[method-assign]

    def test_pause_between_investigate_actions(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        actions = {"n": 0}

        def runner(params):  # noqa: ANN001
            jid = params["job_id"]
            for i in range(5):
                params["job_checkpoint"](phase="investigate_action", action_index=i)
                actions["n"] += 1
                time.sleep(0.05)
            return {"status": "verified", "id": "r_mid"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        # Wait until at least one action started, then pause.
        for _ in range(80):
            if actions["n"] >= 1:
                break
            time.sleep(0.02)
        store.request_pause(job["id"])
        for _ in range(80):
            if store.get(job["id"])["status"] == "paused":
                break
            time.sleep(0.05)
        snap = store.get(job["id"])
        self.assertEqual(snap["status"], "paused")
        paused_at = actions["n"]
        time.sleep(0.2)
        self.assertEqual(actions["n"], paused_at, "no new actions after confirmed pause")

    def test_redirect_processed_at_checkpoint(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        seen = {"notes": []}

        def runner(params):  # noqa: ANN001
            # First checkpoint: no instruction yet may arrive mid-flight.
            time.sleep(0.15)
            params["job_checkpoint"](phase="investigate_action", action_index=0)
            instr = params["fetch_instructions"]()
            pending = [i for i in instr if i.get("status") == "received"]
            if pending:
                versions = [int(i["version"]) for i in pending]
                params["apply_instructions"](versions, action_index=1)
                seen["notes"] = [i["note"] for i in pending]
                # Next action influenced by instruction
                params["job_checkpoint"](phase="investigate_action", action_index=1)
            return {"status": "verified", "id": "r_redir", "applied": seen["notes"]}

        job = store.start(runner=runner, params={"goal": "original", "source_repo": str(tmp)})
        time.sleep(0.05)
        store.redirect(job["id"], "focus on helper module")
        for _ in range(80):
            st = store.get(job["id"])["status"]
            if st in {"verified", "failed"}:
                break
            time.sleep(0.05)
        final = store.get(job["id"])
        self.assertEqual(final["status"], "verified")
        self.assertTrue(any(i.get("status") == "processed" for i in final.get("instructions") or []))
        self.assertTrue(seen["notes"])

    def test_cancel_during_work_no_success_event(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)

        def runner(params):  # noqa: ANN001
            for i in range(40):
                try:
                    params["job_checkpoint"](phase="before_model", action_index=i)
                except CodingJobCancelled:
                    raise
                time.sleep(0.05)
            return {"status": "verified", "id": "should_not"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        time.sleep(0.1)
        store.request_cancel(job["id"])
        for _ in range(120):
            snap = store.get(job["id"])
            kinds = [e["kind"] for e in snap.get("events") or []]
            if snap["status"] == "cancelled" and ("JOB_CANCELLED" in kinds or "CANCEL_HONORED" in kinds):
                break
            time.sleep(0.05)
        final = store.get(job["id"])
        self.assertEqual(final["status"], "cancelled")
        kinds = [e["kind"] for e in final.get("events") or []]
        # Cancel is proven by cancelled status + cancel event family (honored and/or cancelled).
        self.assertTrue(
            "JOB_CANCELLED" in kinds or "CANCEL_HONORED" in kinds,
            kinds,
        )
        self.assertNotIn("JOB_COMPLETED", kinds)

    def test_worker_loss_recoverable_payload(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        started = threading.Event()

        def runner(params):  # noqa: ANN001
            started.set()
            time.sleep(10)
            return {"status": "verified", "id": "x"}

        job = store.start(runner=runner, params={"goal": "recover-me", "source_repo": str(tmp), "strategy": "fast"})
        started.wait(timeout=2)
        # Simulate worker loss by clearing futures without completing.
        with store._lock:
            fut = store._futures.pop(job["id"], None)
        if fut:
            fut.cancel()
        recovered = store.recover_stale(max_age_s=0)
        self.assertIn(job["id"], recovered["recovered"])
        snap = store.get(job["id"])
        self.assertEqual(snap["status"], "interrupted")
        self.assertTrue((snap.get("execution_payload") or {}).get("params", {}).get("goal"))
        # Resume from interrupted must dispatch again.
        ran = {"n": 0}

        def runner2(params):  # noqa: ANN001
            ran["n"] += 1
            return {"status": "verified", "id": "recovered_run"}

        with store._lock:
            store._runners[job["id"]] = runner2
        resumed = store.resume(job["id"], runner=runner2)
        for _ in range(80):
            if store.get(job["id"])["status"] == "verified":
                break
            time.sleep(0.05)
        self.assertEqual(store.get(job["id"])["status"], "verified")
        self.assertEqual(ran["n"], 1)

    def test_events_have_seq_and_cursor(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)

        def runner(params):  # noqa: ANN001
            return {"status": "verified", "id": "e1"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        for _ in range(40):
            if store.get(job["id"])["status"] == "verified":
                break
            time.sleep(0.05)
        all_events = store.list_events(job["id"], limit=100)
        self.assertTrue(all_events)
        self.assertTrue(all(e.get("seq") for e in all_events))
        mid = all_events[0]["seq"]
        after = store.list_events(job["id"], after_seq=mid, limit=100)
        self.assertTrue(all(e["seq"] > mid for e in after))

    def test_failed_result_not_only_job_completed(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)

        def runner(params):  # noqa: ANN001
            return {"status": "tests_failed", "id": "f1"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        for _ in range(40):
            if store.get(job["id"])["status"] == "tests_failed":
                break
            time.sleep(0.05)
        kinds = [e["kind"] for e in store.get(job["id"]).get("events") or []]
        self.assertIn("JOB_FAILED", kinds)


class InvestigateWorkspaceTests(unittest.TestCase):
    def test_tests_write_only_in_work_root(self) -> None:
        source = Path(tempfile.mkdtemp(prefix="src_"))
        work = Path(tempfile.mkdtemp(prefix="work_"))
        # Copy fixture into both; test that writes only in work.
        for root in (source, work):
            (root / "test_write.py").write_text(
                "import pathlib\n"
                "pathlib.Path('side_effect.txt').write_text('x', encoding='utf-8')\n"
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
        inv = InteractiveCodingInvestigator(source, work_root=work, baseline_label="work")
        inv.execute(
            __import__("coding_investigate", fromlist=["InvestigateAction"]).InvestigateAction(
                kind="run_test",
                args={"test_args": ["test_write.py"]},
                rationale="iso",
            )
        )
        self.assertTrue((work / "side_effect.txt").is_file())
        self.assertFalse((source / "side_effect.txt").is_file())

    def test_renamed_fixture_still_investigates(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="renamed_"))
        pkg = root / "billing"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "api.py").write_text(
            "from billing.ops import total\n\ndef invoice(a, b):\n    return total(a, b)\n",
            encoding="utf-8",
        )
        (pkg / "ops.py").write_text("def total(a, b):\n    return a - b\n", encoding="utf-8")
        (root / "test_invoice.py").write_text(
            "import unittest\nfrom billing.api import invoice\n"
            "class T(unittest.TestCase):\n"
            "    def test_invoice(self):\n"
            "        self.assertEqual(invoice(2, 3), 5)\n",
            encoding="utf-8",
        )
        report = InteractiveCodingInvestigator(root).run(
            "Fix the failing invoice API",
            max_steps=14,
            test_args=["test_invoice.py"],
        )
        selected = set(report["selected_files"])
        self.assertTrue(any("ops" in p for p in selected), selected)
        self.assertIsNotNone(report.get("stop_reason"))

    def test_budget_zero_stops(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "a.py").write_text("x=1\n", encoding="utf-8")
        report = InteractiveCodingInvestigator(root).run(
            "look around",
            max_steps=5,
            budget={"max_actions": 0, "max_reads": 0, "max_searches": 0, "max_tests": 0},
        )
        self.assertIn(report["status"], {"budget_exhausted", "ready_to_edit", "done", "running"})
        self.assertEqual(report["counts"]["actions"], 0)
        self.assertEqual(report.get("stop_reason"), "max_actions")

    def test_selector_heuristic_differs_by_error_shape(self) -> None:
        a = _heuristic_from_observations(
            [{"action": {"kind": "run_test"}, "data": {"stderr": "ImportError: missing"}}],
            ["gather_missing_context", "find_definition", "read_diagnostics"],
            [
                {"kind": "gather_missing_context", "args": {}},
                {"kind": "find_definition", "args": {"symbol": "x"}},
                {"kind": "read_diagnostics", "args": {}},
            ],
        )
        b = _heuristic_from_observations(
            [{"action": {"kind": "run_test"}, "data": {"stderr": "TypeError: bad type"}}],
            ["gather_missing_context", "find_definition", "read_diagnostics"],
            [
                {"kind": "gather_missing_context", "args": {}},
                {"kind": "find_definition", "args": {"symbol": "x"}},
                {"kind": "read_diagnostics", "args": {}},
            ],
        )
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a["kind"], b["kind"])

    def test_language_server_scopes_same_name(self) -> None:
        from language_servers import find_definition_scoped

        root = Path(tempfile.mkdtemp())
        (root / "pkg_a").mkdir()
        (root / "pkg_b").mkdir()
        (root / "pkg_a" / "mod.py").write_text("def shared():\n    return 1\n", encoding="utf-8")
        (root / "pkg_b" / "mod.py").write_text("def shared():\n    return 2\n", encoding="utf-8")
        result = find_definition_scoped(root, "shared", preferred_paths=["pkg_b/mod.py"])
        self.assertGreaterEqual(result["count"], 1)
        self.assertTrue(str(result["definitions"][0]["path"]).endswith("pkg_b/mod.py") or "pkg_b" in str(result["definitions"][0]["path"]))
        self.assertIn("method", result)


class BrowserAdapterContractTests(unittest.TestCase):
    def test_unavailable_without_plugin_manager(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=None)
        caps = adapter.capabilities()
        self.assertIn("screenshot", caps)
        self.assertFalse(caps.get("executable_now"))
        self.assertFalse(caps.get("open_page"))
        opened = adapter.open_page("http://127.0.0.1:9/")
        self.assertFalse(opened["ok"])
        self.assertIn(opened["status"], {"unavailable", "not_started"})
        filled = adapter.fill("#a", "b")
        clicked = adapter.click("#go")
        self.assertFalse(filled["ok"])
        self.assertFalse(clicked["ok"])
        flow = adapter.run_user_flow(url="http://127.0.0.1:9/", steps=[{"action": "click", "selector": "#go"}], change_hash="abc")
        self.assertEqual(flow["status"], "unavailable")
        self.assertEqual(flow["evidence"]["change_hash"], "abc")
        self.assertFalse(flow.get("live_host_pass"))

    def test_language_server_fallback_not_claimed_success(self) -> None:
        from language_servers import find_definition_scoped
        from unittest.mock import patch

        root = Path(tempfile.mkdtemp())
        (root / "x.py").write_text("def shared():\n    return 0\n", encoding="utf-8")
        with patch("language_servers.shutil.which", return_value=None):
            with patch("language_servers._try_jedi_definitions", return_value=None):
                result = find_definition_scoped(root, "shared")
        self.assertFalse(result.get("lsp_success"))
        self.assertTrue(result.get("degraded"))
        self.assertNotEqual(result.get("method"), "language_server")


class ReviewerExtraChecksTests(unittest.TestCase):
    def test_suggests_edge_without_claiming_proven_defect(self) -> None:
        from coding_reviewer import review_coding_result

        review = review_coding_result(
            goal="Fix async race in worker",
            diff_text="+ def worker():\n+   return 1\n",
            changed_files=["worker.py"],
            test_result={"status": "passed"},
            suggest_extra_checks=True,
        )
        self.assertTrue(review.get("extra_checks"))
        self.assertTrue(all(c.get("status") == "suggested_not_proven" for c in review["extra_checks"]))
        self.assertTrue(review.get("suggestions_are_not_proof"))
        # Not elevated to defects solely by suspicion.
        self.assertFalse(any(d.get("code") == "edge_async_race" for d in review.get("defects") or []))

    def test_poll_timeout_helper_rejects_false_completion(self) -> None:
        from coding_job_control import interpret_job_poll

        out = interpret_job_poll({"status": "running", "worker_live": True}, timed_out=True)
        self.assertFalse(out["complete"])
        self.assertTrue(out["continue_observing"])
        self.assertEqual(out["reason"], "poll_timeout_not_completion")


if __name__ == "__main__":
    unittest.main()
