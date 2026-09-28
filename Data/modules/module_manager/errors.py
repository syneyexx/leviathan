"""Authoritative module lifecycle error contract.

Adapters and installers raise implementation-specific failures (InstallError,
VersionError, and other objects carrying an ExternalFailureCode). ModuleManager
normalizes those into ModuleManagerError before they cross into routes,
JobRuntime, or cognition. Unexpected programming defects are not rewritten
into operational HTTP statuses.
"""

from __future__ import annotations

import re
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key|authorization|credential)\b\s*[:=]\s*\S+"
)

# Keep aligned with ExternalFailureCode. Do not import the external package
# here: its package init loads adapters that import this module.
_KNOWN_CODES = frozenset(
    {
        "NOT_INSTALLED",
        "START_FAILED",
        "HEALTH_FAILED",
        "TIMEOUT",
        "CANCELLED",
        "EXIT_NONZERO",
        "INVALID_RESULT",
        "REMOTE_ERROR",
        "DEPENDENCY_MISSING",
        "DEPENDENCY_UNSUPPORTED",
        "DEPENDENCY_VERIFY_FAILED",
        "PACKAGE_MANAGER_UNAVAILABLE",
        "PACKAGE_MANAGER_BUSY",
        "PACKAGE_METADATA_REFRESH_FAILED",
        "PACKAGE_INSTALL_FAILED",
        "PRIVILEGE_REQUIRED",
        "APPROVAL_REQUIRED",
        "APPROVAL_INVALID",
        "APPROVAL_EXPIRED",
        "APPROVAL_SERVICE_UNAVAILABLE",
        "PLAN_STALE_REAPPROVAL_REQUIRED",
        "SOURCE_UNAVAILABLE",
        "INSTALL_WORKER_UNAVAILABLE",
        "INSTALL_QUEUE_FAILED",
        "INSTALL_CONFLICT",
        "NETWORK_POLICY_BLOCKED",
        "INSTALLED_RESTART_REQUIRED",
        "CAPABILITY_NOT_FOUND",
        "PROTOCOL_ERROR",
        "CANCEL_UNSUPPORTED",
        "INSTALL_FAILED",
        "VERIFY_FAILED",
        "ROLLBACK_PARTIAL",
        "UPDATE_BLOCKED_ACTIVE",
        "NOT_AVAILABLE",
        "PORT_IN_USE",
    }
)
_SUCCESS_STATUSES = frozenset(
    {
        "INSTALLED",
        "READY",
        "RUNNING",
        "STOPPED",
        "OK",
        "COMPLETED",
        "SUCCESS",
        "ACTIVE",
        "DISABLED",
    }
)
_FAILURE_STATUSES = frozenset({"FAILED", "ERROR"})

# Codes that mean "the requested lifecycle action cannot be completed".
_CONFLICT_CODES = frozenset(
    {
        "INSTALL_FAILED",
        "START_FAILED",
        "EXIT_NONZERO",
        "PORT_IN_USE",
        "CANCELLED",
        "CANCEL_UNSUPPORTED",
        "NOT_INSTALLED",
        "UPDATE_BLOCKED_ACTIVE",
        "INSTALL_CONFLICT",
        "PLAN_STALE_REAPPROVAL_REQUIRED",
        "APPROVAL_REQUIRED",
        "APPROVAL_INVALID",
        "APPROVAL_EXPIRED",
    }
)
# Required external dependency or remote service is unavailable.
_DEPENDENCY_CODES = frozenset(
    {
        "DEPENDENCY_MISSING",
        "DEPENDENCY_UNSUPPORTED",
        "DEPENDENCY_VERIFY_FAILED",
        "PACKAGE_MANAGER_UNAVAILABLE",
        "PACKAGE_MANAGER_BUSY",
        "PACKAGE_METADATA_REFRESH_FAILED",
        "PACKAGE_INSTALL_FAILED",
        "PRIVILEGE_REQUIRED",
        "SOURCE_UNAVAILABLE",
        "NETWORK_POLICY_BLOCKED",
        "INSTALLED_RESTART_REQUIRED",
        "NOT_AVAILABLE",
        "PROTOCOL_ERROR",
        "HEALTH_FAILED",
        "REMOTE_ERROR",
        "APPROVAL_SERVICE_UNAVAILABLE",
        "INSTALL_WORKER_UNAVAILABLE",
        "INSTALL_QUEUE_FAILED",
        "VERIFY_FAILED",
        "ROLLBACK_PARTIAL",
    }
)


def scrub_error_text(text: str, *, limit: int = 400) -> str:
    """Bound a diagnostic string and strip credential-like assignments."""
    cleaned = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", str(text or ""))
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1] + "…"
    return cleaned


def bounded_process_output(stderr: str | None, stdout: str | None, *, limit: int = 400) -> str:
    raw = (stderr or "").strip() or (stdout or "").strip()
    return scrub_error_text(raw, limit=limit) or "no output"


