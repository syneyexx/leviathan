from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from Data.modules.function_runtime.types import FunctionCallStatus, SideEffect

from .catalog import CapabilityCatalog
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
    # When set, path-bearing args are confined under this root (Round 8).
    filesystem_root: str | Path | None = None
    effect_ledger: list[EffectRecord] = field(default_factory=list)
    # Process-local COMPLETED replay cache keyed by idempotency_key.
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
        }
    )

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

        # Strip audit-only client fields before schema validation — never authority.
        arguments = dict(request.arguments)
        arguments.pop("approved_by_user", None)
        arguments.pop("_approved_by_user", None)
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

        # Idempotent replay before policy/dispatch — no second side-effect.
        if request.idempotency_key:
            replay = self._replay_idempotent(request, request_id=request_id, started=started)
            if replay is not None:
                return replay

        authority_decision = "pending"
        try:
            self._validate_args(definition, request.arguments)
            request = self._confine_filesystem_args(request)
        except GatewayRejection as exc:
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
        except Exception as exc:  # noqa: BLE001 — normalized into CapabilityResult
            result = CapabilityResult(
                request_id=request_id,
                capability_id=definition.id,
                status=CapabilityStatus.FAILED,
                error=str(exc),
                side_effects=definition.side_effects,
                provider_kind=definition.provider_kind.value,
                provider_ref=definition.provider_ref,
                approval_id=request.approval_id,
                telemetry={"duration_ms": (time.perf_counter() - started) * 1000},
            )
            self.telemetry["failed"] += 1
            self._record_effect(result, request=request, authority_decision=authority_decision)
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
            self._maybe_consume_approval(request, output)
            self._record_effect(output, request=request, authority_decision=authority_decision)
            self._remember_idempotent(request, output)
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
        self._maybe_consume_approval(request, result)
        self._record_effect(result, request=request, authority_decision=authority_decision)
        self._remember_idempotent(request, result)
        return result

    def _replay_idempotent(
        self,
        request: CapabilityRequest,
        *,
        request_id: str,
        started: float,
    ) -> CapabilityResult | None:
        key = request.idempotency_key
        if not key:
            return None
        cached = self._idempotency_cache.get(key)
        if cached is not None and cached.capability_id == request.capability_id:
            return self._mark_replay(cached, request_id=request_id, started=started, source="memory")

        # Durable observation ledger (same process restart / multi-gateway share DB).
        store = self.observation_store
        getter = getattr(store, "get_completed_by_idempotency_key", None) if store else None
        if callable(getter):
            try:
                prior = getter(key)
            except Exception:  # noqa: BLE001 — lookup must not block execution
                prior = None
            if prior is not None:
                observation, effect = prior
                if observation.capability_id != request.capability_id:
                    return self._reject(
                        request_id,
                        request.capability_id,
                        f"Idempotency key {key!r} already used for capability "
                        f"{observation.capability_id!r}",
                        reason="idempotency_conflict",
                        started=started,
                        request=request,
                        authority_decision="rejected_idempotency_conflict",
                    )
                from Data.modules.function_runtime.types import SideEffect as _SE

                side_effects: tuple[Any, ...] = ()
                try:
                    side_effects = tuple(
                        _SE(s) if not isinstance(s, _SE) else s for s in observation.side_effects
                    )
                except Exception:  # noqa: BLE001
                    side_effects = ()
                rebuilt = CapabilityResult(
                    request_id=request_id,
                    capability_id=observation.capability_id,
                    status=CapabilityStatus.COMPLETED,
                    output=observation.output,
                    error=observation.error,
                    side_effects=side_effects,  # type: ignore[arg-type]
                    provider_kind=observation.provider_kind,
                    provider_ref=observation.provider_ref,
                    approval_id=observation.approval_id,
                    telemetry={
                        "duration_ms": (time.perf_counter() - started) * 1000,
                        "observation_id": observation.observation_id,
                        "effect_id": effect.effect_id,
                        "idempotent_replay": True,
                        "idempotent_replay_source": "observation_store",
                    },
                )
                self._idempotency_cache[key] = rebuilt
                self.telemetry["idempotent_replays"] = (
                    int(self.telemetry.get("idempotent_replays", 0)) + 1
                )
                self.telemetry["completed"] += 1
                return rebuilt
        return None

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
                "original_request_id": prior.request_id,
            },
        )
        self.telemetry["idempotent_replays"] = int(self.telemetry.get("idempotent_replays", 0)) + 1
        if prior.status == CapabilityStatus.COMPLETED:
            self.telemetry["completed"] += 1
        return replayed

    def _remember_idempotent(self, request: CapabilityRequest, result: CapabilityResult) -> None:
        if not request.idempotency_key or result.status != CapabilityStatus.COMPLETED:
            return
        self._idempotency_cache[request.idempotency_key] = result

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

        Workers (``LEVIATHAN_WORKER_ID`` set) and developer mode
        (``LEVIATHAN_WORKERS_EXTERNALIZE_API=false``) are exempt.
        Authorization/approval still apply independently.
        """
        from .workload import (
            ExecutionWorkloadClass,
            api_may_execute_inline,
            classify_capability,
        )

        meta = definition.normalized_metadata()
        cls = classify_capability(
            definition.id,
            metadata=meta,
            provider_kind=definition.provider_kind.value,
        )
        if cls != ExecutionWorkloadClass.EXTERNAL_REQUIRED:
            return
        if api_may_execute_inline(
            definition.id,
            metadata=meta,
            provider_kind=definition.provider_kind.value,
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
        if not self.approval_checker.is_approved(
            request.approval_id,
            capability_id=definition.id,
            side_effects=definition.side_effects,
        ):
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
    ) -> dict[str, Any]:
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
        if status == "FAILED":
            raise RuntimeError(str(result.get("error") or result.get("detail") or "Browser failed"))
        return result

    def _dispatch_media(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> dict[str, Any]:
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
        if status == "FAILED":
            raise RuntimeError(str(result.get("error") or result.get("detail") or "Media failed"))
        return result

    def _dispatch_voice(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> dict[str, Any]:
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
        if status in {"UNSUPPORTED", "CANCELLED"}:
            # CANCELLED is an honest barge-in outcome — surface as rejected for policy
            # but preserve payload for callers that inspect output via public_dict paths.
            if status == "CANCELLED":
                return result
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
        return self.module_executor.execute_module_capability(
            definition.id,
            definition.provider_ref,
            dict(request.arguments),
            request_id=request.request_id or "",
            run_id=request.run_id,
        )

    def _dispatch_mcp(
        self, definition: CapabilityDefinition, request: CapabilityRequest
    ) -> CapabilityResult:
        if self.mcp_executor is None:
            raise RuntimeError("MCP executor not configured on ExecutionGateway")
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
        return CapabilityResult(
            request_id=request.request_id or "",
            capability_id=definition.id,
            status=status,
            output=fn_result.output,
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
                observation, durable = self.observation_store.record_execution(
                    request_id=result.request_id,
                    capability_id=result.capability_id,
                    status=result.status.value,
                    side_effects=side_effects,
                    provider_kind=result.provider_kind,
                    provider_ref=result.provider_ref,
                    approval_id=result.approval_id,
                    run_id=run_id,
                    job_id=job_id,
                    output=result.output,
                    error=result.error,
                    duration_ms=duration_ms,
                    metadata={
                        "reason": (result.telemetry or {}).get("reason"),
                        "trace_id": request.trace_id if request else None,
                    },
                    idempotency_key=idem_for_ledger,
                    trace_id=request.trace_id if request else None,
                )
                observation_id = observation.observation_id
                effect_id = durable.effect_id
                self.telemetry["observations_recorded"] += 1
                result.telemetry["observation_id"] = observation_id
                result.telemetry["effect_id"] = effect_id
            except TypeError:
                # Older ObservationRecorder protocol without idempotency kwargs.
                try:
                    observation, durable = self.observation_store.record_execution(
                        request_id=result.request_id,
                        capability_id=result.capability_id,
                        status=result.status.value,
                        side_effects=side_effects,
                        provider_kind=result.provider_kind,
                        provider_ref=result.provider_ref,
                        approval_id=result.approval_id,
                        run_id=run_id,
                        job_id=job_id,
                        output=result.output,
                        error=result.error,
                        duration_ms=duration_ms,
                        metadata={
                            "reason": (result.telemetry or {}).get("reason"),
                            "trace_id": request.trace_id if request else None,
                        },
                    )
                    observation_id = observation.observation_id
                    effect_id = durable.effect_id
                    self.telemetry["observations_recorded"] += 1
                    result.telemetry["observation_id"] = observation_id
                    result.telemetry["effect_id"] = effect_id
                except Exception as exc:  # noqa: BLE001
                    result.telemetry["observation_persist_error"] = str(exc)
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
