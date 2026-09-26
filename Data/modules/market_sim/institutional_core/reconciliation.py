"""W43 — Reconciliation breaks + compare contracts.

No silent auto-resolve. Correlate identical breaks; human/status workflow only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


BREAK_STATUSES: tuple[str, ...] = (
    "OPEN",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "EXPLAINED",
    "REMEDIATION_REQUIRED",
    "RESOLVED",
    "WAIVED",
)

TERMINAL_STATUSES: frozenset[str] = frozenset({"RESOLVED", "WAIVED"})

# Allowed transitions — no silent OPEN→RESOLVED.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "OPEN": frozenset({"ACKNOWLEDGED", "INVESTIGATING", "WAIVED"}),
    "ACKNOWLEDGED": frozenset({"INVESTIGATING", "EXPLAINED", "REMEDIATION_REQUIRED", "WAIVED"}),
    "INVESTIGATING": frozenset({"EXPLAINED", "REMEDIATION_REQUIRED", "ACKNOWLEDGED", "WAIVED"}),
    "EXPLAINED": frozenset({"REMEDIATION_REQUIRED", "RESOLVED", "WAIVED"}),
    "REMEDIATION_REQUIRED": frozenset({"INVESTIGATING", "RESOLVED", "WAIVED"}),
    "RESOLVED": frozenset(),
    "WAIVED": frozenset(),
}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def break_fingerprint(
    *,
    domain: str,
    left_key: str,
    right_key: str,
    field: str,
    left_value: Any,
    right_value: Any,
) -> str:
    payload = {
        "domain": domain,
        "left_key": left_key,
        "right_key": right_key,
        "field": field,
        "left_value": left_value,
        "right_value": right_value,
    }
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


@dataclass
class Break:
    break_id: str
    domain: str
    field: str
    left_system: str
    right_system: str
    left_key: str
    right_key: str
    left_value: Any
    right_value: Any
    status: str = "OPEN"
    fingerprint: str = ""
    correlation_id: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    explanation: str | None = None

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = break_fingerprint(
                domain=self.domain,
                left_key=self.left_key,
                right_key=self.right_key,
                field=self.field,
                left_value=self.left_value,
                right_value=self.right_value,
            )
        if self.status not in BREAK_STATUSES:
            raise ValueError(f"invalid break status: {self.status}")

    def public_dict(self) -> dict[str, Any]:
        return {
            "breakId": self.break_id,
            "domain": self.domain,
            "field": self.field,
            "leftSystem": self.left_system,
            "rightSystem": self.right_system,
            "leftKey": self.left_key,
            "rightKey": self.right_key,
            "leftValue": self.left_value,
            "rightValue": self.right_value,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "correlationId": self.correlation_id,
            "history": list(self.history),
            "explanation": self.explanation,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "no_silent_auto_resolve": True,
            },
        }


def transition_break(
    brk: Break,
    *,
    new_status: str,
    actor: str,
    ts: str,
    note: str = "",
    auto: bool = False,
) -> Break:
    if auto and new_status in TERMINAL_STATUSES:
        raise ValueError("silent auto-resolve is forbidden")
    allowed = ALLOWED_TRANSITIONS.get(brk.status, frozenset())
    if new_status not in allowed:
        raise ValueError(f"illegal transition {brk.status} -> {new_status}")
    if new_status == "RESOLVED" and not (note or brk.explanation):
        raise ValueError("RESOLVED requires explanation/note")
    brk.history.append(
        {
            "from": brk.status,
            "to": new_status,
            "actor": actor,
            "ts": ts,
            "note": note,
            "auto": False,
        }
    )
    brk.status = new_status
    if note and new_status in {"EXPLAINED", "RESOLVED", "WAIVED"}:
        brk.explanation = note
    return brk


@dataclass
class CompareContract:
    """Declarative comparison between two keyed value maps."""

    contract_id: str
    domain: str
    left_system: str
    right_system: str
    fields: tuple[str, ...]
    key_field: str = "id"
    numeric_tolerance: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "contractId": self.contract_id,
            "domain": self.domain,
            "leftSystem": self.left_system,
            "rightSystem": self.right_system,
            "fields": list(self.fields),
            "keyField": self.key_field,
            "numericTolerance": self.numeric_tolerance,
        }


def _values_differ(left: Any, right: Any, *, tol: float) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) > tol
    return left != right


def compare_maps(
    contract: CompareContract,
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    id_prefix: str = "brk",
) -> list[Break]:
    left_by = {str(r.get(contract.key_field)): dict(r) for r in left_rows}
    right_by = {str(r.get(contract.key_field)): dict(r) for r in right_rows}
    keys = sorted(set(left_by) | set(right_by))
    breaks: list[Break] = []
    seq = 0
    for key in keys:
        left = left_by.get(key)
        right = right_by.get(key)
        if left is None or right is None:
            seq += 1
            breaks.append(
                Break(
                    break_id=f"{id_prefix}-{seq}",
                    domain=contract.domain,
                    field=contract.key_field,
                    left_system=contract.left_system,
                    right_system=contract.right_system,
                    left_key=key if left is not None else "",
                    right_key=key if right is not None else "",
                    left_value=None if left is None else left.get(contract.key_field),
                    right_value=None if right is None else right.get(contract.key_field),
                )
            )
            continue
        for field_name in contract.fields:
            lv = left.get(field_name)
            rv = right.get(field_name)
            if _values_differ(lv, rv, tol=contract.numeric_tolerance):
                seq += 1
                breaks.append(
                    Break(
                        break_id=f"{id_prefix}-{seq}",
                        domain=contract.domain,
                        field=field_name,
                        left_system=contract.left_system,
                        right_system=contract.right_system,
                        left_key=key,
                        right_key=key,
                        left_value=lv,
                        right_value=rv,
                    )
                )
    return breaks


def correlate_breaks(breaks: Sequence[Break]) -> list[Break]:
    """Group identical fingerprints under one correlation_id (first break id)."""
    groups: dict[str, list[Break]] = {}
    for brk in breaks:
        groups.setdefault(brk.fingerprint, []).append(brk)
    out: list[Break] = []
    for fingerprint, group in groups.items():
        corr = group[0].break_id
        for brk in group:
            brk.correlation_id = corr
            out.append(brk)
        _ = fingerprint
    return out


@dataclass
class ReconciliationRun:
    run_id: str
    contract: CompareContract
    breaks: list[Break]
    status: str = MeasurementState.OBSERVED.value

    def public_dict(self) -> dict[str, Any]:
        open_count = sum(1 for b in self.breaks if b.status not in TERMINAL_STATUSES)
        return {
            "runId": self.run_id,
            "contract": self.contract.public_dict(),
            "breaks": [b.public_dict() for b in self.breaks],
            "openCount": open_count,
            "breakCount": len(self.breaks),
            "status": MeasurementState.FAIL.value if open_count else MeasurementState.PASS.value,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "empty_left_and_right_is_not_pass_unless_expected": True,
                "no_silent_auto_resolve": True,
            },
        }


def run_reconciliation(
    *,
    run_id: str,
    contract: CompareContract,
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
) -> ReconciliationRun:
    breaks = correlate_breaks(compare_maps(contract, left_rows, right_rows, id_prefix=run_id))
    return ReconciliationRun(run_id=run_id, contract=contract, breaks=breaks)
