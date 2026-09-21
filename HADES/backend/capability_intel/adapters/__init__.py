from .base import AdapterRegistry, PackageAdapter, default_registry
from .claude_upstream import ClaudeUpstreamAdapter
from .convention import ConventionAdapter
from .hades_manifest import HadesManifestAdapter
from .mcp_discovery import McpDiscoveryAdapter
from .native import native_capabilities

__all__ = [
    "AdapterRegistry",
    "PackageAdapter",
    "default_registry",
    "ClaudeUpstreamAdapter",
    "ConventionAdapter",
    "HadesManifestAdapter",
    "McpDiscoveryAdapter",
    "native_capabilities",
]
