"""Provider_io job executor — policy + adapters + cancellation."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from Data.modules.jobs.states import JobState
from Data.modules.provider_io.adapters.alpaca_paper import AlpacaPaperAdapter
from Data.modules.provider_io.adapters.generic_http import GenericHttpAdapter
from Data.modules.provider_io.adapters.huggingface_meta import HuggingFaceMetaAdapter
from Data.modules.provider_io.adapters.market_data import MarketDataAdapter
from Data.modules.provider_io.adapters.market_stream import MarketStreamAdapter
from Data.modules.provider_io.adapters.openai_compatible import OpenAICompatibleAdapter
from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import (
    assert_no_secrets_in_payload,
    resolve_credential,
)
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import (
    DeadlineBudget,
    ProviderIoSettings,
    ProviderPolicyRegistry,
)
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import (
    IdempotencyClass,
    ProviderExecutionResult,
    ProviderRequest,
    StreamEventType,
)


def _request_from_job_args(args: dict[str, Any], *, job_id: str) -> ProviderRequest:
    payload = dict(args.get("payload") or {})
    # Also accept flattened fields for ergonomics.
    for key in (
        "url",
        "method",
        "headers",
        "body",
        "messages",
        "endpoint",
        "base_url",
        "temperature",
        "max_tokens",
        "provider_id",
        "symbol",
        "timeframe",
        "limit",
        "markets_root",
        "repository_id",
        "revision",
        "model",
        "tools",
        "tool_choice",
        "response_format",
        "max_bytes",
        "allow_private_hosts",
    ):
        if key in args and key not in payload:
            payload[key] = args[key]

    assert_no_secrets_in_payload(payload)
    assert_no_secrets_in_payload(
        {k: v for k, v in args.items() if k not in {"payload", "messages"}}
    )

    capability = str(args.get("capability") or args.get("operation") or "http").strip()
    provider = str(args.get("provider") or payload.get("provider_id") or "generic").strip()
    streaming = bool(args.get("streaming") or capability.endswith("stream"))
    idem_raw = str(args.get("idempotency_class") or "READ").upper()
    try:
        idem = IdempotencyClass(idem_raw)
    except ValueError:
        idem = IdempotencyClass.READ

    return ProviderRequest(
        provider=provider,
        capability=capability,
        model=(str(args.get("model") or payload.get("model") or "").strip() or None),
        payload=payload,
        streaming=streaming,
        deadline_seconds=(
            float(args["deadline_seconds"])
            if args.get("deadline_seconds") is not None
            else None
        ),
        correlation_id=(str(args.get("correlation_id") or "").strip() or None),
        job_id=job_id,
        principal_ref=(str(args.get("principal_ref") or "").strip() or None),
        idempotency_class=idem,
        idempotency_key=(str(args.get("idempotency_key") or "").strip() or None),
        credential_ref=(str(args.get("credential_ref") or "").strip() or None),
        allow_private_hosts=bool(
            args.get("allow_private_hosts") or payload.get("allow_private_hosts")
        ),
    )


class ProviderIoExecutor:
    """Stateful executor owned by one provider_io worker process."""

    def __init__(
        self,
        *,
        db_path: str | None = None,
        settings: ProviderIoSettings | None = None,
    ) -> None:
        self.settings = settings or ProviderIoSettings.load()
        self.policy = ProviderPolicyRegistry(self.settings)
        self.clients = ProviderClientPool(self.settings)
        self.stream_store = ProviderStreamStore(
            db_path or os.environ.get("LEVIATHAN_DB_PATH") or "Data/state/leviathan.db",
            max_events_per_job=self.settings.max_buffered_stream_events,
        )
        self.stream_store.initialize()
        self._adapters = {
            "http": GenericHttpAdapter(),
            "generic_http": GenericHttpAdapter(),
            "chat.complete": OpenAICompatibleAdapter(),
            "chat.stream": OpenAICompatibleAdapter(),
            "openai_compatible": OpenAICompatibleAdapter(),
            "market.fetch": MarketDataAdapter(),
            "market.stream": MarketStreamAdapter(),
            "market.stream.stop": MarketStreamAdapter(),
            "alpaca.paper": AlpacaPaperAdapter(),
            "hf.list": HuggingFaceMetaAdapter(),
            "huggingface.list": HuggingFaceMetaAdapter(),
        }

    def close(self) -> None:
        self.clients.close()

    def execute_job(self, ctx: dict[str, Any], job: Any) -> dict[str, Any]:
        store = ctx["job_store"]
        args = dict(job.arguments or {})
        request = _request_from_job_args(args, job_id=job.job_id)
        worker_id = str(ctx.get("worker_id") or f"provider_io-{os.getpid()}")

        def cancel_check() -> bool:
            try:
                current = store.get(job.job_id)
            except Exception:  # noqa: BLE001
                return False
            if current is None:
                return True
            return current.state == JobState.CANCEL_REQUESTED

        def heartbeat() -> None:
            try:
                if hasattr(store, "heartbeat_lease"):
                    store.heartbeat_lease(
                        job.job_id,
                        worker_id=worker_id,
                        ttl_seconds=float(ctx.get("lease_ttl_seconds") or 30.0),
                    )
            except Exception:  # noqa: BLE001
                pass

        deadline = float(
            request.deadline_seconds
            if request.deadline_seconds is not None
            else getattr(job, "timeout_seconds", None)
            or self.settings.total_deadline_seconds
        )
        # Long-lived market streams use payload max_runtime_seconds as the wall clock.
        if request.capability == "market.stream":
            payload_runtime = request.payload.get("max_runtime_seconds")
            if payload_runtime is not None:
                deadline = max(deadline, float(payload_runtime))
            elif request.deadline_seconds is None and getattr(job, "timeout_seconds", None) is None:
                deadline = max(deadline, 3600.0)
        budget = DeadlineBudget(total_seconds=max(1.0, deadline))

        adapter = self._adapters.get(request.capability)
        if adapter is None:
            # Fallback: treat unknown capability as generic HTTP when url present.
            if "url" in request.payload:
                adapter = self._adapters["http"]
            else:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                    f"Unknown provider capability: {request.capability}",
                    provider=request.provider,
                )

        credential = resolve_credential(request.credential_ref)
        circuit = self.policy.circuit(request.provider)
        emitted_output = False
        last_error: ProviderError | None = None
        t_queue = time.monotonic()

        # Queue saturation is primarily enforced at enqueue time; here we only execute.
        self.policy.telemetry["calls"] = int(self.policy.telemetry.get("calls", 0)) + 1

        for attempt in range(self.settings.max_attempts):
            budget.raise_if_exhausted()
            if cancel_check():
                result = ProviderExecutionResult(
                    status="cancelled",
                    provider=request.provider,
                    model=request.model,
                    error=ProviderError(
                        ProviderErrorCode.EXECUTION_CANCELLED,
                        "Cancelled",
                        provider=request.provider,
                    ).public_dict(),
                    worker_pid=os.getpid(),
                )
                store.transition(
                    job.job_id,
                    JobState.CANCELLED,
                    error="EXECUTION_CANCELLED",
                    result=result.public_dict(),
                )
                self.policy.telemetry["cancelled"] = (
                    int(self.policy.telemetry.get("cancelled", 0)) + 1
                )
                return result.public_dict()

            try:
                circuit.allow()
            except ProviderError as exc:
                self.policy.telemetry["circuit_open"] = (
                    int(self.policy.telemetry.get("circuit_open", 0)) + 1
                )
                last_error = exc
                break

            wait = self.policy.rate_limits.wait_seconds(request.provider)
            if wait > 0:
                sleep_for = min(wait, budget.remaining())
                time.sleep(sleep_for)

            acquired = self.policy.concurrency.acquire(
                request.provider, timeout=min(5.0, budget.remaining())
            )
            if not acquired:
                last_error = ProviderError(
                    ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED,
                    f"Provider concurrency saturated for {request.provider}",
                    provider=request.provider,
                    retryable=True,
                )
                time.sleep(self.policy.backoff(attempt))
                continue

            heartbeat()
            try:
                emit_cb = None
                if callable(ctx.get("emit")):
                    emit_cb = ctx.get("emit")
                elif callable(args.get("emit")):
                    emit_cb = args.get("emit")
                execute_kwargs: dict[str, Any] = {
                    "clients": self.clients,
                    "credential": credential,
                    "policy": self.policy,
                    "budget": budget,
                    "stream_store": self.stream_store if request.streaming else None,
                    "cancel_check": cancel_check,
                }
                # Market stream adapter accepts optional emit/ingest/ctx.
                if request.capability in {"market.stream", "market.stream.stop"}:
                    store_path = getattr(store, "path", None)
                    execute_kwargs["emit"] = emit_cb
                    execute_kwargs["ingest"] = ctx.get("ingest") or request.payload.get(
                        "ingest_callback"
                    )
                    execute_kwargs["ctx"] = {
                        **{k: v for k, v in ctx.items() if k != "job_store"},
                        "db_path": str(
                            store_path
                            or os.environ.get("LEVIATHAN_DB_PATH")
                            or self.stream_store.db_path
                            or ""
                        ),
                        "emit": emit_cb,
                    }
                result = adapter.execute(request, **execute_kwargs)
                result.worker_pid = os.getpid()
                result.timing = {
                    **dict(result.timing or {}),
                    "attempt": attempt + 1,
                    "queue_wait_seconds": max(0.0, time.monotonic() - t_queue),
                }
                circuit.record_success()
                self.policy.telemetry["success"] = (
                    int(self.policy.telemetry.get("success", 0)) + 1
                )
                store.transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result=result.public_dict(),
                )
                return result.public_dict()
            except ProviderError as exc:
                last_error = exc
                exc.attempt = attempt + 1
                if exc.code == ProviderErrorCode.PROVIDER_RATE_LIMITED:
                    self.policy.rate_limits.observe_rate_limit(
                        request.provider, retry_after=exc.retry_after_seconds
                    )
                    self.policy.telemetry["rate_limited"] = (
                        int(self.policy.telemetry.get("rate_limited", 0)) + 1
                    )
                if exc.code == ProviderErrorCode.EXECUTION_CANCELLED:
                    if request.streaming and request.job_id:
                        self.stream_store.append(
                            request.job_id,
                            StreamEventType.CANCELLED,
                            {"reason": "cancel_requested"},
                            correlation_id=request.correlation_id,
                        )
                    store.transition(
                        job.job_id,
                        JobState.CANCELLED,
                        error=exc.code.value,
                        result=ProviderExecutionResult(
                            status="cancelled",
                            provider=request.provider,
                            error=exc.public_dict(),
                            worker_pid=os.getpid(),
                        ).public_dict(),
                    )
                    self.policy.telemetry["cancelled"] = (
                        int(self.policy.telemetry.get("cancelled", 0)) + 1
                    )
                    return {"status": "cancelled", "error": exc.public_dict()}

                # Detect prior stream emission via stream store
                if request.streaming and request.job_id:
                    prior = self.stream_store.read_after(request.job_id, 0, limit=5)
                    emitted_output = any(
                        e.event_type == StreamEventType.DELTA for e in prior
                    )

                if self.policy.should_retry(
                    exc,
                    attempt=attempt,
                    emitted_output=emitted_output,
                    budget=budget,
                    idempotency_class=request.idempotency_class.value,
                ):
                    circuit.record_failure()
                    self.policy.telemetry["retries"] = (
                        int(self.policy.telemetry.get("retries", 0)) + 1
                    )
                    delay = self.policy.backoff(
                        attempt, retry_after=exc.retry_after_seconds
                    )
                    delay = min(delay, budget.remaining())
                    time.sleep(max(0.0, delay))
                    continue
                circuit.record_failure()
                break
            except Exception as exc:  # noqa: BLE001
                last_error = ProviderError(
                    ProviderErrorCode.UNKNOWN,
                    str(exc),
                    provider=request.provider,
                    retryable=False,
                )
                circuit.record_failure()
                break
            finally:
                self.policy.concurrency.release(request.provider)

        self.policy.telemetry["failure"] = int(self.policy.telemetry.get("failure", 0)) + 1
        err = last_error or ProviderError(
            ProviderErrorCode.UNKNOWN,
            "Provider execution failed",
            provider=request.provider,
        )
        result = ProviderExecutionResult(
            status="failed",
            provider=request.provider,
            model=request.model,
            error=err.public_dict(),
            worker_pid=os.getpid(),
        )
        # Non-retryable or exhausted → FAILED (job kernel may still schedule retry on lease)
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=err.code.value,
            result=result.public_dict(),
        )
        return result.public_dict()


def build_handler(ctx: dict[str, Any]) -> Callable[[Any, Any], dict[str, Any]]:
    """Create a pool-loop handler bound to a process-local executor."""
    db_path = str(getattr(ctx.get("settings"), "database_path", "") or "")
    executor = ProviderIoExecutor(db_path=db_path or None)
    ctx["provider_io_executor"] = executor
    ctx["worker_id"] = ctx.get("worker_id") or f"provider_io-{os.getpid()}"

    def _handler(inner_ctx: dict[str, Any], job: Any) -> dict[str, Any]:
        return executor.execute_job(inner_ctx, job)

    return _handler
