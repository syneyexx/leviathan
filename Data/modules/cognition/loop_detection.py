"""Loop detection for ineffective repeated cognitive actions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .types import CognitiveAction


@dataclass
class LoopDetector:
    """Track normalized action signatures; force replan/stop on repetition."""

    threshold: int = 3
    signatures: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)

    def signature(self, action: CognitiveAction, *, failure: str | None = None) -> str:
        payload = {
            "kind": action.kind.value,
            "capability_id": action.capability_id,
            "arguments": self._normalize_args(action.arguments),
            "failure": failure,
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def observe(self, action: CognitiveAction, *, failure: str | None = None) -> dict[str, Any]:
        sig = self.signature(action, failure=failure)
        self.signatures.append(sig)
        self.scores[sig] = self.scores.get(sig, 0) + 1
        score = self.scores[sig]
        looped = score >= self.threshold
        return {
            "signature": sig,
            "score": score,
            "loop_detected": looped,
            "threshold": self.threshold,
        }

    def reset(self) -> None:
        self.signatures.clear()
        self.scores.clear()

    @staticmethod
    def _normalize_args(arguments: dict[str, Any]) -> dict[str, Any]:
        # Drop volatile ids; keep semantic keys.
        skip = {"action_id", "request_id", "trace_id", "timestamp"}
        return {k: arguments[k] for k in sorted(arguments) if k not in skip}
