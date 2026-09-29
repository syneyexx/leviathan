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


FINCEPT_MODULE_ID = "fincept-terminal"
FINCEPT_CAPABILITIES = (
    "external.fincept.analyze",
    "external.fincept.quant",
    "external.fincept.stats",
    "external.fincept.fixed_income",
)


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


def discover_fincept_capabilities(
    catalog: Sequence[dict[str, Any]] | None = None,
    *,
    module_enabled: bool | None = None,
    module_installed: bool | None = None,
) -> dict[str, Any]:
    """Return Fincept capabilities with honest availability."""
    if module_enabled is False:
        return {
            "moduleId": FINCEPT_MODULE_ID,
            "available": False,
            "state": FinceptResultState.DISABLED.value,
            "capabilities": [],
            "operatorAction": "Enable fincept-terminal in module settings.",
        }
    if module_installed is False:
        return {
            "moduleId": FINCEPT_MODULE_ID,
            "available": False,
            "state": FinceptResultState.UNAVAILABLE.value,
            "capabilities": [],
            "operatorAction": (
                "Install external module fincept-terminal "
                "(Fincept-Corporation/FinceptTerminal analytics CLIs)."
            ),
        }
    caps = []
    if catalog:
        for row in catalog:
            cid = str(row.get("capability_id") or row.get("capabilityId") or "")
            if cid.startswith("external.fincept."):
                caps.append(row)
    else:
        caps = [{"capability_id": c, "module_id": FINCEPT_MODULE_ID} for c in FINCEPT_CAPABILITIES]
    return {
        "moduleId": FINCEPT_MODULE_ID,
        "available": True,
        "state": "AVAILABLE",
        "capabilities": caps,
        "operatorAction": None,
    }


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

    def invoke(self, request: FinceptInvocationRequest) -> FinceptArtifact:
        started = utc_now()
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
        except Exception as exc:  # noqa: BLE001
            return self._terminal(
                request,
                started,
                FinceptResultState.FAILED,
                error=str(exc)[:500],
            )
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
                "Install/enable fincept-terminal and bind executor"
                if state in {FinceptResultState.UNAVAILABLE, FinceptResultState.DISABLED}
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