class ModuleManagerError(RuntimeError):
    """Lifecycle failure that has crossed the ModuleManager boundary.

    ``str(exc)`` stays a single human-readable line (``CODE: message`` when a
    code is known). ``public_dict()`` is the HTTP/API contract.
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: str = "MODULE_ERROR",
        module_id: str | None = None,
        action: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code = str(code or "MODULE_ERROR")
        self.module_id = module_id
        self.action = action
        human = detail if detail is not None else _strip_code_prefix(message, self.code)
        self.detail = scrub_error_text(human or message or self.code)
        text = self.detail
        if self.code and self.code != "MODULE_ERROR" and not text.startswith(f"{self.code}:"):
            text = f"{self.code}: {text}" if text else self.code
        elif not text:
            text = message or self.code
        super().__init__(text)

    def public_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.detail,
        }
        if self.module_id:
            body["module_id"] = self.module_id
        if self.action:
            body["action"] = self.action
        return body


def _strip_code_prefix(message: str, code: str) -> str:
    text = str(message or "").strip()
    prefix = f"{code}:"
    if text.startswith(prefix):
        return text[len(prefix) :].strip()
    return text


def _code_of(exc: BaseException) -> str | None:
    raw = getattr(exc, "code", None)
    if raw is None:
        return None
    value = str(getattr(raw, "value", raw) or "").strip()
    if value in _KNOWN_CODES:
        return value
    return None


def coerce_lifecycle_error(
    exc: BaseException,
    *,
    module_id: str | None,
    action: str,
) -> ModuleManagerError | None:
    """Return a lifecycle error, or None when ``exc`` is an unexpected defect."""
    if isinstance(exc, ModuleManagerError):
        if exc.module_id == module_id and exc.action == action:
            return exc
        return ModuleManagerError(
            str(exc),
            code=exc.code,
            module_id=exc.module_id or module_id,
            action=exc.action or action,
            detail=exc.detail,
        )
    code = _code_of(exc)
    if code is None and type(exc).__name__ in {"InstallError", "VersionError"}:
        code = "INSTALL_FAILED"
    if code is None:
        return None
    raw_detail = getattr(exc, "message", None)
    detail = scrub_error_text(_strip_code_prefix(str(raw_detail if raw_detail is not None else exc), code))
    return ModuleManagerError(
        f"{code}: {detail}" if detail else code,
        code=code,
        module_id=module_id,
        action=action,
        detail=detail or code,
    )


def http_status_for_lifecycle_error(exc: ModuleManagerError) -> int:
    """Map a normalized lifecycle error onto an HTTP status.

    500 is reserved for unexpected defects that are not ModuleManagerError.
    """
    code = (exc.code or "MODULE_ERROR").upper()
    message = f"{exc.detail} {exc}".lower()
    if code == "UNKNOWN_MODULE" or message.startswith("unknown module"):
        return 404
    if code == "CAPABILITY_NOT_FOUND":
        return 404
    if code == "NOT_INSTALLED" and any(
        token in message
        for token in ("unknown version", "no versions", "no rollback", "unknown module")
    ):
        return 404
    if code == "UPDATE_BLOCKED_ACTIVE":
        return 409
    if code in {"INSTALL_WORKER_UNAVAILABLE", "INSTALL_QUEUE_FAILED"}:
        return 503
    if code in _DEPENDENCY_CODES:
        return 424
    if code == "TIMEOUT":
        return 504
    if code in _CONFLICT_CODES:
        return 409
    if code == "INVALID_RESULT" or any(
        token in message for token in ("invalid", "does not support", "unsupported", "not installable")
    ):
        return 422
    return 400


def failure_from_lifecycle_result(result: Any) -> tuple[str, str] | None:
    """Detect a failed install/start payload that was returned instead of raised."""
    if not isinstance(result, dict):
        return None
    children = result.get("children")
    if isinstance(children, list):
        for child in children:
            found = failure_from_lifecycle_result(child)
            if found is not None:
                return found
    status = str(result.get("status") or "").upper()
    raw_code = result.get("code")
    code = str(raw_code).strip().upper() if raw_code else ""
    if code not in _KNOWN_CODES:
        code = ""
    if status in _FAILURE_STATUSES or (code and status not in _SUCCESS_STATUSES):
        detail_raw = result.get("detail") or result.get("message") or result.get("error") or "lifecycle failed"
        if not isinstance(detail_raw, str):
            detail_raw = str(detail_raw)
        return (code or "INSTALL_FAILED"), scrub_error_text(detail_raw)
    return None


def unknown_module_error(module_id: str, *, action: str) -> ModuleManagerError:
    return ModuleManagerError(
        f"Unknown module: {module_id}",
        code="UNKNOWN_MODULE",
        module_id=module_id,
        action=action,
        detail=f"Unknown module: {module_id}",
    )
