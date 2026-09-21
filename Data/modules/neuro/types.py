from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NeuroSignal:
    """Advisory neural-style signal. Never authority for execution or completion."""

    signal_id: str
    kind: str
    strength: float
    summary: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "kind": self.kind,
            "strength": self.strength,
            "summary": self.summary,
            "provenance": self.provenance,
            "truth": {
                "neural_signal_is_not_authority": True,
                "advisory_only": True,
            },
        }


@dataclass(frozen=True)
class NeuroAssessment:
    enabled: bool
    signals: tuple[NeuroSignal, ...]
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "signals": [item.public_dict() for item in self.signals],
            "notes": list(self.notes),
            "truth": {
                "neural_signal_is_not_authority": True,
                "does_not_authorize_execution": True,
                "does_not_prove_completion": True,
            },
        }
