"""HADES Control Plane types.

Unlimited numeric limits use ``None`` (JSON null). Never use fake sentinels like 999999.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Literal


class SettingType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DURATION_SECONDS = "duration_seconds"
    BYTES = "bytes"
    TOKENS = "tokens"
    STRING = "string"
    STRING_LIST = "string_list"
    OBJECT = "object"
    NULLABLE_INTEGER = "nullable_integer"  # None = unlimited


class SettingScope(str, Enum):
    SYSTEM = "system"
    GLOBAL = "global"
    PROJECT = "project"
    AGENT_TYPE = "agent_type"
    AGENT = "agent"
    PLUGIN = "plugin"
    SESSION = "session"
    TASK = "task"


class SettingSource(str, Enum):
    SYSTEM_DEFAULT = "system_default"
    GLOBAL_USER = "global_user"
    PROJECT = "project"
    AGENT_TYPE = "agent_type"
    AGENT = "agent"
    PLUGIN = "plugin"
    SESSION = "session"
    TASK = "task"
    RUNTIME_CAPABILITY = "runtime_capability"
    PROVIDER_CAPABILITY = "provider_capability"
    IMMUTABLE = "immutable"
    PRESET = "preset"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApplyMode(str, Enum):
    IMMEDIATE = "immediate"
    NEXT_TASK = "next_task"
    NEXT_AGENT_RESTART = "next_agent_restart"
    PLUGIN_RESTART = "plugin_restart"
    HADES_RESTART = "hades_restart"


class ConstraintKind(str, Enum):
    HADES_CONTROLLED = "hades_controlled"
    PROVIDER_LIMIT = "provider_limit"
    RUNTIME_CAPABILITY = "runtime_capability"
    SECURITY_INVARIANT = "security_invariant"


# Scope precedence for resolution (lowest → highest, excluding external constraints).
SCOPE_PRECEDENCE: tuple[SettingScope, ...] = (
    SettingScope.SYSTEM,
    SettingScope.GLOBAL,
    SettingScope.PROJECT,
    SettingScope.AGENT_TYPE,
    SettingScope.AGENT,
    SettingScope.PLUGIN,
    SettingScope.SESSION,
    SettingScope.TASK,
)

CONFIG_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ValidationRule:
    kind: str
    value: Any = None
    message: str = ""


@dataclass(slots=True)
class SettingDefinition:
    id: str
    storage_key: str
    category: str
    label: str
    description: str
    type: SettingType
    default_value: Any
    allow_unlimited: bool = False
    min: float | int | None = None
    max: float | int | None = None  # soft guidance / hard max when overrideable=False for safety
    enum_values: list[str] = field(default_factory=list)
    scopes: list[SettingScope] = field(default_factory=lambda: [SettingScope.GLOBAL])
    source: SettingSource = SettingSource.SYSTEM_DEFAULT
    restart_required: bool = False
    apply_mode: ApplyMode = ApplyMode.IMMEDIATE
    risk_level: RiskLevel = RiskLevel.LOW
    overrideable: bool = True
    validation: list[ValidationRule] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    unit: str = ""
    legacy_keys: list[str] = field(default_factory=list)
    ui_group: str = ""
    tags: list[str] = field(default_factory=list)
    # None = not yet audited for runtime enforcement; True = enforced (must have
    # a SETTING_CONSUMERS entry); False = stored only / not enforced.
    implemented: bool | None = None

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        data["scopes"] = [s.value for s in self.scopes]
        data["source"] = self.source.value
        data["apply_mode"] = self.apply_mode.value
        data["risk_level"] = self.risk_level.value
        data["validation"] = [asdict(v) for v in self.validation]
        return data


@dataclass(slots=True)
class ResolveContext:
    project_id: str | None = None
    agent_type: str | None = None
    agent_id: str | None = None
    plugin_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    model_id: str | None = None
    provider: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EffectiveValue:
    setting_id: str
    configured: Any
    effective: Any
    source: SettingSource
    scope: SettingScope
    overrideable: bool
    clamped: bool = False
    clamp_reason: str | None = None
    capability_max: Any = None
    unlimited_requested: bool = False
    inheritance: list[dict[str, Any]] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return {
            "setting_id": self.setting_id,
            "configured": self.configured,
            "effective": self.effective,
            "source": self.source.value,
            "scope": self.scope.value,
            "overrideable": self.overrideable,
            "clamped": self.clamped,
            "clamp_reason": self.clamp_reason,
            "capability_max": self.capability_max,
            "unlimited_requested": self.unlimited_requested,
            "inheritance": self.inheritance,
        }


@dataclass(slots=True)
class ImmutableConstraint:
    id: str
    label: str
    value: Any
    reason: str
    enforcement_location: str
    source: Literal["hades", "external"]
    category: str = "security"
    threat_or_correctness_rationale: str = ""
    test_location: str = ""
    why_not_configurable: str = ""

    def to_public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LimitEvent:
    """Recorded when a HADES-owned limit stops or clamps execution."""

    constraint_id: str
    configured: Any
    effective: Any
    current: Any
    scope: str
    source: str
    enforced_by: str
    message: str
    task_id: str | None = None
    agent_id: str | None = None
    timestamp: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityDescriptor:
    id: str
    kind: ConstraintKind
    label: str
    supported: bool = True
    provider_max: Any = None
    runtime_max: Any = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


ValidatorFn = Callable[[Any, SettingDefinition], Any]
