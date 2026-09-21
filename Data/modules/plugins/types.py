from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PluginStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class AdapterKind(str, Enum):
    DECLARATIVE = "DECLARATIVE"
    MCP = "MCP"
    PROTOCOL = "PROTOCOL"


@dataclass(frozen=True)
class PluginCapabilityBinding:
    """Maps an external tool name onto a LEVIATHAN capability id."""

    external_name: str
    capability_id: str
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "external_name": self.external_name,
            "capability_id": self.capability_id,
            "description": self.description,
        }


@dataclass(frozen=True)
class PluginRecord:
    plugin_id: str
    name: str
    kind: AdapterKind
    status: PluginStatus
    version: str
    bindings: tuple[PluginCapabilityBinding, ...]
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status.value,
            "version": self.version,
            "bindings": [item.public_dict() for item in self.bindings],
            "endpoint": self.endpoint,
            "metadata": self.metadata,
            "error": self.error,
            "truth": {
                "discoverable_capability_is_not_authorized_capability": True,
                "plugins_use_shared_gateway": True,
            },
        }
