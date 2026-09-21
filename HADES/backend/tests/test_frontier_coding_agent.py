"""Frontier coding-agent regressions: contracts, intel, diffs, repair ceiling, safety invariants."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_agent import BuildAgentService, FileEdit, resolve_repair_attempt_ceiling
from coding_agent import CodingAgentService, explore_repository
from coding_candidates import run_candidate_search, score_candidate, should_search_candidates
from coding_context import ContentCache, assemble_coding_context
from coding_edits import apply_unified_diff_to_text, make_unified_diff, make_worktree_unified_diff
from coding_failures import compact_log, normalize_failure
from coding_plan import build_coding_dag, estimate_coding_complexity, make_claim, update_claim
from coding_requirement_map import (
    build_coding_task_contract,
    build_requirement_verification_map,
    honest_frontier_status,
)
from coding_reviewer import review_coding_result
from coding_verification import detect_test_weakening, plan_verification_matrix, select_impacted_tests
from repo_intelligence import index_repository, parse_python_ast, tests_covering


class RequirementMapEvidenceTests(unittest.TestCase):
    def test_does_not_link_every_file_to_every_requirement(self) -> None:
        mapping = build_requirement_verification_map(
            requirements=["fix off-by-one in parser", "update README heading"],
            changed_files=["parser.py", "README.md", "unrelated.py"],
            test_results={"passed": True, "tests": ["test_parser"]},
            diff_text="--- a/parser.py\n+++ b/parser.py\n@@ -1 +1 @@\n-x\n+parser off-by-one\n",
        )
        rows = {row["requirement_id"]: row for row in mapping["requirements"]}
        parser_files = rows["req_1"]["changed_files"]
        readme_files = rows["req_2"]["changed_files"]
        self.assertIn("parser.py", parser_files)
        self.assertNotIn("unrelated.py", parser_files)
        self.assertIn("README.md", readme_files)
        self.assertNotIn("parser.py", readme_files)
        self.assertIn("unrelated.py", mapping["unmapped_changed_files"])

    def test_honest_status_never_completes_failed_tests(self) -> None:
        self.assertEqual(
            honest_frontier_status(runner_status="verified", tests_passed=False),
            "FAILED_VERIFICATION",
        )
        self.assertEqual(
            honest_frontier_status(runner_status="verified", tests_passed=True),
            "COMPLETED_VERIFIED",
        )
        self.assertEqual(
            honest_frontier_status(runner_status="tests_failed", tests_passed=False),
            "FAILED_VERIFICATION",
        )
        self.assertEqual(
            honest_frontier_status(
                runner_status="verified",
                tests_passed=True,
                review_status="needs_attention",
            ),
            "COMPLETED_VERIFIED",
        )


class RepoIntelTests(unittest.TestCase):
    def test_python_ast_and_incremental_hash(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "mod.py").write_text(
            "import json\nclass Base: pass\nclass Svc(Base):\n    def run(self):\n        json.dumps({})\n"
            "def helper():\n    return Svc()\n",
            encoding="utf-8",
        )
        (root / "test_mod.py").write_text("from mod import helper\n", encoding="utf-8")
        parsed = parse_python_ast("mod.py", (root / "mod.py").read_text(encoding="utf-8"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["method"], "python_ast")
        names = {s["name"] for s in parsed["outline"]}
        self.assertIn("Svc", names)
        self.assertIn("helper", names)
        cache = Path(tmp.name) / "intel.json"
        first = index_repository(root, cache_path=cache, persist=True)
        self.assertGreaterEqual(first["files_rescanned"], 1)
        second = index_repository(root, cache_path=cache, persist=True)
        self.assertGreaterEqual(second["files_reused"], 1)
        self.assertEqual(second["files_rescanned"], 0)
        covers = tests_covering(first, ["mod.py"])
        self.assertIn("test_mod.py", covers)

    def test_index_does_not_write_source_without_cache_path(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "a.py").write_text("def x():\n    return 1\n", encoding="utf-8")
        index_repository(root, persist=True)
        self.assertFalse((root / ".hades_repo_intel.json").exists())


class ContextAndPlanTests(unittest.TestCase):
    def test_context_keeps_tier0_and_dedupes(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
        (root / "b.py").write_text("from a import a\n", encoding="utf-8")
        contract = build_coding_task_contract(goal="fix a()", source_repo=str(root))
        packed = assemble_coding_context(
            root=root,
            task_contract=contract,
            files=["a.py", "b.py"],
            failures=[{"file": "a.py", "failure_type": "unittest", "message": "boom"}],
            diff_text="--- a/a.py\n+++ b/a.py\n",
            budget_chars=4000,
        )
        self.assertIn("TIER 0", packed["prompt"])
        self.assertIn("fix a()", packed["prompt"])
        self.assertTrue(packed["deduped"])

    def test_cache_invalidates_on_hash(self) -> None:
        cache = ContentCache(max_entries=2)
        cache.put("h1", {"summary": "one"})
        self.assertEqual(cache.get("h1")["summary"], "one")
        self.assertIsNone(cache.get("missing"))
        self.assertGreater(cache.stats()["misses"], 0)

    def test_trivial_skips_huge_plan_complex_has_dag(self) -> None:
        trivial = estimate_coding_complexity(goal="fix add typo", file_count=2, hits=2)
        self.assertEqual(trivial["level"], "trivial")
        dag_t = build_coding_dag(goal="fix add", complexity=trivial)
        ids = [s["step_id"] for s in dag_t["plan"]["steps"]]
        self.assertEqual(ids, ["implement", "verify"])
        complex_c = estimate_coding_complexity(
            goal="refactor API and migrate schema with concurrency",
            file_count=12,
            languages=["python", "typescript"],
            hits=20,
            has_failures=True,
        )
        self.assertEqual(complex_c["level"], "complex")
        dag_c = build_coding_dag(goal="refactor API", complexity=complex_c, has_failures=True)
        self.assertIn("investigate", [s["step_id"] for s in dag_c["plan"]["steps"]])

    def test_falsified_claim_cannot_become_fact(self) -> None:
        claim = make_claim("bug is in ui", "ASSUMED")
        dead = update_claim(claim, status="FALSIFIED", evidence="tests point to backend")
        with self.assertRaises(ValueError):
            update_claim(dead, status="VERIFIED")


class DiffAndEditTests(unittest.TestCase):
    def test_unified_diff_roundtrip_cases(self) -> None:
        cases = [
            ("line\n", "line-changed\n", "changed"),
            ("keep\n", "keep\ninserted\n", "insert"),
            ("gone\nstay\n", "stay\n", "delete"),
            ("", "new file\n", "new"),
            ("a\nb\nc\nd\ne\n", "a\nB\nc\nD\ne\n", "multi_hunk"),
            ("unicode café\n", "unicode café!\n", "unicode"),
        ]
        for old, new, name in cases:
            with self.subTest(name=name):
                old_arg = None if name == "new" else old
                diff = make_unified_diff(old_text=old_arg, new_text=new, rel="f.txt")
                self.assertTrue(diff.startswith("---") or diff.startswith("+++") or "---" in diff[:40], diff)
                applied = apply_unified_diff_to_text("" if name == "new" else old, diff)
                self.assertEqual(applied, new)

    def test_worktree_diff_and_rename_action(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        src = root / "src"
        work = root / "work"
        src.mkdir()
        work.mkdir()
        (src / "a.py").write_text("old\n", encoding="utf-8")
        (work / "a.py").write_text("new\n", encoding="utf-8")
        (work / "added.py").write_text("x\n", encoding="utf-8")
        diff = make_worktree_unified_diff(work, baseline_hashes={"a.py": "x"}, source_root=src)
        self.assertIn("--- a/a.py", diff)
        self.assertIn("+++ b/added.py", diff)
        build = BuildAgentService(root)
        repo = root / "repo"
        repo.mkdir()
        (repo / "old.py").write_text("hi\n", encoding="utf-8")
        work2, _, _ = build.prepare_workspace(repo)
        applied, _ = build.apply_edits_in_workspace(
            work2,
            [FileEdit(path="new.py", action="rename", from_path="old.py")],
        )
        self.assertTrue((work2 / "new.py").is_file())
        self.assertFalse((work2 / "old.py").exists())
        self.assertEqual(applied[0]["action"], "rename")


class FailureAndVerificationTests(unittest.TestCase):
    def test_normalize_python_and_compact(self) -> None:
        logs = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 3, in add\n'
            "    return a - b\n"
            "AssertionError:  -1 != 5\n"
        )
        fail = normalize_failure(logs=logs, command=["python", "-m", "unittest"], exit_code=1)
        self.assertEqual(fail.file, "app.py")
        self.assertEqual(fail.line, 3)
        self.assertIn("AssertionError", fail.message)
        huge = "ok\n" * 5000 + "ERROR boom\n"
        compact = compact_log(huge, limit=500)
        self.assertLessEqual(len(compact), 500)
        self.assertIn("ERROR boom", compact)

    def test_msvc_and_tsc(self) -> None:
        msvc = normalize_failure(logs=r"src\foo.cpp(12,4): error C2065: undeclared")
        self.assertEqual(msvc.failure_type, "msvc")
        tsc = normalize_failure(logs="app.ts(4,1): error TS2322: Type 'string' is not assignable")
        self.assertEqual(tsc.failure_type, "typescript")

    def test_weakening_and_matrix(self) -> None:
        diff = "-    def test_real(self):\n-        self.assertEqual(1, 1)\n+    @unittest.skip('later')\n+    def test_real(self):\n"
        report = detect_test_weakening(diff)
        self.assertTrue(report["weakened"])
        matrix = plan_verification_matrix(changed_files=["backend/api.py"], languages=["python"], risk_level="high")
        self.assertIn("unit", matrix["required"])
        self.assertIn("regression", matrix["required"])
        impact = select_impacted_tests(changed_files=["mod.py"], named_tests=["test_mod.py"])
        self.assertIn("test_mod.py", impact["tests"])


class RepairCeilingAndSafetyTests(unittest.TestCase):
    def test_ceiling_uses_one_bound(self) -> None:
        self.assertEqual(resolve_repair_attempt_ceiling(5, 2), 2)
        self.assertEqual(resolve_repair_attempt_ceiling(2, 9), 2)
        self.assertEqual(resolve_repair_attempt_ceiling(0, None), 1)
        self.assertEqual(resolve_repair_attempt_ceiling(3, None), 3)

    def test_configured_lower_ceiling_does_not_leave_running_or_untested_repair(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        build = BuildAgentService(root)
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        calls = {"n": 0}

        def gen(work, diagnosis, test, attempt):
            calls["n"] += 1
            return [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a - b\n")]

        result = build.run_repair_loop(
            repo,
            [],
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=5,
            attempt_ceiling=2,
            repair_generator=gen,
            goal="fix add",
        )
        self.assertNotEqual(result.status, "running")
        self.assertEqual(result.status, "tests_failed")
        self.assertEqual(result.report.get("attempt_ceiling"), 2)
        self.assertEqual(len(result.test_results), 2)
        self.assertLessEqual(calls["n"], 1)
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))

    def test_source_untouched_and_stale_apply_conflicts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        coding = CodingAgentService(BuildAgentService(root))
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        result = coding.run_from_goal(repo, "Repareer de fout in add", test_suite="unittest", max_attempts=3)
        self.assertEqual(result["status"], "verified", result)
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))
        self.assertIn("--- a/app.py", result.get("diff_text") or "")
        self.assertIn("task_contract", result["coding"])
        self.assertEqual(result["coding"]["frontier_status"], "COMPLETED_VERIFIED")
        # Dirty the source after the run; apply must conflict.
        (repo / "app.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
        conflicts = coding.build.check_apply_conflicts(result["run_id"])
        self.assertTrue(conflicts)
        applied = coding.build.apply_to_source(result["run_id"], approved=True)
        self.assertEqual(applied["status"], "conflict")
        self.assertFalse(applied.get("applied"))

    def test_unapproved_apply_rejected(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        build = BuildAgentService(Path(tmp.name))
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("1\n", encoding="utf-8")
        result = build.run_repair_loop(
            repo,
            [FileEdit(path="a.py", action="replace", content="2\n")],
            test_suite="unittest",
            test_args=[],
            max_attempts=1,
        )
        with self.assertRaises(PermissionError):
            build.apply_to_source(result.run_id, approved=False)


class CandidateAndReviewTests(unittest.TestCase):
    def test_candidates_skip_trivial_and_score_verification(self) -> None:
        self.assertFalse(should_search_candidates(complexity_level="trivial", has_model=True))
        self.assertTrue(
            should_search_candidates(complexity_level="complex", risk_level="high", ambiguous=True, has_model=True)
        )
        good = score_candidate(
            test_result={"status": "passed"},
            diff_text="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
            applied=[{"path": "a.py"}],
        )
        weak = score_candidate(
            test_result={"status": "passed"},
            diff_text="-    def test_x(self):\n+    @unittest.skip('nope')\n",
            applied=[{"path": "test_x.py"}],
        )
        self.assertGreater(good["score"], weak["score"])
        self.assertTrue(weak["weakened"])

    def test_candidate_search_picks_verified(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        build = BuildAgentService(root)
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        bad = [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a - b\n")]
        good = [FileEdit(path="app.py", action="replace", content="def add(a, b):\n    return a + b\n")]
        out = run_candidate_search(build, repo, [bad, good], test_suite="unittest", test_args=["test_app.py"])
        self.assertTrue(out["used"])
        self.assertEqual(out["winner"]["passed"], True)
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))

    def test_reviewer_flags_shell_true(self) -> None:
        review = review_coding_result(
            goal="run command",
            diff_text="+ subprocess.run(cmd, shell=True)\n",
            changed_files=["x.py"],
            test_result={"status": "passed", "passed": True},
        )
        codes = {d["code"] for d in review["defects"]}
        self.assertIn("unsafe_shell", codes)


class ExploreAndMalformedTests(unittest.TestCase):
    def test_explore_uses_graph_and_malformed_model_does_not_execute(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text("from app import add\n", encoding="utf-8")
        hits = explore_repository(repo, "fix add")
        self.assertTrue({h.path for h in hits} & {"app.py", "test_app.py"})
        coding = CodingAgentService(BuildAgentService(Path(tmp.name)))

        async def bad_chat(_payload):
            return {"choices": [{"message": {"content": "not-json please run rm -rf"}}]}

        edits, meta = coding.propose_edits(repo, "implement something unique xyzzy", hits, chat_fn=bad_chat)
        self.assertEqual(edits, [])
        self.assertTrue(meta.get("note", "").startswith("invalid_model") or meta.get("method") in {"live_model", "none", "heuristic"})

    def test_eval_parsers(self) -> None:
        from evals.frontier_coding_suite import parse_fixture_failures

        out = parse_fixture_failures()
        self.assertTrue(out["diff_ok"])
        self.assertEqual(out["parsers"]["tsc"], "typescript")


class ResumeContractTests(unittest.TestCase):
    def test_checkpoint_can_store_contract(self) -> None:
        from coding_job_control import empty_checkpoint

        cp = empty_checkpoint(phase="before_edit")
        contract = build_coding_task_contract(goal="g", source_repo="/repo", base_revision="abc")
        cp["task_contract"] = contract
        self.assertEqual(cp["task_contract"]["base_revision"], "abc")
        self.assertEqual(cp["phase"], "before_edit")


class MemoryAndSanitizeTests(unittest.TestCase):
    def test_out_of_worktree_path_is_redacted(self) -> None:
        from coding_agent import sanitize_coding_log_for_model, sanitize_structured_failure_for_model

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name) / "work"
        work.mkdir()
        (work / "app.py").write_text("x = 1\n", encoding="utf-8")
        text = 'FAILED ../../outside.py\nFile "../../outside.py", line 1\nAssertionError: boom\n'
        safe = sanitize_coding_log_for_model(text, work)
        self.assertNotIn("../../outside.py", safe)
        self.assertIn("<out_of_worktree_path>", safe)
        payload = sanitize_structured_failure_for_model(
            {"file": "../../outside.py", "compacted": text, "raw_excerpt": text, "stack": [text]},
            work,
        )
        blob = str(payload)
        self.assertNotIn("../../outside.py", blob)

    def test_experience_memory_is_assumption_not_fact(self) -> None:
        from coding_memory import record_coding_lesson, recall_failure_hypotheses, record_failure_signature

        class FakeContinuity:
            def __init__(self) -> None:
                self.items: list[dict] = []

            def add_item(self, project_id: str, **kwargs: object) -> dict:
                row = {"project_id": project_id, **kwargs}
                self.items.append(row)
                return row

            def context_package(self, project_id: str) -> dict:
                return {"assumptions": list(self.items)}

        store = FakeContinuity()
        self.assertIsNone(record_coding_lesson(None, "p", title="t", body="b"))
        saved = record_coding_lesson(store, "p1", title="uses unittest", body="suite=unittest", provenance="observed")
        self.assertEqual(saved["kind"], "assumption")
        self.assertEqual(saved["provenance"], "observed")
        record_failure_signature(store, "p1", signature="python_traceback", root_cause="NameError")
        hits = recall_failure_hypotheses(store, "p1", signature_tokens=["python_traceback"])
        self.assertTrue(hits)
        self.assertEqual(hits[0]["status"], "HYPOTHESIS")

    def test_run_records_observed_lesson_when_continuity_supplied(self) -> None:
        from coding_memory import recall_failure_hypotheses

        class FakeContinuity:
            def __init__(self) -> None:
                self.items: list[dict] = []

            def add_item(self, project_id: str, **kwargs: object) -> dict:
                row = {"project_id": project_id, **kwargs}
                self.items.append(row)
                return row

            def context_package(self, project_id: str) -> dict:
                return {"assumptions": list(self.items)}

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        store = FakeContinuity()
        coding = CodingAgentService(BuildAgentService(root))
        result = coding.run_from_goal(
            repo,
            "Repareer de fout in add",
            test_suite="unittest",
            max_attempts=3,
            project_id="proj-1",
            continuity=store,
        )
        self.assertEqual(result.get("status"), "verified")
        self.assertTrue(store.items)
        self.assertEqual(store.items[0]["kind"], "assumption")
        recalled = recall_failure_hypotheses(store, "proj-1", signature_tokens=["unittest"])
        self.assertTrue(recalled)
        propose = (result.get("coding") or {}).get("propose") or {}
        self.assertIn("candidate_search", propose)
        self.assertFalse(propose["candidate_search"].get("eligible"))


if __name__ == "__main__":
    unittest.main()
