"""COMPOSITE adapter — skill pack + CLI/MCP/HTTP/process combined via one manifest."""

from __future__ import annotations

from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..types import AdapterType, ExternalRuntimeState, normalize_capability_parts
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
            results.append(child.ensure_installed(progress=progress, cancel_check=cancel_check))
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

    def health(self) -> ModuleHealth:
        child_health = [child.health().public_dict() for child in self._children]
        ok = all(h.get("status") in {"READY", "INITIALIZED", "LOADED"} for h in child_health)
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=ModuleStatus.READY if ok else ModuleStatus.ERROR,
            detail="composite",
            telemetry={"adapter": "COMPOSITE", "children": child_health},
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
