"""Per-provider/model tool-calling capability cache.

States: native_verified | native_advertised | text_fallback | unsupported | unknown

No model-name hardcodes. ``native_verified`` only after a successful runtime probe
that exercised tools/tool_calls. Invalidate on model/endpoint/fingerprint change.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

NativeCapability = Literal[
    "native_verified",
    "native_advertised",
    "text_fallback",
    "unsupported",
    "unknown",
]


def capability_fingerprint(*, endpoint: str, model_id: str, config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    raw = "|".join(
        [
            str(endpoint or "").rstrip("/").lower(),
            str(model_id or "").strip(),
            str(cfg.get("api_variant") or "openai-chat"),
            str(cfg.get("tools_api") or "tools"),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class CapabilityRecord:
    fingerprint: str
    endpoint: str
    model_id: str
    state: NativeCapability = "unknown"
    reason: str = ""
    probed_at: float | None = None
    last_error: str | None = None
    successful_native_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolCapabilityCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, CapabilityRecord] = {}

    def get(
        self,
        *,
        endpoint: str,
        model_id: str,
        config: dict[str, Any] | None = None,
    ) -> CapabilityRecord:
        fp = capability_fingerprint(endpoint=endpoint, model_id=model_id, config=config)
        with self._lock:
            record = self._records.get(fp)
            if record is None:
                record = CapabilityRecord(fingerprint=fp, endpoint=endpoint, model_id=model_id)
                self._records[fp] = record
            return CapabilityRecord(**asdict(record))

    def set_state(
        self,
        *,
        endpoint: str,
        model_id: str,
        state: NativeCapability,
        reason: str = "",
        error: str | None = None,
        config: dict[str, Any] | None = None,
        increment_success: bool = False,
    ) -> CapabilityRecord:
        fp = capability_fingerprint(endpoint=endpoint, model_id=model_id, config=config)
        with self._lock:
            record = self._records.get(fp) or CapabilityRecord(fingerprint=fp, endpoint=endpoint, model_id=model_id)
            # Never downgrade native_verified to advertised/unknown without invalidate.
            if record.state == "native_verified" and state in {"native_advertised", "unknown"}:
                return CapabilityRecord(**asdict(record))
            record.state = state
            record.reason = reason
            record.last_error = error
            record.probed_at = time.time()
            if increment_success:
                record.successful_native_calls += 1
                record.state = "native_verified"
                record.reason = reason or "native tool_calls succeeded at runtime"
            self._records[fp] = record
            return CapabilityRecord(**asdict(record))

    def mark_native_success(self, *, endpoint: str, model_id: str, config: dict[str, Any] | None = None) -> CapabilityRecord:
        return self.set_state(
            endpoint=endpoint,
            model_id=model_id,
            state="native_verified",
            reason="native tool_calls succeeded at runtime",
            config=config,
            increment_success=True,
        )

    def mark_unsupported(self, *, endpoint: str, model_id: str, error: str, config: dict[str, Any] | None = None) -> CapabilityRecord:
        return self.set_state(
            endpoint=endpoint,
            model_id=model_id,
            state="text_fallback",
            reason="provider rejected or ignored native tools; using text fallback",
            error=error,
            config=config,
        )

    def invalidate(self, *, endpoint: str | None = None, model_id: str | None = None) -> int:
        """Drop cached rows matching endpoint and/or model (or all if both None)."""
        with self._lock:
            if endpoint is None and model_id is None:
                count = len(self._records)
                self._records.clear()
                return count
            drop = []
            for key, record in self._records.items():
                if endpoint is not None and record.endpoint.rstrip("/").lower() != str(endpoint).rstrip("/").lower():
                    continue
                if model_id is not None and record.model_id != model_id:
                    continue
                drop.append(key)
            for key in drop:
                del self._records[key]
            return len(drop)

    def prefer_native(self, record: CapabilityRecord | None) -> bool:
        if record is None:
            return True
        return record.state in {"native_verified", "native_advertised", "unknown"}


tool_capability_cache = ToolCapabilityCache()


class ToolsUnsupportedError(RuntimeError):
    """Raised when the provider rejects native tools; engine should fall back."""

    def __init__(self, message: str, *, endpoint: str = "", model_id: str = "") -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.model_id = model_id
