"""Fincept / external financial intelligence lifecycle (Wave 7).

Fincept is an external research capability — never execution authority.
Lifecycle: need → discover → admit → call → normalize → immutable artifact →
Evidence → provenance → optional Brain assimilation → agent citations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Sequence


class FinceptResultState(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    UNHEALTHY = "UNHEALTHY"


class FinceptAvailabilityState(str, Enum):
    """Honest capability availability — discovery state is not authorization.

    UNKNOWN must never be promoted to AVAILABLE.
    """

    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    UNHEALTHY = "UNHEALTHY"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


FINCEPT_MODULE_ID = "fincept-terminal"
FINCEPT_CAPABILITIES = (
    "external.fincept.analyze",
    "external.fincept.quant",
    "external.fincept.stats",
    "external.fincept.fixed_income",
)

# ModuleManager lifecycle → Fincept availability. Missing / ambiguous → UNKNOWN.
_MODULE_STATUS_TO_AVAILABILITY: dict[str, FinceptAvailabilityState] = {
    "READY": FinceptAvailabilityState.AVAILABLE,
    "RUNNING": FinceptAvailabilityState.AVAILABLE,
    "BUSY": FinceptAvailabilityState.AVAILABLE,
    "EXECUTING": FinceptAvailabilityState.AVAILABLE,
    "INITIALIZED": FinceptAvailabilityState.AVAILABLE,
    "INSTALLED": FinceptAvailabilityState.UNAVAILABLE,  # installed ≠ ready to call
    "LOADED": FinceptAvailabilityState.UNAVAILABLE,
    "DISCOVERED": FinceptAvailabilityState.UNAVAILABLE,
    "STARTING": FinceptAvailabilityState.UNAVAILABLE,
    "INITIALIZING": FinceptAvailabilityState.UNAVAILABLE,
    "STOPPING": FinceptAvailabilityState.UNAVAILABLE,
    "STOPPED": FinceptAvailabilityState.UNAVAILABLE,
    "SHUTDOWN": FinceptAvailabilityState.UNAVAILABLE,
    "DISABLED": FinceptAvailabilityState.DISABLED,
    "DEGRADED": FinceptAvailabilityState.UNHEALTHY,
    "FAILED": FinceptAvailabilityState.FAILED,
    "ERROR": FinceptAvailabilityState.FAILED,
}

_HEALTH_STATUS_TO_AVAILABILITY: dict[str, FinceptAvailabilityState] = {
    "READY": FinceptAvailabilityState.AVAILABLE,
    "RUNNING": FinceptAvailabilityState.AVAILABLE,
    "BUSY": FinceptAvailabilityState.AVAILABLE,
    "INSTALLED": FinceptAvailabilityState.AVAILABLE,
    "INITIALIZED": FinceptAvailabilityState.AVAILABLE,
    "DEGRADED": FinceptAvailabilityState.UNHEALTHY,
    "FAILED": FinceptAvailabilityState.FAILED,
    "ERROR": FinceptAvailabilityState.FAILED,
    "DISABLED": FinceptAvailabilityState.DISABLED,
    "STOPPED": FinceptAvailabilityState.UNAVAILABLE,
    "UNKNOWN": FinceptAvailabilityState.UNKNOWN,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FinceptInvocationRequest:
    """Justified analytical need — not invoked on every trading decision."""

    capability_id: str
    role: str
    objective: str
    command: str
    parameters: dict[str, Any] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    decision_as_of: str | None = None
    experiment_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    justified: bool = True
    justification: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "role": self.role,
            "objective": self.objective,
            "command": self.command,
            "parameters": dict(self.parameters),
            "symbols": list(self.symbols),
            "decisionAsOf": self.decision_as_of,
            "experimentId": self.experiment_id,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "justified": self.justified,
            "justification": self.justification,
            "truth": {
                "finceptIsNotExecutionAuthority": True,
                "riskGuardRemainsDeterministic": True,
                "notInvokedOnEveryDecision": True,
            },
        }


@dataclass
class FinceptArtifact:
    artifact_id: str
    module_id: str
    module_version: str | None
    capability_id: str
    command: str
    parameters: dict[str, Any]
    started_at: str
    ended_at: str
    result_state: FinceptResultState
    content_hash: str
    normalized: dict[str, Any] = field(default_factory=dict)
    raw_ref: str | None = None
    evidence_id: str | None = None
    external_source_ref: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "moduleId": self.module_id,
            "moduleVersion": self.module_version,
            "capabilityId": self.capability_id,
            "command": self.command,
            "parameters": dict(self.parameters),
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "resultState": self.result_state.value,
            "contentHash": self.content_hash,
            "normalized": dict(self.normalized),
            "rawRef": self.raw_ref,
            "evidenceId": self.evidence_id,
            "externalSourceRef": self.external_source_ref,
            "error": self.error,
            "metadata": dict(self.metadata),
            "truth": {
                "immutableArtifact": True,
                "noSilentSubstitution": True,
            },
        }


def _availability_public(
    state: FinceptAvailabilityState,
    *,
    capabilities: list[dict[str, Any]] | None = None,
    operator_action: str | None = None,
    detail: str | None = None,
    module_status: str | None = None,
    health_status: str | None = None,
) -> dict[str, Any]:
    # UNKNOWN / non-ready never count as available — including silent None.
    available = state is FinceptAvailabilityState.AVAILABLE
    return {
        "moduleId": FINCEPT_MODULE_ID,
        "available": available,
        "state": state.value,
        "capabilities": list(capabilities or []),
        "operatorAction": operator_action,
        "detail": detail,
        "moduleStatus": module_status,
        "healthStatus": health_status,
        "truth": {
            "finceptIsNotExecutionAuthority": True,
            "unknownMustNotBecomeAvailable": True,
            "discoverableIsNotAuthorized": True,
        },
    }


def map_module_status_to_fincept_availability(
    module_status: str | None,
    *,
    health_status: str | None = None,
) -> FinceptAvailabilityState:
    """Map ModuleManager lifecycle/health to Fincept availability honestly.

    UNKNOWN and unrecognized statuses stay UNKNOWN — never AVAILABLE.
    Explicit health overrides when present and more severe / definitive.
    """
    raw = str(module_status or "").strip().upper() or "UNKNOWN"
    state = _MODULE_STATUS_TO_AVAILABILITY.get(raw, FinceptAvailabilityState.UNKNOWN)

    health = str(health_status or "").strip().upper()
    if health:
        health_state = _HEALTH_STATUS_TO_AVAILABILITY.get(health, FinceptAvailabilityState.UNKNOWN)
        # Health can only demote AVAILABLE, or clarify UNKNOWN — never invent AVAILABLE
        # from UNKNOWN module status alone.
        if state is FinceptAvailabilityState.AVAILABLE:
            if health_state is FinceptAvailabilityState.UNKNOWN:
                return FinceptAvailabilityState.UNKNOWN
            if health_state is not FinceptAvailabilityState.AVAILABLE:
                return health_state
        elif state is FinceptAvailabilityState.UNKNOWN and health_state is FinceptAvailabilityState.AVAILABLE:
            # Health READY without a ready module lifecycle is not enough.
            return FinceptAvailabilityState.UNKNOWN
        elif health_state in {
            FinceptAvailabilityState.DISABLED,
            FinceptAvailabilityState.FAILED,
            FinceptAvailabilityState.UNHEALTHY,
            FinceptAvailabilityState.PERMISSION_DENIED,
            FinceptAvailabilityState.TIMEOUT,
        }:
            return health_state
    return state


def _fincept_caps_from_manifest(manifest: Any) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    announcements = getattr(manifest, "capabilities", None) or ()
    for ann in announcements:
        if hasattr(ann, "public_dict"):
            row = ann.public_dict()
        elif isinstance(ann, dict):
            row = dict(ann)
        else:
            continue
        cid = str(row.get("capability_id") or row.get("capabilityId") or "")
        if cid.startswith("external.fincept."):
            caps.append(row)
    return caps


def discover_fincept_capabilities(
    catalog: Sequence[dict[str, Any]] | None = None,
    *,
    module_enabled: bool | None = None,
    module_installed: bool | None = None,
    module_manager: Any | None = None,
) -> dict[str, Any]:
    """Return Fincept capabilities with honest availability via ModuleManager when bound."""
    if module_enabled is False:
        return _availability_public(
            FinceptAvailabilityState.DISABLED,
            operator_action="Enable fincept-terminal in module settings.",
        )
    if module_installed is False:
        return _availability_public(
            FinceptAvailabilityState.UNAVAILABLE,
            operator_action=(
                "Install external module fincept-terminal "
                "(Fincept-Corporation/FinceptTerminal analytics CLIs)."
            ),
        )

    if module_manager is not None:
        return discover_fincept_via_module_manager(module_manager, catalog=catalog)

    # Without ModuleManager, capability rows alone are not proof of runtime readiness.
    # UNKNOWN / catalog-declared must never become AVAILABLE unless module_installed=True.
    caps: list[dict[str, Any]] = []
    if catalog:
        for row in catalog:
            cid = str(row.get("capability_id") or row.get("capabilityId") or "")
            if cid.startswith("external.fincept."):
                caps.append(row if isinstance(row, dict) else {"capability_id": cid})
    else:
        caps = [{"capability_id": c, "module_id": FINCEPT_MODULE_ID} for c in FINCEPT_CAPABILITIES]

    if module_installed is True and module_enabled is not False:
        return _availability_public(
            FinceptAvailabilityState.AVAILABLE,
            capabilities=caps,
        )
    return _availability_public(
        FinceptAvailabilityState.UNKNOWN,
        capabilities=caps,
        operator_action=(
            "Bind ModuleManager or set module_installed=True after verifying fincept-terminal."
        ),
        detail="catalog_declared_without_runtime_proof",
    )


def discover_fincept_via_module_manager(
    module_manager: Any,
    *,
    catalog: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capability discovery through ModuleManager — evidence-only, never execution authority."""
    if module_manager is None:
        return _availability_public(
            FinceptAvailabilityState.UNKNOWN,
            operator_action="ModuleManager not bound.",
            detail="module_manager_unbound",
        )
    if getattr(module_manager, "enabled", True) is False:
        return _availability_public(
            FinceptAvailabilityState.DISABLED,
            operator_action="Enable ModuleManager / fincept-terminal in module settings.",
            detail="module_manager_disabled",
        )

    managed = None
    try:
        getter = getattr(module_manager, "get", None)
        if callable(getter):
            managed = getter(FINCEPT_MODULE_ID)
    except Exception as exc:  # noqa: BLE001
        return _availability_public(
            FinceptAvailabilityState.FAILED,
            operator_action="Inspect ModuleManager errors for fincept-terminal.",
            detail=f"module_manager_get_error:{exc}",
        )

    if managed is None:
        # Attempt discovery so DISCOVERED manifests surface as UNAVAILABLE, not UNKNOWN.
        try:
            discover = getattr(module_manager, "discover", None)
            if callable(discover):
                discover()
            getter = getattr(module_manager, "get", None)
            if callable(getter):
                managed = getter(FINCEPT_MODULE_ID)
        except Exception as exc:  # noqa: BLE001
            return _availability_public(
                FinceptAvailabilityState.FAILED,
                detail=f"discover_error:{exc}",
                operator_action="Install external module fincept-terminal.",
            )

    if managed is None:
        return _availability_public(
            FinceptAvailabilityState.UNAVAILABLE,
            operator_action=(
                "Install external module fincept-terminal "
                "(Fincept-Corporation/FinceptTerminal analytics CLIs)."
            ),
            detail="module_not_found",
        )

    module_status = str(getattr(managed, "status", None) or "")
    if hasattr(module_status, "value"):
        module_status = str(getattr(module_status, "value"))
    else:
        status_obj = getattr(managed, "status", None)
        module_status = str(getattr(status_obj, "value", status_obj) or "")

    health_status: str | None = None
    try:
        health_fn = getattr(module_manager, "health", None)
        if callable(health_fn) and module_status.upper() in {
            "READY",
            "RUNNING",
            "BUSY",
            "EXECUTING",
            "INITIALIZED",
            "DEGRADED",
            "INSTALLED",
        }:
            health = health_fn(FINCEPT_MODULE_ID)
            if health is not None:
                if hasattr(health, "status"):
                    hs = health.status
                    health_status = str(getattr(hs, "value", hs) or "")
                elif isinstance(health, dict):
                    health_status = str(health.get("status") or "")
    except Exception:  # noqa: BLE001
        # Failed health probe after claimed-ready → UNHEALTHY, not AVAILABLE.
        health_status = "FAILED"

    state = map_module_status_to_fincept_availability(module_status, health_status=health_status)

    caps: list[dict[str, Any]] = []
    manifest = getattr(managed, "manifest", None)
    if manifest is not None:
        caps = _fincept_caps_from_manifest(manifest)
    if not caps and catalog:
        for row in catalog:
            cid = str(row.get("capability_id") or row.get("capabilityId") or "")
            if cid.startswith("external.fincept."):
                caps.append(row if isinstance(row, dict) else {"capability_id": cid})
    if not caps:
        caps = [{"capability_id": c, "module_id": FINCEPT_MODULE_ID} for c in FINCEPT_CAPABILITIES]

    operator = None
    if state is FinceptAvailabilityState.DISABLED:
        operator = "Enable fincept-terminal in module settings."
    elif state is FinceptAvailabilityState.UNAVAILABLE:
        operator = "Install/activate fincept-terminal and ensure ModuleManager reports READY."
    elif state is FinceptAvailabilityState.UNHEALTHY:
        operator = "fincept-terminal is degraded/unhealthy — repair before research use."
    elif state is FinceptAvailabilityState.FAILED:
        operator = "fincept-terminal failed — inspect ModuleManager health/logs."
    elif state is FinceptAvailabilityState.UNKNOWN:
        operator = "fincept-terminal status UNKNOWN — do not treat as available."
    elif state is FinceptAvailabilityState.PERMISSION_DENIED:
        operator = "Permission denied for fincept-terminal capabilities."
    elif state is FinceptAvailabilityState.TIMEOUT:
        operator = "fincept-terminal health/discovery timed out."

    return _availability_public(
        state,
        capabilities=caps,
        operator_action=operator,
        module_status=module_status or None,
        health_status=health_status,
    )


