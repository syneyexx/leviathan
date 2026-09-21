"""Live model usage telemetry for Chat (exact provider usage vs estimates)."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

UsageKind = Literal["exact", "estimate", "unavailable"]
UsageStatus = Literal["idle", "queued", "generating", "tool_continuation", "error", "cancelled"]


def estimate_tokens_from_text(text: str) -> int:
    """Conservative char/4 heuristic. Labeled estimate only — never claim provider-exact."""
    length = len(text or "")
    return max(1, (length + 3) // 4) if length else 0


def estimate_usage_from_response(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Derive a labeled token estimate from response text when provider usage is absent."""
    if not isinstance(response, dict):
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(content)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else {}
            parts.append(str(fn.get("name") or ""))
            parts.append(str(fn.get("arguments") or ""))
    if not any(parts):
        return None
    out = estimate_tokens_from_text("\n".join(parts))
    if out <= 0:
        return None
    return {
        "total_tokens": out,
        "completion_tokens": out,
        "prompt_tokens": None,
        "estimated": True,
    }


@dataclass
class UsageSample:
    at: float
    total_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    kind: UsageKind
    model_id: str | None = None
    status: UsageStatus = "idle"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UsageSnapshot:
    status: UsageStatus = "idle"
    model_id: str | None = None
    current_total: int | None = None
    current_input: int | None = None
    current_output: int | None = None
    current_kind: UsageKind = "unavailable"
    peak_total: int | None = None
    session_total: int = 0
    conversation_total: int = 0
    model_calls: int = 0
    history: list[UsageSample] = field(default_factory=list)
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_id": self.model_id,
            "current": {
                "total_tokens": self.current_total,
                "input_tokens": self.current_input,
                "output_tokens": self.current_output,
                "kind": self.current_kind,
            },
            "peak": {"total_tokens": self.peak_total},
            "totals": {
                "session_tokens": self.session_total,
                "conversation_tokens": self.conversation_total,
            },
            "model_calls": self.model_calls,
            "history": [item.to_dict() for item in self.history[-60:]],
            "last_error": self.last_error,
        }


