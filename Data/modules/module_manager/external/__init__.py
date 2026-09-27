"""Generic external capability fabric — one adapter family under ModuleManager.

Individual third-party packages are declarative manifests + this fabric.
No per-repository wrapper explosion. MCP sessions remain owned by McpBridge.
"""

from .types import (
    AdapterType,
    AssimilationMode,
    ExternalConfig,
    ExternalFailureCode,
    ExternalRuntimeState,
    InstallStrategy,
    ResultFormat,
    RuntimeMode,
)
from .module import ExternalCapabilityModule, create_external_capability_module
from .executor import ExternalModuleExecutor
from .store import ExternalCapabilityStore
from .skills import SkillImporter, SkillRecord

__all__ = [
    "AdapterType",
    "AssimilationMode",
    "ExternalCapabilityModule",
    "ExternalCapabilityStore",
    "ExternalConfig",
    "ExternalFailureCode",
    "ExternalModuleExecutor",
    "ExternalRuntimeState",
    "InstallStrategy",
    "ResultFormat",
    "RuntimeMode",
    "SkillImporter",
    "SkillRecord",
    "create_external_capability_module",
]
