"""GI6 — tool intelligence: CapabilityCatalog, AST-safe math, budget coherence, honesty."""

from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from Data.functions import math_calculate
from Data.modules.cognition import CognitiveRunStatus, CognitiveRuntime, TaskModelBuilder
from Data.modules.cognition.runtime import CognitiveRunState
from Data.modules.compute.numeric import NumericComputeEngine
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry


MODULES_ROOT = Path(__file__).resolve().parents[2] / "modules"

REQUIRED_CAPS = (
    "system.inspect",
    "web.search",
    "web.fetch",
    "math.calculate",
)

OPTIONAL_RESEARCH_CAPS = (
    "research.advance",
    "research.plan",
    "research.retrieve",
    "research.synthesize",
    "research.verify",
    "research.fetch_url",
)


class CapabilityCatalogWorldTests(unittest.TestCase):
    def test_required_capabilities_registered(self) -> None:
        catalog = build_default_catalog()
        for cap_id in REQUIRED_CAPS:
            definition = catalog.get(cap_id)
            self.assertIsNotNone(definition, f"missing capability {cap_id}")
        # research.* is optional in some profiles — assert when present.
        for cap_id in OPTIONAL_RESEARCH_CAPS:
            if catalog.get(cap_id) is not None:
                self.assertEqual(catalog.get(cap_id).id, cap_id)

    def test_no_duplicate_tool_registry_owner(self) -> None:
        """CapabilityCatalog is the sole tool registry — no parallel ToolRegistry class."""
        catalog_owner_hits = 0
        forbidden_class_hits: list[str] = []
        for py_path in MODULES_ROOT.rglob("*.py"):
            if py_path.name == "ownership.py":
                continue
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if node.name == "CapabilityCatalog":
                    catalog_owner_hits += 1
                    rel = py_path.relative_to(MODULES_ROOT)
                    self.assertEqual(
                        rel.parts[0],
                        "execution",
                        f"CapabilityCatalog must live under execution/, found {rel}",
                    )
                if node.name in {
                    "ToolRegistry",
                    "UniversalToolRegistry",
                    "ToolRuntime2",
                }:
                    forbidden_class_hits.append(
                        f"{py_path.relative_to(MODULES_ROOT)}:{node.name}"
                    )
        self.assertEqual(catalog_owner_hits, 1)
        self.assertEqual(forbidden_class_hits, [])


