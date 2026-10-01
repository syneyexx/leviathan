from __future__ import annotations

import hashlib
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from Data.modules.function_runtime.types import FunctionCallStatus, SideEffect

from .catalog import CapabilityCatalog
from .idempotency import CapabilityIdempotencyStore, execution_fingerprint
from .receipts import CapabilityReceiptStore, build_receipt_from_result
from .types import (
    CapabilityDefinition,
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

# Argument keys that name filesystem paths and must stay under filesystem_root.
_PATH_ARGUMENT_KEYS = frozenset(
    {
        "path",
        "cwd",
        "workspace_root",
        "file_path",
        "source_path",
        "dest_path",
        "target",
        "output_path",
        "content_path",
    }
)

# Side effects that may proceed without an approval_id in Phase 9.
_AUTO_ALLOWED_EFFECTS = frozenset({SideEffect.READ})


class GatewayRejection(Exception):
    """Raised when the gateway rejects a request before provider dispatch."""

    def __init__(self, message: str, *, reason: str = "rejected") -> None:
        super().__init__(message)
        self.reason = reason


class FunctionExecutor(Protocol):
    def execute(self, function_id: str, arguments: dict[str, Any] | None = None) -> Any: ...


class KnowledgeSearcher(Protocol):
    def search(self, query: Any) -> list[Any]: ...


class KnowledgeIngestor(Protocol):
    def scan_data_root(self, *, limit: int = 50) -> list[Any]: ...


class ArtifactWriter(Protocol):
    def create_from_bytes(self, **kwargs: Any) -> Any: ...


class ApprovalChecker(Protocol):
    """Optional Phase 10 hook — returns True when approval_id authorizes the request."""

    def is_approved(
        self,
        approval_id: str,
        *,
        capability_id: str,
        side_effects: tuple[SideEffect, ...],
        arguments: dict[str, Any] | None = None,
    ) -> bool: ...


class ObservationRecorder(Protocol):
    def record_execution(self, **kwargs: Any) -> Any: ...


class McpExecutor(Protocol):
    """MCP provider adapter — invoked only after gateway authorization."""

    def execute_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        approval_id: str | None = None,
        requested_by: str = "api",
        approved_by_user: bool | None = None,
    ) -> CapabilityResult: ...


