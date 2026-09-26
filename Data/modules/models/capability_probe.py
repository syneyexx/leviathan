"""Capability probing — tiny, cancellable, cached.

W2: probes measure real transport behavior where a probe harness exists.
Declared config alone never upgrades a capability to SUPPORTED.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from Data.modules.models.contracts import CapabilityState, VerifiedCapability
from Data.modules.models.errors import REQUEST_TIMEOUT, ModelControlError
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


# Default probe set for frontier transport (W2).
DEFAULT_PROBE_CAPABILITIES = [
    "chat",
    "streaming",
    "structuredOutput",
    "jsonSchemaResponse",
    "toolCalling",
    "logprobs",
    "reasoning",
    "embeddings",
]


class CapabilityProbeService:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        get_adapter: Callable[[str], Any],
    ) -> None:
        self.store = store
        self.registry = registry
        self._get_adapter = get_adapter
        self._cancel: dict[str, asyncio.Event] = {}

    def list_for_model(self, model_id: str) -> list[VerifiedCapability]:
        model = self.registry.get(model_id)
        declared = model.capabilities.public_dict()
        stored = {
            row["capability"]: row for row in self.store.list_capability_results(model_id)
        }
        results: list[VerifiedCapability] = []
        for name, declared_state in declared.items():
            row = stored.get(name)
            results.append(
                VerifiedCapability(
                    capability=name,
                    declared=CapabilityState(declared_state),
                    verified=CapabilityState(row["verified"]) if row else CapabilityState.UNKNOWN,
                    last_tested_at=row.get("last_tested_at") if row else None,
                    detail=row.get("detail") if row else None,
                )
            )
        return results

    async def probe(
        self,
        model_id: str,
        *,
        capabilities: list[str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> list[VerifiedCapability]:
        model = self.registry.get(model_id)
        adapter = self._get_adapter(model.provider_id)
        targets = capabilities or list(DEFAULT_PROBE_CAPABILITIES)
        cancel = asyncio.Event()
        self._cancel[model_id] = cancel
        results: list[VerifiedCapability] = []
        try:
            for name in targets:
                if cancel.is_set():
                    break
                declared = CapabilityState(
                    model.capabilities.public_dict().get(name, CapabilityState.UNKNOWN.value)
                )
                verified = CapabilityState.UNKNOWN
                detail = None
                try:
                    verified, detail = await self._probe_one(
                        adapter,
                        model_id,
                        name,
                        timeout_seconds=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    verified = CapabilityState.UNKNOWN
                    detail = "probe timed out"
                except ModelControlError as exc:
                    verified = (
                        CapabilityState.UNSUPPORTED
                        if exc.code != REQUEST_TIMEOUT
                        else CapabilityState.UNKNOWN
                    )
                    detail = exc.message
                except Exception as exc:  # noqa: BLE001
                    verified = CapabilityState.UNKNOWN
                    detail = str(exc)

                now = utc_now()
                self.store.upsert_capability_result(
                    {
                        "model_id": model_id,
                        "capability": name,
                        "declared": declared.value,
                        "verified": verified.value,
                        "last_tested_at": now,
                        "detail": detail,
                    }
                )
                results.append(
                    VerifiedCapability(
                        capability=name,
                        declared=declared,
                        verified=verified,
                        last_tested_at=now,
                        detail=detail,
                    )
                )
        finally:
            self._cancel.pop(model_id, None)
        return results

    async def _probe_one(
        self,
        adapter: Any,
        model_id: str,
        name: str,
        *,
        timeout_seconds: float,
    ) -> tuple[CapabilityState, str | None]:
        """Run one capability probe. Prefer adapter-specific hooks; never invent SUPPORTED."""
        # Adapter may expose measured probe hooks (preferred).
        hook = getattr(adapter, "probe_capability", None)
        if callable(hook):
            outcome = await asyncio.wait_for(
                hook(model_id, capability=name),
                timeout=timeout_seconds,
            )
            return self._interpret_hook_outcome(name, outcome)

        if name in {"chat", "streaming"}:
            coro = adapter.test_inference(model_id, prompt="Reply with OK", max_tokens=4)
            outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
            ok = bool(outcome.get("ok"))
            return (
                CapabilityState.SUPPORTED if ok else CapabilityState.UNSUPPORTED,
                f"latencyMs={outcome.get('latencyMs')}",
            )

        if name in {"structuredOutput", "jsonSchemaResponse"}:
            # Prefer schema-valid probe when adapter supports it.
            schema_hook = getattr(adapter, "test_structured_output", None)
            if callable(schema_hook):
                outcome = await asyncio.wait_for(
                    schema_hook(
                        model_id,
                        schema={
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"],
                        },
                    ),
                    timeout=timeout_seconds,
                )
                if outcome.get("schema_valid"):
                    return CapabilityState.SUPPORTED, "schema-valid JSON response"
                if outcome.get("ok") and outcome.get("json_parsed"):
                    # Parsed JSON but not schema-valid → UNVERIFIED / partial honesty.
                    return (
                        CapabilityState.UNVERIFIED,
                        "JSON parsed but schema validation failed",
                    )
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "structured probe failed")

            coro = adapter.test_inference(
                model_id,
                prompt='Reply with only JSON: {"ok":true}',
                max_tokens=16,
            )
            outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
            preview = str(outcome.get("preview") or "")
            try:
                parsed = json.loads(preview[preview.find("{") : preview.rfind("}") + 1])
                valid = isinstance(parsed, dict) and "ok" in parsed
            except Exception:  # noqa: BLE001
                valid = False
            if valid:
                return (
                    CapabilityState.UNVERIFIED,
                    "heuristic JSON parse — not native json_schema response_format probe",
                )
            return CapabilityState.UNSUPPORTED, "no parseable JSON object in probe response"

        if name == "toolCalling":
            tool_hook = getattr(adapter, "test_tool_calling", None)
            if callable(tool_hook):
                outcome = await asyncio.wait_for(tool_hook(model_id), timeout=timeout_seconds)
                if outcome.get("tool_call_roundtrip"):
                    return CapabilityState.SUPPORTED, "tool call roundtrip observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "no tool call")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_tool_calling probe — not inferred from config",
            )

        if name == "logprobs":
            logprob_hook = getattr(adapter, "test_logprobs", None)
            if callable(logprob_hook):
                outcome = await asyncio.wait_for(logprob_hook(model_id), timeout=timeout_seconds)
                if outcome.get("logprobs_present"):
                    return CapabilityState.SUPPORTED, "logprobs present in response"
                return CapabilityState.UNSUPPORTED, "logprobs requested but absent"
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_logprobs probe — not inferred from config",
            )

        if name == "reasoning":
            reason_hook = getattr(adapter, "test_reasoning", None)
            if callable(reason_hook):
                outcome = await asyncio.wait_for(reason_hook(model_id), timeout=timeout_seconds)
                if outcome.get("reasoning_usage"):
                    return CapabilityState.SUPPORTED, "reasoning usage fields observed"
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "no reasoning usage")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_reasoning probe — not inferred from config",
            )

        if name == "embeddings":
            emb_hook = getattr(adapter, "test_embeddings", None)
            if callable(emb_hook):
                outcome = await asyncio.wait_for(emb_hook(model_id), timeout=timeout_seconds)
                if outcome.get("ok") and outcome.get("dimensions"):
                    return (
                        CapabilityState.SUPPORTED,
                        f"embedding dims={outcome.get('dimensions')}",
                    )
                return CapabilityState.UNSUPPORTED, str(outcome.get("detail") or "embeddings failed")
            return (
                CapabilityState.UNMEASURED,
                "adapter has no test_embeddings probe — not inferred from config",
            )

        return CapabilityState.UNMEASURED, "probe not implemented for this capability"

    @staticmethod
    def _interpret_hook_outcome(
        name: str, outcome: Any
    ) -> tuple[CapabilityState, str | None]:
        if not isinstance(outcome, dict):
            return CapabilityState.UNKNOWN, "probe hook returned non-dict"
        state_raw = outcome.get("state") or outcome.get("verified")
        if state_raw:
            try:
                return CapabilityState(str(state_raw)), outcome.get("detail")
            except ValueError:
                pass
        if outcome.get("ok") or outcome.get("supported"):
            return CapabilityState.SUPPORTED, outcome.get("detail")
        if outcome.get("unsupported"):
            return CapabilityState.UNSUPPORTED, outcome.get("detail")
        if outcome.get("unmeasured"):
            return CapabilityState.UNMEASURED, outcome.get("detail")
        return CapabilityState.UNKNOWN, outcome.get("detail") or f"probe={name}"

    def cancel(self, model_id: str) -> bool:
        event = self._cancel.get(model_id)
        if not event:
            return False
        event.set()
        return True
