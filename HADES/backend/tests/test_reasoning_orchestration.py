"""Behavior regressions for reasoning/orchestration defects A–G.

These tests assert runtime behavior with temporary DBs and controlled model/tool
responses. They must fail before the corresponding fixes land.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from reasoning import (
    ContextItem,
    assemble_context_messages,
    budget_context_items,
    build_request_spec,
    build_route_decision,
    parse_verification_result,
    verification_allows_success,
)
from reasoning.profiles import PROFILE_CONFIGS
from reasoning.verification import validate_evidence_refs


class FakeChatLm:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chat_calls = 0

    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        self.calls.append(payload)
        self.chat_calls += 1
        prompt = payload["messages"][-1]["content"] if payload.get("messages") else ""
        if "HADES Work Planner" in prompt:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "acceptance_criteria": ["Resultaat is concreet en gecontroleerd"],
                                    "steps": [
                                        {
                                            "agent_id": "executor",
                                            "kind": "work",
                                            "title": "Uitvoeren",
                                            "instruction": "Lever het gevraagde testresultaat.",
                                        }
                                    ],
                                }
                            ),
                        }
                    }
                ]
            }
        if "onafhankelijke HADES Verification/Critic" in prompt:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "passed": True,
                                    "issues": [],
                                    "final": "Geverifieerd chat-werkresultaat",
                                    "evidence_refs": ["step:1"],
                                    "incomplete": False,
                                }
                            ),
                        }
                    }
                ]
            }
        return {
            "choices": [
                {"message": {"role": "assistant", "content": f"Lokaal antwoord op: {prompt[:60]}"}}
            ]
        }


class ExhaustedToolLm(FakeChatLm):
    async def chat(self, payload):
        self.calls.append(payload)
        self.chat_calls += 1
        # Always request a tool — used to prove final round must not leak JSON.
        content = json.dumps(
            {
                "hades_tool_call": {
                    "plugin_id": "any",
                    "tool_name": "echo",
                    "input": {"args": ["x"]},
                }
            }
        )
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class FakeSuccessCriticLm(FakeChatLm):
    """Work planner + step model + critic that invents evidence after a failed tool."""

    def __init__(self, plugin_id: str) -> None:
        super().__init__()
        self.plugin_id = plugin_id
        self.phase = 0

    async def chat(self, payload):
        self.calls.append(payload)
        self.chat_calls += 1
        prompt = payload["messages"][-1]["content"] if payload.get("messages") else ""
        joined = "\n".join(item.get("content", "") for item in payload.get("messages", []))
        if "HADES Work Planner" in prompt or "HADES Work Planner" in joined:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "acceptance_criteria": [
                                        "De echo-tool moet succesvol draaien",
                                        "Evidence moet naar een echte toolcall wijzen",
                                    ],
                                    "steps": [
                                        {
                                            "agent_id": "executor",
                                            "kind": "work",
                                            "title": "Echo uitvoeren",
                                            "instruction": f"Gebruik plugin {self.plugin_id} tool echo verplicht.",
                                        }
                                    ],
                                }
                            ),
                        }
                    }
                ]
            }
        if "onafhankelijke HADES Verification/Critic" in prompt or "Verification/Critic" in joined:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "passed": True,
                                    "issues": [],
                                    "final": "Alles gelukt volgens model",
                                    "evidence_refs": ["tool:does-not-exist", "step:99"],
                                    "incomplete": False,
                                }
                            ),
                        }
                    }
                ]
            }
        # First work-step model call: choose the failing tool.
        if self.phase == 0:
            self.phase = 1
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "hades_tool_call": {
                                        "plugin_id": self.plugin_id,
                                        "tool_name": "echo",
                                        "input": {"args": ["must-fail"]},
                                    }
                                }
                            ),
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Tool faalde; ik claim toch succes zonder herstel.",
                    }
                }
            ]
        }


class ReasoningOrchestrationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "orch-test.db"))
        main.runner = main.TaskRunner()
        self.fake = FakeChatLm()
        self.client_patch = patch.object(main, "lm_client", return_value=self.fake)
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        main.ensure_platform_services()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def install_echo_plugin(self, plugin_id: str, exit_code: int = 0) -> dict:
        source = Path(self.temp_dir.name) / plugin_id
        source.mkdir(exist_ok=True)
        (source / "echo.py").write_text(
            f"import sys\nprint('ECHO ' + ' '.join(sys.argv[1:]))\nraise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        manifest = {
            "format": 1,
            "id": plugin_id,
            "name": f"Echo {plugin_id}",
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": ["subprocess"],
            "category": "Test",
            "labels": ["test", "echo"],
            "autonomous": True,
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo woorden",
                    "command": ["{python}", "echo.py", "{args}"],
                    "input_schema": {
                        "type": "object",
                        "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                    },
                }
            ],
        }
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = main.plugin_manager.import_local_folder(source, install_dependencies=False)["plugin"]
        return main.platform_db.set_plugin_state(plugin["id"], enabled=True) or main.platform_db.get_plugin(plugin["id"])

    def test_A_complex_chat_executes_work_or_verification_not_only_route_metadata(self) -> None:
        """A: work_runtime + require_verification must actually plan/verify, not one plain chat call."""
        complex_prompt = (
            "Implementeer een meerstaps migratieplan met architectuur, refactor en tests. "
            "Gebruik concrete stappen, afhankelijkheden en controleer het eindresultaat."
        )
        spec = build_request_spec(complex_prompt)
        route = build_route_decision(
            spec,
            requested_profile="high",
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(route.target, "work_runtime")
        self.assertTrue(route.require_verification)

        conversation = self.client.post("/api/conversations", json={"title": "Complex"}).json()
        # Force high profile for this request path via settings.
        self.client.put(
            "/api/settings",
            json={
                **self.client.get("/api/settings").json(),
                "reasoning_profile": "high",
                "plugin_autonomous_tools": True,
            },
        )
        response = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": complex_prompt},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["route"]["target"], "work_runtime")
        self.assertTrue(body["route"]["require_verification"])
        # Actual execution must reflect planner and/or verification, not a single direct chat completion.
        executed = body.get("executed_route") or body.get("execution") or {}
        self.assertTrue(
            executed.get("planner_called") or executed.get("verification_called") or executed.get("work_runtime_called"),
            msg=f"Route claimed work_runtime/verification but execution was direct-only: {body.keys()} {executed}",
        )
        self.assertGreaterEqual(
            self.fake.chat_calls,
            2,
            msg=f"Expected planner and/or critic beyond one model call; got {self.fake.chat_calls}",
        )

    def test_B_fake_evidence_refs_cannot_complete_after_required_tool_failure(self) -> None:
        """B: passed=true with invented evidence_refs must not complete after required tool failure."""
        plugin = self.install_echo_plugin("fail-evidence", exit_code=9)
        fake = FakeSuccessCriticLm(plugin["id"])
        with patch.object(main, "lm_client", return_value=fake):
            created = self.client.post(
                "/api/tasks",
                json={
                    "title": "Evidence gate",
                    "prompt": f"Gebruik verplicht de echo tool van {plugin['id']} en lever werkend bewijs.",
                    "agent": "executor",
                    "priority": "high",
                    "auto_start": True,
                },
            )
            self.assertEqual(created.status_code, 201)
            task_id = created.json()["id"]
            state = created.json()
            for _ in range(150):
                import time

                time.sleep(0.02)
                state = next(item for item in self.client.get("/api/tasks").json() if item["id"] == task_id)
                if state["status"] in {"completed", "failed", "cancelled"}:
                    break
        self.assertEqual(state["status"], "failed", state)
        self.assertNotEqual(state.get("result"), "Alles gelukt volgens model")
        error = (state.get("error") or "").lower()
        self.assertTrue(
            "bewijs" in error or "evidence" in error or "verification" in error or "tool" in error,
            msg=state.get("error"),
        )

    def test_C_repeated_identical_latest_user_message_is_present(self) -> None:
        """C: newest user turn must appear once even when identical text exists earlier."""
        history = [
            {"role": "user", "content": "Doe het opnieuw", "id": "m1"},
            {"role": "assistant", "content": "Klaar"},
            {"role": "user", "content": "Doe het opnieuw", "id": "m2"},
            {"role": "assistant", "content": "Nogmaals klaar"},
        ]
        # Caller removes the just-added latest message (id=m3) from history; assembler must append it.
        messages = assemble_context_messages(
            system_parts=["policy"],
            history=[{"role": item["role"], "content": item["content"]} for item in history],
            context_items=[],
            user_text="Doe het opnieuw",
            user_message_id="m3",
        )
        user_turns = [item for item in messages if item["role"] == "user"]
        self.assertGreaterEqual(len(user_turns), 3)
        self.assertEqual(user_turns[-1]["content"], "Doe het opnieuw")
        self.assertEqual(user_turns[-1].get("id"), "m3")

    def test_D_full_request_respects_fast_context_budget(self) -> None:
        """D: Fast profile budget must cover the full model request, not only retrieval."""
        from reasoning.context import assemble_budgeted_messages

        history = [{"role": "user", "content": "oud " * 4000}, {"role": "assistant", "content": "antwoord " * 4000}]
        context_items = [
            ContextItem("k1", "knowledge", "kennis " * 3000, "doc1", 40, False, True),
            ContextItem("k2", "knowledge", "meer " * 3000, "doc2", 50, False, True),
        ]
        max_chars = PROFILE_CONFIGS["fast"].context_chars
        messages, report = assemble_budgeted_messages(
            system_parts=["SYSTEEM " * 200],
            history=history,
            context_items=context_items,
            user_text="Nieuwe vraag " * 50,
            max_chars=max_chars,
            reserve_output_chars=1024,
        )
        total = sum(len(item.get("content", "")) for item in messages)
        self.assertLessEqual(total, max_chars)
        self.assertTrue(report.truncated or report.dropped_items >= 1 or report.used_chars <= max_chars)
        self.assertLessEqual(report.used_chars, max_chars)
        self.assertEqual(messages[-1]["role"], "user")

    def test_E_oversized_retrieval_keeps_useful_passages(self) -> None:
        """E: a huge merged retrieval block must not discard all useful passages."""
        items = [
            ContextItem("p1", "knowledge", "bruikbare passage alpha " * 20, "src:alpha", 10, False, True),
            ContextItem("p2", "knowledge", "x" * 50_000, "src:huge", 90, False, True),
            ContextItem("p3", "knowledge", "bruikbare passage beta " * 20, "src:beta", 20, False, True),
        ]
        kept, report = budget_context_items(items, max_chars=2500)
        kept_ids = {item.item_id for item in kept}
        self.assertIn("p1", kept_ids)
        self.assertTrue("p3" in kept_ids or any("beta" in item.content for item in kept))
        self.assertTrue(report.dropped_items >= 1 or report.truncated)

    def test_F_exhausted_tool_budget_does_not_return_tool_json(self) -> None:
        """F: when tool rounds are exhausted, final content must not be a hades_tool_call JSON."""
        plugin = self.install_echo_plugin("budget-echo")
        conversation = self.client.post("/api/conversations", json={"title": "Budget"}).json()
        self.client.put(
            "/api/settings",
            json={
                **self.client.get("/api/settings").json(),
                "max_tool_rounds": 1,
                "plugin_autonomous_tools": True,
                "reasoning_profile": "standard",
            },
        )
        fake = ExhaustedToolLm()
        with patch.object(main, "lm_client", return_value=fake):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": f"Gebruik {plugin['id']} echo tool herhaaldelijk"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        content = response.json()["assistant_message"]["content"]
        self.assertNotIn("hades_tool_call", content)
        self.assertFalse(content.strip().startswith("{"))

    def test_G_profile_and_global_budgets_are_enforced(self) -> None:
        """G: max_model_calls / max_replans must be enforced; profiles cannot raise global tool caps via max()."""
        from reasoning.budgets import ExecutionBudget, resolve_tool_round_budget

        # Hard global cap must win; profile must not raise it.
        rounds = resolve_tool_round_budget(
            settings_max_tool_rounds=2,
            profile_max_tool_rounds=8,
            route_max_tool_rounds=8,
            tools_allowed=True,
        )
        self.assertEqual(rounds, 2)

        rounds_off = resolve_tool_round_budget(
            settings_max_tool_rounds=5,
            profile_max_tool_rounds=8,
            route_max_tool_rounds=0,
            tools_allowed=False,
        )
        self.assertEqual(rounds_off, 0)

        budget = ExecutionBudget(
            max_model_calls=3,
            max_tool_rounds=2,
            max_replans=1,
            max_repair_attempts=2,
        )
        budget.record_model_call()
        budget.record_model_call()
        budget.record_model_call()
        self.assertFalse(budget.can_model_call())
        budget.record_replan()
        self.assertFalse(budget.can_replan())

    def test_simple_chat_skips_planner_and_critic(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "Simple"}).json()
        self.client.put(
            "/api/settings",
            json={**self.client.get("/api/settings").json(), "reasoning_profile": "fast"},
        )
        response = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Hoi, hoe gaat het?"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["route"]["target"], "direct_chat")
        self.assertFalse(body["route"]["require_verification"])
        executed = body.get("executed_route") or body.get("execution") or {}
        self.assertFalse(executed.get("planner_called", False))
        self.assertFalse(executed.get("verification_called", False))
        self.assertEqual(self.fake.chat_calls, 1)

    def test_cancel_running_work_does_not_commit_late_success(self) -> None:
        """Annulering mag geen late completed-commit veroorzaken."""
        plugin = self.install_echo_plugin("cancel-echo")

        class SlowThenSuccessLm(FakeChatLm):
            def __init__(self) -> None:
                super().__init__()
                self.gate = 0

            async def chat(self, payload):
                self.calls.append(payload)
                self.chat_calls += 1
                prompt = payload["messages"][-1]["content"] if payload.get("messages") else ""
                if "HADES Work Planner" in prompt:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(
                                        {
                                            "acceptance_criteria": ["Echo werkt"],
                                            "steps": [
                                                {
                                                    "agent_id": "executor",
                                                    "kind": "work",
                                                    "title": "Echo",
                                                    "instruction": f"Gebruik {plugin['id']} echo",
                                                }
                                            ],
                                        }
                                    ),
                                }
                            }
                        ]
                    }
                # Block briefly so cancel can land while running.
                import asyncio

                self.gate += 1
                await asyncio.sleep(0.15)
                if "Verification/Critic" in prompt:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(
                                        {
                                            "passed": True,
                                            "issues": [],
                                            "final": "Laat succes",
                                            "evidence_refs": ["step:1"],
                                            "incomplete": False,
                                        }
                                    ),
                                }
                            }
                        ]
                    }
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "hades_tool_call": {
                                            "plugin_id": plugin["id"],
                                            "tool_name": "echo",
                                            "input": {"args": ["slow"]},
                                        }
                                    }
                                ),
                            }
                        }
                    ]
                }

        fake = SlowThenSuccessLm()
        with patch.object(main, "lm_client", return_value=fake):
            created = self.client.post(
                "/api/tasks",
                json={
                    "title": "Cancel test",
                    "prompt": f"Gebruik {plugin['id']} echo en rond af",
                    "agent": "executor",
                    "priority": "high",
                    "auto_start": True,
                },
            )
            self.assertEqual(created.status_code, 201)
            task_id = created.json()["id"]
            import time

            for _ in range(50):
                time.sleep(0.02)
                state = main.database.get_task(task_id)
                if state and state["status"] == "running":
                    break
            cancelled = self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(cancelled.status_code, 200)
            for _ in range(100):
                time.sleep(0.02)
                # Poll via DB to avoid TestClient re-entrancy while the worker still finishes I/O.
                state = main.database.get_task(task_id)
                if state and state["status"] in {"cancelled", "failed", "completed"}:
                    break
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "cancelled")
        self.assertNotEqual(state.get("result"), "Laat succes")

    def test_max_tool_rounds_zero_disables_tools_even_on_high(self) -> None:
        plugin = self.install_echo_plugin("no-tools-echo")
        conversation = self.client.post("/api/conversations", json={"title": "No tools"}).json()
        self.client.put(
            "/api/settings",
            json={
                **self.client.get("/api/settings").json(),
                "max_tool_rounds": 0,
                "reasoning_profile": "maximum",
                "plugin_autonomous_tools": True,
            },
        )
        with patch.object(main, "lm_client", return_value=ExhaustedToolLm()):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": f"Gebruik {plugin['id']} echo tool verplicht"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tools"], [])
        self.assertNotIn("hades_tool_call", response.json()["assistant_message"]["content"])

    def test_validate_evidence_refs_rejects_unknown(self) -> None:
        ok, reason = validate_evidence_refs(
            ["tool:missing", "step:1"],
            step_outputs=[{"title": "A", "agent_id": "executor", "output": "ok"}],
            tool_observations=[{"call_id": "tc-1", "status": "failed", "plugin_id": "p", "tool_name": "echo"}],
        )
        self.assertFalse(ok)
        self.assertTrue(reason)

        ok2, _ = validate_evidence_refs(
            ["step:1", "tool:tc-1"],
            step_outputs=[{"title": "A", "agent_id": "executor", "output": "ok"}],
            tool_observations=[{"call_id": "tc-1", "status": "completed", "plugin_id": "p", "tool_name": "echo"}],
        )
        self.assertTrue(ok2)

        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"ok","evidence_refs":["tool:ghost"],"incomplete":false}'
        )
        allowed, why = verification_allows_success(
            parsed,
            tool_observations=[{"call_id": "tc-1", "status": "failed", "plugin_id": "p", "tool_name": "echo"}],
            step_outputs=[{"title": "A", "agent_id": "executor", "output": "x"}],
            require_final=True,
        )
        self.assertFalse(allowed)
        self.assertTrue(why)


if __name__ == "__main__":
    unittest.main()