class BrowserExecutor(Protocol):
    """Browser domain worker — invoked only after gateway authorization."""

    def execute(
        self,
        *,
        action: Any,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...


class MediaExecutor(Protocol):
    """Media domain worker — invoked only after gateway authorization."""

    def execute(
        self,
        *,
        action: Any,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...


class VoiceExecutor(Protocol):
    """Voice domain worker — invoked only after gateway authorization."""

    def execute(
        self,
        *,
        action: Any,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...


class ModuleExecutor(Protocol):
    """Optional MODULE provider_kind adapter."""

    def execute_module_capability(
        self,
        capability_id: str,
        provider_ref: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        run_id: str | None = None,
        job_id: str | None = None,
        cancel_check: Any = None,
        progress: Any = None,
    ) -> dict[str, Any] | CapabilityResult: ...


@dataclass
class EffectRecord:
    effect_id: str
    request_id: str
    capability_id: str
    side_effects: tuple[str, ...]
    status: str
    provider_kind: str | None
    provider_ref: str | None
    recorded_at_ms: float
    approval_id: str | None = None
    error: str | None = None
    observation_id: str | None = None


@dataclass
class ExecutionGateway:
    """Single controlled path for privileged capability execution.

    Flow: validate → policy → (approval if required) → provider → result + effect record.
    Idempotent COMPLETED invocations with the same ``idempotency_key`` replay the prior
    result and do not re-dispatch providers (no double side-effects).
    """

    catalog: CapabilityCatalog
    function_runtime: FunctionExecutor | None = None
    knowledge_retriever: KnowledgeSearcher | None = None
    knowledge_store: KnowledgeIngestor | None = None
    artifact_store: ArtifactWriter | None = None
    approval_checker: ApprovalChecker | None = None
    observation_store: ObservationRecorder | None = None
    mcp_executor: McpExecutor | None = None
    browser_executor: BrowserExecutor | None = None
    media_executor: MediaExecutor | None = None
    voice_executor: VoiceExecutor | None = None
    module_executor: ModuleExecutor | None = None
    receipt_store: CapabilityReceiptStore | None = None
    # Durable request-bound idempotency (fingerprint + claim). Optional; derived
    # from observation_store.db_path when omitted.
    idempotency_store: CapabilityIdempotencyStore | None = None
    # When set, path-bearing args are confined under this root (Round 8).
    filesystem_root: str | Path | None = None
    effect_ledger: list[EffectRecord] = field(default_factory=list)
    # Process-local COMPLETED replay cache keyed by idempotency_key+fingerprint.
    _idempotency_cache: dict[str, CapabilityResult] = field(default_factory=dict, repr=False)
    telemetry: dict[str, Any] = field(
        default_factory=lambda: {
            "requests": 0,
            "completed": 0,
            "failed": 0,
            "rejected": 0,
            "timeouts": 0,
            "cancellations": 0,
            "approval_required": 0,
            "observations_recorded": 0,
            "receipts_recorded": 0,
            "idempotent_replays": 0,
            "idempotency_conflicts": 0,
            "idempotency_in_flight": 0,
        }
    )

    def _resolve_idempotency_store(self) -> CapabilityIdempotencyStore | None:
        if self.idempotency_store is not None:
            return self.idempotency_store
        store = self.observation_store
        db_path = getattr(store, "db_path", None) if store is not None else None
        if db_path is None:
            return None
        resolved = CapabilityIdempotencyStore(Path(db_path))
        try:
            resolved.initialize()
        except Exception:  # noqa: BLE001 — initialize best-effort; claim will surface errors
            pass
        self.idempotency_store = resolved
        return resolved

    @staticmethod
    def _callable_accepts_kwarg(fn: Any, name: str) -> bool:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        params = sig.parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return True
        return name in params

    def list_capabilities(self) -> list[CapabilityDefinition]:
        return self.catalog.list()

    def get_capability(self, capability_id: str) -> CapabilityDefinition | None:
        return self.catalog.get(capability_id)

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        request_id = request.request_id or str(uuid.uuid4())
        started = time.perf_counter()
        self.telemetry["requests"] += 1

        definition = self.catalog.get(request.capability_id)
        if definition is None:
            return self._reject(
                request_id,
                request.capability_id,
                f"Unknown capability: {request.capability_id}",
                reason="unknown_capability",
                started=started,
                request=request,
                authority_decision="rejected_unknown",
            )

        # Strip audit-only / forgeable client fields before schema validation —
        # never authority. Gateway re-injects `_trusted_authority` after approval.
        arguments = dict(request.arguments)
        arguments.pop("approved_by_user", None)
        arguments.pop("_approved_by_user", None)
        arguments.pop("_trusted_authority", None)
        request = CapabilityRequest(
            capability_id=request.capability_id,
            arguments=arguments,
            request_id=request.request_id or request_id,
            run_id=request.run_id,
            job_id=request.job_id,
            approval_id=request.approval_id,
            requested_by=request.requested_by,
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
        )

        fingerprint = execution_fingerprint(
            request,
            schema_hash=definition.resolved_schema_hash(),
            schema_version=str((definition.normalized_metadata() or {}).get("schema_version") or ""),
        )

        # Idempotent claim / replay before policy/dispatch — no second side-effect.
        if request.idempotency_key:
            early = self._begin_idempotent(
                request,
                request_id=request_id,
                started=started,
                fingerprint=fingerprint,
                definition=definition,
            )
            if early is not None:
                # Either a terminal replay / conflict / in-flight response, or a claim marker.
                if isinstance(early, CapabilityResult):
                    return early

        authority_decision = "pending"
        approval_reserved = False
        try:
            self._validate_args(definition, request.arguments)
            request = self._confine_filesystem_args(request)
        except GatewayRejection as exc:
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=None)
            return self._reject(
                request_id,
                definition.id,
                str(exc),
                reason=exc.reason,
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision="rejected_validation",
            )

        if not definition.available:
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=None)
            return self._reject(
                request_id,
                definition.id,
                f"Capability unavailable: {definition.availability_reason or 'unavailable'}",
                reason="unavailable",
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision="rejected_unavailable",
            )

        # W2: EXTERNAL_REQUIRED must not execute heavy work inline in the API process.
        try:
            self._enforce_external_workload(definition, request)
        except GatewayRejection as exc:
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=None)
            return self._reject(
                request_id,
                definition.id,
                str(exc),
                reason=exc.reason,
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision=f"rejected_{exc.reason}",
            )

        try:
            self._enforce_policy(definition, request)
            authority_decision = "allowed" if not request.approval_id else "allowed_with_approval"
        except GatewayRejection as exc:
            if exc.reason == "approval_required":
                self.telemetry["approval_required"] += 1
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=None)
            return self._reject(
                request_id,
                definition.id,
                str(exc),
                reason=exc.reason,
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision=f"rejected_{exc.reason}",
            )

        # Inject non-forgeable trusted authority after approval verification.
        request = self._inject_trusted_authority(definition, request)

        # Atomic single-use approval reservation — must succeed before side effects.
        try:
            approval_reserved = self._reserve_approval(definition, request)
        except GatewayRejection as exc:
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=None)
            return self._reject(
                request_id,
                definition.id,
                str(exc),
                reason=exc.reason,
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision=f"rejected_{exc.reason}",
            )

        try:
            output = self._dispatch(definition, request)
        except GatewayRejection as exc:
            # Provider rejected before completing — treat as no irreversible effect when
            # the rejection is pre-dispatch style; still release reservation.
            if approval_reserved:
                self._release_approval(request, uncertain=False)
            rejected = self._reject(
                request_id,
                definition.id,
                str(exc),
                reason=exc.reason,
                started=started,
                definition=definition,
                approval_id=request.approval_id,
                request=request,
                authority_decision=f"rejected_{exc.reason}",
            )
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=rejected)
            return rejected
        except Exception as exc:  # noqa: BLE001 — normalized into CapabilityResult
            # Dispatch may have started irreversible work — never pretend clean pre-exec failure.
            if approval_reserved:
                self._release_approval(request, uncertain=True)
            result = CapabilityResult(
                request_id=request_id,
                capability_id=definition.id,
                status=CapabilityStatus.FAILED,
                error=str(exc),
                side_effects=definition.side_effects,
                provider_kind=definition.provider_kind.value,
                provider_ref=definition.provider_ref,
                approval_id=request.approval_id,
                telemetry={
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "approval_reservation_uncertain": bool(approval_reserved),
                },
            )
            self.telemetry["failed"] += 1
            self._record_effect(result, request=request, authority_decision=authority_decision)
            self._fail_idempotent_claim(request, fingerprint=fingerprint, result=result)
            return result

        if isinstance(output, CapabilityResult):
            output.request_id = request_id
            output.capability_id = definition.id
            output.side_effects = definition.side_effects
            output.provider_kind = definition.provider_kind.value
            output.provider_ref = definition.provider_ref
            output.approval_id = request.approval_id
            output.telemetry = {
                **(output.telemetry or {}),
                "duration_ms": (time.perf_counter() - started) * 1000,
            }
            self._bump_status(output.status)
            self._finalize_approval(request, output, reserved=approval_reserved)
            self._record_effect(output, request=request, authority_decision=authority_decision)
            self._remember_idempotent(request, output, fingerprint=fingerprint)
            return output

        result = CapabilityResult(
            request_id=request_id,
            capability_id=definition.id,
            status=CapabilityStatus.COMPLETED,
            output=output if isinstance(output, dict) else {"value": output},
            side_effects=definition.side_effects,
            provider_kind=definition.provider_kind.value,
            provider_ref=definition.provider_ref,
            approval_id=request.approval_id,
            telemetry={"duration_ms": (time.perf_counter() - started) * 1000},
        )
        self.telemetry["completed"] += 1
        self._finalize_approval(request, result, reserved=approval_reserved)
        self._record_effect(result, request=request, authority_decision=authority_decision)
        self._remember_idempotent(request, result, fingerprint=fingerprint)
        return result

    def _begin_idempotent(
        self,
        request: CapabilityRequest,
        *,
        request_id: str,
        started: float,
        fingerprint: str,
        definition: CapabilityDefinition,
    ) -> CapabilityResult | str | None:
        """Claim or replay durable idempotency. Returns result, ``'claimed'``, or None."""
        key = request.idempotency_key
        if not key:
            return None

        cache_key = f"{key}:{fingerprint}"
        cached = self._idempotency_cache.get(cache_key)
        if cached is not None and cached.capability_id == request.capability_id:
            return self._mark_replay(cached, request_id=request_id, started=started, source="memory")

        durable = self._resolve_idempotency_store()
        has_side_effects = any(effect not in _AUTO_ALLOWED_EFFECTS for effect in definition.side_effects)
        if durable is None:
            if has_side_effects:
                return self._reject(
                    request_id,
                    request.capability_id,
                    "Durable idempotency authority unavailable for side-effecting capability",
                    reason="idempotency_authority_unavailable",
                    started=started,
                    definition=definition,
                    request=request,
                    authority_decision="rejected_idempotency_authority_unavailable",
                )
            # READ-only may proceed with memory-only semantics.
            return "claimed"

        try:
            outcome, record = durable.claim(
                idempotency_key=key,
                fingerprint=fingerprint,
                capability_id=request.capability_id,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001
            if has_side_effects:
                return self._reject(
                    request_id,
                    request.capability_id,
                    f"Durable idempotency claim failed: {exc}",
                    reason="idempotency_authority_unavailable",
                    started=started,
                    definition=definition,
                    request=request,
                    authority_decision="rejected_idempotency_authority_unavailable",
                )
            return "claimed"

        if outcome == "claimed":
            return "claimed"
        if outcome == "conflict":
            self.telemetry["idempotency_conflicts"] = (
                int(self.telemetry.get("idempotency_conflicts", 0)) + 1
            )
            return self._reject(
                request_id,
                request.capability_id,
                f"Idempotency key {key!r} already bound to a different request fingerprint",
                reason="idempotency_conflict",
                started=started,
                definition=definition,
                request=request,
                authority_decision="rejected_idempotency_conflict",
            )
        if outcome == "in_flight":
            self.telemetry["idempotency_in_flight"] = (
                int(self.telemetry.get("idempotency_in_flight", 0)) + 1
            )
            return CapabilityResult(
                request_id=request_id,
                capability_id=request.capability_id,
                status=CapabilityStatus.REJECTED,
                error=f"Idempotent request already in flight (request_id={record.request_id})",
                side_effects=definition.side_effects,
                provider_kind=definition.provider_kind.value,
                provider_ref=definition.provider_ref,
                approval_id=request.approval_id,
                telemetry={
                    "reason": "idempotency_in_flight",
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "in_flight_request_id": record.request_id,
                    "idempotency_key": key,
                    "fingerprint": fingerprint,
                },
            )
        # replay
        rebuilt = CapabilityIdempotencyStore.result_from_record(record, request_id=request_id)
        if rebuilt is None:
            # Completed record without payload — treat as conflict rather than re-execute.
            return self._reject(
                request_id,
                request.capability_id,
                f"Idempotency key {key!r} completed without durable payload",
                reason="idempotency_conflict",
                started=started,
                definition=definition,
                request=request,
                authority_decision="rejected_idempotency_conflict",
            )
        return self._mark_replay(
            rebuilt,
            request_id=request_id,
            started=started,
            source="capability_idempotency",
        )

    def _fail_idempotent_claim(
        self,
        request: CapabilityRequest,
        *,
        fingerprint: str,
        result: CapabilityResult | None,
    ) -> None:
        key = request.idempotency_key
        if not key:
            return
        durable = self._resolve_idempotency_store()
        if durable is None:
            return
        try:
            durable.fail(key, result=result, request_id=request.request_id)
        except Exception:  # noqa: BLE001
            pass

    def _mark_replay(
        self,
        prior: CapabilityResult,
        *,
        request_id: str,
        started: float,
        source: str,
    ) -> CapabilityResult:
        replayed = CapabilityResult(
            request_id=request_id,
            capability_id=prior.capability_id,
            status=prior.status,
            output=dict(prior.output) if isinstance(prior.output, dict) else prior.output,
            error=prior.error,
            side_effects=prior.side_effects,
            provider_kind=prior.provider_kind,
            provider_ref=prior.provider_ref,
            approval_id=prior.approval_id,
            telemetry={
                **(prior.telemetry or {}),
                "duration_ms": (time.perf_counter() - started) * 1000,
                "idempotent_replay": True,
                "idempotent_replay_source": source,
                "original_request_id": (prior.telemetry or {}).get("original_request_id")
                or prior.request_id,
            },
        )
        self.telemetry["idempotent_replays"] = int(self.telemetry.get("idempotent_replays", 0)) + 1
        if prior.status == CapabilityStatus.COMPLETED:
            self.telemetry["completed"] += 1
        return replayed

    def _remember_idempotent(
        self,
        request: CapabilityRequest,
        result: CapabilityResult,
        *,
        fingerprint: str,
    ) -> None:
        if not request.idempotency_key:
            return
        cache_key = f"{request.idempotency_key}:{fingerprint}"
        durable = self._resolve_idempotency_store()
        if result.status == CapabilityStatus.COMPLETED:
            self._idempotency_cache[cache_key] = result
            if durable is not None:
                try:
                    durable.complete(
                        request.idempotency_key,
                        result=result,
                        request_id=result.request_id,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return
        if durable is not None:
            try:
                durable.fail(
                    request.idempotency_key,
                    result=result,
                    request_id=result.request_id,
                )
            except Exception:  # noqa: BLE001
                pass

    def _inject_trusted_authority(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> CapabilityRequest:
        """After approval verification, inject non-forgeable authority for module dispatch."""
        if definition.provider_kind != CapabilityProviderKind.MODULE:
            return request
        args = dict(request.arguments)
        args.pop("_trusted_authority", None)
        if request.approval_id:
            args["_trusted_authority"] = {
                "approval_id": request.approval_id,
                # Echo explicit client intent only after gateway verified approval.
                "allow_system_deps": bool(request.arguments.get("allow_system_deps")),
            }
        return CapabilityRequest(
            capability_id=request.capability_id,
            arguments=args,
            request_id=request.request_id,
            run_id=request.run_id,
            job_id=request.job_id,
            approval_id=request.approval_id,
            requested_by=request.requested_by,
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
        )

    def _reserve_approval(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> bool:
        """Atomically reserve single-use approval before side effects. Returns True if reserved."""
        needs_approval = any(effect not in _AUTO_ALLOWED_EFFECTS for effect in definition.side_effects)
        if not needs_approval or not request.approval_id:
            return False
        reserve = getattr(self.approval_checker, "reserve_for_execution", None)
        if not callable(reserve):
            # Legacy checkers without reserve — consume-after remains best-effort.
            return False
        # Digests were computed without gateway-injected _trusted_authority.
        args_for_digest = {
            k: v for k, v in request.arguments.items() if k != "_trusted_authority"
        }
        digest = hashlib.sha256(
            json.dumps(args_for_digest, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        kwargs: dict[str, Any] = {
            "capability_id": definition.id,
            "arguments": args_for_digest,
            "arguments_digest": digest,
        }
        if not self._callable_accepts_kwarg(reserve, "arguments"):
            kwargs.pop("arguments", None)
        if not self._callable_accepts_kwarg(reserve, "arguments_digest"):
            kwargs.pop("arguments_digest", None)
        reserved = reserve(request.approval_id, **kwargs)
        if reserved is None:
            raise GatewayRejection(
                f"Approval {request.approval_id!r} could not be reserved for "
                f"capability {definition.id!r} (already reserved/consumed or mismatch)",
                reason="approval_denied",
            )
        return True

    def _release_approval(self, request: CapabilityRequest, *, uncertain: bool) -> None:
        if not request.approval_id:
            return
        if uncertain:
            # Irreversible effect may have occurred — leave RESERVED for repair.
            return
        release = getattr(self.approval_checker, "release_reservation", None)
        if not callable(release):
            return
        try:
            release(request.approval_id)
        except Exception:  # noqa: BLE001
            pass

    def _finalize_approval(
        self,
        request: CapabilityRequest,
        result: CapabilityResult,
        *,
        reserved: bool,
    ) -> None:
        if not request.approval_id:
            return
        if result.status == CapabilityStatus.COMPLETED:
            self._maybe_consume_approval(request, result)
            return
        if not reserved:
            return
        # Non-success after reservation: release when outcome is clean cancel/reject;
        # mark uncertain for FAILED (side effect may have partially occurred).
        if result.status in {CapabilityStatus.REJECTED, CapabilityStatus.CANCELLED}:
            self._release_approval(request, uncertain=False)
            result.telemetry["approval_released"] = True
            return
        result.telemetry["approval_reservation_uncertain"] = True
        # Leave RESERVED for operator repair — never pretend clean pre-exec failure.

    def _maybe_consume_approval(self, request: CapabilityRequest, result: CapabilityResult) -> None:
        if result.status != CapabilityStatus.COMPLETED or not request.approval_id:
            return
        consume = getattr(self.approval_checker, "consume_if_single_use", None)
        if not callable(consume):
            return
        try:
            consume(request.approval_id)
            result.telemetry["approval_consumed"] = True
        except Exception as exc:  # noqa: BLE001 — do not fail completed work on ledger consume
            result.telemetry["approval_consume_error"] = str(exc)
            result.telemetry["approval_reservation_uncertain"] = True

    def _confine_filesystem_args(self, request: CapabilityRequest) -> CapabilityRequest:
        """Refuse path escape when filesystem_root is configured (Round 8)."""
        if self.filesystem_root is None:
            return request
        from Data.modules.coding.workspace import confine
        from Data.modules.common.paths import PathEscapeError

        root = Path(self.filesystem_root)
        args = dict(request.arguments)
        changed = False
        for key in _PATH_ARGUMENT_KEYS:
            if key not in args or args[key] is None:
                continue
            raw = str(args[key]).strip()
            if not raw:
                continue
            try:
                confined = confine(root, raw)
            except PathEscapeError as exc:
                raise GatewayRejection(
                    f"Path escapes filesystem_root for {key!r}: {exc}",
                    reason="path_escape",
                ) from exc
            args[key] = str(confined)
            changed = True
        if not changed:
            return request
        return CapabilityRequest(
            capability_id=request.capability_id,
            arguments=args,
            request_id=request.request_id,
            run_id=request.run_id,
            job_id=request.job_id,
            approval_id=request.approval_id,
            requested_by=request.requested_by,
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
        )

    def _enforce_external_workload(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> None:
        """Refuse inline API execution of EXTERNAL_REQUIRED capabilities.

        Uses request-aware classification AFTER path confinement so the same
        capability can be INLINE_SAFE for small work and EXTERNAL_REQUIRED for
        large / recursive / unbounded filesystem work.

        Workers (``LEVIATHAN_WORKER_ID`` set) may execute their owned work;
        request-escalated filesystem ops require the ``file_io`` pool.
        Developer mode (``LEVIATHAN_WORKERS_EXTERNALIZE_API=false``) is exempt.
        Authorization/approval still apply independently.
        """
        from .workload import (
            ExecutionWorkloadClass,
            api_may_execute_inline,
            classify_request_workload,
        )

        meta = definition.normalized_metadata()
        cls = classify_request_workload(
            definition.id,
            request.arguments,
            metadata=meta,
            provider_kind=definition.provider_kind.value,
            filesystem_root=self.filesystem_root,
        )
        if cls != ExecutionWorkloadClass.EXTERNAL_REQUIRED:
            return
        if api_may_execute_inline(
            definition.id,
            metadata=meta,
            provider_kind=definition.provider_kind.value,
            arguments=request.arguments,
            filesystem_root=self.filesystem_root,
        ):
            return
        raise GatewayRejection(
            f"Capability {definition.id!r} is EXTERNAL_REQUIRED and must run on an "
            f"external worker (WORKER_UNAVAILABLE / enqueue via JobRuntime). "
            f"requested_by={request.requested_by!r}",
            reason="worker_required",
        )

    def _enforce_policy(self, definition: CapabilityDefinition, request: CapabilityRequest) -> None:
        needs_approval = any(effect not in _AUTO_ALLOWED_EFFECTS for effect in definition.side_effects)
        if not needs_approval:
            return
        if not request.approval_id:
            raise GatewayRejection(
                f"Capability {definition.id!r} requires approval "
                f"(side_effects={[e.value for e in definition.side_effects]})",
                reason="approval_required",
            )
        if self.approval_checker is None:
            raise GatewayRejection(
                "Approval checker not configured; cannot verify gated capability",
                reason="approval_denied",
            )
        kwargs: dict[str, Any] = {
            "capability_id": definition.id,
            "side_effects": definition.side_effects,
        }
        if self._callable_accepts_kwarg(self.approval_checker.is_approved, "arguments"):
            kwargs["arguments"] = request.arguments
        approved = self.approval_checker.is_approved(request.approval_id, **kwargs)
        if not approved:
            raise GatewayRejection(
                f"Approval {request.approval_id!r} is not valid for capability {definition.id!r}",
                reason="approval_denied",
            )

    def _dispatch(self, definition: CapabilityDefinition, request: CapabilityRequest) -> Any:
        kind = definition.provider_kind
        if kind == CapabilityProviderKind.FUNCTION:
            return self._dispatch_function(definition, request)
        if kind == CapabilityProviderKind.KNOWLEDGE:
            return self._dispatch_knowledge(definition, request)
        if kind == CapabilityProviderKind.ARTIFACT:
            return self._dispatch_artifact(definition, request)
        if kind == CapabilityProviderKind.MCP:
            return self._dispatch_mcp(definition, request)
        if kind == CapabilityProviderKind.BROWSER:
            return self._dispatch_browser(definition, request)
        if kind == CapabilityProviderKind.MEDIA:
            return self._dispatch_media(definition, request)
        if kind == CapabilityProviderKind.VOICE:
            return self._dispatch_voice(definition, request)
        if kind == CapabilityProviderKind.MODULE:
            return self._dispatch_module(definition, request)
        raise GatewayRejection(
            f"Unsupported provider kind: {kind.value}",
            reason="unsupported_provider",
        )

    def _dispatch_browser(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> Any:
        if self.browser_executor is None:
            raise RuntimeError("Browser executor not configured on ExecutionGateway")
        action = definition.provider_ref
        result = self.browser_executor.execute(
            action=action,
            arguments=dict(request.arguments),
            run_id=request.run_id,
            request_id=request.request_id,
        )
        status = str(result.get("status") or "").upper()
        # Honest provider outcomes — never invent success (U179).
        if status == "REJECTED":
            raise GatewayRejection(
                str(result.get("error") or result.get("detail") or "Browser rejected"),
                reason="browser_rejected",
            )
        if status == "UNSUPPORTED":
            raise GatewayRejection(
                str(result.get("detail") or "Browser action unsupported"),
                reason="browser_unsupported",
            )
        if status == "CANCELLED":
            return CapabilityResult(
                request_id=request.request_id or "",
                capability_id=definition.id,
                status=CapabilityStatus.CANCELLED,
                output=result if isinstance(result, dict) else {"value": result},
                error=str(result.get("error") or result.get("detail") or "Browser cancelled"),
            )
        if status == "FAILED":
            raise RuntimeError(str(result.get("error") or result.get("detail") or "Browser failed"))
        return result

    def _dispatch_media(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> Any:
        if self.media_executor is None:
            raise RuntimeError("Media executor not configured on ExecutionGateway")
        result = self.media_executor.execute(
            action=definition.provider_ref,
            arguments=dict(request.arguments),
            run_id=request.run_id,
            request_id=request.request_id,
        )
        status = str(result.get("status") or "").upper()
        if status == "REJECTED":
            raise GatewayRejection(
                str(result.get("error") or result.get("detail") or "Media rejected"),
                reason="media_rejected",
            )
        if status == "UNSUPPORTED":
            raise GatewayRejection(
                str(result.get("detail") or "Media action unsupported"),
                reason="media_unsupported",
            )
        if status == "CANCELLED":
            return CapabilityResult(
                request_id=request.request_id or "",
                capability_id=definition.id,
                status=CapabilityStatus.CANCELLED,
                output=result if isinstance(result, dict) else {"value": result},
                error=str(result.get("error") or result.get("detail") or "Media cancelled"),
            )
        if status == "FAILED":
            raise RuntimeError(str(result.get("error") or result.get("detail") or "Media failed"))
        return result

    def _dispatch_voice(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> Any:
        if self.voice_executor is None:
            raise RuntimeError("Voice executor not configured on ExecutionGateway")
        result = self.voice_executor.execute(
            action=definition.provider_ref,
            arguments=dict(request.arguments),
            run_id=request.run_id,
            request_id=request.request_id,
        )
        status = str(result.get("status") or "").upper()
        if status == "REJECTED":
            raise GatewayRejection(
                str(result.get("error") or result.get("detail") or "Voice rejected"),
                reason="voice_rejected",
            )
        if status == "CANCELLED":
            # Honest barge-in — typed CANCELLED (never wrap as COMPLETED via plain dict).
            return CapabilityResult(
                request_id=request.request_id or "",
                capability_id=definition.id,
                status=CapabilityStatus.CANCELLED,
                output=result if isinstance(result, dict) else {"value": result},
                error=str(result.get("error") or result.get("detail") or "Voice cancelled"),
            )
        if status == "UNSUPPORTED":
            raise GatewayRejection(
                str(result.get("detail") or "Voice action unsupported"),
                reason="voice_unsupported",
            )
        if status == "FAILED":
            raise RuntimeError(str(result.get("error") or result.get("detail") or "Voice failed"))
        return result

    def _dispatch_module(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> Any:
        if self.module_executor is None:
            raise RuntimeError("Module executor not configured on ExecutionGateway")
        cancel_check = None
        progress = None
        job_id = request.job_id
        # Cooperative cancel when JobRuntime owns this request.
        if job_id and hasattr(self, "_job_cancel_check") and callable(getattr(self, "_job_cancel_check")):
            cancel_check = lambda jid=job_id: bool(self._job_cancel_check(jid))  # noqa: E731
        # Optional progress sink — never invent percent; adapters report honestly.
        if hasattr(self, "_job_progress") and callable(getattr(self, "_job_progress")) and job_id:
            progress = lambda pct, phase, msg, jid=job_id: self._job_progress(  # noqa: E731
                jid, float(pct or 0.0), str(phase or ""), str(msg or "")
            )
        elif isinstance(request.arguments, dict) and callable(request.arguments.get("_progress_cb")):
            # Test/dev only: explicit callable not persisted into provider args.
            progress = request.arguments.get("_progress_cb")
        args = dict(request.arguments)
        args.pop("_progress_cb", None)
        args.pop("_cancel_check", None)
        if cancel_check is None and callable(request.arguments.get("_cancel_check")):
            cancel_check = request.arguments.get("_cancel_check")
        fn = self.module_executor.execute_module_capability
        kwargs: dict[str, Any] = {
            "request_id": request.request_id or "",
            "run_id": request.run_id,
        }
        if self._callable_accepts_kwarg(fn, "job_id"):
            kwargs["job_id"] = job_id
        if self._callable_accepts_kwarg(fn, "cancel_check"):
            kwargs["cancel_check"] = cancel_check
        if self._callable_accepts_kwarg(fn, "progress"):
            kwargs["progress"] = progress
        return fn(
            definition.id,
            definition.provider_ref,
            args,
            **kwargs,
        )

    def _dispatch_mcp(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> CapabilityResult:
        if self.mcp_executor is None:
            raise RuntimeError("MCP executor not configured on ExecutionGateway")
        # Trading boundary for MCP tools expanded from external finance packages.
        meta = dict(getattr(definition, "metadata", None) or {})
        if meta.get("marketsim_bypass_forbidden") or meta.get("real_money_blocked"):
            from Data.modules.module_manager.external.trading_boundary import (
                enforce_trading_boundary,
                module_trading_flags,
            )

            flags = module_trading_flags(definition)
            op = definition.provider_ref or definition.id
            rejected = enforce_trading_boundary(
                flags=flags,
                capability_id=definition.id,
                operation=str(op),
                arguments=dict(request.arguments),
                request_id=request.request_id or "",
                provider_kind="mcp",
                provider_ref=definition.provider_ref,
            )
            if rejected is not None:
                return rejected
        # approved_by_user may arrive as a top-level sibling in API payloads — never authorize from it.
        return self.mcp_executor.execute_capability(
            definition.id,
            dict(request.arguments),
            request_id=request.request_id or "",
            approval_id=request.approval_id,
            requested_by=request.requested_by,
            approved_by_user=None,
        )

    def _dispatch_function(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> CapabilityResult | dict[str, Any]:
        if self.function_runtime is None:
            raise RuntimeError("Function runtime not configured on ExecutionGateway")
        fn_result = self.function_runtime.execute(definition.provider_ref, request.arguments)
        status_map = {
            FunctionCallStatus.COMPLETED: CapabilityStatus.COMPLETED,
            FunctionCallStatus.FAILED: CapabilityStatus.FAILED,
            FunctionCallStatus.REJECTED: CapabilityStatus.REJECTED,
            FunctionCallStatus.CANCELLED: CapabilityStatus.CANCELLED,
            FunctionCallStatus.TIMEOUT: CapabilityStatus.TIMEOUT,
        }
        status = status_map.get(fn_result.status, CapabilityStatus.FAILED)
        output = fn_result.output
        if (
            status == CapabilityStatus.COMPLETED
            and isinstance(output, dict)
            and definition.id.startswith(("file.", "filesystem.", "workspace."))
        ):
            try:
                from Data.modules.file_io.spill import maybe_spill_result

                output = maybe_spill_result(
                    output,
                    artifact_store=self.artifact_store,
                    producer=f"capability:{definition.id}",
                    artifact_type="file_io_result",
                    filename="result.json",
                    run_id=request.run_id,
                    job_id=request.job_id,
                )
            except Exception:  # noqa: BLE001 — spill failure must not discard success
                pass
        return CapabilityResult(
            request_id=request.request_id or "",
            capability_id=definition.id,
            status=status,
            output=output,
            error=fn_result.error,
            telemetry={
                "function_call_id": fn_result.call_id,
                "function_telemetry": dict(fn_result.telemetry or {}),
                "function_duration_ms": fn_result.duration_ms,
            },
        )

    def _dispatch_knowledge(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> dict[str, Any]:
        if definition.provider_ref == "ingest_scan":
            if self.knowledge_store is None:
                raise RuntimeError("Knowledge store not configured on ExecutionGateway for ingest")
            limit = int(request.arguments.get("limit") or 50)
            records = self.knowledge_store.scan_data_root(limit=limit)
            return {
                "ingested": len(records),
                "document_ids": [
                    item.document_id if hasattr(item, "document_id") else str(item) for item in records
                ],
                "provider_ref": definition.provider_ref,
                "truth": {"uses_knowledge_v2_ingest": True},
            }
        if self.knowledge_retriever is None:
            raise RuntimeError("Knowledge retriever not configured on ExecutionGateway")
        from Data.modules.knowledge import RetrievalQuery

        query = RetrievalQuery(
            text=str(request.arguments["query"]),
            limit=int(request.arguments.get("limit") or 5),
            source=request.arguments.get("source"),
        )
        hits = self.knowledge_retriever.search(query)
        return {
            "hits": [hit.public_dict() if hasattr(hit, "public_dict") else hit for hit in hits],
            "count": len(hits),
            "provider_ref": definition.provider_ref,
        }

    def _dispatch_artifact(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> dict[str, Any]:
        if self.artifact_store is None:
            raise RuntimeError("Artifact store not configured on ExecutionGateway")
        content = str(request.arguments["content"])
        filename = str(request.arguments["filename"])
        artifact_type = str(request.arguments.get("artifact_type") or "text")
        run_id = request.arguments.get("run_id") or request.run_id
        record = self.artifact_store.create_from_bytes(
            data=content.encode("utf-8"),
            artifact_type=artifact_type,
            producer="execution.gateway",
            filename=filename,
            run_id=run_id,
            metadata={"capability_id": definition.id, "provider_ref": definition.provider_ref},
        )
        return record.public_dict() if hasattr(record, "public_dict") else dict(record)

    def _validate_args(self, definition: CapabilityDefinition, args: dict[str, Any]) -> None:
        schema = definition.input_schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            raise GatewayRejection("Invalid input_schema on capability definition", reason="bad_schema")
        for key in required:
            if key not in args:
                raise GatewayRejection(f"Missing required argument: {key}", reason="validation")
        for key, value in args.items():
            if key not in properties:
                # Honor JSON Schema additionalProperties when explicitly true.
                if schema.get("additionalProperties") is True:
                    continue
                raise GatewayRejection(f"Unexpected argument: {key}", reason="validation")
            expected = properties[key].get("type")
            if expected is None:
                continue
            if not self._type_matches(expected, value):
                raise GatewayRejection(
                    f"Argument {key!r} expected type {expected}, got {type(value).__name__}",
                    reason="validation",
                )

    @staticmethod
    def _type_matches(expected: str, value: Any) -> bool:
        mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        py_type = mapping.get(expected)
        if py_type is None:
            return True
        if expected == "number" and isinstance(value, bool):
            return False
        if expected == "integer" and isinstance(value, bool):
            return False
        return isinstance(value, py_type)

    def _reject(
        self,
        request_id: str,
        capability_id: str,
        error: str,
        *,
        reason: str,
        started: float,
        definition: CapabilityDefinition | None = None,
        approval_id: str | None = None,
        request: CapabilityRequest | None = None,
        authority_decision: str | None = None,
    ) -> CapabilityResult:
        self.telemetry["rejected"] += 1
        result = CapabilityResult(
            request_id=request_id,
            capability_id=capability_id,
            status=CapabilityStatus.REJECTED,
            error=error,
            side_effects=definition.side_effects if definition else (),
            provider_kind=definition.provider_kind.value if definition else None,
            provider_ref=definition.provider_ref if definition else None,
            approval_id=approval_id,
            telemetry={
                "reason": reason,
                "duration_ms": (time.perf_counter() - started) * 1000,
            },
        )
        self._record_effect(
            result,
            request=request,
            authority_decision=authority_decision or f"rejected_{reason}",
        )
        return result

    def _bump_status(self, status: CapabilityStatus) -> None:
        if status == CapabilityStatus.COMPLETED:
            self.telemetry["completed"] += 1
        elif status == CapabilityStatus.TIMEOUT:
            self.telemetry["timeouts"] += 1
        elif status == CapabilityStatus.CANCELLED:
            self.telemetry["cancellations"] += 1
        elif status == CapabilityStatus.REJECTED:
            self.telemetry["rejected"] += 1
        else:
            self.telemetry["failed"] += 1

    def _record_effect(
        self,
        result: CapabilityResult,
        *,
        request: CapabilityRequest | None = None,
        authority_decision: str = "allowed",
    ) -> None:
        observation_id = None
        effect_id = str(uuid.uuid4())
        side_effects = [item.value for item in result.side_effects]
        duration_ms = (result.telemetry or {}).get("duration_ms")
        run_id = request.run_id if request else None
        job_id = request.job_id if request else None

        if self.observation_store is not None:
            try:
                # Only stamp idempotency_key on COMPLETED so failed/rejected calls
                # can retry under the same key without unique-index collisions.
                idem_for_ledger = (
                    request.idempotency_key
                    if request and result.status == CapabilityStatus.COMPLETED
                    else None
                )
                record_kwargs: dict[str, Any] = {
                    "request_id": result.request_id,
                    "capability_id": result.capability_id,
                    "status": result.status.value,
                    "side_effects": side_effects,
                    "provider_kind": result.provider_kind,
                    "provider_ref": result.provider_ref,
                    "approval_id": result.approval_id,
                    "run_id": run_id,
                    "job_id": job_id,
                    "output": result.output,
                    "error": result.error,
                    "duration_ms": duration_ms,
                    "metadata": {
                        "reason": (result.telemetry or {}).get("reason"),
                        "trace_id": request.trace_id if request else None,
                    },
                }
                fn = self.observation_store.record_execution
                if self._callable_accepts_kwarg(fn, "idempotency_key"):
                    record_kwargs["idempotency_key"] = idem_for_ledger
                if self._callable_accepts_kwarg(fn, "trace_id"):
                    record_kwargs["trace_id"] = request.trace_id if request else None
                observation, durable = fn(**record_kwargs)
                observation_id = observation.observation_id
                effect_id = durable.effect_id
                self.telemetry["observations_recorded"] += 1
                result.telemetry["observation_id"] = observation_id
                result.telemetry["effect_id"] = effect_id
            except Exception as exc:  # noqa: BLE001 — never fail execution on ledger write
                result.telemetry["observation_persist_error"] = str(exc)

        self.effect_ledger.append(
            EffectRecord(
                effect_id=effect_id,
                request_id=result.request_id,
                capability_id=result.capability_id,
                side_effects=tuple(side_effects),
                status=result.status.value,
                provider_kind=result.provider_kind,
                provider_ref=result.provider_ref,
                recorded_at_ms=time.time() * 1000,
                approval_id=result.approval_id,
                error=result.error,
                observation_id=observation_id,
            )
        )

        if self.receipt_store is not None:
            try:
                receipt = build_receipt_from_result(
                    result=result,
                    request=request,
                    authority_decision=authority_decision,
                )
                self.receipt_store.record(receipt)
                self.telemetry["receipts_recorded"] = int(self.telemetry.get("receipts_recorded", 0)) + 1
                result.telemetry["receipt_id"] = receipt.receipt_id
            except Exception as exc:  # noqa: BLE001 — never fail execution on receipt write
                result.telemetry["receipt_persist_error"] = str(exc)
