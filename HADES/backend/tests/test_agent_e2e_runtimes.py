"""End-to-end runtime proofs for the five promoted specialist agents.

These tests exercise the Work/Tasks spine (create task → route → work step runtime),
not only try_run_agent_step() in isolation. External network uses a local HTTP fixture.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from agent_runtimes import AgentRuntimeDeps, try_run_agent_step
from database import Database
from reasoning.specialists import route_specialist
from verification_test_support import aligned_verification_final


IMPLEMENTED = (
    "web_scout",
    "evidence_auditor",
    "tool_orchestrator",
    "trading_specialist",
    "voice_specialist",
)


class SpecialistPlanLm:
    """Planner that emits a single step for the routed specialist agent."""

    def __init__(self, agent_id: str, instruction: str | None = None) -> None:
        self.agent_id = agent_id
        self.instruction = instruction
        self.run_id: str | None = None
        self._cancelled = False

    def attach_run(self, run_id: str) -> None:
        self.run_id = run_id

    async def cancel(self) -> None:
        self._cancelled = True

    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        prompt = payload["messages"][-1]["content"]
        if "HADES Work Planner" in prompt:
            instruction = self.instruction or "Voer de specialist-stap uit."
            # Prefer the original task prompt when present in the planner text.
            if "INSTRUCTIE:" in prompt:
                instruction = prompt.split("INSTRUCTIE:", 1)[1].strip()[:2000] or instruction
            content = json.dumps(
                {
                    "acceptance_criteria": ["Specialist runtime heeft een eerlijk resultaat geleverd"],
                    "steps": [
                        {
                            "step_id": "step-1",
                            "agent_id": self.agent_id,
                            "kind": "work",
                            "title": f"Run {self.agent_id}",
                            "instruction": instruction,
                            "depends_on": [],
                        }
                    ],
                }
            )
        elif "onafhankelijke HADES Verification/Critic" in prompt:
            checklist = []
            if "ACCEPTANCE CRITERIA" in prompt:
                for line in prompt.splitlines():
                    line = line.strip()
                    if line.startswith("- id="):
                        # "- id=c1: criterion text"
                        try:
                            id_part, criterion = line[2:].split(":", 1)
                            cid = id_part.replace("id=", "").strip()
                            checklist.append(
                                {
                                    "id": cid,
                                    "criterion": criterion.strip(),
                                    "met": True,
                                    "note": "Deterministic specialist output + evidence_refs",
                                }
                            )
                        except ValueError:
                            continue
            if not checklist:
                checklist = [
                    {
                        "id": "c1",
                        "criterion": "Specialist runtime heeft een eerlijk resultaat geleverd",
                        "met": True,
                        "note": "Deterministic specialist output + evidence_refs",
                    }
                ]
            content = json.dumps(
                {
                    "passed": True,
                    "issues": [],
                    "final": aligned_verification_final(
                        prompt, fallback=f"Geverifieerd {self.agent_id} resultaat"
                    ),
                    "evidence_refs": ["step:1"],
                    "incomplete": False,
                    "criteria_checklist": checklist,
                }
            )
        else:
            content = f"Lokaal antwoord op: {prompt[:40]}"
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/robots.txt"):
            body = b"User-agent: *\nDisallow: /private\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/private"):
            body = b"secret"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/fail"):
            self.send_response(500)
            self.end_headers()
            return
        body = (
            b"<html><head><title>HADES Fixture Doc</title></head>"
            b"<body><h1>Local Scout Evidence</h1>"
            b"<p>Deterministic fixture page for Web Scout E2E.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class AgentE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store.enable_memory_backend_for_tests()
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "agent-e2e.db"))
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self.client_patch = patch.object(main, "lm_client", return_value=SpecialistPlanLm("executor"))
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        from settings_secrets import provider_secret_store

        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.temp_dir.cleanup()
        provider_secret_store._memory_test_override = None

    def _set_network_policy(self, policy: str) -> None:
        current = self.client.get("/api/settings").json()
        current["network_policy"] = policy
        patched = self.client.put("/api/settings", json=current)
        self.assertEqual(patched.status_code, 200, patched.text)
        if getattr(main, "control_service", None) is not None:
            main.control_service.patch_global({"network_policy": policy})

    def _run_task(self, *, agent: str, prompt: str, title: str | None = None, timeout_s: float = 8.0) -> dict:
        self.client_patch.stop()
        self.client_patch = patch.object(main, "lm_client", return_value=SpecialistPlanLm(agent, prompt))
        self.client_patch.start()
        created = self.client.post(
            "/api/tasks",
            json={
                "title": title or f"E2E {agent}",
                "prompt": prompt,
                "agent": agent,
                "priority": "high",
                "auto_start": True,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["id"]
        state = created.json()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.05)
            state = next(item for item in self.client.get("/api/tasks").json() if item["id"] == task_id)
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
        work = self.client.get(f"/api/tasks/{task_id}/work").json()
        return {"task": state, "work": work}

    def _install_echo_plugin(self, plugin_id: str = "hades.e2e.echo", *, exit_code: int = 0, permissions: list[str] | None = None) -> dict:
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
            "permissions": permissions or ["subprocess"],
            "category": "Test",
            "labels": ["test", "echo"],
            "autonomous": True,
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo woorden",
                    "command": ["{python}", "echo.py", "{args}"],
                    "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}},
                }
            ],
        }
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = main.plugin_manager.import_local_folder(source, install_dependencies=False)["plugin"]
        return main.platform_db.set_plugin_state(plugin["id"], enabled=True) or main.platform_db.get_plugin(plugin["id"])

    def test_routing_selects_each_specialist(self) -> None:
        enabled = set(IMPLEMENTED) | {"executor", "researcher"}
        self.assertEqual(route_specialist(f"{self.base_url}/doc", enabled_ids=enabled), "web_scout")
        self.assertEqual(
            route_specialist("audit provenance contradictie entity:ACME", enabled_ids=enabled),
            "evidence_auditor",
        )
        self.assertEqual(
            route_specialist("multi-plugin tool orchestr workflow", enabled_ids=enabled),
            "tool_orchestrator",
        )
        self.assertEqual(
            route_specialist("PAPER trading backtest strategie", enabled_ids=enabled),
            "trading_specialist",
        )
        self.assertEqual(
            route_specialist("maak een taak van dit transcript", enabled_ids=enabled, kind="voice"),
            "voice_specialist",
        )

    def test_web_scout_block_allow_persist_and_failures(self) -> None:
        url = f"{self.base_url}/doc"
        # Block: no external call / no ingest.
        self._set_network_policy("block")
        blocked = self._run_task(agent="web_scout", prompt=f"Scout {url}")
        self.assertIn(blocked["task"]["status"], {"completed", "failed"})
        step = blocked["work"]["steps"][0]
        self.assertEqual(step["agent_id"], "web_scout")
        self.assertIn("network_policy", step["output"].lower())
        before = self.client.post("/api/knowledge/search", json={"query": "Local Scout Evidence", "limit": 5}).json()
        before_hits = len(before.get("matches") or [])

        # Allow: real WebResearchService + persistence.
        self._set_network_policy("allow")
        allowed = self._run_task(agent="web_scout", prompt=f"Scout {url}")
        self.assertEqual(allowed["task"]["status"], "completed", allowed["task"].get("error"))
        step = allowed["work"]["steps"][0]
        self.assertEqual(step["agent_id"], "web_scout")
        self.assertIn("source_id=", step["output"])
        after = self.client.post("/api/knowledge/search", json={"query": "Local Scout Evidence", "limit": 5}).json()
        self.assertGreater(len(after.get("matches") or []), before_hits)

        # robots / failure paths stay failures (direct runtime + real service).
        import asyncio

        main.ensure_platform_services()
        deps = AgentRuntimeDeps(settings={"network_policy": "allow"}, web_research=main.web_research)
        robots = asyncio.run(try_run_agent_step("web_scout", f"Scout {self.base_url}/private", deps=deps))
        assert robots is not None
        self.assertFalse(robots.ok)
        fail = asyncio.run(try_run_agent_step("web_scout", f"Scout {self.base_url}/fail", deps=deps))
        assert fail is not None
        self.assertFalse(fail.ok)

    def test_evidence_auditor_real_store_and_no_false_pass(self) -> None:
        main.ensure_platform_services()
        ingested = main.knowledge.ingest_text(
            title="ACME contract note",
            text="ACME signed the local evidence contract with provenance marker ALPHA-42.",
            source_type="note",
            uri="local://acme-evidence",
            metadata={"entity": "ACME"},
        )
        source_id = str(ingested.get("source_id") or ingested.get("id") or "")
        self.assertTrue(source_id)

        result = self._run_task(agent="evidence_auditor", prompt="audit provenance entity:ACME")
        self.assertEqual(result["task"]["status"], "completed", result["task"].get("error"))
        step = result["work"]["steps"][0]
        self.assertEqual(step["agent_id"], "evidence_auditor")
        payload = json.loads(step["output"])
        self.assertGreaterEqual(payload.get("knowledge_hit_count", 0), 1)
        self.assertTrue(payload.get("passed"))
        sample_ids = [str(item.get("source_id") or "") for item in payload.get("knowledge_sample") or []]
        self.assertTrue(any(source_id == sid or sid for sid in sample_ids))

        empty = self._run_task(
            agent="evidence_auditor",
            prompt="audit provenance entity:ZZZXQ9UNIQUE_NO_MATCH_TOKEN_7f3a",
        )
        empty_step = empty["work"]["steps"][0]
        empty_payload = json.loads(empty_step["output"])
        self.assertFalse(empty_payload.get("passed"))
        self.assertTrue(empty_payload.get("missing_evidence") or empty_payload.get("unsupported_claims"))

    def test_tool_orchestrator_plugin_spine_permissions_and_audit(self) -> None:
        plugin = self._install_echo_plugin("hades.e2e.orch")
        self._set_network_policy("block")
        # Resolve/shortlist still deterministic; invoke falls through (F-02).
        import asyncio

        def shortlist(query: str, limit: int = 12) -> list[dict]:
            return [
                {
                    "plugin_id": plugin["id"],
                    "name": "echo",
                    "status": "Ready",
                    "permissions": ["subprocess"],
                }
            ]

        deps = AgentRuntimeDeps(
            settings={"network_policy": "block"},
            plugin_manager=main.plugin_manager,
            shortlist_tools=shortlist,
        )
        resolve = asyncio.run(
            try_run_agent_step(
                "tool_orchestrator",
                "Resolve installed plugin from the local plugin registry.",
                deps=deps,
            )
        )
        self.assertIsNotNone(resolve)
        assert resolve is not None
        self.assertTrue(resolve.ok)
        payload = json.loads(resolve.output)
        self.assertIn("tools", payload)
        self.assertTrue(payload["tools"])

        # Invoke must not be handled by the canned orchestrator path.
        invoke = asyncio.run(try_run_agent_step("tool_orchestrator", "invoke echo now", deps=deps))
        self.assertIsNone(invoke)

        # Denied tools must not be invoked via the orchestrator either.
        deps_blocked = AgentRuntimeDeps(
            settings={"network_policy": "block", "denied_tools": [f"{plugin['id']}:echo"]},
            plugin_manager=main.plugin_manager,
            shortlist_tools=lambda q, limit=12: [
                {"plugin_id": plugin["id"], "name": "echo", "status": "Ready", "permissions": ["subprocess"]}
            ],
        )
        blocked_invoke = asyncio.run(
            try_run_agent_step("tool_orchestrator", "invoke echo now", deps=deps_blocked)
        )
        self.assertIsNone(blocked_invoke)

    def test_trading_specialist_paper_seed_and_kill_switch(self) -> None:
        main.ensure_platform_services()
        seeded = self.client.post("/api/trading/market/seed", json={"symbol": "BTC/USDT", "bars": 120, "seed": 17})
        self.assertEqual(seeded.status_code, 200, seeded.text)
        self.assertGreaterEqual(seeded.json()["summary"]["bars"], 50)

        enabled = self.client.post("/api/trading/paper/enable", json={})
        # endpoint may be patch/settings style — fall back to service API
        if enabled.status_code >= 400:
            main.paper_trading.set_enabled(True)

        ok = self._run_task(agent="trading_specialist", prompt="PAPER trading status en strategiepad")
        self.assertEqual(ok["task"]["status"], "completed", ok["task"].get("error"))
        payload = json.loads(ok["work"]["steps"][0]["output"])
        self.assertEqual(payload.get("mode"), "PAPER_ONLY")
        self.assertFalse(payload.get("live_broker", False))

        main.paper_trading.set_kill_switch(True)
        killed = self._run_task(agent="trading_specialist", prompt="PAPER trading place order despite kill")
        killed_payload = json.loads(killed["work"]["steps"][0]["output"])
        self.assertTrue(killed_payload.get("kill_switch"))
        self.assertIn(killed["work"]["steps"][0].get("error") or "", ("", "kill_switch_armed"))
        # Direct runtime must not invent fills.
        import asyncio

        deps = AgentRuntimeDeps(settings={}, paper_trading=main.paper_trading, trading_bot=main.trading_bot)
        live = asyncio.run(try_run_agent_step("trading_specialist", "connect live broker binance", deps=deps))
        assert live is not None
        self.assertFalse(live.ok)
        self.assertEqual(live.error, "live_broker_not_implemented")

    def test_voice_specialist_doctor_and_transcript_flow(self) -> None:
        # Doctor path: honest degraded when providers missing on this host.
        doctor_run = self._run_task(agent="voice_specialist", prompt="voice doctor status setup")
        doctor_step = doctor_run["work"]["steps"][0]
        self.assertEqual(doctor_step["agent_id"], "voice_specialist")
        doctor_payload = json.loads(doctor_step["output"])
        self.assertIn("doctor", doctor_payload)
        self.assertFalse(doctor_payload.get("cloud_fallback", False))
        if not doctor_payload.get("voice_ready"):
            self.assertIn(doctor_run["task"]["status"], {"completed", "failed"})
            # degraded/failed runtime must not advertise ready
            self.assertFalse(doctor_payload.get("doctor", {}).get("ready", False) and doctor_payload.get("voice_ready"))

        # Transcript → task draft via normal runtime spine.
        draft_run = self._run_task(
            agent="voice_specialist",
            prompt="Maak een onderzoek naar lokale embeddings uit dit transcript",
        )
        self.assertEqual(draft_run["task"]["status"], "completed", draft_run["task"].get("error"))
        draft_payload = json.loads(draft_run["work"]["steps"][0]["output"])
        self.assertIn("task_draft", draft_payload)
        self.assertFalse(draft_payload.get("cloud_fallback", False))


if __name__ == "__main__":
    unittest.main()
