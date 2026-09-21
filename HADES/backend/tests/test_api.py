import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from verification_test_support import aligned_verification_final


class FakeLmStudio:
    def __init__(self) -> None:
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
            content = '{"acceptance_criteria":["Resultaat is concreet en gecontroleerd"],"steps":[{"agent_id":"executor","kind":"work","title":"Uitvoeren","instruction":"Lever het gevraagde testresultaat."}]}'
        elif "onafhankelijke HADES Verification/Critic" in prompt:
            checklist = []
            if "ACCEPTANCE CRITERIA" in prompt:
                for line in prompt.splitlines():
                    line = line.strip()
                    if line.startswith("- id="):
                        try:
                            id_part, criterion = line[2:].split(":", 1)
                            cid = id_part.replace("id=", "").strip()
                            checklist.append(
                                {
                                    "id": cid,
                                    "criterion": criterion.strip(),
                                    "met": True,
                                    "note": "Step output + evidence aanwezig",
                                }
                            )
                        except ValueError:
                            continue
            if not checklist:
                checklist = [
                    {
                        "id": "c1",
                        "criterion": "Resultaat is concreet en gecontroleerd",
                        "met": True,
                        "note": "Step output + evidence aanwezig",
                    }
                ]
            # Multi-step plans need evidence_refs for each completed step mentioned.
            refs = ["step:1"]
            for i in range(2, 8):
                if f"=== {i}." in prompt:
                    refs.append(f"step:{i}")
            content = json.dumps(
                {
                    "passed": True,
                    "issues": [],
                    "final": aligned_verification_final(
                        prompt, fallback="Geverifieerd lokaal werkresultaat"
                    ),
                    "evidence_refs": refs,
                    "incomplete": False,
                    "criteria_checklist": checklist,
                }
            )
        else:
            content = f"Lokaal antwoord op: {prompt[:40]}"
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ToolChoosingLmStudio(FakeLmStudio):
    def __init__(self, plugin_id: str) -> None:
        super().__init__()
        self.plugin_id = plugin_id
        self.calls = 0
        self.last_prompt = ""

    async def chat(self, payload):
        self.calls += 1
        if self.calls == 1:
            content = json.dumps({"hades_tool_call": {"plugin_id": self.plugin_id, "tool_name": "echo", "input": {"args": ["autonomous"]}}})
        else:
            self.last_prompt = payload["messages"][-1]["content"]
            content = "De plugin leverde een gecontroleerd autonoom resultaat."
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

class InvalidToolChoosingLmStudio(FakeLmStudio):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def chat(self, payload):
        self.calls += 1
        content = json.dumps({"hades_tool_call": {"plugin_id": "invented", "tool_name": "invented", "input": {}}}) if self.calls == 1 else "Geen toegestane tool uitgevoerd."
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

