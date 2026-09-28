"""COMPOSITE adapter — skill pack + CLI/MCP/HTTP/process combined via one manifest."""

from __future__ import annotations

from typing import Any, Mapping

from ...errors import failure_from_lifecycle_result
from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..install import InstallError
from ..types import AdapterType, ExternalFailureCode, ExternalRuntimeState, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb
from .catalog_source import CatalogSourceAdapter
from .cli import CliAdapter
from .http_openapi import HttpOpenApiAdapter
from .mcp_adapter import McpAdapter
from .process_service import ProcessServiceAdapter
from .script_package import ScriptPackageAdapter
from .skill_pack import SkillPackAdapter


def build_adapter(adapter_type: AdapterType, ctx: AdapterContext) -> Any:
    if adapter_type == AdapterType.CLI:
        return CliAdapter(ctx)
    if adapter_type == AdapterType.PROCESS_SERVICE:
        return ProcessServiceAdapter(ctx)
    if adapter_type == AdapterType.HTTP_OPENAPI:
        return HttpOpenApiAdapter(ctx)
    if adapter_type == AdapterType.MCP:
        return McpAdapter(ctx)
    if adapter_type == AdapterType.SKILL_PACK:
        return SkillPackAdapter(ctx)
    if adapter_type == AdapterType.CATALOG_SOURCE:
        return CatalogSourceAdapter(ctx)
    if adapter_type == AdapterType.SCRIPT_PACKAGE:
        return ScriptPackageAdapter(ctx)
    if adapter_type == AdapterType.COMPOSITE:
        return CompositeAdapter(ctx)
    raise ValueError(f"Unknown adapter type: {adapter_type}")


class CompositeAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        children = list(ctx.config.children) or [AdapterType.SKILL_PACK, AdapterType.CLI]
        # Avoid recursive COMPOSITE children.
        children = [c for c in children if c != AdapterType.COMPOSITE]
        self._children = [build_adapter(c, ctx) for c in children]
        self._primary = self._children[0] if self._children else CliAdapter(ctx)
        self._exec = next(
            (
                c
                for c in self._children
                if isinstance(c, (CliAdapter, ScriptPackageAdapter, ProcessServiceAdapter, HttpOpenApiAdapter, McpAdapter))
            ),
            self._primary,
        )
        self._skills = next((c for c in self._children if isinstance(c, (SkillPackAdapter, CatalogSourceAdapter))), None)

    def runtime_state(self) -> ExternalRuntimeState:
        return self._exec.runtime_state()

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        results = []
        for child in self._children:
            result = child.ensure_installed(progress=progress, cancel_check=cancel_check)
            results.append(result)
            failed = failure_from_lifecycle_result(result if isinstance(result, dict) else {"result": result})
            if failed is not None:
                code, detail = failed
                try:
                    failure_code = ExternalFailureCode(code)
                except ValueError:
                    failure_code = ExternalFailureCode.INSTALL_FAILED
                raise InstallError(failure_code, detail)
        return {"status": "INSTALLED", "children": results}

    def start(self) -> dict[str, Any]:
        results = [child.start() for child in self._children]
        return {"status": "READY", "children": results}

    def stop(self) -> dict[str, Any]:
        results = [child.stop() for child in reversed(self._children)]
        return {"status": "STOPPED", "children": results}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        results = [child.ensure_ready() for child in self._children]
        # Optional MCP children may report ready=lazy without a live session.
        ready = all(r.get("ready", True) for r in results if isinstance(r, dict))
        return {"ready": ready, "children": results}

    def _child_role(self, child: Any) -> str:
        """Classify child adapters for health aggregation.

        Required executable children drive composite readiness.
        Optional skill/catalog (and lazy MCP) children must not force ERROR
        merely for DISCOVERED / not-yet-connected lifecycle states.
        """
        if isinstance(child, (SkillPackAdapter, CatalogSourceAdapter)):
            return "optional"
        if isinstance(child, McpAdapter) and not child.config.runtime.eager_start:
            return "optional"
        return "required"

    def health(self) -> ModuleHealth:
        pairs = [(child, child.health()) for child in self._children]
        child_health = [h.public_dict() for _, h in pairs]

        healthy = {
            ModuleStatus.READY,
            ModuleStatus.INITIALIZED,
            ModuleStatus.LOADED,
            ModuleStatus.RUNNING,
            ModuleStatus.BUSY,
        }
        installed_ok = healthy | {ModuleStatus.INSTALLED}
        lifecycle_soft = installed_ok | {
            ModuleStatus.DISCOVERED,
            ModuleStatus.STOPPED,
            ModuleStatus.DISABLED,
            ModuleStatus.SHUTDOWN,
        }
        fatal = {ModuleStatus.FAILED, ModuleStatus.ERROR}

        required: list[ModuleStatus] = []
        optional: list[ModuleStatus] = []
        roles: list[dict[str, Any]] = []
        for child, health in pairs:
            role = self._child_role(child)
            status = health.status if isinstance(health.status, ModuleStatus) else ModuleStatus(str(health.status))
            roles.append(
                {
                    "adapter": type(child).__name__,
                    "role": role,
                    "status": status.value,
                }
            )
            if role == "required":
                required.append(status)
            else:
                optional.append(status)

        if any(s in fatal for s in required):
            aggregate = ModuleStatus.FAILED
            detail = "composite_required_child_failed"
        elif required and all(s in healthy for s in required):
            if any(s in fatal for s in optional):
                aggregate = ModuleStatus.DEGRADED
                detail = "composite_optional_child_failed"
            else:
                aggregate = ModuleStatus.READY
                detail = "composite"
        elif required and all(s in installed_ok for s in required):
            aggregate = ModuleStatus.INSTALLED
            detail = "composite_installed"
        elif required and all(s in lifecycle_soft for s in required):
            # Executable surface not ready yet — report lifecycle truth, not ERROR.
            if all(s == ModuleStatus.DISCOVERED for s in required):
                aggregate = ModuleStatus.DISCOVERED
            elif any(s == ModuleStatus.STOPPED for s in required):
                aggregate = ModuleStatus.STOPPED
            elif any(s == ModuleStatus.DISABLED for s in required):
                aggregate = ModuleStatus.DISABLED
            else:
                aggregate = ModuleStatus.DISCOVERED
            detail = "composite_lifecycle"
        elif not required:
            # Skill/catalog-only composite: optional children define status.
            if optional and all(s in healthy for s in optional):
                aggregate = ModuleStatus.READY
                detail = "composite"
            elif optional and all(s in installed_ok for s in optional):
                aggregate = ModuleStatus.INSTALLED
                detail = "composite_installed"
            elif optional and any(s in fatal for s in optional):
                aggregate = ModuleStatus.FAILED
                detail = "composite_optional_only_failed"
            else:
                aggregate = ModuleStatus.DISCOVERED
                detail = "composite_lifecycle"
        else:
            aggregate = ModuleStatus.DEGRADED
            detail = "composite_partial"

        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=aggregate,
            detail=detail,
            telemetry={
                "adapter": "COMPOSITE",
                "children": child_health,
                "child_roles": roles,
                "truth": {
                    "optional_discovered_is_not_fatal": True,
                    "required_failure_is_fatal": True,
                },
            },
        )

    def logs(self, *, limit: int = 200) -> list[str]:
        lines: list[str] = []
        per = max(1, limit // max(1, len(self._children)))
        for child in self._children:
            lines.extend(child.logs(limit=per))
        return lines[:limit]

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        # Declared executable ops (CLI/HTTP/process) win over skill-pack names like "search".
        declared_exec_ops = {
            str(op.get("name") or op.get("operation") or "")
            for op in (self.config.runtime.operations or ())
            if isinstance(op, dict)
        }
        if operation in declared_exec_ops:
            return self._exec.invoke(operation, arguments, progress=progress, cancel_check=cancel_check)

        # Skill-only ops → skill/catalog child; lifecycle → all; else executable child.
        if self._skills is not None and operation in {
            "list",
            "search",
            "search_skills",
            "load",
            "get",
            "enable",
            "disable",
            "index",
            "refresh",
            "materialize",
            "install_skill",
        }:
            skill_op = "search" if operation == "search_skills" else operation
            return self._skills.invoke(skill_op, arguments, progress=progress, cancel_check=cancel_check)
        if operation in {"start", "stop", "restart"}:
            if operation == "start":
                out = self.start()
            elif operation == "stop":
                out = self.stop()
            else:
                out = self.restart()
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(summary=operation, structured_data=out),
            )
        return self._exec.invoke(operation, arguments, progress=progress, cancel_check=cancel_check)
