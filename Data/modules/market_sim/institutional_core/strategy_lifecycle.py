"""W55 — Closed research / strategy lifecycle states.

Extends strategy_lineage + promotion — closed-loop research states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .status import MeasurementState, DEFAULT_TRUTH


LIFECYCLE_STATES: tuple[str, ...] = (
    "IDEA",
    "RESEARCH",
    "BACKTEST",
    "VALIDATION",
    "SEALED_EVAL",
    "PAPER",
    "CHALLENGER",
    "CHAMPION",
    "RETIRED",
    "REJECTED",
)

ALLOWED_LIFECYCLE: dict[str, frozenset[str]] = {
    "IDEA": frozenset({"RESEARCH", "REJECTED"}),
    "RESEARCH": frozenset({"BACKTEST", "REJECTED", "IDEA"}),
    "BACKTEST": frozenset({"VALIDATION", "RESEARCH", "REJECTED"}),
    "VALIDATION": frozenset({"SEALED_EVAL", "BACKTEST", "REJECTED"}),
    "SEALED_EVAL": frozenset({"PAPER", "REJECTED", "VALIDATION"}),
    "PAPER": frozenset({"CHALLENGER", "RETIRED", "REJECTED"}),
    "CHALLENGER": frozenset({"CHAMPION", "PAPER", "RETIRED"}),
    "CHAMPION": frozenset({"RETIRED", "CHALLENGER"}),
    "RETIRED": frozenset(),
    "REJECTED": frozenset(),
}


@dataclass
class StrategyLifecycleRecord:
    strategy_id: str
    version: str
    state: str = "IDEA"
    evidence: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategyId": self.strategy_id,
            "version": self.version,
            "state": self.state,
            "evidence": dict(self.evidence),
            "history": list(self.history),
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "profitable_backtest_is_not_proof": True,
                "extends_strategy_lineage": True,
            },
        }


class StrategyLifecycle:
    def __init__(self) -> None:
        self._items: dict[str, StrategyLifecycleRecord] = {}

    def upsert(self, record: StrategyLifecycleRecord) -> StrategyLifecycleRecord:
        if record.state not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {record.state}")
        key = f"{record.strategy_id}@{record.version}"
        self._items[key] = record
        return record

    def transition(
        self,
        strategy_id: str,
        version: str,
        *,
        new_state: str,
        actor: str,
        ts: str,
        evidence_key: str | None = None,
        evidence_state: str | None = None,
        note: str = "",
    ) -> StrategyLifecycleRecord:
        key = f"{strategy_id}@{version}"
        rec = self._items[key]
        allowed = ALLOWED_LIFECYCLE.get(rec.state, frozenset())
        if new_state not in allowed:
            raise ValueError(f"illegal lifecycle transition {rec.state} -> {new_state}")

        # Honesty gates: sealed/paper require evidence labels.
        if new_state in {"SEALED_EVAL", "PAPER", "CHALLENGER", "CHAMPION"}:
            sealed = rec.evidence.get("sealed_holdout", MeasurementState.UNMEASURED.value)
            if new_state != "SEALED_EVAL" and sealed not in {
                MeasurementState.PASS.value,
                MeasurementState.OBSERVED.value,
                MeasurementState.MEASURED.value,
            }:
                if evidence_key != "sealed_holdout" or evidence_state not in {
                    MeasurementState.PASS.value,
                    MeasurementState.OBSERVED.value,
                    MeasurementState.MEASURED.value,
                }:
                    raise ValueError("sealed_holdout evidence required before paper/champion path")

        if evidence_key and evidence_state:
            rec.evidence[evidence_key] = evidence_state

        rec.history.append(
            {"from": rec.state, "to": new_state, "actor": actor, "ts": ts, "note": note}
        )
        rec.state = new_state
        if note:
            rec.notes.append(note)
        return rec

    def get(self, strategy_id: str, version: str) -> StrategyLifecycleRecord | None:
        return self._items.get(f"{strategy_id}@{version}")

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [r.public_dict() for r in self._items.values()],
            "count": len(self._items),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def record_from_mapping(raw: Mapping[str, Any]) -> StrategyLifecycleRecord:
    return StrategyLifecycleRecord(
        strategy_id=str(raw.get("strategy_id") or raw.get("strategyId") or ""),
        version=str(raw.get("version") or "0"),
        state=str(raw.get("state") or "IDEA"),
        evidence=dict(raw.get("evidence") or {}),
        notes=list(raw.get("notes") or []),
    )