class TwoToolChoosingLmStudio(ToolChoosingLmStudio):
    async def chat(self, payload):
        self.calls += 1
        if self.calls <= 2:
            content = json.dumps({"hades_tool_call": {"plugin_id": self.plugin_id, "tool_name": "echo", "input": {"args": [f"round-{self.calls}"]}}})
        else:
            self.last_prompt = payload["messages"][-1]["content"]
            content = "Twee gecontroleerde toolcalls zijn uitgevoerd."
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from settings_secrets import provider_secret_store

        provider_secret_store.enable_memory_backend_for_tests()
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        main.database = Database(str(Path(self.temp_dir.name) / "api-test.db"))
        main.runner = main.TaskRunner()
        self.client_patch = patch.object(main, "lm_client", return_value=FakeLmStudio())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        from settings_secrets import provider_secret_store

        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()
        provider_secret_store._memory_test_override = None

    def install_echo_plugin(self, plugin_id: str, permissions: list[str] | None = None, exit_code: int = 0) -> dict:
        source = Path(self.temp_dir.name) / plugin_id
        source.mkdir()
        (source / "echo.py").write_text(f"import sys\nprint('ECHO ' + ' '.join(sys.argv[1:]))\nraise SystemExit({exit_code})\n", encoding="utf-8")
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
            "tools": [{"name": "echo", "description": "Echo woorden", "command": ["{python}", "echo.py", "{args}"], "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}}}],
        }
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugin = main.plugin_manager.import_local_folder(source, install_dependencies=False)["plugin"]
        return main.platform_db.set_plugin_state(plugin["id"], enabled=True) or main.platform_db.get_plugin(plugin["id"])

    def test_health_models_and_chat_flow(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["lm_studio"], "connected")

        conversation = self.client.post("/api/conversations", json={"title": "Test"}).json()
        answer = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Geef een testantwoord"},
        )
        self.assertEqual(answer.status_code, 200)
        self.assertIn("Lokaal antwoord", answer.json()["assistant_message"]["content"])
        knowledge = self.client.post("/api/knowledge/search", json={"query": "Geef een testantwoord", "limit": 5})
        self.assertEqual(knowledge.status_code, 200)
        self.assertTrue(any(item["source_type"] == "conversation" for item in knowledge.json()["matches"]))


    def test_chat_metadata_patch_is_persistent(self) -> None:
        conversation = self.client.post("/api/conversations", json={"title": "Test"}).json()
        patched = self.client.patch(
            f"/api/conversations/{conversation['id']}",
            json={"title": "Nieuwe naam", "system_prompt_override": "Alleen deze chat", "update_system_prompt": True},
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["title"], "Nieuwe naam")
        self.assertEqual(patched.json()["system_prompt_override"], "Alleen deze chat")
        listed = self.client.get("/api/conversations").json()
        item = next(row for row in listed if row["id"] == conversation["id"])
        self.assertEqual(item["system_prompt_override"], "Alleen deze chat")

    def test_conversation_patch_cors_preflight_allows_browser_update(self) -> None:
        """Browsers preflight PATCH; missing Allow-Methods looks like 'backend unreachable'."""
        conversation = self.client.post("/api/conversations", json={"title": "CORS"}).json()
        origin = "http://127.0.0.1:3000"
        preflight = self.client.options(
            f"/api/conversations/{conversation['id']}",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertIn(preflight.status_code, {200, 204})
        allowed = preflight.headers.get("access-control-allow-methods", "")
        self.assertIn("PATCH", allowed.upper())
        self.assertEqual(preflight.headers.get("access-control-allow-origin"), origin)

    def test_persistent_work_runtime_plans_executes_and_verifies(self) -> None:
        created = self.client.post(
            "/api/tasks",
            json={"title": "Work test", "prompt": "Voer deze controleerbare testtaak uit", "agent": "executor", "priority": "high", "auto_start": True},
        )
        self.assertEqual(created.status_code, 201)
        task_id = created.json()["id"]
        state = created.json()
        for _ in range(100):
            time.sleep(0.02)
            state = next(item for item in self.client.get("/api/tasks").json() if item["id"] == task_id)
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
        self.assertEqual(state["status"], "completed", state.get("error"))
        self.assertTrue(str(state.get("result") or "").strip())
        self.assertIn("Lokaal antwoord", str(state.get("result") or ""))
        work = self.client.get(f"/api/tasks/{task_id}/work")
        self.assertEqual(work.status_code, 200)
        self.assertEqual(len(work.json()["steps"]), 1)
        self.assertEqual(work.json()["steps"][0]["status"], "completed")
        self.assertEqual(work.json()["checkpoint"]["state"]["phase"], "verified")

    def test_work_tasks_http_family_contract(self) -> None:
        """Characterization pin for tasks/work/runs HTTP family (Wave 2 extract)."""
        listed = self.client.get("/api/tasks")
        self.assertEqual(listed.status_code, 200)
        self.assertIsInstance(listed.json(), list)

        missing_work = self.client.get("/api/tasks/does-not-exist/work")
        self.assertEqual(missing_work.status_code, 404)
        missing_events = self.client.get("/api/tasks/does-not-exist/events")
        self.assertEqual(missing_events.status_code, 404)

        created = self.client.post(
            "/api/tasks",
            json={"title": "Contract pin", "prompt": "Pin extract", "agent": "chat", "auto_start": False},
        )
        self.assertEqual(created.status_code, 201, created.text)
        task = created.json()
        self.assertEqual(task["status"], "queued")
        task_id = task["id"]

        events = self.client.get(f"/api/tasks/{task_id}/events")
        self.assertEqual(events.status_code, 200)
        self.assertIsInstance(events.json(), list)

        work = self.client.get(f"/api/tasks/{task_id}/work")
        self.assertEqual(work.status_code, 200)
        self.assertIn("steps", work.json())

        started = self.client.post(f"/api/tasks/{task_id}/run")
        self.assertEqual(started.status_code, 200, started.text)

        created2 = self.client.post(
            "/api/tasks",
            json={"title": "Cancel pin", "prompt": "Cancel me", "agent": "chat", "auto_start": False},
        )
        self.assertEqual(created2.status_code, 201, created2.text)
        tid2 = created2.json()["id"]
        cancelled = self.client.post(f"/api/tasks/{tid2}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")

        specialists = self.client.get("/api/specialists")
        self.assertEqual(specialists.status_code, 200)
        self.assertIn("items", specialists.json())

        run_events = self.client.get(f"/api/runs/{task_id}/events")
        self.assertEqual(run_events.status_code, 200)
        run_body = run_events.json()
        self.assertEqual(run_body["run_id"], task_id)
        self.assertIn("events", run_body)
        self.assertIn("latest_sequence", run_body)

        cancel_run = self.client.post(f"/api/runs/{task_id}/cancel")
        self.assertEqual(cancel_run.status_code, 200)

        inspection = self.client.get(f"/api/runs/{task_id}/inspection")
        self.assertEqual(inspection.status_code, 200)
        self.assertEqual(inspection.json().get("kind"), "task")

        missing_run = self.client.get("/api/runs/no-such-run/inspection")
        self.assertEqual(missing_run.status_code, 404)

        control = self.client.post(f"/api/tasks/{task_id}/control", json={"action": "status"})
        self.assertEqual(control.status_code, 200, control.text)
        self.assertIn("task", control.json())

    def test_local_document_research_runs_and_persists_evidence(self) -> None:
        source = Path(self.temp_dir.name) / "research.md"
        source.write_text("# HADES Research\nSpecialistische agents delen context en gebruiken persistente lokale kennis.", encoding="utf-8")
        created = self.client.post(
            "/api/research",
            json={
                "topic": "HADES specialistische agents",
                "depth": "standard",
                "allow_web": False,
                "sources": [str(source)],
                "auto_start": True,
                "approved_network": False,
                "approved_file_read": True,
                "authorized_downloads": False,
            },
        )
        self.assertEqual(created.status_code, 201)
        project_id = created.json()["id"]
        detail = None
        for _ in range(100):
            time.sleep(0.02)
            detail = self.client.get(f"/api/research/{project_id}").json()
            if detail["project"]["status"] in {"completed", "failed", "needs_more_evidence"}:
                break
        self.assertEqual(detail["project"]["status"], "completed", detail["project"].get("error"))
        self.assertTrue(detail["sources"])
        self.assertIn("Lokaal antwoord", detail["project"]["report"])

    def test_memory_and_brain_flow(self) -> None:
        created = self.client.post(
            "/api/memories",
            json={"title": "API-geheugen", "content": "Testinhoud", "collection": "Tests", "tags": ["api"]},
        )
        self.assertEqual(created.status_code, 201)
        results = self.client.get("/api/memories", params={"q": "API-geheugen"}).json()
        self.assertEqual(len(results["items"]), 1)
        brain = self.client.get("/api/brain").json()
        self.assertTrue(any(node["label"] == "API-geheugen" for node in brain["nodes"]))
        memory_node = next(node for node in brain["nodes"] if node["label"] == "API-geheugen")
        created_node = self.client.post(
            "/api/brain/nodes",
            json={"label": "Gekoppelde notitie", "kind": "note", "description": "test", "tags": [], "connect_to": memory_node["id"]},
        ).json()
        brain_after = self.client.get("/api/brain").json()
        self.assertTrue(any(link["source_id"] == created_node["id"] and link["target_id"] == memory_node["id"] for link in brain_after["links"]))

    def test_manual_plugin_invoke_returns_and_persists_structured_result(self) -> None:
        plugin = self.install_echo_plugin("manual-echo")
        response = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["manual"]}, "timeout_seconds": 10, "approved_by_user": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertIn("ECHO manual", result["stdout"])
        self.assertEqual(result["stderr"], "")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNotNone(result["duration_ms"])
        self.assertEqual(result["invocation_type"], "manual")
        self.assertTrue(result["approved_by_user"])
        calls = self.client.get(f"/api/plugins/{plugin['id']}/tool-calls").json()
        self.assertEqual(calls[0]["id"], result["id"])

    def test_bot_autonomously_invokes_enabled_plugin_and_receives_result(self) -> None:
        plugin = self.install_echo_plugin("autonomous-echo")
        conversation = self.client.post("/api/conversations", json={"title": "Tooltest"}).json()
        with patch.object(main, "lm_client", return_value=ToolChoosingLmStudio(plugin["id"])):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "Gebruik autonomous-echo om dit te echoën"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["tools"][0]["status"], "completed")
        self.assertIn("gecontroleerd autonoom resultaat", body["assistant_message"]["content"])
        call = main.platform_db.tool_calls(plugin["id"])[0]
        self.assertEqual(call["invocation_type"], "autonomous")
        self.assertFalse(call["approved_by_user"])

    def test_failed_autonomous_tool_result_is_returned_to_bot(self) -> None:
        plugin = self.install_echo_plugin("failing-echo", exit_code=7)
        conversation = self.client.post("/api/conversations", json={"title": "Toolfout"}).json()
        fake = ToolChoosingLmStudio(plugin["id"])
        with patch.object(main, "lm_client", return_value=fake):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "Gebruik failing-echo en rapporteer de uitkomst"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tools"][0]["status"], "failed")
        self.assertIn('"status": "failed"', fake.last_prompt)
        self.assertIn('"exit_code": 7', fake.last_prompt)
        call = main.platform_db.tool_calls(plugin["id"])[0]
        self.assertEqual(call["exit_code"], 7)
        self.assertIn("ECHO autonomous", call["stdout"])

    def test_global_block_permission_blocks_even_approved_manual_run(self) -> None:
        plugin = self.install_echo_plugin("blocked-echo", ["subprocess", "network"])
        main.database.update_settings({"network_policy": "block"})
        response = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["blocked"]}, "approved_by_user": True},
        )
        self.assertEqual(response.status_code, 403, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["tool_call"]["status"], "blocked")
        self.assertTrue(detail["tool_call"]["approved_by_user"])
        self.assertNotIn("ECHO blocked", detail["tool_call"]["stdout"])

    def test_autonomous_registry_excludes_tools_requiring_unapproved_policy(self) -> None:
        plugin = self.install_echo_plugin("ask-network-echo", ["subprocess", "network"])
        main.database.update_settings({"network_policy": "ask"})
        tools = main.shortlist_plugin_tools("Gebruik ask-network-echo om iets te echoën")
        self.assertFalse(any(item["plugin_id"] == plugin["id"] for item in tools))

    def test_invalid_autonomous_tool_choice_returns_truthful_chat_response(self) -> None:
        self.install_echo_plugin("available-echo")
        conversation = self.client.post("/api/conversations", json={"title": "Invalid tool"}).json()
        with patch.object(main, "lm_client", return_value=InvalidToolChoosingLmStudio()):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "Gebruik available-echo voor deze taak"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["tools"][0]["status"], "blocked")
        content = body["assistant_message"]["content"]
        self.assertTrue(
            ("Geen toegestane tool" in content)
            or ("niet toegestaan" in content)
            or ("capability ontbreekt" in content),
            content,
        )

    def test_bot_can_execute_multiple_tools_in_one_chat_response(self) -> None:
        plugin = self.install_echo_plugin("multi-echo")
        conversation = self.client.post("/api/conversations", json={"title": "Multi tool"}).json()
        with patch.object(main, "lm_client", return_value=TwoToolChoosingLmStudio(plugin["id"])):
            response = self.client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "Gebruik multi-echo voor een taak met meerdere stappen"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["status"] for item in response.json()["tools"]], ["completed", "completed"])
        self.assertEqual(len(main.platform_db.tool_calls(plugin["id"])), 2)

    def test_manual_plugin_invoke_requires_explicit_run_approval(self) -> None:
        plugin = self.install_echo_plugin("approval-echo")
        response = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["no"]}, "approved_by_user": False},
        )
        self.assertEqual(response.status_code, 428, response.text)
        self.assertEqual(response.json()["detail"]["tool_call"]["status"], "approval_required")

    def test_agents_console_lists_registry_with_live_fields(self) -> None:
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("items", payload)
        self.assertIn("summary", payload)
        self.assertGreaterEqual(len(payload["items"]), 10)
        by_id = {item["id"]: item for item in payload["items"]}
        self.assertIn("chat", by_id)
        self.assertIn("status", by_id["chat"])
        self.assertIn("usage", by_id["chat"])
        self.assertIn("web_scout", by_id)
        self.assertFalse(by_id["web_scout"]["planned"])
        self.assertNotEqual(by_id["web_scout"]["status"], "unavailable")
        self.assertNotIn("(*)", by_id["web_scout"]["name"])
        self.assertFalse(by_id["chat"]["usage"]["known"])
        self.assertIsNone(by_id["chat"]["usage"]["total_tokens"])

    def test_agent_detail_enable_disable_and_usage(self) -> None:
        detail = self.client.get("/api/agents/chat")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["id"], "chat")
        self.assertIn("recent_runs", detail.json())

        enabled = self.client.put("/api/agents/web_scout/state", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(enabled.json()["enabled"])
        self.assertFalse(enabled.json().get("planned", False))

        disabled = self.client.put("/api/agents/chat/state", json={"enabled": False})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["enabled"])
        self.assertEqual(disabled.json()["status"], "disabled")

        enabled = self.client.put("/api/agents/chat/state", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(enabled.json()["enabled"])

        main.platform_db.record_agent_usage(
            agent_id="chat",
            provider="lm_studio",
            model_id="local-test-model",
            usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "cached_tokens": None, "reasoning_tokens": None, "cost": None},
        )
        listed = self.client.get("/api/agents").json()
        chat = next(item for item in listed["items"] if item["id"] == "chat")
        self.assertTrue(chat["usage"]["known"])
        self.assertEqual(chat["usage"]["total_tokens"], 18)
        self.assertIsNone(chat["usage"]["cost"])

    def test_agent_cancel_current_for_running_task(self) -> None:
        created = self.client.post(
            "/api/tasks",
            json={"title": "Agent cancel", "prompt": "Stop mij", "agent": "chat", "priority": "normal", "auto_start": False},
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["id"]
        main.database.update_task(task_id, status="running", progress=20)
        cancelled = self.client.post("/api/agents/chat/cancel-current")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertIn(task_id, cancelled.json()["cancelled_task_ids"])
        task = main.database.get_task(task_id)
        self.assertEqual(task["status"], "cancelled")

    def test_pick_folder_cancelled_and_selected_paths(self) -> None:
        with patch.object(main, "pick_directory", return_value=None):
            cancelled = self.client.post("/api/plugins/pick-folder")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertTrue(cancelled.json()["cancelled"])
        self.assertIsNone(cancelled.json()["path"])

        selected = Path(self.temp_dir.name) / "picked-source"
        selected.mkdir()
        with patch.object(main, "pick_directory", return_value=str(selected)):
            response = self.client.post("/api/plugins/pick-folder")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["cancelled"])
        self.assertEqual(response.json()["path"], str(selected.resolve()))

        with patch.object(main, "pick_directory", side_effect=main.FolderPickerUnavailable("geen display")):
            missing = self.client.post("/api/plugins/pick-folder")
        self.assertEqual(missing.status_code, 503)

    def test_import_folder_builds_usable_hadesplugin(self) -> None:
        manifest = {
            "format": 1,
            "id": "browser-folder-echo",
            "name": "Browser Folder Echo",
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": ["subprocess"],
            "tools": [{"name": "echo", "command": ["{python}", "echo.py", "{args}"], "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}}}],
        }
        response = self.client.post(
            "/api/plugins/import-folder",
            files=[
                ("files", ("browser-folder-echo/hades-plugin.json", json.dumps(manifest), "application/json")),
                ("files", ("browser-folder-echo/echo.py", "import sys\nprint('BROWSER ' + ' '.join(sys.argv[1:]))\n", "text/x-python")),
                ("files", ("browser-folder-echo/node_modules/skip.js", "nope", "text/javascript")),
            ],
            data={
                "install_dependencies": "false",
                "approved_file_write": "true",
                "approved_file_read": "true",
                "approved_network": "false",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["plugin"]["status"], "ready")
        self.assertFalse(body["plugin"]["enabled"])
        self.assertTrue(str(body["package_path"]).endswith(".HadesPlugin"))
        self.assertFalse((Path(body["plugin"]["local_path"]) / "node_modules").exists())
        enabled = self.client.put(f"/api/plugins/{body['plugin']['id']}/state", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        invoked = self.client.post(
            f"/api/plugins/{body['plugin']['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["ok"]}, "timeout_seconds": 10, "approved_by_user": True},
        )
        self.assertEqual(invoked.status_code, 200, invoked.text)
        self.assertIn("BROWSER ok", invoked.json()["stdout"])

        escaped = self.client.post(
            "/api/plugins/import-folder",
            files=[("files", ("../evil.py", "print(1)\n", "text/x-python"))],
            data={"install_dependencies": "false", "approved_file_write": "true", "approved_file_read": "true", "approved_network": "false"},
        )
        self.assertEqual(escaped.status_code, 400)

    def test_picked_folder_import_builds_hadesplugin(self) -> None:
        source = Path(self.temp_dir.name) / "native-folder-echo"
        source.mkdir()
        (source / "echo.py").write_text("import sys\nprint('NATIVE ' + ' '.join(sys.argv[1:]))\n", encoding="utf-8")
        (source / "hades-plugin.json").write_text(json.dumps({
            "format": 1,
            "id": "native-folder-echo",
            "name": "Native Folder Echo",
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": ["subprocess"],
            "tools": [{"name": "echo", "command": ["{python}", "echo.py", "{args}"], "input_schema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}}}],
        }), encoding="utf-8")
        imported = self.client.post(
            "/api/plugins/import",
            json={
                "source_type": "folder",
                "path_or_url": str(source),
                "install_dependencies": False,
                "approved_network": False,
                "approved_file_read": True,
                "approved_file_write": True,
            },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        plugin = imported.json()["plugin"]
        self.assertEqual(plugin["status"], "ready")
        self.assertFalse(plugin["enabled"])
        self.assertTrue(str(imported.json()["package_path"]).endswith(".HadesPlugin"))
        enabled = self.client.put(f"/api/plugins/{plugin['id']}/state", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        invoked = self.client.post(
            f"/api/plugins/{plugin['id']}/invoke",
            json={"tool_name": "echo", "input": {"args": ["ok"]}, "timeout_seconds": 10, "approved_by_user": True},
        )
        self.assertEqual(invoked.status_code, 200, invoked.text)
        self.assertIn("NATIVE ok", invoked.json()["stdout"])

    def test_files_upload_workspace_detail_rescan_and_delete(self) -> None:
        docs = Path(self.temp_dir.name) / "files-docs"
        docs.mkdir()
        (docs / "guide.md").write_text("# Guide\nBestanden pagina indexeert lokale documenten in Knowledge.", encoding="utf-8")

        listed = self.client.get("/api/files")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn("uploads_count", listed.json())

        created = self.client.post(
            "/api/files/workspaces",
            json={"path": str(docs), "name": "FilesDocs", "recursive": True, "max_files": 100, "approved": True},
        )
        self.assertEqual(created.status_code, 200, created.text)
        workspace = created.json()["workspace"]
        self.assertEqual(created.json()["ready"], 1)

        scoped = self.client.get("/api/files", params={"workspace_id": workspace["id"]})
        self.assertEqual(scoped.status_code, 200, scoped.text)
        self.assertEqual(len(scoped.json()["files"]), 1)
        file_id = scoped.json()["files"][0]["id"]

        detail = self.client.get(f"/api/files/{file_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertGreaterEqual(len(detail.json()["chunks"]), 1)

        upload = self.client.post(
            "/api/files/upload",
            files={"file": ("upload.md", b"# Upload\nGeuploade inhoud voor tests.", "text/markdown")},
            data={"approved": "true"},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(upload.json()["file"]["status"], "ready")
        upload_id = upload.json()["file"]["id"]

        uploads = self.client.get("/api/files", params={"workspace_id": "uploads"})
        self.assertEqual(uploads.status_code, 200, uploads.text)
        self.assertTrue(any(item["id"] == upload_id for item in uploads.json()["files"]))

        rescanned = self.client.post(f"/api/files/workspaces/{workspace['id']}/rescan", json={"approved": True})
        self.assertEqual(rescanned.status_code, 200, rescanned.text)
        self.assertGreaterEqual(rescanned.json()["unchanged"] + rescanned.json()["ready"], 1)

        reindexed = self.client.post(f"/api/files/{file_id}/reindex", params={"approved": "true"})
        self.assertEqual(reindexed.status_code, 200, reindexed.text)

        deleted_upload = self.client.delete(f"/api/files/{upload_id}")
        self.assertEqual(deleted_upload.status_code, 200, deleted_upload.text)
        self.assertTrue(deleted_upload.json()["removed"])

        deleted_workspace = self.client.delete(f"/api/files/workspaces/{workspace['id']}")
        self.assertEqual(deleted_workspace.status_code, 200, deleted_workspace.text)
        remaining = self.client.get("/api/files", params={"workspace_id": workspace["id"]})
        self.assertEqual(remaining.json()["files"], [])

    def test_trading_dashboard_seed_discover_and_paper_flow(self) -> None:
        paper = self.client.get("/api/trading")
        self.assertEqual(paper.status_code, 200, paper.text)
        self.assertIn("wallets", paper.json())

        seeded = self.client.post("/api/trading/market/seed", json={"symbol": "BTC/USDT", "bars": 120, "seed": 11})
        self.assertEqual(seeded.status_code, 200, seeded.text)
        self.assertEqual(seeded.json()["summary"]["bars"], 120)
        self.assertGreaterEqual(len(seeded.json()["dashboard"]["bars"]), 50)

        enabled = self.client.put("/api/trading/enabled", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(enabled.json()["settings"]["enabled"])

        run = self.client.post(
            "/api/trading/runs",
            json={"kind": "discover", "symbol": "BTC/USDT", "timeframe": "1h", "top_n": 3, "auto_start": True},
        )
        self.assertEqual(run.status_code, 200, run.text)
        run_id = run.json()["run"]["id"]
        state = run.json()["run"]
        for _ in range(200):
            time.sleep(0.03)
            detail = self.client.get(f"/api/trading/runs/{run_id}")
            self.assertEqual(detail.status_code, 200, detail.text)
            state = detail.json()["run"]
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
        self.assertEqual(state["status"], "completed", state.get("error"))
        self.assertTrue(state.get("knowledge_source_id"))

        dashboard = self.client.get("/api/trading/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        payload = dashboard.json()
        self.assertGreaterEqual(len(payload["strategies"]), 1)
        strategy_id = payload["strategies"][0]["id"]
        activated = self.client.put("/api/trading/bot", json={"strategy_id": strategy_id, "symbol": "BTC/USDT"})
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()["bot"]["strategy_id"], strategy_id)

        last_close = payload["bars"][-1]["close"]
        bought = self.client.post("/api/trading/buy", json={"symbol": "BTC/USDT", "quantity": 0.01, "price": last_close})
        self.assertEqual(bought.status_code, 200, bought.text)
        position_id = bought.json()["position_id"]
        closed = self.client.post(f"/api/trading/positions/{position_id}/close", json={"price": last_close * 1.01})
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertGreater(closed.json()["realized_pnl"], 0)


if __name__ == "__main__":
    unittest.main()
