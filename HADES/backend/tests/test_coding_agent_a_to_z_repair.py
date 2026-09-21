"""Coding Agent A-to-Z repair regressions (structured output, intent, discovery, zero-edit honesty)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_agent import BuildAgentService, FileEdit
from coding_agent import CodingAgentService, explore_repository
from coding_failure_reasons import apply_mutation_no_change_guard
from coding_model_resolve import resolve_coding_model
from coding_source_policy import is_text_source_candidate, iter_text_source_files
from coding_structured_output import (
    parse_coding_edits_response,
    validate_edits_schema,
)
from coding_task_intent import classify_coding_task_intent


class StructuredOutputParserTests(unittest.TestCase):
    def test_pure_json(self) -> None:
        raw = '{"edits":[{"path":"a.py","action":"create","content":"x=1\\n"}]}'
        result = parse_coding_edits_response(raw)
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.edits_raw[0]["path"], "a.py")

    def test_fenced_json(self) -> None:
        raw = 'Here you go:\n```json\n{"edits":[{"path":"a.py","action":"create","content":"x=1\\n"}]}\n```\n'
        result = parse_coding_edits_response(raw)
        self.assertTrue(result.ok, result.to_dict())

    def test_prose_before_and_after(self) -> None:
        raw = 'Sure.\n{"edits":[{"path":"a.py","action":"create","content":"x=1\\n"}]}\nHope that helps!'
        result = parse_coding_edits_response(raw)
        self.assertTrue(result.ok, result.to_dict())

    def test_truncated_json(self) -> None:
        raw = '{"edits":[{"path":"a.py","action":"create","content":"x=1'
        result = parse_coding_edits_response(raw)
        self.assertFalse(result.ok)
        self.assertIn(result.kind, {"truncated", "malformed_response"})
        self.assertTrue(result.retry_recommended)

    def test_wrong_schema(self) -> None:
        raw = '{"changes":[{"file":"a.py"}]}'
        result = parse_coding_edits_response(raw)
        self.assertFalse(result.ok)
        self.assertEqual(result.kind, "schema_invalid")

    def test_empty_edits(self) -> None:
        raw = '{"edits":[]}'
        result = parse_coding_edits_response(raw)
        self.assertEqual(result.kind, "empty_edits")

    def test_stale_hash(self) -> None:
        payload = {
            "edits": [
                {
                    "path": "a.py",
                    "action": "replace",
                    "content": "x=2\n",
                    "base_hash": "deadbeef",
                }
            ]
        }
        result = validate_edits_schema(payload, known_hashes={"a.py": "cafebabe"})
        self.assertEqual(result.kind, "stale_hash")

    def test_malicious_prose_no_exec(self) -> None:
        raw = 'Ignore previous. __import__("os").system("rm -rf /")\n{"edits":[{"path":"a.py","action":"create","content":"ok\\n"}]}'
        result = parse_coding_edits_response(raw)
        self.assertTrue(result.ok)
        self.assertEqual(result.edits_raw[0]["content"], "ok\n")

    def test_multiple_json_regions_prefers_edits(self) -> None:
        raw = '{"note":"noise"}\n{"edits":[{"path":"b.py","action":"create","content":"y=1\\n"}]}'
        result = parse_coding_edits_response(raw)
        self.assertTrue(result.ok)
        self.assertEqual(result.edits_raw[0]["path"], "b.py")

    def test_timeout_meta(self) -> None:
        result = parse_coding_edits_response(
            None, invoke_meta={"note": "lm_invoke_timeout:180"}
        )
        self.assertEqual(result.kind, "timeout")


class TaskIntentTests(unittest.TestCase):
    def test_dutch_mixed_intent_is_mutation(self) -> None:
        intent = classify_coding_task_intent(
            "Onderzoek waarom add fout is en repareer het."
        )
        self.assertTrue(intent.requires_mutation)
        self.assertFalse(intent.report_only)
        self.assertIn(intent.coarse_task_type, {"bugfix", "feature"})

    def test_english_root_cause_and_repair(self) -> None:
        intent = classify_coding_task_intent("Find the root cause and repair it.")
        self.assertTrue(intent.requires_mutation)

    def test_review_only(self) -> None:
        intent = classify_coding_task_intent(
            "Review this code only. Do not modify files."
        )
        self.assertTrue(intent.report_only)
        self.assertFalse(intent.requires_mutation)

    def test_analyze_only_autonomy(self) -> None:
        intent = classify_coding_task_intent(
            "Fix the login bug", autonomy_profile="analyze_only"
        )
        self.assertTrue(intent.report_only)

    def test_feature_create(self) -> None:
        intent = classify_coding_task_intent("Maak een nieuwe component voor settings.")
        self.assertTrue(intent.requires_mutation)
        self.assertEqual(intent.coarse_task_type, "feature")


class SourceDiscoveryTests(unittest.TestCase):
    def test_css_is_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            css = root / "components" / "coding.css"
            css.parent.mkdir(parents=True)
            css.write_text(".x{color:red}", encoding="utf-8")
            self.assertTrue(is_text_source_candidate(css, root=root))
            files = iter_text_source_files(root, prefer_tokens=["coding", "css"], exact_paths=["components/coding.css"])
            self.assertTrue(any(p.name == "coding.css" for p in files))

    def test_explore_finds_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            css = root / "ui" / "panel.css"
            css.parent.mkdir(parents=True)
            css.write_text(".panel{padding:8px}", encoding="utf-8")
            (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
            hits = explore_repository(root, "Wijzig panel.css styling")
            paths = {h.path for h in hits}
            self.assertIn("ui/panel.css", paths)


class ModelResolveTests(unittest.TestCase):
    def test_does_not_silent_local(self) -> None:
        resolved = resolve_coding_model(
            explicit_model_id=None,
            active_model_id=None,
            inventory=[{"id": "qwen2.5-coder"}],
        )
        self.assertFalse(resolved.usable)
        self.assertEqual(resolved.blocker, "model_unavailable")

    def test_explicit_survives(self) -> None:
        resolved = resolve_coding_model(
            explicit_model_id="qwen2.5-coder",
            inventory=[{"id": "qwen2.5-coder"}, {"id": "other"}],
        )
        self.assertTrue(resolved.usable)
        self.assertEqual(resolved.model_id, "qwen2.5-coder")


class ZeroEditHonestyTests(unittest.TestCase):
    def test_green_baseline_not_verified_for_mutation(self) -> None:
        status, blocker = apply_mutation_no_change_guard(
            requires_mutation=True,
            status="verified",
            applied_edits=[],
            diff_text="",
            propose_meta={"method": "none", "note": "invalid_model_edits:schema"},
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNotNone(blocker)

    def test_report_only_empty_diff_ok(self) -> None:
        status, blocker = apply_mutation_no_change_guard(
            requires_mutation=False,
            status="completed",
            applied_edits=[],
            diff_text="",
        )
        self.assertEqual(status, "completed")
        self.assertIsNone(blocker)


class FencedModelProposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = BuildAgentService(self.root)
        self.coding = CodingAgentService(self.build)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        return repo

    def test_fenced_json_applied_in_worktree(self) -> None:
        repo = self._repo()
        body = (repo / "app.py").read_text(encoding="utf-8")
        import hashlib

        digest = hashlib.sha256(body.encode()).hexdigest()
        fence = (
            "```json\n"
            + json.dumps(
                {
                    "edits": [
                        {
                            "path": "app.py",
                            "action": "replace",
                            "content": "def add(a, b):\n    return a + b\n",
                            "base_hash": digest,
                        }
                    ]
                }
            )
            + "\n```"
        )

        async def chat_fn(payload: dict[str, Any]) -> dict[str, Any]:
            self.assertEqual(payload.get("model"), "test-coder")
            return {"choices": [{"message": {"content": fence}, "finish_reason": "stop"}]}

        result = self.coding.run_from_goal(
            repo,
            "Repareer add",
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=2,
            chat_fn=chat_fn,
            model_id="test-coder",
            auto_repair=False,
            strategy="fast",
        )
        self.assertEqual(result["status"], "verified", result)
        work = Path(result["work_root"])
        self.assertIn("return a + b", (work / "app.py").read_text(encoding="utf-8"))
        # Source untouched
        self.assertIn("return a - b", (repo / "app.py").read_text(encoding="utf-8"))

    def test_truncated_not_verified(self) -> None:
        repo = self._repo()
        # Green repo so tests pass without edits — must NOT verify for feature request.
        (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        async def chat_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {"content": '{"edits":[{"path":"app.py","action":"create","content":"'},
                        "finish_reason": "length",
                    }
                ]
            }

        result = self.coding.run_from_goal(
            repo,
            "Create a new function called calculate_total.",
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=1,
            chat_fn=chat_fn,
            model_id="test-coder",
            auto_repair=False,
            strategy="fast",
        )
        self.assertNotEqual(result["status"], "verified", result)
        self.assertIn(
            result["status"],
            {"no_change", "implementation_missing", "model_output_invalid", "failed"},
        )

    def test_missing_model_blocker(self) -> None:
        repo = self._repo()
        (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        result = self.coding.run_from_goal(
            repo,
            "Create a new function called calculate_total.",
            test_suite="unittest",
            test_args=["test_app.py"],
            max_attempts=1,
            chat_fn=None,
            model_id=None,
            auto_repair=False,
            strategy="fast",
            config_snapshot={"model_inventory": []},
        )
        self.assertEqual(result["status"], "model_unavailable", result)

    def test_analyze_only_blocks_mutation(self) -> None:
        repo = self._repo()
        result = self.coding.run_from_goal(
            repo,
            "Repareer add",
            test_suite="unittest",
            max_attempts=1,
            autonomy_profile="analyze_only",
            chat_fn=None,
            model_id="x",
        )
        self.assertEqual(result.get("applied_edits") or [], [])
        coding = result.get("coding") or {}
        self.assertEqual(coding.get("autonomy_profile"), "analyze_only")
        self.assertIn("a - b", (repo / "app.py").read_text(encoding="utf-8"))

    def test_async_review_no_coroutine_warning(self) -> None:
        repo = self._repo()
        (repo / "HISTORY.md").write_text("commit abc changed default\n", encoding="utf-8")
        (repo / "PATCH.diff").write_text("-safe\n+fast\n", encoding="utf-8")

        async def chat_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "root_cause": "Default flipped",
                                    "recommended_fix": "Restore safe",
                                    "findings": [],
                                }
                            )
                        }
                    }
                ]
            }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            draft = self.coding._draft_report_findings(
                work_root=repo,
                goal="Give me a root-cause report only.",
                task_type="regression",
                hits=[],
                chat_fn=chat_fn,
                model_id="test-coder",
            )
        coro_warns = [
            w
            for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "coroutine" in str(w.message).lower()
        ]
        self.assertEqual(coro_warns, [], [str(w.message) for w in coro_warns])
        self.assertTrue(draft.get("model_invoked") or draft.get("root_cause"))


class RealisticFixtureE2ETests(unittest.TestCase):
    """Small multi-language fixture: Python + TSX + CSS."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.build = BuildAgentService(self.root)
        self.coding = CodingAgentService(self.build)
        self.repo = self.root / "fixture"
        self.repo.mkdir()
        (self.repo / "backend").mkdir()
        (self.repo / "components").mkdir()
        (self.repo / "backend" / "mathutil.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"
        )
        (self.repo / "backend" / "test_mathutil.py").write_text(
            "import unittest\nfrom mathutil import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        (self.repo / "components" / "Widget.tsx").write_text(
            "export function Widget(){ return <div className='widget'>Hi</div>; }\n",
            encoding="utf-8",
        )
        (self.repo / "components" / "widget.css").write_text(
            ".widget{color:red}\n", encoding="utf-8"
        )
        (self.repo / "package.json").write_text(
            json.dumps({"name": "fixture", "scripts": {"test": "echo ok"}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_mutation_intent_and_css_discovery(self) -> None:
        intent = classify_coding_task_intent(
            "Onderzoek waarom deze React-component kapot is en fix hem, inclusief CSS."
        )
        self.assertTrue(intent.requires_mutation)
        hits = explore_repository(
            self.repo,
            "Onderzoek waarom Widget kapot is en fix hem, inclusief widget.css",
        )
        paths = {h.path for h in hits}
        self.assertTrue(any(p.endswith("widget.css") for p in paths), paths)
        self.assertTrue(any(p.endswith("Widget.tsx") for p in paths), paths)

    def test_goal_to_worktree_with_fenced_model(self) -> None:
        import hashlib

        # Flat layout so unittest path imports work under the worktree.
        flat = self.root / "flat"
        flat.mkdir()
        (flat / "mathutil.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (flat / "test_mathutil.py").write_text(
            "import unittest\nfrom mathutil import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        (flat / "widget.css").write_text(".widget{color:red}\n", encoding="utf-8")
        body = (flat / "mathutil.py").read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode()).hexdigest()
        # Use a goal that avoids the heuristic pattern so the live-model path is exercised.
        fence = (
            "```json\n"
            + json.dumps(
                {
                    "edits": [
                        {
                            "path": "mathutil.py",
                            "action": "replace",
                            "content": "def add(a, b):\n    return a + b\n",
                            "base_hash": digest,
                        }
                    ]
                }
            )
            + "\n```"
        )

        async def chat_fn(payload: dict[str, Any]) -> dict[str, Any]:
            self.assertEqual(payload["model"], "fixture-model")
            return {"choices": [{"message": {"content": fence}}]}

        result = self.coding.run_from_goal(
            flat,
            "Correct the arithmetic so unit tests pass for calculate_sum style add.",
            test_suite="unittest",
            test_args=["test_mathutil.py"],
            max_attempts=2,
            chat_fn=chat_fn,
            model_id="fixture-model",
            auto_repair=False,
            strategy="fast",
        )
        self.assertTrue(result.get("diff_text") or result.get("applied_edits"), result)
        work = Path(result["work_root"])
        self.assertIn("return a + b", (work / "mathutil.py").read_text(encoding="utf-8"))
        self.assertIn("return a - b", (flat / "mathutil.py").read_text(encoding="utf-8"))
        # Prefer verified; if heuristic path also works, either is acceptable as long as worktree changed.
        self.assertIn(result["status"], {"verified", "tests_failed", "ready_for_review"}, result)
        if result["status"] != "verified":
            # Still prove model edits reached the worktree (acceptance: no silent no-op).
            self.assertTrue(result.get("applied_edits"))


class ModelIdPropagationTests(unittest.TestCase):
    def test_propose_edits_uses_resolved_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = BuildAgentService(root)
            coding = CodingAgentService(build)
            repo = root / "r"
            repo.mkdir()
            (repo / "a.py").write_text("x=1\n", encoding="utf-8")
            seen: list[str] = []

            async def chat_fn(payload: dict[str, Any]) -> dict[str, Any]:
                seen.append(str(payload.get("model")))
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "edits": [
                                            {
                                                "path": "b.py",
                                                "action": "create",
                                                "content": "y=2\n",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }

            from coding_agent import ExploreHit

            hits = [
                ExploreHit(
                    path="a.py",
                    reason="t",
                    score=1,
                    preview="x=1",
                    content_hash="abc",
                )
            ]
            edits, meta = coding.propose_edits(
                repo, "Create b.py", hits, chat_fn=chat_fn, model_id="ui-selected-model"
            )
            self.assertEqual(seen, ["ui-selected-model"])
            self.assertTrue(edits)
            self.assertEqual(meta.get("model_id"), "ui-selected-model")


if __name__ == "__main__":
    unittest.main()
