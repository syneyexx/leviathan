"""MCP adapter — lifecycle only. Protocol/session/tools owned by McpBridge."""

from __future__ import annotations

from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..types import ExternalFailureCode, ExternalRuntimeState, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb


class McpAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self._state = ExternalRuntimeState.STOPPED
        self._server_id = ctx.config.runtime.mcp_server_id or ctx.module_id

    def runtime_state(self) -> ExternalRuntimeState:
        bridge = self.ctx.mcp_bridge
        if bridge is None:
            return ExternalRuntimeState.FAILED
        try:
            health = bridge.server_health(self._server_id)
            state = str(health.get("state") or health.get("current_state") or "").upper()
            if state in {"READY", "BUSY"}:
                return ExternalRuntimeState.RUNNING
            if state in {"CONNECTING", "RESTARTING"}:
                return ExternalRuntimeState.STARTING
            if state in {"DISABLED"}:
                return ExternalRuntimeState.DISABLED
            if state in {"ERROR", "CIRCUIT_OPEN", "UNRESPONSIVE"}:
                return ExternalRuntimeState.FAILED
            if state in {"DEGRADED"}:
                return ExternalRuntimeState.DEGRADED
            return ExternalRuntimeState.STOPPED
        except Exception:  # noqa: BLE001
            return self._state

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        # MCP install is registering config with McpBridge (may still need local checkout for stdio).
        bridge = self.ctx.mcp_bridge
        if bridge is None:
            return {"status": "FAILED", "code": ExternalFailureCode.PROTOCOL_ERROR.value, "detail": "mcp_bridge missing"}
        # If source is git/path, install via CLI install path first for stdio command resolution.
        if self.config.source.source and self.config.source.source_type in {"git", "path"}:
            from .cli import CliAdapter

            installed = CliAdapter(self.ctx).ensure_installed(progress=progress, cancel_check=cancel_check)
        else:
            installed = {"status": "INSTALLED"}
        self._reregister_mcp(install_root=(installed or {}).get("install_root"))
        self._state = ExternalRuntimeState.INSTALLED
        return installed

    def _reregister_mcp(self, *, install_root: str | None = None) -> None:
        """Ensure module.json mcp.servers are registered with resolved $INSTALL_ROOT."""
        bridge = self.ctx.mcp_bridge
        if bridge is None:
            return
        root = install_root
        if not root and self.ctx.store is not None:
            version = self.ctx.store.get_active_version(self.ctx.module_id)
            if version:
                root = version.get("install_root")
        if not root:
            root = self.ctx.install_root
        meta = self.ctx.metadata or {}
        manifest_path = meta.get("manifest_path") if isinstance(meta, dict) else None
        if not manifest_path:
            try:
                from pathlib import Path

                candidate = (
                    Path(__file__).resolve().parents[4]
                    / "external_capabilities"
                    / self.ctx.module_id
                    / "module.json"
                )
                if candidate.is_file():
                    manifest_path = str(candidate)
            except Exception:  # noqa: BLE001
                pass
        if not manifest_path:
            return
        try:
            from Data.modules.mcp.module_integration import register_module_mcp

            register_module_mcp(
                bridge,
                module_id=self.ctx.module_id,
                manifest_path=str(manifest_path),
                install_root=root,
            )
        except Exception:  # noqa: BLE001 — optional MCP must not break install
            pass

    def start(self) -> dict[str, Any]:
        bridge = self.ctx.mcp_bridge
        if bridge is None:
            raise RuntimeError("mcp_bridge not configured")
        self._state = ExternalRuntimeState.STARTING
        self._reregister_mcp()
        try:
            bridge.enable(self._server_id)
        except Exception:  # noqa: BLE001 — enable may already be on
            pass
        try:
            bridge.connect(self._server_id)
            try:
                bridge.refresh_tools(self._server_id)
            except Exception:  # noqa: BLE001
                pass
            self._state = ExternalRuntimeState.RUNNING
            if self.ctx.store is not None:
                self.ctx.store.set_runtime_state(
                    self.ctx.module_id,
                    ExternalRuntimeState.RUNNING.value,
                    desired_state="RUNNING",
                )
            return {"status": "RUNNING", "server_id": self._server_id}
        except Exception as exc:  # noqa: BLE001
            self._state = ExternalRuntimeState.FAILED
            raise RuntimeError(f"MCP start failed: {exc}") from exc

    def stop(self) -> dict[str, Any]:
        bridge = self.ctx.mcp_bridge
        if bridge is None:
            return {"status": "STOPPED"}
        self._state = ExternalRuntimeState.STOPPING
        try:
            bridge.disconnect(self._server_id)
        except Exception:  # noqa: BLE001
            pass
        # Desired state may keep enabled=true while disconnected — honor disable only when asked via args elsewhere.
        self._state = ExternalRuntimeState.STOPPED
        if self.ctx.store is not None:
            self.ctx.store.set_runtime_state(
                self.ctx.module_id,
                ExternalRuntimeState.STOPPED.value,
                desired_state="STOPPED",
            )
        return {"status": "STOPPED", "server_id": self._server_id}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        state = self.runtime_state()
        if state == ExternalRuntimeState.RUNNING:
            return {"ready": True, "server_id": self._server_id}
        started = self.start()
        return {"ready": True, **started}

    def health(self) -> ModuleHealth:
        bridge = self.ctx.mcp_bridge
        detail = "mcp_bridge_missing"
        telemetry: dict[str, Any] = {"adapter": "MCP", "server_id": self._server_id}
        status = ModuleStatus.ERROR
        if bridge is not None:
            try:
                health = bridge.server_health(self._server_id)
                telemetry["mcp"] = health if isinstance(health, dict) else {"raw": str(health)}
                state = str((health or {}).get("state") or (health or {}).get("current_state") or "").upper()
                detail = state or "unknown"
                status = ModuleStatus.READY if state in {"READY", "BUSY"} else ModuleStatus.ERROR
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
        return ModuleHealth(module_id=self.ctx.module_id, status=status, detail=detail, telemetry=telemetry)

    def logs(self, *, limit: int = 200) -> list[str]:
        if self.ctx.store is not None:
            return self.ctx.store.get_logs(self.ctx.module_id, limit=limit)
        return []

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        """Lifecycle/status only — tool calls must go through ExecutionGateway → McpProvider."""
        if operation in {"start", "connect"}:
            out = self.start()
            return ModuleResult(module_id=self.ctx.module_id, operation=operation, status="COMPLETED", output=normalize_capability_parts(summary="started", structured_data=out))
        if operation in {"stop", "disconnect"}:
            out = self.stop()
            return ModuleResult(module_id=self.ctx.module_id, operation=operation, status="COMPLETED", output=normalize_capability_parts(summary="stopped", structured_data=out))
        if operation in {"restart"}:
            out = self.restart()
            return ModuleResult(module_id=self.ctx.module_id, operation=operation, status="COMPLETED", output=normalize_capability_parts(summary="restarted", structured_data=out))
        if operation in {"health", "status"}:
            out = self.health().public_dict()
            return ModuleResult(module_id=self.ctx.module_id, operation=operation, status="COMPLETED", output=normalize_capability_parts(summary=out.get("detail"), structured_data=out))
        if operation in {"refresh_tools"}:
            bridge = self.ctx.mcp_bridge
            if bridge is None:
                return ModuleResult(module_id=self.ctx.module_id, operation=operation, status="FAILED", error=ExternalFailureCode.PROTOCOL_ERROR.value)
            tools = bridge.refresh_tools(self._server_id)
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(summary="tools refreshed", structured_data={"tools": tools if isinstance(tools, list) else tools}),
            )
        return ModuleResult(
            module_id=self.ctx.module_id,
            operation=operation,
            status="REJECTED",
            error="MCP tool calls must use ExecutionGateway / McpProvider",
            output={
                "error": {
                    "code": ExternalFailureCode.PROTOCOL_ERROR.value,
                    "detail": "Use mcp.<server>.<tool> capabilities via ExecutionGateway",
                }
            },
        )
