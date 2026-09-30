"""Decision receipt projection for externally reportable trading/research decisions.

Projects existing DecisionPacket / risk receipt authorities into a UI-safe receipt.
Does NOT create a second trading authority or decision ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from Data.modules.observability.redaction import redact_payload


DECISION_RECEIPT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DecisionCheckResult:
    name: str
    status: str  # PASS | FAIL | PENDING | SKIPPED | UNMEASURED | UNAVAILABLE | BLOCKED
    detail: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidenceRefs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class DecisionReceipt:
    """Externally reportable decision receipt — projection, not authority."""

    decision_id: str
    operation_id: str | None = None
    actor_id: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    model_version: str | None = None
    timestamp: str | None = None
    instrument_or_universe: str | None = None
    data_version: str | None = None
    market_data_snapshot_ref: str | None = None
    feature_provenance_refs: tuple[str, ...] = ()
    research_evidence_refs: tuple[str, ...] = ()
    hypothesis_ref: str | None = None
    checks: tuple[DecisionCheckResult, ...] = ()
    risk_limits_in_force: dict[str, Any] = field(default_factory=dict)
    requested_config: dict[str, Any] = field(default_factory=dict)
    effective_config: dict[str, Any] = field(default_factory=dict)
    decision_result: str | None = None
    execution_status: str | None = None
    artifact_or_order_ref: str | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    source: str = "decision_packet"
    schema_version: int = DECISION_RECEIPT_SCHEMA_VERSION

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "operationId": self.operation_id,
            "actorId": self.actor_id,
            "strategyId": self.strategy_id,
            "strategyVersion": self.strategy_version,
            "modelVersion": self.model_version,
            "timestamp": self.timestamp,
            "instrumentOrUniverse": self.instrument_or_universe,
            "dataVersion": self.data_version,
            "marketDataSnapshotRef": self.market_data_snapshot_ref,
            "featureProvenanceRefs": list(self.feature_provenance_refs),
            "researchEvidenceRefs": list(self.research_evidence_refs),
            "hypothesisRef": self.hypothesis_ref,
            "checks": [c.public_dict() for c in self.checks],
            "riskLimitsInForce": redact_payload(dict(self.risk_limits_in_force)),
            "requestedConfig": redact_payload(dict(self.requested_config)),
            "effectiveConfig": redact_payload(dict(self.effective_config)),
            "decisionResult": self.decision_result,
            "executionStatus": self.execution_status,
            "artifactOrOrderRef": self.artifact_or_order_ref,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "source": self.source,
            "schemaVersion": self.schema_version,
            "truth": {
                "projection_not_authority": True,
                "pass_requires_real_check": True,
                "extends_decision_packet": self.source == "decision_packet",
            },
        }


def _status_from_measurement(value: Any) -> str:
    raw = str(value or "").strip().upper()
    allowed = {
        "PASS",
        "FAIL",
        "PENDING",
        "SKIPPED",
        "UNMEASURED",
        "UNAVAILABLE",
        "BLOCKED",
        "OBSERVED",
        "ALLOW",
        "REJECT",
    }
    if raw in {"ALLOW", "ALLOWED", "OK", "SUCCESS"}:
        return "PASS"
    if raw in {"REJECT", "REJECTED", "DENIED"}:
        return "FAIL"
    if raw in allowed:
        return raw
    if not raw:
        return "UNMEASURED"
    return "UNMEASURED"


def decision_receipt_from_packet(
    packet: Mapping[str, Any] | Any,
    *,
    operation_id: str | None = None,
) -> DecisionReceipt:
    """Project a DecisionPacket.public_dict() (or similar) into a DecisionReceipt."""
    if hasattr(packet, "public_dict"):
        data = packet.public_dict()
    else:
        data = dict(packet)

    payload = dict(data.get("payload") or {})
    checks_raw = payload.get("checks") or data.get("checks") or []
    checks: list[DecisionCheckResult] = []
    if isinstance(checks_raw, Sequence) and not isinstance(checks_raw, (str, bytes)):
        for item in checks_raw:
            if not isinstance(item, Mapping):
                continue
            status = _status_from_measurement(item.get("status") or item.get("result"))
            # Never upgrade missing verification to PASS.
            if status == "OBSERVED":
                status = "UNMEASURED"
            checks.append(
                DecisionCheckResult(
                    name=str(item.get("name") or item.get("check") or "check"),
                    status=status,
                    detail=str(item["detail"]) if item.get("detail") is not None else None,
                    evidence_refs=tuple(
                        str(x) for x in (item.get("evidenceRefs") or item.get("evidence_refs") or ())
                    ),
                )
            )

    refs = data.get("refs") or []
    evidence_refs: list[str] = []
    if isinstance(refs, Sequence):
        for ref in refs:
            if isinstance(ref, Mapping) and ref.get("digest"):
                evidence_refs.append(f"{ref.get('kind')}:{ref.get('digest')}")
            elif isinstance(ref, str):
                evidence_refs.append(ref)

    decision_id = str(
        data.get("packetId")
        or data.get("packet_id")
        or data.get("decisionId")
        or data.get("decision_id")
        or ""
    )
    return DecisionReceipt(
        decision_id=decision_id,
        operation_id=operation_id or (str(data["operationId"]) if data.get("operationId") else None),
        actor_id=str(data.get("actor") or payload.get("actorId") or "") or None,
        strategy_id=_opt(payload.get("strategyId") or payload.get("strategy_id")),
        strategy_version=_opt(payload.get("strategyVersion") or payload.get("strategy_version")),
        model_version=_opt(payload.get("modelVersion") or payload.get("model_version")),
        timestamp=_opt(data.get("createdAt") or data.get("asOf") or data.get("as_of")),
        instrument_or_universe=_opt(
            payload.get("instrumentOrUniverse")
            or payload.get("universe")
            or payload.get("instrument")
        ),
        data_version=_opt(payload.get("dataVersion") or payload.get("data_version")),
        market_data_snapshot_ref=_opt(
            payload.get("marketDataSnapshotRef") or payload.get("market_data_snapshot_ref")
        ),
        feature_provenance_refs=tuple(
            str(x) for x in (payload.get("featureProvenanceRefs") or ())
        ),
        research_evidence_refs=tuple(evidence_refs),
        hypothesis_ref=_opt(payload.get("hypothesisRef") or payload.get("hypothesis_id")),
        checks=tuple(checks),
        risk_limits_in_force=dict(payload.get("riskLimitsInForce") or payload.get("risk_limits") or {}),
        requested_config=dict(payload.get("requestedConfig") or payload.get("requested") or {}),
        effective_config=dict(payload.get("effectiveConfig") or payload.get("effective") or {}),
        decision_result=_opt(payload.get("decisionResult") or data.get("status") or payload.get("result")),
        execution_status=_opt(payload.get("executionStatus") or payload.get("execution_status")),
        artifact_or_order_ref=_opt(
            payload.get("artifactOrOrderRef")
            or payload.get("order_ref")
            or payload.get("artifact_ref")
        ),
        warnings=tuple(str(x) for x in (payload.get("warnings") or ())),
        errors=tuple(str(x) for x in (payload.get("errors") or ())),
        source="decision_packet",
    )


def decision_receipt_from_risk_receipt(
    receipt: Mapping[str, Any],
    *,
    operation_id: str | None = None,
) -> DecisionReceipt:
    """Project a MarketSim risk receipt row/dict into a DecisionReceipt."""
    data = dict(receipt)
    decision = str(data.get("decision") or data.get("status") or "").upper()
    status = _status_from_measurement(decision)
    check = DecisionCheckResult(
        name="risk_guard",
        status=status if status in {"PASS", "FAIL", "PENDING", "BLOCKED", "UNAVAILABLE"} else "UNMEASURED",
        detail=_opt(data.get("reason") or data.get("detail")),
    )
    return DecisionReceipt(
        decision_id=str(data.get("receipt_id") or data.get("id") or data.get("decision_id") or ""),
        operation_id=operation_id,
        actor_id=_opt(data.get("actor") or data.get("agent_id")),
        strategy_id=_opt(data.get("strategy_id")),
        timestamp=_opt(data.get("created_at") or data.get("timestamp")),
        instrument_or_universe=_opt(data.get("symbol") or data.get("instrument")),
        checks=(check,),
        risk_limits_in_force=dict(data.get("limits") or {}),
        requested_config=dict(data.get("requested") or {}),
        effective_config=dict(data.get("effective") or {}),
        decision_result=status,
        execution_status=_opt(data.get("execution_status")),
        warnings=tuple(str(x) for x in (data.get("warnings") or ())),
        errors=tuple(str(x) for x in (data.get("errors") or ())),
        source="market_risk_receipt",
    )


def _opt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
