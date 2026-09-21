"""Regression tests for capability-based work-plan routing and deadlock diagnostics."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtimes import AgentRuntimeDeps, try_run_agent_step
from reasoning.plan_scheduler import (
    PlanValidationError,
    diagnose_deadlock,
    format_deadlock_error,
    ready_steps,
    validate_plan,
)
from reasoning.specialists import SPECIALISTS, route_specialist
from reasoning.work_capabilities import (
    EXECUTOR_CAPABILITIES,
    executor_supports,
    infer_required_capability,
    pick_executor_for_capability,
)
from reasoning.work_intents import (
    assign_step_agent_for_instruction,
    build_existing_plugin_to_knowledge_plan,
    classify_plugin_intent,
    classify_work_intent,
    preserve_required_capabilities,
)


ENABLED = set(SPECIALISTS.keys())


class PluginIntentRoutingTests(unittest.TestCase):
    def test_use_existing_never_routes_to_evidence_auditor(self) -> None:
        prompts = [
            "gebruik NewsFeeder",
            "voer NewsFeeder uit",
            "haal data uit NewsFeeder",
            "verwerk output van NewsFeeder",
            "Gebruik de bestaande geïnstalleerde plugin NewsFeeder en sla artikelen op in kennis",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_work_intent(prompt), "USE_EXISTING_PLUGIN")
                self.assertEqual(classify_plugin_intent(prompt), "USE_EXISTING_PLUGIN")
                chosen = route_specialist(prompt, enabled_ids=ENABLED)
                self.assertNotEqual(chosen, "evidence_auditor")
                self.assertEqual(chosen, "tool_orchestrator")

    def test_use_existing_never_routes_to_build(self) -> None:
        prompt = "Gebruik bestaande NewsFeeder plugin, voer uit, sla artikelen op in knowledge"
        chosen = route_specialist(prompt, enabled_ids=ENABLED)
        self.assertNotEqual(chosen, "build")
        self.assertEqual(chosen, "tool_orchestrator")

    def test_use_existing_never_routes_to_plugin_converter(self) -> None:
        prompt = "voer NewsFeeder plugin uit en verwerk artikelen"
        chosen = route_specialist(prompt, enabled_ids=ENABLED)
        self.assertNotEqual(chosen, "plugin_converter")
        self.assertEqual(chosen, "tool_orchestrator")

    def test_create_and_convert_intents(self) -> None:
        self.assertEqual(classify_work_intent("bouw een NewsFeeder plugin van deze GitHub repo"), "CREATE_PLUGIN")
        self.assertEqual(classify_work_intent("converteer deze tool naar een plugin"), "CONVERT_PLUGIN")
        self.assertEqual(
            route_specialist("bouw een NewsFeeder plugin van deze GitHub repo", enabled_ids=ENABLED),
            "plugin_converter",
        )

    def test_plugin_lookup_never_routes_to_knowledge_builder(self) -> None:
        agent = assign_step_agent_for_instruction(
            "Zoek de bestaande geïnstalleerde plugin NewsFeeder in de registry",
            title="Resolve installed NewsFeeder",
            proposed="knowledge_builder",
            required_capability="plugin.resolve",
            enabled_agents=ENABLED,
        )
        self.assertNotEqual(agent, "knowledge_builder")
        self.assertEqual(agent, "tool_orchestrator")


class CapabilityRegistryTests(unittest.TestCase):
    def test_plugin_resolve_requires_owner(self) -> None:
        self.assertTrue(executor_supports("tool_orchestrator", "plugin.resolve"))
        self.assertFalse(executor_supports("knowledge_builder", "plugin.resolve"))
        self.assertFalse(executor_supports("build", "plugin.resolve"))
        self.assertEqual(
            pick_executor_for_capability("plugin.resolve", enabled_agents=ENABLED),
            "tool_orchestrator",
        )

    def test_plugin_execute_requires_owner(self) -> None:
        self.assertTrue(executor_supports("tool_orchestrator", "plugin.execute"))
        self.assertFalse(executor_supports("build", "plugin.execute"))
        self.assertFalse(executor_supports("evidence_auditor", "plugin.execute"))

    def test_invalid_executor_assignment_rejected_before_runtime(self) -> None:
        with self.assertRaises(PlanValidationError) as ctx:
            validate_plan(
                {
                    "steps": [
                        {
                            "step_id": "step-1",
                            "instruction": "Execute existing plugin NewsFeeder via PluginManager",
                            "agent_id": "build",
                            "required_capability": "plugin.execute",
                            "depends_on": [],
                        }
                    ]
                },
                allowed_agents={"build", "tool_orchestrator"},
                enforce_capabilities=True,
            )
        self.assertTrue(ctx.exception.diagnostics.get("executor_capability_mismatch"))
        self.assertEqual(ctx.exception.diagnostics.get("required_capability"), "plugin.execute")

    def test_infer_capabilities_from_instructions(self) -> None:
        self.assertEqual(
            infer_required_capability("Resolve installed NewsFeeder from registry", title="Resolve"),
            "plugin.resolve",
        )
        self.assertEqual(
            infer_required_capability("Check NewsFeeder health/availability", title="Health"),
            "plugin.health",
        )
        self.assertEqual(
            infer_required_capability("Invoke/execute the resolved NewsFeeder plugin", title="Execute"),
            "plugin.execute",
        )


class ReplanCapabilityTests(unittest.TestCase):
    def test_replanning_preserves_required_capabilities(self) -> None:
        prior = [
            {
                "step_id": "step-1",
                "instruction": "resolve plugin",
                "required_capability": "plugin.resolve",
                "agent_id": "tool_orchestrator",
            },
            {
                "step_id": "step-2",
                "instruction": "execute plugin",
                "required_capability": "plugin.execute",
                "agent_id": "tool_orchestrator",
            },
        ]
        # Bad replan attempt that downgrades resolve → knowledge_builder and execute → build.
        bad = [
            {
                "step_id": "step-1",
                "title": "Zoek plugin",
                "instruction": "Zoek de bestaande geïnstalleerde NewsFeeder-plugin",
                "agent_id": "knowledge_builder",
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "title": "Voer uit",
                "instruction": "Voer de bestaande NewsFeeder-plugin daadwerkelijk uit",
                "agent_id": "build",
                "depends_on": ["step-1"],
            },
        ]
        fixed = preserve_required_capabilities(bad, prior_steps=prior)
        self.assertEqual(fixed[0]["required_capability"], "plugin.resolve")
        self.assertEqual(fixed[0]["agent_id"], "tool_orchestrator")
        self.assertEqual(fixed[1]["required_capability"], "plugin.execute")
        self.assertEqual(fixed[1]["agent_id"], "tool_orchestrator")


class DependencyGraphTests(unittest.TestCase):
    def test_valid_graph_exposes_root_executable_step(self) -> None:
        plan = validate_plan(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "instruction": "resolve plugin",
                        "agent_id": "tool_orchestrator",
                        "required_capability": "plugin.resolve",
                        "depends_on": [],
                    },
                    {
                        "step_id": "step-2",
                        "instruction": "execute plugin",
                        "agent_id": "tool_orchestrator",
                        "required_capability": "plugin.execute",
                        "depends_on": ["step-1"],
                    },
                    {
                        "step_id": "step-3",
                        "instruction": "convert to knowledge items",
                        "agent_id": "knowledge_builder",
                        "required_capability": "knowledge.transform",
                        "depends_on": ["step-2"],
                    },
                ]
            },
            allowed_agents={"tool_orchestrator", "knowledge_builder"},
        )
        ready = ready_steps(plan.steps)
        self.assertEqual(ready, ["step-1"])

    def test_step_becomes_ready_after_dependencies_complete(self) -> None:
        steps = [
            {"step_id": "a", "instruction": "one", "agent_id": "executor", "depends_on": [], "status": "completed"},
            {"step_id": "b", "instruction": "two", "agent_id": "executor", "depends_on": ["a"], "status": "pending"},
        ]
        self.assertEqual(ready_steps(steps, completed_ids={"a"}), ["b"])

    def test_failed_dependency_blocks_dependent_step(self) -> None:
        steps = [
            {"step_id": "a", "instruction": "one", "agent_id": "executor", "depends_on": [], "status": "failed"},
            {"step_id": "b", "instruction": "two", "agent_id": "executor", "depends_on": ["a"], "status": "pending"},
        ]
        self.assertEqual(ready_steps(steps, failed_ids={"a"}), [])
        diagnostics = diagnose_deadlock(steps, failed_ids={"a"})
        self.assertIn("b", diagnostics["blocked_steps"])
        self.assertIn("a", diagnostics["failed_steps"])

    def test_cyclic_dependency_graph_detected(self) -> None:
        with self.assertRaises(PlanValidationError) as ctx:
            validate_plan(
                {
                    "steps": [
                        {"step_id": "a", "instruction": "one", "agent_id": "executor", "depends_on": ["b"]},
                        {"step_id": "b", "instruction": "two", "agent_id": "executor", "depends_on": ["a"]},
                    ]
                },
                allowed_agents={"executor"},
            )
        self.assertTrue(ctx.exception.diagnostics.get("cycle_detected") or "cyclic" in str(ctx.exception).lower())

    def test_missing_executor_detected_before_execution(self) -> None:
        with self.assertRaises(PlanValidationError) as ctx:
            validate_plan(
                {
                    "steps": [
                        {
                            "step_id": "a",
                            "instruction": "do work",
                            "agent_id": "does_not_exist",
                            "depends_on": [],
                        }
                    ]
                },
                allowed_agents={"executor", "tool_orchestrator"},
                require_executable_path=True,
            )
        self.assertTrue(ctx.exception.diagnostics.get("missing_executors") or "not allowed" in str(ctx.exception))

    def test_dependency_failure_produces_explicit_blocked_diagnostics(self) -> None:
        steps = [
            {
                "step_id": "step-1",
                "instruction": "lookup",
                "agent_id": "tool_orchestrator",
                "required_capability": "plugin.resolve",
                "depends_on": [],
                "status": "failed",
            },
            {
                "step_id": "step-2",
                "instruction": "execute existing plugin",
                "agent_id": "build",
                "required_capability": "plugin.execute",
                "depends_on": ["step-1"],
                "status": "pending",
            },
        ]
        diagnostics = diagnose_deadlock(steps, failed_ids={"step-1"})
        self.assertEqual(diagnostics["ready_steps"], [])
        self.assertIn("step-1", diagnostics["failed_steps"])
        self.assertIn("step-2", diagnostics["blocked_steps"])
        self.assertIn("blocked_by_failed_dependency", diagnostics["reasons"])
        self.assertIn("executor_capability_mismatch", diagnostics["reasons"])
        self.assertTrue(diagnostics["capability_mismatches"])
        message = format_deadlock_error(diagnostics)
        self.assertIn("Step step-2 blocked", message)
        self.assertIn("executor capability mismatch=True", message)
        self.assertIn("dependency_states", diagnostics)


class NewsFeederPlanTests(unittest.TestCase):
    def test_newsfeeder_like_task_produces_valid_executable_plan(self) -> None:
        prompt = "use an existing NewsFeeder plugin and save its returned articles to knowledge"
        raw = build_existing_plugin_to_knowledge_plan(prompt)
        plan = validate_plan(
            raw,
            allowed_agents={"tool_orchestrator", "knowledge_builder", "executor", "chat"},
            max_steps=8,
        )
        self.assertEqual(len(plan.steps), 6)
        self.assertEqual(ready_steps(plan.steps), ["step-1"])
        caps = [step.required_capability for step in plan.steps]
        self.assertEqual(
            caps,
            [
                "plugin.resolve",
                "plugin.health",
                "plugin.execute",
                "knowledge.transform",
                "knowledge.persist",
                "knowledge.verify_persistence",
            ],
        )
        agents = [step.agent_id for step in plan.steps]
        self.assertEqual(agents[:3], ["tool_orchestrator", "tool_orchestrator", "tool_orchestrator"])
        self.assertEqual(agents[3:], ["knowledge_builder", "knowledge_builder", "knowledge_builder"])
        self.assertNotIn("evidence_auditor", agents)
        self.assertNotIn("web_scout", agents)
        self.assertNotIn("plugin_converter", agents)
        self.assertNotIn("build", agents)
        self.assertNotEqual(plan.steps[0].agent_id, "knowledge_builder")

    def test_step_numbering_increments_correctly(self) -> None:
        steps = [
            {"step_index": 0, "title": "A"},
            {"step_index": 1, "title": "B"},
            {"step_index": 2, "title": "C"},
            {"step_index": 3, "title": "D"},
        ]
        total = len(steps)
        labels = []
        for step in steps:
            step_number = int(step.get("step_index") if step.get("step_index") is not None else 0) + 1
            labels.append(f"Stap {step_number}/{total}")
        self.assertEqual(labels, ["Stap 1/4", "Stap 2/4", "Stap 3/4", "Stap 4/4"])


class DeterministicBudgetTests(unittest.TestCase):
    def test_deterministic_plugin_execution_does_not_consume_llm_budget(self) -> None:
        plugins = [
            {
                "id": "newsfeeder",
                "name": "NewsFeeder",
                "status": "ready",
                "enabled": True,
                "manifest": {"name": "NewsFeeder"},
            }
        ]
        tools = [
            {
                "plugin_id": "newsfeeder",
                "name": "fetch_articles",
                "status": "ready",
                "permissions": [],
            }
        ]

        class FakeDB:
            def list_plugins(self):
                return plugins

            def plugin_tools(self, plugin_id=None):
                if plugin_id is None:
                    return tools
                return [t for t in tools if t["plugin_id"] == plugin_id]

        class FakePM:
            def invoke(self, plugin_id, tool_name, payload, approved_by_user=False):
                return {
                    "status": "completed",
                    "result": {"articles": [{"title": "Hello", "content": "World", "url": "https://example.com/a"}]},
                }

        for title, instruction in [
            ("Resolve installed NewsFeeder", "Resolve installed plugin 'NewsFeeder' from the local plugin registry."),
            ("Check NewsFeeder health/availability", "Check NewsFeeder health/availability via plugin runtime."),
        ]:
            result = asyncio.run(
                try_run_agent_step(
                    "tool_orchestrator",
                    instruction,
                    deps=AgentRuntimeDeps(
                        settings={"network_policy": "allow"},
                        platform_db=FakeDB(),
                        plugin_manager=FakePM(),
                        step_title=title,
                        prior_outputs=[],
                    ),
                )
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.ok)
            self.assertEqual(result.mode, "deterministic")
            self.assertFalse(result.metadata.get("llm_budget_consumed", True))
            payload = json.loads(result.output)
            self.assertFalse(payload.get("llm_budget_consumed", True))

        # F-02: execute falls through to model+tool-engine (not deterministic here).
        execute = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Invoke/execute the resolved 'NewsFeeder' plugin via PluginManager.",
                deps=AgentRuntimeDeps(
                    settings={"network_policy": "allow"},
                    platform_db=FakeDB(),
                    plugin_manager=FakePM(),
                    step_title="Execute NewsFeeder",
                    prior_outputs=[
                        {
                            "output": json.dumps({"plugin_id": "newsfeeder", "resolved": True}),
                            "step_key": "step-1",
                            "agent_id": "tool_orchestrator",
                        }
                    ],
                ),
            )
        )
        self.assertIsNone(execute)

    def test_deterministic_persistence_does_not_consume_llm_budget(self) -> None:
        class FakeDB:
            def get_knowledge_source(self, source_id):
                return {"id": source_id, "status": "ready"}

            def list_knowledge_chunks(self, source_id, limit=5):
                return [{"id": "c1", "source_id": source_id}]

        class FakeKnowledge:
            def ingest_text(self, **kwargs):
                return {"id": "src-1", "source_id": "src-1", "chunks": 1, "title": kwargs.get("title")}

        convert = asyncio.run(
            try_run_agent_step(
                "knowledge_builder",
                "Convert/normalize the prior plugin tool output into KnowledgeItems.",
                deps=AgentRuntimeDeps(
                    settings={},
                    platform_db=FakeDB(),
                    knowledge=FakeKnowledge(),
                    prior_outputs=[
                        {
                            "output": json.dumps(
                                {"articles": [{"title": "Hello", "content": "World article body", "url": "https://example.com/a"}]}
                            ),
                            "step_key": "step-3",
                            "agent_id": "tool_orchestrator",
                        }
                    ],
                    step_title="Normalize returned articles into KnowledgeItems",
                ),
            )
        )
        self.assertIsNotNone(convert)
        assert convert is not None
        self.assertTrue(convert.ok)
        self.assertFalse(convert.metadata.get("llm_budget_consumed", True))

        persist = asyncio.run(
            try_run_agent_step(
                "knowledge_builder",
                "Persist KnowledgeItems via the knowledge repository (DB insert + SQLite commit).",
                deps=AgentRuntimeDeps(
                    settings={},
                    platform_db=FakeDB(),
                    knowledge=FakeKnowledge(),
                    prior_outputs=[{"output": convert.output, "step_key": "step-4", "agent_id": "knowledge_builder"}],
                    step_title="Persist KnowledgeItems",
                ),
            )
        )
        self.assertIsNotNone(persist)
        assert persist is not None
        self.assertTrue(persist.ok)
        self.assertFalse(persist.metadata.get("llm_budget_consumed", True))
        persist_payload = json.loads(persist.output)
        self.assertFalse(persist_payload.get("llm_budget_consumed", True))

        verify = asyncio.run(
            try_run_agent_step(
                "knowledge_builder",
                "Read back inserted KnowledgeItem records and verify persistence.",
                deps=AgentRuntimeDeps(
                    settings={},
                    platform_db=FakeDB(),
                    knowledge=FakeKnowledge(),
                    prior_outputs=[{"output": persist.output, "step_key": "step-5", "agent_id": "knowledge_builder"}],
                    step_title="Read back and verify persistence",
                ),
            )
        )
        self.assertIsNotNone(verify)
        assert verify is not None
        self.assertTrue(verify.ok)
        self.assertFalse(verify.metadata.get("llm_budget_consumed", True))


class PluginKnowledgeRuntimePipelineTests(unittest.TestCase):
    def test_work_plan_completes_plugin_execution_to_knowledge_persistence(self) -> None:
        plugins = [
            {
                "id": "newsfeeder",
                "name": "NewsFeeder",
                "status": "ready",
                "enabled": True,
                "manifest": {"name": "NewsFeeder"},
            }
        ]
        tools = [
            {
                "plugin_id": "newsfeeder",
                "name": "fetch_articles",
                "status": "ready",
                "permissions": [],
            }
        ]

        class FakeDB:
            def list_plugins(self):
                return plugins

            def plugin_tools(self, plugin_id=None):
                if plugin_id is None:
                    return tools
                return [t for t in tools if t["plugin_id"] == plugin_id]

            def get_knowledge_source(self, source_id):
                return {"id": source_id, "status": "ready"}

            def list_knowledge_chunks(self, source_id, limit=5):
                return [{"id": "c1", "source_id": source_id}]

        class FakeKnowledge:
            def ingest_text(self, **kwargs):
                return {"id": "src-1", "source_id": "src-1", "chunks": 1, "title": kwargs.get("title")}

        class FakePM:
            def invoke(self, plugin_id, tool_name, payload, approved_by_user=False):
                return {
                    "status": "completed",
                    "result": {
                        "articles": [
                            {"title": "Hello", "content": "World article body", "url": "https://example.com/a"}
                        ]
                    },
                }

        db = FakeDB()
        knowledge = FakeKnowledge()
        pm = FakePM()

        resolve = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Resolve installed plugin 'NewsFeeder' from the local plugin registry.",
                deps=AgentRuntimeDeps(
                    settings={"network_policy": "allow"},
                    platform_db=db,
                    plugin_manager=pm,
                    knowledge=knowledge,
                    step_title="Resolve installed NewsFeeder",
                ),
            )
        )
        self.assertIsNotNone(resolve)
        assert resolve is not None
        self.assertTrue(resolve.ok)
        resolve_payload = json.loads(resolve.output)
        self.assertEqual(resolve_payload.get("plugin_id"), "newsfeeder")

        health = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Check NewsFeeder health/availability via plugin runtime.",
                deps=AgentRuntimeDeps(
                    settings={"network_policy": "allow"},
                    platform_db=db,
                    plugin_manager=pm,
                    knowledge=knowledge,
                    prior_outputs=[{"output": resolve.output, "step_key": "step-1", "agent_id": "tool_orchestrator"}],
                    step_title="Check NewsFeeder health/availability",
                ),
            )
        )
        self.assertIsNotNone(health)
        assert health is not None
        self.assertTrue(health.ok)

        execute = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Invoke/execute the resolved 'NewsFeeder' plugin via PluginManager.",
                deps=AgentRuntimeDeps(
                    settings={"network_policy": "allow"},
                    platform_db=db,
                    plugin_manager=pm,
                    knowledge=knowledge,
                    prior_outputs=[{"output": resolve.output, "step_key": "step-1", "agent_id": "tool_orchestrator"}],
                    step_title="Execute NewsFeeder",
                ),
            )
        )
        # F-02: invoke falls through to model+tool-engine (no canned args/approval).
        self.assertIsNone(execute)

        # Simulate a prior tool-engine invoke result for knowledge_builder coverage.
        fake_invoke_output = json.dumps(
            {
                "plugin_id": "newsfeeder",
                "invoke": {
                    "status": "completed",
                    "result": {
                        "articles": [
                            {"title": "Hello", "content": "World article body", "url": "https://example.com/a"}
                        ]
                    },
                },
            }
        )

        convert = asyncio.run(
            try_run_agent_step(
                "knowledge_builder",
                "Convert/normalize the prior plugin tool output into KnowledgeItems.",
                deps=AgentRuntimeDeps(
                    settings={},
                    platform_db=db,
                    knowledge=knowledge,
                    prior_outputs=[{"output": fake_invoke_output, "step_key": "step-3", "agent_id": "tool_orchestrator"}],
                    step_title="Normalize returned articles into KnowledgeItems",
                ),
            )
        )
        self.assertIsNotNone(convert)
        assert convert is not None
        self.assertTrue(convert.ok)
        convert_payload = json.loads(convert.output)
        self.assertTrue(convert_payload.get("knowledge_items"))

        persist = asyncio.run(
            try_run_agent_step(
                "knowledge_builder",
                "Persist KnowledgeItems via the knowledge repository (DB insert + SQLite commit).",
                deps=AgentRuntimeDeps(
                    settings={},
                    platform_db=db,
                    knowledge=knowledge,
                    prior_outputs=[
                        {"output": fake_invoke_output, "step_key": "step-3", "agent_id": "tool_orchestrator"},
                        {"output": convert.output, "step_key": "step-4", "agent_id": "knowledge_builder"},
                    ],
                    step_title="Persist KnowledgeItems",
                ),
            )
        )
        self.assertIsNotNone(persist)
        assert persist is not None
        self.assertTrue(persist.ok)
        persist_payload = json.loads(persist.output)
        self.assertTrue(persist_payload.get("persisted"))
        self.assertTrue(all(row.get("verified") for row in persist_payload["persisted"]))


if __name__ == "__main__":
    unittest.main()
