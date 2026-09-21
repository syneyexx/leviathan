"""Capability probing — tiny, cancellable, cached."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from Data.modules.models.contracts import CapabilityState, VerifiedCapability
from Data.modules.models.errors import REQUEST_TIMEOUT, ModelControlError
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


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
        targets = capabilities or ["chat", "streaming", "structuredOutput"]
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
                    if name in {"chat", "streaming"}:
                        coro = adapter.test_inference(model_id, prompt="Reply with OK", max_tokens=4)
                        outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
                        verified = (
                            CapabilityState.SUPPORTED
                            if outcome.get("ok")
                            else CapabilityState.UNSUPPORTED
                        )
                        detail = f"latencyMs={outcome.get('latencyMs')}"
                    elif name == "structuredOutput":
                        # Tiny structured probe: ask for JSON; verify parse — does not claim native schema support.
                        coro = adapter.test_inference(
                            model_id,
                            prompt='Reply with only JSON: {"ok":true}',
                            max_tokens=16,
                        )
                        outcome = await asyncio.wait_for(coro, timeout=timeout_seconds)
                        preview = str(outcome.get("preview") or "")
                        verified = (
                            CapabilityState.SUPPORTED
                            if "{" in preview and "}" in preview
                            else CapabilityState.UNVERIFIED
                        )
                        detail = "heuristic JSON presence check — not schema validation"
                    else:
                        verified = CapabilityState.UNVERIFIED
                        detail = "probe not implemented for this capability"
                except asyncio.TimeoutError:
                    verified = CapabilityState.UNKNOWN
                    detail = "probe timed out"
                except ModelControlError as exc:
                    verified = CapabilityState.UNSUPPORTED if exc.code != REQUEST_TIMEOUT else CapabilityState.UNKNOWN
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

    def cancel(self, model_id: str) -> bool:
        event = self._cancel.get(model_id)
        if not event:
            return False
        event.set()
        return True
