"""Fixture SDK over existing domain services (U391–U393 foundations).

Not a published package — stable local client surface for tests and operators.
Custom agents/plugins still execute through Cognition/Agents/Gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from Data.modules.execution import CapabilityRequest, ExecutionGateway
from Data.modules.plugins import AdapterKind, PluginCapabilityBinding, PluginRegistry
from Data.modules.projects.store import ProjectStore
from Data.modules.timeline.store import WorkTimeline


@dataclass
class FixtureSdk:
    """Thin SDK façade — discoverable ≠ authorized."""

    projects: ProjectStore
    timeline: WorkTimeline
    gateway: ExecutionGateway
    plugins: PluginRegistry | None = None
    api_version: str = "2026-09-23.wave11"
    _custom_agents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "surfaces": ["projects", "timeline", "invoke", "plugins", "custom_agents"],
            "truth": {
                "sdk_is_not_second_gateway": True,
                "discoverable_is_not_authorized": True,
                "marketplace_private_local_first": True,
            },
        }

    def create_project(self, name: str, **kwargs: Any) -> dict[str, Any]:
        project, workspace = self.projects.create_project(name, **kwargs)
        return {"project": project.public_dict(), "workspace": workspace.public_dict()}

    def append_timeline(self, **kwargs: Any) -> dict[str, Any]:
        return self.timeline.append(**kwargs).public_dict()

    def invoke_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        project_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=dict(arguments or {}),
                run_id=run_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                requested_by="sdk",
            )
        )
        if project_id:
            self.timeline.append(
                project_id=project_id,
                domain="capability",
                name="invoke",
                entity_id=result.request_id,
                run_id=run_id,
                trace_id=trace_id,
                summary=f"{capability_id}:{result.status.value}",
                metadata={"capability_id": capability_id},
            )
        return result.public_dict()

    def register_plugin(
        self,
        *,
        name: str,
        capability_ids: list[str],
        kind: AdapterKind = AdapterKind.DECLARATIVE,
    ) -> dict[str, Any]:
        if self.plugins is None:
            raise RuntimeError("PluginRegistry not configured on FixtureSdk")
        bindings = [
            PluginCapabilityBinding(external_name=cid, capability_id=cid)
            for cid in capability_ids
        ]
        record = self.plugins.register(name=name, kind=kind, bindings=bindings)
        return record.public_dict()

    def register_custom_agent(
        self,
        *,
        name: str,
        instructions: str,
        tools: list[str] | None = None,
        memory_scope: str = "PROJECT",
        output_schema: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Declarative custom agent — still executes via shared Agents/Gateway."""
        agent_id = f"custom_{name.lower().replace(' ', '_')}"
        definition = {
            "agent_id": agent_id,
            "name": name,
            "instructions": instructions,
            "tools": list(tools or []),
            "memory_scope": memory_scope,
            "output_schema": output_schema or {},
            "project_id": project_id,
            "truth": {
                "custom_agent_uses_shared_cognition_gateway": True,
                "not_private_agent_runtime": True,
            },
        }
        self._custom_agents[agent_id] = definition
        return definition

    def list_custom_agents(self) -> list[dict[str, Any]]:
        return list(self._custom_agents.values())
