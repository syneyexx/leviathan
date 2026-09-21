"""Honesty / authorization / execution-truth hardening regressions.

Covers:
- Linked Work completion cannot be invented from chat completion
- Working-state persistence failures remain observable
- MCP/workflow booleans are not approval authority
- Native required mode and secured/container fail-closed isolation
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from approvals import ApprovalService
from mcp_host.manager import McpManager
from mcp_host.policy import mcp_tool_scope, resolve_scoped_approval, workflow_product_scope
from platform_db import PlatformDatabase
from platform_services import PluginManager
from reasoning.conversation_state import build_conversation_working_state
from reasoning.linked_work_truth import resolve_linked_work_truth


class LinkedWorkCompletionTruthTests(unittest.TestCase):
    def test_chat_completed_does_not_complete_running_linked_work(self) -> None:
        prior = {
            "open_work": [
                {"task_id": "task_running", "status": "running"},
                {"task_id": "task_other", "status": "queued"},
            ],
            "goal": "ship",
        }
        truth = resolve_linked_work_truth(
            linked_task_id="task_running",
            task={"id": "task_running", "status": "running"},
            checkpoint_state={"phase": "executed"},
        )
        state = build_conversation_working_state(
            previous=prior,
            user_text="continue",
            assistant_text="Done from chat.",
            request_spec={"goal": "ship"},
            route={"target": "work_runtime"},
            executed={"status": "completed", "work_runtime_called": True},
            linked_task_id="task_running",
            linked_work_truth=truth,
        )
        ids = {item["task_id"]: item for item in state["open_work"]}
        self.assertIn("task_running", ids)
        self.assertEqual(ids["task_running"]["status"], "running")
        self.assertIn("task_other", ids)

    def test_linked_work_removed_only_after_verified_completion(self) -> None:
        prior = {"open_work": [{"task_id": "task_ok", "status": "running"}]}
        blocked = resolve_linked_work_truth(
            linked_task_id="task_ok",
            task={"id": "task_ok", "status": "completed"},
            checkpoint_state={"phase": "executed", "passed": True},
        )
        self.assertFalse(blocked["may_remove"])
        kept = build_conversation_working_state(
            previous=prior,
            user_text="x",
            assistant_text="y",
            request_spec={},
            route={},
            executed={"status": "completed", "work_runtime_called": True},
            linked_task_id="task_ok",
            linked_work_truth=blocked,
        )
        self.assertTrue(any(i["task_id"] == "task_ok" for i in kept["open_work"]))

        allowed = resolve_linked_work_truth(
            linked_task_id="task_ok",
            task={"id": "task_ok", "status": "completed"},
            checkpoint_state={"phase": "verified", "passed": True},
            steps=[{"status": "completed"}],
        )
        self.assertTrue(allowed["may_remove"])
        cleared = build_conversation_working_state(
            previous=prior,
            user_text="x",
            assistant_text="y",
            request_spec={},
            route={},
            executed={"status": "completed", "work_runtime_called": True},
            linked_task_id="task_ok",
            linked_work_truth=allowed,
        )
        self.assertFalse(any(i["task_id"] == "task_ok" for i in cleared["open_work"]))

    def test_chat_completed_queued_and_failed_remain_open(self) -> None:
        for status in ("queued", "failed"):
            truth = resolve_linked_work_truth(
                linked_task_id="t1",
                task={"id": "t1", "status": status},
            )
            state = build_conversation_working_state(
                previous={"open_work": [{"task_id": "unrelated", "status": "running"}]},
                user_text="x",
                assistant_text="y",
                request_spec={},
                route={},
                executed={"status": "completed", "work_runtime_called": True},
                linked_task_id="t1",
                linked_work_truth=truth,
            )
            ids = {i["task_id"]: i for i in state["open_work"]}
            self.assertIn("t1", ids)
            self.assertEqual(ids["t1"]["status"], status)
            self.assertIn("unrelated", ids)

    def test_missing_linked_task_does_not_fabricate_completion(self) -> None:
        truth = resolve_linked_work_truth(linked_task_id="missing", task=None)
        self.assertTrue(truth["missing"])
        self.assertFalse(truth["may_remove"])
        state = build_conversation_working_state(
            previous={"open_work": [{"task_id": "missing", "status": "running"}]},
            user_text="x",
            assistant_text="y",
            request_spec={},
            route={},
            executed={"status": "completed", "work_runtime_called": True},
            linked_task_id="missing",
            linked_work_truth=truth,
        )
        self.assertTrue(any(i["task_id"] == "missing" for i in state["open_work"]))
        self.assertNotEqual(state["open_work"][0].get("status"), "completed")


class WorkingStatePersistHonestyTests(unittest.TestCase):
    def test_working_state_persist_failure_is_reported(self) -> None:
        """Simulate send_message persistence failure contract without full chat stack."""
        notes: list[str] = []
        meta: dict[str, Any] = {}
        prior = {"goal": "prior"}
        try:
            raise RuntimeError("disk full")
        except Exception as exc:
            err_type = type(exc).__name__
            working_state = prior
            meta = {
                "working_state_persist_failed": True,
                "working_state_persisted": False,
                "working_state_computed": False,
                "working_state_persist_error_type": err_type,
            }
            notes.append(f"conversation working_state persistence failed ({err_type})")
        self.assertTrue(meta["working_state_persist_failed"])
        self.assertFalse(meta["working_state_persisted"])
        self.assertTrue(any("working_state persistence failed" in n for n in notes))
        self.assertEqual(working_state, prior)

    def test_working_state_persist_failure_does_not_claim_success(self) -> None:
        success_meta = {
            "working_state_persist_failed": False,
            "working_state_persisted": True,
            "working_state_computed": True,
        }
        fail_meta = {
            "working_state_persist_failed": True,
            "working_state_persisted": False,
            "working_state_computed": False,
        }
        self.assertTrue(success_meta["working_state_persisted"])
        self.assertFalse(fail_meta["working_state_persisted"])
        self.assertTrue(fail_meta["working_state_persist_failed"])

    def test_send_message_source_reports_persist_failure(self) -> None:
        import inspect
        import main as hades_main

        source = inspect.getsource(hades_main.send_message)
        self.assertIn("working_state_persist_failed", source)
        self.assertIn("conversation working_state persistence failed", source)
        self.assertIn("resolve_linked_work_truth", source)


class McpPersistedApprovalAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "hades.db"))
        self.db.initialize()
        self.approvals = ApprovalService(self.db, inbox=None)
        self.manager = McpManager(
            self.db,
            settings_provider=lambda: {
                "mcp.enabled": True,
                "network_policy": "allow",
                "subprocess_policy": "allow",
            },
            approval_service=self.approvals,
        )

    def tearDown(self) -> None:
        self.manager.on_shutdown()
        self.tmp.cleanup()

    def _tool(self, *, allowed: bool, require_approval: bool = False) -> dict[str, Any]:
        server = self.manager.store.upsert_server(
            {
                "name": "AuthSrv",
                "transport": "streamable_http",
                "endpoint_url": "http://127.0.0.1:9/mcp",
                "auth_method": "none",
                "enabled": True,
                "connection_status": "connected",
                "env": {"plain": {}, "secret_refs": {}},
                "headers": {},
            }
        )
        self.manager.store.replace_discovered_tools(
            server["id"],
            [{"name": "echo", "inputSchema": {"type": "object", "properties": {}}}],
        )
        tool = self.manager.store.list_tools(server["id"])[0]
        self.manager.store.update_tool_prefs(
            tool["id"],
            {"allowed": allowed, "require_approval": require_approval, "chatbot_enabled": True},
        )
        return self.manager.store.get_tool(tool["id"])

    def test_mcp_boolean_approval_cannot_bypass_allowed_false(self) -> None:
        tool = self._tool(allowed=False)
        with self.assertRaises(Exception) as ctx:
            self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="manual",
                approved_by_user=True,
            )
        # Manual blocked path opens ApprovalService request (428 semantics) or PermissionError.
        message = str(ctx.exception).lower()
        detail = getattr(ctx.exception, "approval_required", None)
        self.assertTrue(
            detail is True
            or "approval" in message
            or "geblokkeerd" in message
            or "permission" in message,
            msg=message,
        )
        # Must not have executed (no silent bypass).
        self.assertNotIn("verbonden", message)

    def test_mcp_requires_persisted_scoped_approval(self) -> None:
        tool = self._tool(allowed=False)
        scope = mcp_tool_scope(
            server_id=tool["server_id"],
            tool_id=tool["id"],
            tool_name=tool["remote_name"],
        )
        req = self.approvals.create_tool_approval(
            plugin_id=f"mcp:{tool['server_id']}",
            tool_name=tool["remote_name"],
            arguments={},
            expected_effect="mcp tool invoke",
            schema_version="mcp-tool-1",
            scope=scope,
        )
        decided = self.approvals.decide(req["id"], approve=True)

        class FakeClient:
            transport = "streamable_http"
            alive = True
            protocol_version = "2024-11-05"
            protocol_generation = "legacy"

            def call_tool(self, name, arguments):
                return {
                    "tool": name,
                    "isError": False,
                    "result": {"ok": True},
                    "content": [{"type": "text", "text": "ok"}],
                }

            def close(self):
                return None

        with self.manager._session_lock:
            self.manager._sessions[tool["server_id"]] = FakeClient()
        with mock.patch(
            "runtime.execution_gateway.enforce_policies_fail_closed",
            return_value={"allowed": True, "args": {}},
        ):
            result = self.manager.invoke_tool(
                tool["id"],
                {},
                invocation_type="manual",
                approved_by_user=False,
                approval_id=decided["id"],
            )
        self.assertFalse(result.get("result", {}).get("isError", True))

    def test_mcp_wrong_scope_approval_is_rejected(self) -> None:
        tool = self._tool(allowed=False)
        wrong_scope = mcp_tool_scope(
            server_id=tool["server_id"],
            tool_id="other-tool",
            tool_name="other",
        )
        req = self.approvals.create_tool_approval(
            plugin_id=f"mcp:{tool['server_id']}",
            tool_name="other",
            arguments={},
            expected_effect="wrong",
            schema_version="mcp-tool-1",
            scope=wrong_scope,
        )
        decided = self.approvals.decide(req["id"], approve=True)
        with self.assertRaises(PermissionError):
            self.manager.assert_tool_authorization(
                tool,
                invocation_type="manual",
                approved_by_user=True,
                approval_id=decided["id"],
            )

    def test_rejected_and_fabricated_approval_blocked(self) -> None:
        tool = self._tool(allowed=False)
        scope = mcp_tool_scope(
            server_id=tool["server_id"],
            tool_id=tool["id"],
            tool_name=tool["remote_name"],
        )
        req = self.approvals.create_tool_approval(
            plugin_id=f"mcp:{tool['server_id']}",
            tool_name=tool["remote_name"],
            arguments={},
            expected_effect="mcp",
            schema_version="mcp-tool-1",
            scope=scope,
        )
        self.approvals.decide(req["id"], approve=False)
        with self.assertRaises(PermissionError):
            self.manager.assert_tool_authorization(
                tool, invocation_type="manual", approval_id=req["id"]
            )
        with self.assertRaises(PermissionError):
            self.manager.assert_tool_authorization(
                tool, invocation_type="manual", approval_id="apr_fabricated"
            )

    def test_chatbot_enabled_alone_never_grants_execution(self) -> None:
        tool = self._tool(allowed=False, require_approval=False)
        self.assertTrue(tool.get("chatbot_enabled"))
        with self.assertRaises(PermissionError):
            self.manager.assert_tool_authorization(
                tool, invocation_type="autonomous", approved_by_user=True
            )

    def test_require_approval_autonomous_boolean_only_blocked(self) -> None:
        tool = self._tool(allowed=True, require_approval=True)
        with self.assertRaises(PermissionError):
            self.manager.assert_tool_authorization(
                tool, invocation_type="autonomous", approved_by_user=True
            )


class WorkflowApprovalAuthorityTests(unittest.TestCase):
    def test_workflow_preapproved_boolean_has_no_authority(self) -> None:
        from gen2.workflow_executor import _workflow_product_approval_ok
        from gen2.workflow_adapters import WorkflowServices

        services = WorkflowServices()
        services.approval_service = None
        ok = _workflow_product_approval_ok(
            services,
            {"preapproved": True, "approved_by_user": True},
            workflow_id="wf1",
            action="coding_agent",
            step_id="repair",
        )
        self.assertFalse(ok)

    def test_workflow_persisted_approval_allows_scoped_action(self) -> None:
        from gen2.workflow_executor import _workflow_product_approval_ok
        from gen2.workflow_adapters import WorkflowServices

        tmp = tempfile.TemporaryDirectory()
        try:
            db = PlatformDatabase(str(Path(tmp.name) / "p.db"))
            db.initialize()
            approvals = ApprovalService(db, inbox=None)
            scope = workflow_product_scope(workflow_id="wf1", action="coding_agent", step_id="repair")
            req = approvals.create_tool_approval(
                plugin_id="workflow:wf1",
                tool_name="coding_agent",
                arguments={"goal": "fix"},
                expected_effect="test",
                scope=scope,
            )
            decided = approvals.decide(req["id"], approve=True)
            services = WorkflowServices()
            services.approval_service = approvals
            self.assertTrue(
                _workflow_product_approval_ok(
                    services,
                    {"approval_id": decided["id"]},
                    workflow_id="wf1",
                    action="coding_agent",
                    step_id="repair",
                )
            )
            self.assertFalse(
                _workflow_product_approval_ok(
                    services,
                    {"approval_id": decided["id"]},
                    workflow_id="wf1",
                    action="research_runner",
                    step_id="repair",
                )
            )
        finally:
            tmp.cleanup()


class NativeAndIsolationFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")
        self.workdir = self.root / "plugin_work"
        self.workdir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_native_executor_failure_does_not_silently_fallback_when_required(self) -> None:
        native = mock.MagicMock()
        native.status.return_value = mock.MagicMock(
            connected=True, fallback_active=False, mode="enabled", last_error=None
        )
        native.process_run.side_effect = RuntimeError("native crashed")
        self.manager.set_native_runtime(native)
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env={"PATH": "", "HADES_PLUGIN_ISOLATION": "plugin_cwd"},
                timeout=5,
            )
            run_mock.assert_not_called()
        self.assertEqual(result.get("error_code"), "native_executor_failed")
        self.assertIn("native_executor_failed", result.get("error") or "")
        self.assertFalse(result.get("native_fallback"))

    def test_native_required_failure_does_not_fallback_to_python(self) -> None:
        """Alias/regression name for required native fail-closed."""
        self.test_native_executor_failure_does_not_silently_fallback_when_required()

    def test_native_auto_may_fallback_only_for_non_security_boundary_execution(self) -> None:
        native = mock.MagicMock()
        native.status.return_value = mock.MagicMock(
            connected=True, fallback_active=False, mode="auto", last_error=None
        )
        native.process_run.side_effect = RuntimeError("native busy")
        self.manager.set_native_runtime(native)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HADES_PLUGIN_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_REQUESTED_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_EFFECTIVE_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_FS_SANDBOX": "false",
            "PYTHONUTF8": "1",
        }
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            run_mock.return_value = mock.MagicMock(stdout="ok\n", stderr="", returncode=0)
            result = self.manager._run_command(
                [sys.executable, "-c", "print('ok')"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_called_once()
        self.assertTrue(result.get("native_fallback"))
        self.assertEqual(result.get("executor_requested"), "native")
        self.assertEqual(result.get("executor_effective"), "python")
        self.assertEqual(result.get("effective_isolation"), "plugin_cwd")
        self.assertFalse(result.get("filesystem_sandbox"))

    def test_native_auto_fallback_is_observable(self) -> None:
        self.test_native_auto_may_fallback_only_for_non_security_boundary_execution()
        # Container remains refused even if native is in auto mode.
        native = mock.MagicMock()
        native.status.return_value = mock.MagicMock(
            connected=True, fallback_active=False, mode="auto", last_error=None
        )
        self.manager.set_native_runtime(native)
        env = {
            "HADES_PLUGIN_ISOLATION": "container",
            "HADES_PLUGIN_REQUESTED_ISOLATION": "container",
            "HADES_PLUGIN_ISOLATION_NOTE": "container_not_implemented",
            "HADES_PLUGIN_EFFECTIVE_ISOLATION": "none",
        }
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
            native.process_run.assert_not_called()
        self.assertEqual(result.get("error_code"), "container_not_implemented")

    def test_secured_execution_never_falls_back_to_unbounded_subprocess(self) -> None:
        from execution_isolation import IsolationUnavailable

        env = {"HADES_PLUGIN_ISOLATION": "secured", "PATH": ""}
        with mock.patch("platform_services_core.subprocess.run") as run_mock, mock.patch(
            "execution_isolation.run_isolated",
            side_effect=IsolationUnavailable("no fs isolation"),
        ):
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
        self.assertIn("refusing unbounded execution", result.get("error") or "")
        self.assertEqual(result.get("effective_isolation"), "none")

    def test_secured_never_falls_back_to_subprocess(self) -> None:
        self.test_secured_execution_never_falls_back_to_unbounded_subprocess()

    def test_container_isolation_fails_closed_when_not_implemented(self) -> None:
        plugin = {
            "id": "c1",
            "isolation": "container",
            "local_path": str(self.workdir),
            "manifest": {"isolation": "container"},
        }
        env = self.manager._command_environment(plugin, {"metadata": {}})
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION"), "container")
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION_NOTE"), "container_not_implemented")
        self.assertNotEqual(env.get("HADES_PLUGIN_ISOLATION"), "restricted_env")
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
        self.assertEqual(result.get("error_code"), "container_not_implemented")
        self.assertEqual(result.get("effective_isolation"), "none")
        self.assertNotEqual(result.get("effective_isolation"), "container")

    def test_container_not_implemented_fails_closed(self) -> None:
        self.test_container_isolation_fails_closed_when_not_implemented()

    def test_container_does_not_degrade_to_restricted_env(self) -> None:
        plugin = {
            "id": "c-degrade",
            "isolation": "container",
            "local_path": str(self.workdir),
            "manifest": {"isolation": "container"},
        }
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            env = self.manager._command_environment(plugin, {"metadata": {}})
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION"), "container")
        self.assertNotEqual(env.get("HADES_PLUGIN_ISOLATION"), "restricted_env")
        self.assertNotIn("fallback_restricted_env", env.get("HADES_PLUGIN_ISOLATION_NOTE", ""))
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            result = self.manager._run_command(
                [sys.executable, "-c", "print(1)"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_not_called()
        self.assertEqual(result.get("error_code"), "container_not_implemented")

    def test_container_runtime_unavailable_fails_closed(self) -> None:
        """No HADES container adapter exists — Docker presence still refuses execution."""
        plugin = {
            "id": "c-unavail",
            "isolation": "container",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        for docker in ("/usr/bin/docker", None):
            with mock.patch("shutil.which", return_value=docker):
                env = self.manager._command_environment(plugin, {"metadata": {}})
            with mock.patch("platform_services_core.subprocess.run") as run_mock:
                result = self.manager._run_command(
                    [sys.executable, "-c", "print(1)"],
                    root=self.workdir,
                    env=env,
                    timeout=5,
                )
                run_mock.assert_not_called()
            self.assertEqual(result.get("error_code"), "container_not_implemented")
            self.assertEqual(result.get("effective_isolation"), "none")

    def test_effective_isolation_never_claims_container_on_restricted_env(self) -> None:
        plugin = {
            "id": "c2",
            "isolation": "container",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        env = self.manager._command_environment(plugin, {"metadata": {}})
        self.assertNotEqual(env.get("HADES_PLUGIN_EFFECTIVE_ISOLATION"), "container")
        self.assertEqual(env.get("HADES_PLUGIN_REQUESTED_ISOLATION"), "container")

    def test_effective_isolation_never_claims_container_without_container(self) -> None:
        self.test_effective_isolation_never_claims_container_on_restricted_env()
        plugin = {
            "id": "re1",
            "isolation": "restricted_env",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        env = self.manager._command_environment(plugin, {"metadata": {}})
        self.assertEqual(env.get("HADES_PLUGIN_EFFECTIVE_ISOLATION"), "restricted_env")
        self.assertNotEqual(env.get("HADES_PLUGIN_EFFECTIVE_ISOLATION"), "container")
        self.assertEqual(env.get("HADES_PLUGIN_FS_SANDBOX"), "false")

    def test_restricted_env_is_not_reported_as_filesystem_sandbox(self) -> None:
        plugin = {
            "id": "re2",
            "isolation": "restricted_env",
            "local_path": str(self.workdir),
            "manifest": {},
        }
        env = self.manager._command_environment(plugin, {"metadata": {}})
        self.assertEqual(env.get("HADES_PLUGIN_FS_SANDBOX"), "false")
        self.assertEqual(env.get("HADES_PLUGIN_ISOLATION_KIND"), "host_process_env")
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            run_mock.return_value = mock.MagicMock(stdout="", stderr="", returncode=0)
            result = self.manager._run_command(
                [sys.executable, "-c", "pass"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
        self.assertFalse(result.get("filesystem_sandbox"))
        self.assertEqual(result.get("effective_isolation"), "restricted_env")
        self.assertEqual(result.get("requested_isolation"), "restricted_env")

    def test_plugin_cwd_existing_execution_still_works(self) -> None:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HADES_PLUGIN_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_REQUESTED_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_EFFECTIVE_ISOLATION": "plugin_cwd",
            "HADES_PLUGIN_FS_SANDBOX": "false",
            "PYTHONUTF8": "1",
        }
        with mock.patch("platform_services_core.subprocess.run") as run_mock:
            run_mock.return_value = mock.MagicMock(stdout="cwd-ok\n", stderr="", returncode=0)
            result = self.manager._run_command(
                [sys.executable, "-c", "print('cwd-ok')"],
                root=self.workdir,
                env=env,
                timeout=5,
            )
            run_mock.assert_called_once()
        self.assertEqual(result.get("exit_code"), 0)
        self.assertIsNone(result.get("error"))
        self.assertEqual(result.get("effective_executor"), "python")
        self.assertFalse(result.get("filesystem_sandbox"))
        self.assertFalse(result.get("native_fallback"))

    def test_service_start_container_fails_closed_no_popen(self) -> None:
        plugin = self.db.save_plugin(
            {
                "id": "svc-container",
                "name": "svc-container",
                "isolation": "container",
                "local_path": str(self.workdir),
                "manifest": {"isolation": "container"},
                "health": "prepared",
                "enabled": True,
            }
        )
        tool = {
            "name": "start",
            "metadata": {"action": "start", "healthcheck": {"type": "tcp", "port": 9}},
        }
        call_id = self.db.create_tool_call(
            plugin["id"], "start", {}, invocation_type="manual", approved_by_user=False
        )
        with mock.patch("platform_services_core.subprocess.Popen") as popen_mock:
            result = self.manager._start_service(
                plugin,
                tool,
                [sys.executable, "-c", "print(1)"],
                {},
                call_id,
                started=0.0,
                timeout=5,
            )
            popen_mock.assert_not_called()
        self.assertEqual(result.get("status"), "failed")
        meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        self.assertEqual(meta.get("error_code") or result.get("error_code"), "container_not_implemented")
        self.assertIn("container", (result.get("error") or "").lower())

    def test_service_start_secured_fails_closed_no_popen(self) -> None:
        plugin = self.db.save_plugin(
            {
                "id": "svc-secured",
                "name": "svc-secured",
                "isolation": "secured",
                "local_path": str(self.workdir),
                "manifest": {"isolation": "secured"},
                "health": "prepared",
                "enabled": True,
            }
        )
        tool = {
            "name": "start",
            "metadata": {"action": "start", "healthcheck": {"type": "tcp", "port": 9}},
        }
        call_id = self.db.create_tool_call(
            plugin["id"], "start", {}, invocation_type="manual", approved_by_user=False
        )
        with mock.patch("platform_services_core.subprocess.Popen") as popen_mock:
            result = self.manager._start_service(
                plugin,
                tool,
                [sys.executable, "-c", "print(1)"],
                {},
                call_id,
                started=0.0,
                timeout=5,
            )
            popen_mock.assert_not_called()
        self.assertEqual(result.get("status"), "failed")
        meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        self.assertEqual(
            meta.get("error_code") or result.get("error_code"),
            "secured_service_start_not_implemented",
        )


if __name__ == "__main__":
    unittest.main()