def build_module_manager_fincept_executor(module_manager: Any) -> Callable[[FinceptInvocationRequest], Any]:
    """Bind FinceptEvidenceBridge.executor to ModuleManager.execute (evidence-only)."""

    def _execute(request: FinceptInvocationRequest) -> Any:
        if module_manager is None:
            raise RuntimeError("FINCEPT_MODULE_MANAGER_UNBOUND")
        discovery = discover_fincept_via_module_manager(module_manager)
        state = str(discovery.get("state") or FinceptAvailabilityState.UNKNOWN.value)
        if state == FinceptAvailabilityState.AVAILABLE.value:
            pass
        elif state == FinceptAvailabilityState.DISABLED.value:
            raise PermissionError("FINCEPT_DISABLED")
        elif state == FinceptAvailabilityState.PERMISSION_DENIED.value:
            raise PermissionError("FINCEPT_PERMISSION_DENIED")
        elif state == FinceptAvailabilityState.TIMEOUT.value:
            raise TimeoutError("FINCEPT_TIMEOUT")
        elif state == FinceptAvailabilityState.UNHEALTHY.value:
            raise RuntimeError("FINCEPT_UNHEALTHY")
        elif state == FinceptAvailabilityState.FAILED.value:
            raise RuntimeError("FINCEPT_FAILED")
        elif state == FinceptAvailabilityState.UNKNOWN.value:
            # CRITICAL: UNKNOWN must not proceed as if AVAILABLE.
            raise RuntimeError("FINCEPT_UNKNOWN_NOT_AVAILABLE")
        else:
            raise RuntimeError(f"FINCEPT_UNAVAILABLE:{state}")

        op = str(request.command or "").strip() or "analyze"
        # capability_id external.fincept.<op> → module operation name
        cap = str(request.capability_id or "")
        if cap.startswith("external.fincept."):
            op = cap.rsplit(".", 1)[-1] or op
        arguments = {
            "command": request.command,
            "parameters": dict(request.parameters),
            "symbols": list(request.symbols),
            "decision_as_of": request.decision_as_of,
            "experiment_id": request.experiment_id,
            "run_id": request.run_id,
            "trace_id": request.trace_id,
            "role": request.role,
            "objective": request.objective,
            "justification": request.justification,
            "capability_id": request.capability_id,
        }
        result = module_manager.execute(FINCEPT_MODULE_ID, op, arguments)
        status = str(getattr(result, "status", None) or (result.get("status") if isinstance(result, dict) else "") or "")
        status_u = status.upper()
        if status_u in {"TIMEOUT"}:
            raise TimeoutError("FINCEPT_EXEC_TIMEOUT")
        if status_u in {"FAILED", "ERROR"}:
            err = getattr(result, "error", None) or (result.get("error") if isinstance(result, dict) else None)
            raise RuntimeError(str(err or "FINCEPT_EXEC_FAILED")[:500])
        if status_u in {"REJECTED", "PERMISSION_DENIED"}:
            raise PermissionError(str(getattr(result, "error", None) or "FINCEPT_PERMISSION_DENIED")[:500])
        if hasattr(result, "output"):
            return result.output if result.output is not None else result.public_dict()
        if isinstance(result, dict):
            return result.get("output") if result.get("output") is not None else result
        return result

    return _execute


