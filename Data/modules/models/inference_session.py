"""Canonical Model Control Plane inference session.

Stage B physical session: residency lease → gateway admission → inference → cleanup.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from Data.modules.model_runtime.serving import InferenceJobClass
from Data.modules.models.contracts import ResolvedModelTarget, ResidencyLease
from Data.modules.models.errors import ModelControlError


@dataclass
class InferenceSession:
    """Active inference session owning lease + gateway admission."""

    target: ResolvedModelTarget
    lease: ResidencyLease
    call_id: str
    job_class: InferenceJobClass
    endpoint: str
    api_key: str | None
    backend_model_id: str
    llm: Any
    plane: Any
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def model_id(self) -> str:
        return self.target.model.id

    @property
    def provider_id(self) -> str:
        return self.target.provider_id

    @property
    def context_window(self) -> int | None:
        return self.target.context_window

    @property
    def profile(self) -> Any:
        return self.target.profile

    async def complete_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        skip_context_fit: bool = False,
        dialect_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        parallel_tool_calls: bool | None = None,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        reasoning_max_tokens: int | None = None,
        logprobs: bool | None = None,
        top_logprobs: int | None = None,
        n: int | None = None,
        prompt_cache_key: str | None = None,
        cache_control: dict[str, Any] | None = None,
        reject_unsupported: bool = True,
        on_context_overflow: str = "refuse",
        enforce_structured: bool = True,
        structured_fail_closed: bool = True,
    ) -> dict[str, Any]:
        profile = self.target.profile
        effective_max = max_tokens
        if effective_max is None:
            effective_max = profile.max_tokens
        elif profile.max_tokens is not None:
            effective_max = min(int(profile.max_tokens), int(effective_max))

        outbound = list(messages)
        context_signal: dict[str, Any] | None = None
        if not skip_context_fit:
            # Prefer efficiency-plane preflight; always fall through to transport
            # contract bounds so overflow is never silent.
            try:
                from Data.modules.context.efficiency import get_efficiency_plane
                from Data.modules.context.fit import preflight_context_fit, raise_if_unfit

                plane_eff = get_efficiency_plane()
                decision = preflight_context_fit(
                    messages=list(outbound),
                    model_id=self.model_id,
                    context_window=self.context_window,
                    max_output_tokens=effective_max,
                    profile_max_tokens=getattr(profile, "max_tokens", None),
                    explicit_selection=bool(getattr(self.target, "explicit_selection", False)),
                    tokenization=plane_eff.tokenization,
                )
                if decision.state.value in {
                    "TOO_LARGE_PINNED_CONTEXT",
                    "TOO_LARGE_FOR_SELECTED_MODEL",
                }:
                    plane_eff.metrics.context_fit_failures += 1
                    if on_context_overflow == "truncate" and decision.state.value != "TOO_LARGE_PINNED_CONTEXT":
                        from Data.modules.model_runtime.inference_contract import (
                            enforce_context_bounds,
                        )

                        outbound, signal = enforce_context_bounds(
                            outbound,
                            context_window=self.context_window,
                            max_output_tokens=effective_max,
                            policy="truncate",
                        )
                        context_signal = signal.public_dict()
                    else:
                        raise_if_unfit(decision)
            except ModelControlError:
                raise
            except Exception:  # noqa: BLE001 — transport contract still enforces bounds
                pass

        result = await self.llm.complete_messages(
            outbound,
            model_id=self.backend_model_id,
            endpoint=self.endpoint,
            api_key=self.api_key,
            temperature=profile.temperature if temperature is None else temperature,
            max_tokens=effective_max,
            top_p=profile.top_p if top_p is None else top_p,
            dialect_id=dialect_id,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
            reasoning_effort=reasoning_effort,
            reasoning_max_tokens=reasoning_max_tokens,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
            n=n,
            prompt_cache_key=prompt_cache_key,
            cache_control=cache_control,
            reject_unsupported=reject_unsupported,
            context_window=self.context_window,
            on_context_overflow=on_context_overflow,
            enforce_structured=enforce_structured,
            structured_fail_closed=structured_fail_closed,
        )
        if context_signal and isinstance(result, dict) and "context_bound" not in result:
            result["context_bound"] = context_signal
        # Record provider cached tokens when present.
        try:
            from Data.modules.context.efficiency import get_efficiency_plane

            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(usage, dict) and "cached_input_tokens" in usage:
                get_efficiency_plane().metrics.cached_input_tokens_provider += int(
                    usage["cached_input_tokens"]
                )
            elif isinstance(usage, dict) and "cached_tokens" in usage:
                get_efficiency_plane().metrics.cached_input_tokens_provider += int(usage["cached_tokens"])
        except Exception:  # noqa: BLE001
            pass
        await self.plane.residency.touch_lease(self.lease.lease_id, model_id=self.model_id)
        self.plane.registry.touch_used(self.model_id)
        return result

    async def chat_stream(self, **kwargs: Any) -> Any:
        """Delegate streaming to the shared transport; residency held by session."""
        stream = self.llm.chat_stream(**kwargs)
        return stream

    async def release(self, *, error: str | None = None) -> None:
        if self._released:
            return
        self._released = True
        try:
            self.plane.gateway.release(
                model_id=self.model_id,
                provider_id=self.provider_id,
                error=error,
                job_class=self.job_class,
            )
        finally:
            await self.plane.residency.release_lease(
                self.lease.lease_id, model_id=self.model_id
            )


@asynccontextmanager
async def open_inference_session(
    plane: Any,
    target: ResolvedModelTarget,
    *,
    llm: Any,
    consumer: str,
    domain: str | None = None,
    model_role: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    job_class: str = "INTERACTIVE",
    gateway_timeout_seconds: float | None = None,
) -> AsyncIterator[InferenceSession]:
    """Acquire residency then Gateway, yield session, always clean up."""
    try:
        jc = InferenceJobClass(job_class)
    except ValueError:
        jc = InferenceJobClass.INTERACTIVE

    binding = target.runtime_binding
    managed = bool(target.managed)
    external = not managed
    runtime_kind = binding.runtime_kind if binding else (target.model.runtime_id or "unknown")

    # Prefer residency ensure before occupying a scarce gateway slot.
    lease = await plane.residency.acquire_lease(
        target.model.id,
        consumer=consumer,
        domain=domain,
        model_role=model_role or target.preferred_role,
        run_id=run_id,
        trace_id=trace_id or target.route.trace_id,
        job_class=jc.value,
        explicit_selection=target.explicit_selection,
        managed=managed,
        runtime_kind=runtime_kind,
        ensure_ready=managed,
        external=external,
        endpoint=target.endpoint,
        load_options=(
            plane.residency.get_policy(target.model.id).load_options if managed else None
        ),
    )

    timeout = gateway_timeout_seconds
    if timeout is None:
        timeout = min(float(getattr(plane.settings, "llm_timeout_seconds", 30.0)), 120.0)

    call_id: str | None = None
    session: InferenceSession | None = None
    error_code: str | None = None
    try:
        # Refresh endpoint from residency if managed worker published one.
        snap = plane.residency.snapshot(target.model.id)
        endpoint = snap.endpoint or target.endpoint
        call_id = plane.gateway.acquire(
            model_id=target.model.id,
            provider_id=target.provider_id,
            timeout_seconds=timeout,
            job_class=jc,
        )
        plane.gateway.record_selection(target.model.id, trace_id=call_id or trace_id)
        session = InferenceSession(
            target=target,
            lease=lease,
            call_id=call_id,
            job_class=jc,
            endpoint=endpoint,
            api_key=target.api_key,
            backend_model_id=target.backend_model_id,
            llm=llm,
            plane=plane,
        )
        yield session
    except ModelControlError as exc:
        error_code = exc.code
        raise
    except Exception:
        error_code = "inference_session_error"
        raise
    finally:
        if session is not None:
            await session.release(error=error_code)
        else:
            # Failed before session object — still release gateway + lease.
            if call_id is not None:
                try:
                    plane.gateway.release(
                        model_id=target.model.id,
                        provider_id=target.provider_id,
                        error=error_code,
                        job_class=jc,
                    )
                except Exception:  # noqa: BLE001
                    pass
            try:
                await plane.residency.release_lease(lease.lease_id, model_id=target.model.id)
            except Exception:  # noqa: BLE001
                pass
