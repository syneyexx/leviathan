"""Token/cost observability. Never fabricate precision. Never spend a model call to compute this."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

TokenKind = Literal["exact", "estimated", "unknown"]


def classify_tokens(value: Any, *, estimated: bool = False) -> tuple[int | None, TokenKind]:
    if estimated:
        try:
            return int(value), "estimated"
        except (TypeError, ValueError):
            return None, "unknown"
    if value is None:
        return None, "unknown"
    try:
        return int(value), "exact"
    except (TypeError, ValueError):
        return None, "unknown"


@dataclass
class CostCounters:
    model_calls: int = 0
    routing_model_calls: int = 0
    unnecessary_model_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    context_chars: int = 0
    agent_count: int = 0
    tool_rounds: int = 0
    retries: int = 0
    duplicate_retrieval: int = 0
    duplicate_tool_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    skill_load_count: int = 0
    tool_schema_load_count: int = 0
    latency_ms_sum: float = 0.0
    token_kind: TokenKind = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "routing_model_calls": self.routing_model_calls,
            "unnecessary_model_calls": self.unnecessary_model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "context_chars": self.context_chars,
            "agent_count": self.agent_count,
            "tool_rounds": self.tool_rounds,
            "retries": self.retries,
            "duplicate_retrieval": self.duplicate_retrieval,
            "duplicate_tool_calls": self.duplicate_tool_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "skill_load_count": self.skill_load_count,
            "tool_schema_load_count": self.tool_schema_load_count,
            "latency_ms_sum": round(self.latency_ms_sum, 2),
            "token_kind": self.token_kind,
            "tokens_per_verified_result": None
            if self.input_tokens is None or self.output_tokens is None
            else (self.input_tokens + self.output_tokens),
            "model_calls_per_verified_result": self.model_calls,
        }


@dataclass
class CostLedger:
    counters: CostCounters = field(default_factory=CostCounters)
    reasons: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_model_call(
        self,
        *,
        reason: str,
        input_tokens: Any = None,
        output_tokens: Any = None,
        cached_tokens: Any = None,
        estimated: bool = False,
        routing: bool = False,
        latency_ms: float | None = None,
    ) -> None:
        if not reason.strip():
            raise ValueError("model_call_requires_reason")
        in_tok, in_kind = classify_tokens(input_tokens, estimated=estimated)
        out_tok, out_kind = classify_tokens(output_tokens, estimated=estimated)
        cached, _cached_kind = classify_tokens(cached_tokens, estimated=estimated)
        kind: TokenKind = "exact"
        if in_kind == "unknown" and out_kind == "unknown":
            kind = "unknown"
        elif "estimated" in {in_kind, out_kind} or estimated:
            kind = "estimated"
        with self._lock:
            self.counters.model_calls += 1
            if routing:
                self.counters.routing_model_calls += 1
            self.counters.token_kind = kind if self.counters.model_calls == 1 else (
                "unknown" if kind != self.counters.token_kind and "unknown" in {kind, self.counters.token_kind} else kind
            )
            if in_tok is not None:
                self.counters.input_tokens = (self.counters.input_tokens or 0) + in_tok
            if out_tok is not None:
                self.counters.output_tokens = (self.counters.output_tokens or 0) + out_tok
            if cached is not None:
                self.counters.cached_tokens = (self.counters.cached_tokens or 0) + cached
            if latency_ms is not None:
                self.counters.latency_ms_sum += float(latency_ms)
            self.reasons.append({"kind": "model_call", "reason": reason, "routing": routing, "token_kind": kind, "at": time.time()})

    def record_unnecessary_model_call(self, reason: str) -> None:
        with self._lock:
            self.counters.unnecessary_model_calls += 1
            self.reasons.append({"kind": "unnecessary_model_call_detected", "reason": reason, "at": time.time()})

    def add(self, **fields: int) -> None:
        with self._lock:
            for key, value in fields.items():
                if hasattr(self.counters, key):
                    current = getattr(self.counters, key)
                    if isinstance(current, int):
                        setattr(self.counters, key, current + int(value))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = self.counters.to_dict()
            payload["decision_reasons"] = list(self.reasons[-40:])
            return payload


_LEDGER = CostLedger()


def get_ledger() -> CostLedger:
    return _LEDGER


def reset_ledger() -> None:
    global _LEDGER
    _LEDGER = CostLedger()