def should_invoke_fincept(*, role: str, objective: str, request_justified: bool) -> bool:
    """Agents discover Fincept when relevant — not on every trading decision."""
    if not request_justified:
        return False
    role_l = str(role or "").lower()
    obj_l = str(objective or "").lower()
    role_ok = role_l in {
        "strategy_researcher",
        "evaluator",
        "market_analyst",
        "portfolio_manager",
        "researcher",
    }
    keywords = (
        "ratio",
        "quant",
        "fixed income",
        "fixed_income",
        "stats",
        "statistical",
        "fundamental",
        "fincept",
        "analytics",
        "yield",
        "duration",
    )
    return role_ok and any(k in obj_l for k in keywords)


def normalize_fincept_output(
    raw: Any,
    *,
    capability_id: str,
    command: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if raw is None:
        return {"status": "empty", "capabilityId": capability_id, "command": command}
    if isinstance(raw, dict):
        payload = dict(raw)
    elif isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"text": raw[:8000]}
    else:
        payload = {"value": str(raw)[:8000]}
    return {
        "capabilityId": capability_id,
        "command": command,
        "parameters": dict(parameters),
        "result": payload,
        "normalizedAt": utc_now(),
    }


def content_hash_for(normalized: dict[str, Any]) -> str:
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class FinceptEvidenceBridge:
    """Records Fincept results as Evidence + optional Brain assimilation hooks.

    Does not grant execution authority. Disabled/uninstalled modules return
    explicit UNAVAILABLE — never silent invented analytics.
    """

    evidence_writer: Callable[[dict[str, Any]], str] | None = None
    artifact_writer: Callable[[dict[str, Any]], str] | None = None
    brain_assimilator: Callable[[dict[str, Any]], Any] | None = None
    executor: Callable[[FinceptInvocationRequest], Any] | None = None
    module_enabled: bool = True
    module_installed: bool = True
    module_version: str | None = None
    external_source_ref: str = "https://github.com/Fincept-Corporation/FinceptTerminal"
    module_manager: Any | None = None
    last_availability: dict[str, Any] = field(default_factory=dict)

    def bind_from_module_manager(self, module_manager: Any | None) -> dict[str, Any]:
        """Discover Fincept via ModuleManager and bind executor when AVAILABLE.

        UNKNOWN / UNHEALTHY / FAILED / DISABLED never receive an AVAILABLE executor.
        """
        self.module_manager = module_manager
        discovery = discover_fincept_capabilities(module_manager=module_manager)
        self.last_availability = dict(discovery)
        state = str(discovery.get("state") or FinceptAvailabilityState.UNKNOWN.value)
        if state == FinceptAvailabilityState.DISABLED.value:
            self.module_enabled = False
            self.module_installed = True
            self.executor = None
        elif state == FinceptAvailabilityState.UNAVAILABLE.value:
            self.module_enabled = True
            self.module_installed = False
            self.executor = None
        elif state == FinceptAvailabilityState.AVAILABLE.value:
            self.module_enabled = True
            self.module_installed = True
            if module_manager is not None:
                self.executor = build_module_manager_fincept_executor(module_manager)
        else:
            # UNKNOWN / UNHEALTHY / FAILED / TIMEOUT / PERMISSION_DENIED:
            # keep installed flag honest but do not claim AVAILABLE executor.
            self.module_enabled = True
            self.module_installed = state != FinceptAvailabilityState.UNAVAILABLE.value
            self.executor = None
            if state == FinceptAvailabilityState.UNKNOWN.value:
                # Explicit: UNKNOWN must not become AVAILABLE via unbound executor path.
                self.module_installed = False
        return discovery

    def availability(self) -> dict[str, Any]:
        if self.module_manager is not None:
            self.last_availability = discover_fincept_capabilities(module_manager=self.module_manager)
            return dict(self.last_availability)
        if self.last_availability:
            return dict(self.last_availability)
        return discover_fincept_capabilities(
            module_enabled=self.module_enabled,
            module_installed=self.module_installed,
        )

    def invoke(self, request: FinceptInvocationRequest) -> FinceptArtifact:
        started = utc_now()
        # Re-check ModuleManager availability when bound — never trust a stale AVAILABLE.
        if self.module_manager is not None:
            discovery = self.availability()
            state = str(discovery.get("state") or FinceptAvailabilityState.UNKNOWN.value)
            if state == FinceptAvailabilityState.DISABLED.value:
                return self._terminal(request, started, FinceptResultState.DISABLED, error="FINCEPT_DISABLED")
            if state == FinceptAvailabilityState.UNAVAILABLE.value:
                return self._terminal(
                    request,
                    started,
                    FinceptResultState.UNAVAILABLE,
                    error="FINCEPT_UNAVAILABLE: install fincept-terminal",
                )
            if state == FinceptAvailabilityState.UNHEALTHY.value:
                return self._terminal(request, started, FinceptResultState.UNHEALTHY, error="FINCEPT_UNHEALTHY")
            if state == FinceptAvailabilityState.FAILED.value:
                return self._terminal(request, started, FinceptResultState.FAILED, error="FINCEPT_FAILED")
            if state == FinceptAvailabilityState.TIMEOUT.value:
                return self._terminal(request, started, FinceptResultState.TIMEOUT, error="FINCEPT_TIMEOUT")
            if state == FinceptAvailabilityState.PERMISSION_DENIED.value:
                return self._terminal(
                    request,
                    started,
                    FinceptResultState.PERMISSION_DENIED,
                    error="FINCEPT_PERMISSION_DENIED",
                )
            if state == FinceptAvailabilityState.UNKNOWN.value:
                return self._terminal(
                    request,
                    started,
                    FinceptResultState.UNAVAILABLE,
                    error="FINCEPT_UNKNOWN_NOT_AVAILABLE",
                )
            if state != FinceptAvailabilityState.AVAILABLE.value:
                return self._terminal(
                    request,
                    started,
                    FinceptResultState.UNAVAILABLE,
                    error=f"FINCEPT_NOT_AVAILABLE:{state}",
                )
            if self.executor is None and self.module_manager is not None:
                self.executor = build_module_manager_fincept_executor(self.module_manager)

        if not self.module_enabled:
            return self._terminal(
                request,
                started,
                FinceptResultState.DISABLED,
                error="FINCEPT_DISABLED",
            )
        if not self.module_installed:
            return self._terminal(
                request,
                started,
                FinceptResultState.UNAVAILABLE,
                error="FINCEPT_UNAVAILABLE: install fincept-terminal",
            )
        if not should_invoke_fincept(
            role=request.role,
            objective=request.objective,
            request_justified=request.justified,
        ):
            return self._terminal(
                request,
                started,
                FinceptResultState.PERMISSION_DENIED,
                error="FINCEPT_NOT_JUSTIFIED_FOR_ROLE_OBJECTIVE",
            )
        if self.executor is None:
            return self._terminal(
                request,
                started,
                FinceptResultState.UNAVAILABLE,
                error="FINCEPT_EXECUTOR_UNBOUND",
            )
        try:
            raw = self.executor(request)
        except TimeoutError as exc:
            return self._terminal(
                request,
                started,
                FinceptResultState.TIMEOUT,
                error=str(exc)[:500],
            )
        except PermissionError as exc:
            return self._terminal(
                request,
                started,
                FinceptResultState.PERMISSION_DENIED,
                error=str(exc)[:500],
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:500]
            upper = msg.upper()
            if "TIMEOUT" in upper:
                state = FinceptResultState.TIMEOUT
            elif "UNHEALTHY" in upper:
                state = FinceptResultState.UNHEALTHY
            elif "UNKNOWN_NOT_AVAILABLE" in upper or "UNKNOWN" in upper:
                state = FinceptResultState.UNAVAILABLE
            elif "DISABLED" in upper:
                state = FinceptResultState.DISABLED
            elif "UNAVAILABLE" in upper:
                state = FinceptResultState.UNAVAILABLE
            else:
                state = FinceptResultState.FAILED
            return self._terminal(request, started, state, error=msg)
        normalized = normalize_fincept_output(
            raw,
            capability_id=request.capability_id,
            command=request.command,
            parameters=request.parameters,
        )
        digest = content_hash_for(normalized)
        artifact_id = f"fincept-{digest[:16]}"
        raw_ref = None
        if self.artifact_writer is not None:
            try:
                raw_ref = self.artifact_writer(
                    {
                        "artifact_id": artifact_id,
                        "content_hash": digest,
                        "normalized": normalized,
                        "trace_id": request.trace_id,
                        "run_id": request.run_id,
                    }
                )
            except Exception:  # noqa: BLE001
                raw_ref = None
        evidence_id = None
        if self.evidence_writer is not None:
            try:
                evidence_id = self.evidence_writer(
                    {
                        "kind": "fincept_result",
                        "summary": f"{request.capability_id}:{request.command}",
                        "artifact_id": artifact_id,
                        "content_hash": digest,
                        "available_at": utc_now(),
                        "provenance": {
                            "moduleId": FINCEPT_MODULE_ID,
                            "moduleVersion": self.module_version,
                            "externalSourceRef": self.external_source_ref,
                            "command": request.command,
                            "parameters": dict(request.parameters),
                            "traceId": request.trace_id,
                            "runId": request.run_id,
                        },
                        "status": FinceptResultState.COMPLETED.value,
                    }
                )
            except Exception:  # noqa: BLE001
                evidence_id = None
        artifact = FinceptArtifact(
            artifact_id=artifact_id,
            module_id=FINCEPT_MODULE_ID,
            module_version=self.module_version,
            capability_id=request.capability_id,
            command=request.command,
            parameters=dict(request.parameters),
            started_at=started,
            ended_at=utc_now(),
            result_state=FinceptResultState.COMPLETED,
            content_hash=digest,
            normalized=normalized,
            raw_ref=raw_ref,
            evidence_id=evidence_id,
            external_source_ref=self.external_source_ref,
            metadata={"role": request.role, "symbols": list(request.symbols)},
        )
        if self.brain_assimilator is not None and evidence_id:
            try:
                self.brain_assimilator(artifact.public_dict())
            except Exception:  # noqa: BLE001
                pass
        return artifact

    def _terminal(
        self,
        request: FinceptInvocationRequest,
        started: str,
        state: FinceptResultState,
        *,
        error: str,
    ) -> FinceptArtifact:
        normalized = {
            "error": error,
            "state": state.value,
            "capabilityId": request.capability_id,
            "operatorAction": (
                "Install/enable fincept-terminal and bind executor via ModuleManager"
                if state
                in {
                    FinceptResultState.UNAVAILABLE,
                    FinceptResultState.DISABLED,
                    FinceptResultState.UNHEALTHY,
                    FinceptResultState.FAILED,
                    FinceptResultState.TIMEOUT,
                }
                else None
            ),
        }
        return FinceptArtifact(
            artifact_id=f"fincept-{state.value.lower()}-{hashlib.sha256(error.encode()).hexdigest()[:12]}",
            module_id=FINCEPT_MODULE_ID,
            module_version=self.module_version,
            capability_id=request.capability_id,
            command=request.command,
            parameters=dict(request.parameters),
            started_at=started,
            ended_at=utc_now(),
            result_state=state,
            content_hash=content_hash_for(normalized),
            normalized=normalized,
            external_source_ref=self.external_source_ref,
            error=error,
        )
