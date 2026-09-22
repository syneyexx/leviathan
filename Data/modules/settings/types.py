"""Types for the LEVIATHAN Settings Control Plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SettingType(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    PATH = "path"
    URL = "url"
    SECRET = "secret"
    STRING_LIST = "string_list"
    ENUM = "enum"


class ApplyMode(str, Enum):
    HOT = "hot"
    SUBSYSTEM_RELOAD = "subsystem_reload"
    RESTART_REQUIRED = "restart_required"
    BOOTSTRAP_ONLY = "bootstrap_only"


class SettingSource(str, Enum):
    DEFAULT = "default"
    ENVIRONMENT = "environment"
    OVERRIDE = "override"
    LOCKED = "locked"


class MutationStatus(str, Enum):
    SAVED = "SAVED"
    APPLIED = "APPLIED"
    RESTART_REQUIRED = "RESTART_REQUIRED"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"
    FAILED = "FAILED"
    RESET = "RESET"


@dataclass(frozen=True)
class CategoryInfo:
    id: str
    label: str
    description: str
    order: int


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    category: str
    label: str
    description: str
    value_type: SettingType
    default: Any
    env_name: str | None = None
    path: tuple[str, ...] = ()
    secret: bool = False
    min_value: float | int | None = None
    max_value: float | int | None = None
    enum_values: tuple[str, ...] = ()
    dangerous: bool = False
    apply_mode: ApplyMode = ApplyMode.HOT
    editable: bool = True
    public: bool = True
    requires: tuple[str, ...] = ()
    requires_any_of: tuple[str, ...] = ()
    consumer: str = ""
    experimental: bool = False


@dataclass
class SettingState:
    key: str
    category: str
    label: str
    description: str
    value_type: str
    default_value: Any
    desired_value: Any
    effective_value: Any
    source: str
    editable: bool
    secret: bool
    configured: bool | None
    restart_required: bool
    apply_mode: str
    status: str
    dangerous: bool
    experimental: bool
    requires: list[str] = field(default_factory=list)
    enum_values: list[str] = field(default_factory=list)
    min_value: float | int | None = None
    max_value: float | int | None = None
    consumer: str = ""
    effective_now: bool = True

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "type": self.value_type,
            "default_value": None if self.secret else self.default_value,
            "desired_value": None if self.secret else self.desired_value,
            "effective_value": None if self.secret else self.effective_value,
            "source": self.source,
            "editable": self.editable,
            "secret": self.secret,
            "restart_required": self.restart_required,
            "apply_mode": self.apply_mode,
            "status": self.status,
            "dangerous": self.dangerous,
            "experimental": self.experimental,
            "requires": list(self.requires),
            "enum_values": list(self.enum_values),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "consumer": self.consumer,
            "effective_now": self.effective_now,
        }
        if self.secret:
            payload["configured"] = bool(self.configured)
        return payload


@dataclass
class MutationResult:
    key: str
    status: MutationStatus
    message: str
    desired_value: Any = None
    effective_value: Any = None
    restart_required: bool = False
    saved: bool = False
    applied: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status.value,
            "message": self.message,
            "desired_value": self.desired_value,
            "effective_value": self.effective_value,
            "restart_required": self.restart_required,
            "saved": self.saved,
            "applied": self.applied,
        }


class SettingsError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}