class MathCalculateAstSafeTests(unittest.TestCase):
    def test_capability_function_two_plus_two(self) -> None:
        out = math_calculate.run(expression="2+2")
        self.assertEqual(out["value"], 4.0)
        self.assertTrue((out.get("details") or {}).get("safe_ast"))
        self.assertTrue((out.get("truth") or {}).get("deterministic"))

    def test_dangerous_expressions_fail(self) -> None:
        dangerous = (
            "__import__('os').system('x')",
            "pow(2, 10)",
            "open('/etc/passwd').read()",
            "(lambda: 1)()",
            "__builtins__",
        )
        for expr in dangerous:
            with self.subTest(expr=expr):
                with self.assertRaises(ValueError):
                    math_calculate.run(expression=expr)
                with self.assertRaises(ValueError):
                    NumericComputeEngine().evaluate_expression(expr)

    def test_implementation_has_no_eval(self) -> None:
        """AST walk must not call builtin eval/exec (mode='eval' on ast.parse is fine)."""
        import textwrap

        source = textwrap.dedent(inspect.getsource(NumericComputeEngine.evaluate_expression))
        self.assertIn("ast.parse", source)
        self.assertIn("safe_ast", source)
        tree = ast.parse(source)
        forbidden_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in {"eval", "exec"}:
                forbidden_calls.append(name)
        self.assertEqual(forbidden_calls, [], msg=f"forbidden calls: {forbidden_calls}")
        fn_tree = ast.parse(textwrap.dedent(inspect.getsource(math_calculate.run)))
        for node in ast.walk(fn_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec"})


class ToolBudgetCoherentAnswerTests(unittest.TestCase):
    def test_budget_exhaustion_rewrites_tool_json_to_prose(self) -> None:
        runtime = CognitiveRuntime(enabled=True, factuality_mode="NONE")
        task = TaskModelBuilder().build("Wat is 2+2?")
        state = CognitiveRunState(
            run_id="gi6-budget-1",
            task=task,
            status=CognitiveRunStatus.REASONING,
        )
        raw_tool_json = json.dumps(
            {
                "tool_calls": [
                    {
                        "name": "math.calculate",
                        "arguments": {"expression": "2+2"},
                    }
                ]
            }
        )
        state.response_text = raw_tool_json
        state.working_memory.upsert(
            "tool",
            "math.calculate: Result: 4",
            priority=0.8,
            verified=True,
        )
        self.assertTrue(runtime._looks_like_tool_json(state.response_text))

        runtime._ensure_coherent_final_answer(state, reason="budget_exhausted")

        answer = state.response_text or ""
        self.assertFalse(runtime._looks_like_tool_json(answer))
        self.assertNotIn('"tool_calls"', answer)
        self.assertIn("math.calculate", answer)
        self.assertIn("4", answer)
        finalize_events = [
            e for e in state.events if e.get("event_type") == "coherent_finalize"
        ]
        self.assertTrue(finalize_events)
        self.assertEqual(finalize_events[-1]["payload"]["reason"], "budget_exhausted")
        self.assertEqual(finalize_events[-1]["payload"]["source"], "observations")

    def test_finalize_budget_exhausted_strips_tool_json(self) -> None:
        runtime = CognitiveRuntime(enabled=True, factuality_mode="NONE")
        task = TaskModelBuilder().build("bereken iets")
        state = CognitiveRunState(
            run_id="gi6-budget-2",
            task=task,
            status=CognitiveRunStatus.REASONING,
        )
        state.response_text = '{"name": "web.search", "arguments": {"query": "x"}}'
        runtime._finalize(state, budget_exhausted=True)
        answer = state.response_text or ""
        self.assertFalse(runtime._looks_like_tool_json(answer))
        self.assertNotIn('"arguments"', answer)
        self.assertTrue(answer.strip())


class ToolFailureHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.runtime = FunctionRuntime(self.registry, max_concurrency=2)
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()

    def test_failed_math_stays_failed_not_invented_success(self) -> None:
        ok = self.gateway.execute(
            CapabilityRequest(
                capability_id="math.calculate",
                arguments={"expression": "2+2"},
            )
        )
        self.assertEqual(ok.status, CapabilityStatus.COMPLETED)
        self.assertEqual((ok.output or {}).get("value"), 4.0)

        failed = self.gateway.execute(
            CapabilityRequest(
                capability_id="math.calculate",
                arguments={"expression": "__import__('os').system('x')"},
            )
        )
        self.assertEqual(failed.status, CapabilityStatus.FAILED)
        self.assertNotEqual(failed.status, CapabilityStatus.COMPLETED)
        self.assertIsNone(failed.output)
        self.assertTrue(failed.error)

    def test_runtime_ingest_does_not_mark_failed_tool_verified(self) -> None:
        runtime = CognitiveRuntime(enabled=True, factuality_mode="NONE")
        task = TaskModelBuilder().build("Wat is 2+2?")
        state = CognitiveRunState(
            run_id="gi6-fail-1",
            task=task,
            status=CognitiveRunStatus.OBSERVING,
        )
        runtime._ingest_tool_result(
            state,
            "math.calculate",
            {
                "status": "FAILED",
                "error": "unsupported expression node: Call",
                "result": None,
            },
            success=False,
        )
        tools = state.working_memory.list_by_kind("tool")
        self.assertTrue(tools)
        self.assertFalse(tools[-1].verified)
        self.assertIn("failed", (tools[-1].content or "").lower())


class ArchitectureNoParallelToolRuntimeTests(unittest.TestCase):
    def test_no_tool_registry_modules_under_data_modules(self) -> None:
        forbidden_stems = {
            "tool_registry",
            "universal_tool_registry",
            "tool_runtime2",
            "toolruntime2",
        }
        forbidden_class_names = {
            "ToolRegistry",
            "UniversalToolRegistry",
            "ToolRuntime2",
        }
        file_hits: list[str] = []
        class_hits: list[str] = []
        for py_path in MODULES_ROOT.rglob("*.py"):
            stem = py_path.stem.lower().replace("-", "_")
            if stem in forbidden_stems or any(s in stem for s in forbidden_stems):
                file_hits.append(str(py_path.relative_to(MODULES_ROOT)))
            if py_path.name == "ownership.py":
                continue
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name in forbidden_class_names:
                    class_hits.append(
                        f"{py_path.relative_to(MODULES_ROOT)}:{node.name}"
                    )
        self.assertEqual(file_hits, [], msg=f"forbidden tool registry modules: {file_hits}")
        self.assertEqual(class_hits, [], msg=f"forbidden tool registry classes: {class_hits}")


if __name__ == "__main__":
    unittest.main()