class UsageTelemetry:
    """Process-local live usage tracker. Peak/session totals survive React rerenders."""

    def __init__(self, *, history_limit: int = 90) -> None:
        self._lock = threading.RLock()
        self._history_limit = history_limit
        self._by_conversation: dict[str, UsageSnapshot] = {}
        self._session = UsageSnapshot()

    def _snap(self, conversation_id: str | None) -> UsageSnapshot:
        if not conversation_id:
            return self._session
        if conversation_id not in self._by_conversation:
            self._by_conversation[conversation_id] = UsageSnapshot()
        return self._by_conversation[conversation_id]

    def _targets(self, conversation_id: str | None) -> tuple[UsageSnapshot, ...]:
        """Return distinct mutation targets; session must never be updated twice."""
        if not conversation_id:
            return (self._session,)
        return (self._session, self._snap(conversation_id))

    def set_status(
        self,
        status: UsageStatus,
        *,
        conversation_id: str | None = None,
        model_id: str | None = None,
        error: str | None = None,
    ) -> UsageSnapshot:
        with self._lock:
            for snap in self._targets(conversation_id):
                snap.status = status
                if model_id:
                    snap.model_id = model_id
                if error is not None:
                    snap.last_error = error
                snap.history.append(
                    UsageSample(
                        at=time.time(),
                        total_tokens=snap.current_total,
                        input_tokens=snap.current_input,
                        output_tokens=snap.current_output,
                        kind=snap.current_kind,
                        model_id=snap.model_id,
                        status=status,
                    )
                )
                snap.history = snap.history[-self._history_limit :]
            return self.snapshot(conversation_id)

    def record_usage(
        self,
        usage: dict[str, Any] | None,
        *,
        conversation_id: str | None = None,
        model_id: str | None = None,
        status: UsageStatus = "generating",
        kind: UsageKind | None = None,
    ) -> UsageSnapshot:
        with self._lock:
            resolved_kind: UsageKind
            if kind is not None:
                resolved_kind = kind
            elif not usage:
                resolved_kind = "unavailable"
            else:
                resolved_kind = "exact"
            total = None
            inp = None
            out = None
            if isinstance(usage, dict) and usage:
                try:
                    total = int(usage["total_tokens"]) if usage.get("total_tokens") is not None else None
                except (TypeError, ValueError):
                    total = None
                try:
                    inp = int(usage["input_tokens"] if "input_tokens" in usage else usage.get("prompt_tokens")) if (
                        usage.get("input_tokens") is not None or usage.get("prompt_tokens") is not None
                    ) else None
                except (TypeError, ValueError):
                    inp = None
                try:
                    out = int(usage["output_tokens"] if "output_tokens" in usage else usage.get("completion_tokens")) if (
                        usage.get("output_tokens") is not None or usage.get("completion_tokens") is not None
                    ) else None
                except (TypeError, ValueError):
                    out = None
                if total is None and inp is not None and out is not None:
                    total = inp + out

            conversation_snap = self._snap(conversation_id) if conversation_id else None
            for snap in self._targets(conversation_id):
                snap.status = status
                if model_id:
                    snap.model_id = model_id
                snap.current_kind = resolved_kind
                snap.current_total = total
                snap.current_input = inp
                snap.current_output = out
                snap.model_calls += 1
                if total is not None:
                    snap.session_total = int(snap.session_total) + total
                    if conversation_snap is not None and snap is conversation_snap:
                        snap.conversation_total = int(snap.conversation_total) + total
                    if snap.peak_total is None or total > snap.peak_total:
                        snap.peak_total = total
                snap.history.append(
                    UsageSample(
                        at=time.time(),
                        total_tokens=total,
                        input_tokens=inp,
                        output_tokens=out,
                        kind=resolved_kind,
                        model_id=snap.model_id,
                        status=status,
                    )
                )
                snap.history = snap.history[-self._history_limit :]
            return self.snapshot(conversation_id)

    def record_provisional(
        self,
        *,
        output_tokens: int | None,
        input_tokens: int | None = None,
        conversation_id: str | None = None,
        model_id: str | None = None,
        status: UsageStatus = "generating",
    ) -> UsageSnapshot:
        """Update live CURRENT counters without bumping model_calls or session totals.

        Used while streaming so the Chat usage card can climb every second without
        inventing completed turn costs.
        """
        with self._lock:
            total = None
            if output_tokens is not None and input_tokens is not None:
                total = int(input_tokens) + int(output_tokens)
            elif output_tokens is not None:
                total = int(output_tokens)
            elif input_tokens is not None:
                total = int(input_tokens)
            for snap in self._targets(conversation_id):
                snap.status = status
                if model_id:
                    snap.model_id = model_id
                snap.current_kind = "estimate"
                if input_tokens is not None:
                    snap.current_input = int(input_tokens)
                if output_tokens is not None:
                    snap.current_output = int(output_tokens)
                if total is not None:
                    snap.current_total = int(total)
                    if snap.peak_total is None or total > snap.peak_total:
                        snap.peak_total = int(total)
                snap.history.append(
                    UsageSample(
                        at=time.time(),
                        total_tokens=snap.current_total,
                        input_tokens=snap.current_input,
                        output_tokens=snap.current_output,
                        kind="estimate",
                        model_id=snap.model_id,
                        status=status,
                    )
                )
                snap.history = snap.history[-self._history_limit :]
            return self.snapshot(conversation_id)

    def snapshot(self, conversation_id: str | None = None) -> UsageSnapshot:
        with self._lock:
            snap = self._snap(conversation_id)
            # Merge session peak if conversation peak missing
            out = UsageSnapshot(
                status=snap.status,
                model_id=snap.model_id or self._session.model_id,
                current_total=snap.current_total,
                current_input=snap.current_input,
                current_output=snap.current_output,
                current_kind=snap.current_kind,
                peak_total=snap.peak_total if snap.peak_total is not None else self._session.peak_total,
                session_total=self._session.session_total,
                conversation_total=snap.conversation_total if conversation_id else self._session.session_total,
                model_calls=snap.model_calls if conversation_id else self._session.model_calls,
                history=list(snap.history),
                last_error=snap.last_error,
            )
            return out


usage_telemetry = UsageTelemetry()
