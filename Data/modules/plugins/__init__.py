"""Plugins / MCP adapters — declarative bindings into CapabilityCatalog."""

from .registry import PluginRegistry
from .types import AdapterKind, PluginCapabilityBinding, PluginRecord, PluginStatus

__all__ = [
    "AdapterKind",
    "PluginCapabilityBinding",
    "PluginRecord",
    "PluginRegistry",
    "PluginStatus",
]
