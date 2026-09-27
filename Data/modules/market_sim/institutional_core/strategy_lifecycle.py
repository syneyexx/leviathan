"""W55 / Wave 13 — Closed research / strategy lifecycle states.

Extends strategy_lineage + promotion — closed-loop research states.

Persistence: prefer ``store.save_strategy_lifecycle`` / ``get_strategy_lifecycle``
when the MARKET store exposes them (Wave 3). Otherwise keep an in-memory map
with an explicit persistence hook so callers can wire durable storage later.

Only :class:`StrategyLifecycle` service methods may perform state transitions.
Do not invent a ``DEGRADED`` state — represent degradation via evidence +
CHALLENGER/RETIRED transitions.
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

_PASSISH = frozenset(
    {
        MeasurementState.PASS.value,
        MeasurementState.OBSERVED.value,
        MeasurementState.MEASURED.value,
        "QUALIFIED",
        "COMPLETED",
        "PRESENT",
    }
)

EVIDENCE_BINDINGS: dict[tuple[str, str], tuple[str, ...]] = {
    ("BACKTEST", "VALIDATION"): ("backtest_completed",),
    ("VALIDATION", "SEALED_EVAL"): (
        "qualification_wfa",
        "qualification_statistics",
        "qualification_robustness",
    ),
    ("SEALED_EVAL", "PAPER"): ("qualification_decision", "sealed_holdout"),
    ("PAPER", "CHALLENGER"): ("paper_evidence",),
    ("CHALLENGER", "CHAMPION"): ("forward_evidence",),
    ("CHAMPION", "CHALLENGER"): ("drift_or_governance",),
    ("CHALLENGER", "RETIRED"): ("retirement_policy",),
    ("CHAMPION", "RETIRED"): ("retirement_policy",),
}


@dataclass
class StrategyLifecycleRecord:
    strategy_id: str
    version: str
    state: str = "IDEA"
    evidence: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    qualification_id: str | None = None
    paper_deployment_id: str | None = None
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategyId": self.strategy_id,
            "version": self.version,
            "state": self.state,
            "evidence": dict(self.evidence),
            "history": list(self.history),
            "notes": list(self.notes),
            "qualificationId": self.qualification_id,
            "paperDeploymentId": self.paper_deployment_id,
            "updatedAt": self.updated_at,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "profitable_backtest_is_not_proof": True,
                "extends_strategy_lineage": True,
                "no_degraded_state": True,
                "transitions_via_service_only": True,
            },
        }

    def persistence_dict(self) -> dict[str, Any]:
        """Canonical MARKET row shape for save_strategy_lifecycle."""
        version_int: int | str
        try:
            version_int = int(self.version)
        except (TypeError, ValueError):
            version_int = self.version
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": version_int,
            "state": self.state,
            "evidence": dict(self.evidence),
            "history": list(self.history),
            "notes": list(self.notes),
            "qualification_id": self.qualification_id,
            "paper_deployment_id": self.paper_deployment_id,
            "updated_at": self.updated_at,
        }


def _evidence_ok(evidence: Mapping[str, str], key: str) -> bool:
    return str(evidence.get(key) or "").strip().upper() in _PASSISH


class StrategyLifecycle:
    """Lifecycle service — sole authority for state transitions."""

    def __init__(self, store: Any | None = None) -> None:
        self._items: dict[str, StrategyLifecycleRecord] = {}
        self._store = store
        self._audit: list[dict[str, Any]] = []

    def bind_store(self, store: Any | None) -> None:
        """Attach / replace MARKET store used for durable lifecycle rows."""
        self._store = store

    def _persist(self, record: StrategyLifecycleRecord) -> None:
        store = self._store
        if store is not None and hasattr(store, "save_strategy_lifecycle"):
            store.save_strategy_lifecycle(record.persistence_dict())

    def _load_from_store(self, strategy_id: str, version: str) -> StrategyLifecycleRecord | None:
        store = self._store
        if store is None or not hasattr(store, "get_strategy_lifecycle"):
            return None
        try:
            version_key: Any = int(version)
        except (TypeError, ValueError):
            version_key = version
        raw = store.get_strategy_lifecycle(strategy_id, version_key)
        if not raw:
            return None
        rec = record_from_mapping(raw if isinstance(raw, Mapping) else dict(raw))
        self._items[f"{rec.strategy_id}@{rec.version}"] = rec
        return rec

    def _write_audit(
        self,
        *,
        strategy_id: str,
        version: str,
        from_state: str,
        to_state: str,
        actor: str,
        ts: str,
        note: str,
        evidence_snapshot: Mapping[str, str],
    ) -> dict[str, Any]:
        event = {
            "kind": "STRATEGY_LIFECYCLE_TRANSITION",
            "strategy_id": strategy_id,
            "version": version,
            "from": from_state,
            "to": to_state,
            "actor": actor,
            "ts": ts,
            "note": note,
            "evidence": dict(evidence_snapshot),
        }
        self._audit.append(event)
        store = self._store
        if store is not None:
            for name in ("append_audit_event", "append_lifecycle_audit", "record_audit"):
                if hasattr(store, name):
                    try:
                        getattr(store, name)(event)
                    except Exception:  # noqa: BLE001
                        pass
                    break
        return event

    def upsert(self, record: StrategyLifecycleRecord) -> StrategyLifecycleRecord:
        """Insert or replace a record (bootstrap / load). Does not validate transitions."""
        if record.state not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {record.state}")
        if record.state == "DEGRADED":
            raise ValueError("DEGRADED is not a lifecycle state")
        key = f"{record.strategy_id}@{record.version}"
        self._items[key] = record
        self._persist(record)
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
        qualification_id: str | None = None,
        paper_deployment_id: str | None = None,
        extra_evidence: Mapping[str, str] | None = None,
    ) -> StrategyLifecycleRecord:
        """Only path that may move a strategy between lifecycle states."""
        if new_state == "DEGRADED":
            raise ValueError(
                "DEGRADED is not a lifecycle state — use evidence + CHALLENGER/RETIRED"
            )
        if new_state not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {new_state}")

        key = f"{strategy_id}@{version}"
        rec = self._items.get(key) or self._load_from_store(strategy_id, version)
        if rec is None:
            raise KeyError(f"lifecycle record not found: {key}")

        allowed = ALLOWED_LIFECYCLE.get(rec.state, frozenset())
        if new_state not in allowed:
            raise ValueError(f"illegal lifecycle transition {rec.state} -> {new_state}")

        # Stage evidence on a copy — only commit to the record after all checks pass.
        staged_evidence = dict(rec.evidence)
        if evidence_key and evidence_state:
            staged_evidence[evidence_key] = evidence_state
        if extra_evidence:
            for k, v in extra_evidence.items():
                staged_evidence[str(k)] = str(v)

        staged = StrategyLifecycleRecord(
            strategy_id=rec.strategy_id,
            version=rec.version,
            state=rec.state,
            evidence=staged_evidence,
            history=list(rec.history),
            notes=list(rec.notes),
            qualification_id=str(qualification_id) if qualification_id else rec.qualification_id,
            paper_deployment_id=(
                str(paper_deployment_id) if paper_deployment_id else rec.paper_deployment_id
            ),
            updated_at=rec.updated_at,
        )

        self._enforce_evidence_bindings(staged, new_state=new_state)

        if new_state in {"SEALED_EVAL", "PAPER", "CHALLENGER", "CHAMPION"}:
            sealed = staged.evidence.get("sealed_holdout", MeasurementState.UNMEASURED.value)
            if new_state != "SEALED_EVAL" and sealed not in {
                MeasurementState.PASS.value,
                MeasurementState.OBSERVED.value,
                MeasurementState.MEASURED.value,
                "QUALIFIED",
            }:
                raise ValueError("sealed_holdout evidence required before paper/champion path")

        if new_state == "PAPER" and staged.state == "SEALED_EVAL":
            q_state = str(staged.evidence.get("qualification_decision") or "").upper()
            if q_state not in {"QUALIFIED", MeasurementState.PASS.value, "TRUE", "1"}:
                raise ValueError(
                    "SEALED_EVAL->PAPER requires QUALIFIED qualification_decision evidence"
                )
            sealed = str(staged.evidence.get("sealed_holdout") or "").upper()
            if sealed not in {
                MeasurementState.PASS.value,
                MeasurementState.OBSERVED.value,
                MeasurementState.MEASURED.value,
                "QUALIFIED",
            }:
                raise ValueError("SEALED_EVAL->PAPER requires sealed receipt evidence")

        # Commit staged evidence only after validation.
        rec.evidence = staged_evidence
        if qualification_id:
            rec.qualification_id = str(qualification_id)
        if paper_deployment_id:
            rec.paper_deployment_id = str(paper_deployment_id)

        from_state = rec.state
        rec.history.append(
            {
                "from": from_state,
                "to": new_state,
                "actor": actor,
                "ts": ts,
                "note": note,
                "evidence": dict(rec.evidence),
            }
        )
        rec.state = new_state
        rec.updated_at = ts
        if note:
            rec.notes.append(note)

        self._write_audit(
            strategy_id=strategy_id,
            version=version,
            from_state=from_state,
            to_state=new_state,
            actor=actor,
            ts=ts,
            note=note,
            evidence_snapshot=rec.evidence,
        )
        self._persist(rec)
        return rec

    def _enforce_evidence_bindings(
        self,
        rec: StrategyLifecycleRecord,
        *,
        new_state: str,
    ) -> None:
        required = EVIDENCE_BINDINGS.get((rec.state, new_state))
        if not required:
            return
        missing = [k for k in required if not _evidence_ok(rec.evidence, k)]
        if missing:
            raise ValueError(
                f"missing evidence for {rec.state}->{new_state}: {', '.join(missing)}"
            )

    def get(self, strategy_id: str, version: str) -> StrategyLifecycleRecord | None:
        key = f"{strategy_id}@{version}"
        rec = self._items.get(key)
        if rec is not None:
            return rec
        return self._load_from_store(strategy_id, version)

    def audit_events(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [r.public_dict() for r in self._items.values()],
            "count": len(self._items),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "no_degraded_state": True,
                "transitions_via_service_only": True,
            },
        }


StrategyLifecycleService = StrategyLifecycle


def record_from_mapping(raw: Mapping[str, Any]) -> StrategyLifecycleRecord:
    version = raw.get("version")
    if version is None:
        version = raw.get("strategy_version")
    return StrategyLifecycleRecord(
        strategy_id=str(raw.get("strategy_id") or raw.get("strategyId") or ""),
        version=str(version if version is not None else "0"),
        state=str(raw.get("state") or "IDEA"),
        evidence=dict(raw.get("evidence") or raw.get("evidence_json") or {}),
        history=list(raw.get("history") or raw.get("history_json") or []),
        notes=list(raw.get("notes") or raw.get("notes_json") or []),
        qualification_id=(
            str(raw["qualification_id"])
            if raw.get("qualification_id") is not None
            else (str(raw["qualificationId"]) if raw.get("qualificationId") is not None else None)
        ),
        paper_deployment_id=(
            str(raw["paper_deployment_id"])
            if raw.get("paper_deployment_id") is not None
            else (
                str(raw["paperDeploymentId"]) if raw.get("paperDeploymentId") is not None else None
            )
        ),
        updated_at=(
            str(raw["updated_at"])
            if raw.get("updated_at") is not None
            else (str(raw["updatedAt"]) if raw.get("updatedAt") is not None else None)
        ),
    )
