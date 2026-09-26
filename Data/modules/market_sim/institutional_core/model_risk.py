"""W53 — Quant model risk lifecycle ( candidacy → validation → production → retire )."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .status import MeasurementState, DEFAULT_TRUTH


MODEL_STATES: tuple[str, ...] = (
    "CANDIDATE",
    "IN_VALIDATION",
    "APPROVED",
    "PRODUCTION",
    "CHALLENGED",
    "DEPRECATED",
    "RETIRED",
    "REJECTED",
)

ALLOWED_MODEL_TRANSITIONS: dict[str, frozenset[str]] = {
    "CANDIDATE": frozenset({"IN_VALIDATION", "REJECTED"}),
    "IN_VALIDATION": frozenset({"APPROVED", "REJECTED", "CANDIDATE"}),
    "APPROVED": frozenset({"PRODUCTION", "DEPRECATED", "REJECTED"}),
    "PRODUCTION": frozenset({"CHALLENGED", "DEPRECATED", "RETIRED"}),
    "CHALLENGED": frozenset({"PRODUCTION", "DEPRECATED", "RETIRED"}),
    "DEPRECATED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
    "REJECTED": frozenset(),
}


@dataclass
class ModelCard:
    model_id: str
    name: str
    version: str
    owner: str
    state: str = "CANDIDATE"
    methodology: str = "UNMEASURED"
    validation_evidence: str = MeasurementState.UNMEASURED.value
    limitations: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "name": self.name,
            "version": self.version,
            "owner": self.owner,
            "state": self.state,
            "methodology": self.methodology,
            "validationEvidence": self.validation_evidence,
            "limitations": list(self.limitations),
            "history": list(self.history),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "approved_is_not_proof_of_edge": True,
            },
        }


class ModelRiskRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelCard] = {}

    def register(self, card: ModelCard) -> ModelCard:
        if card.state not in MODEL_STATES:
            raise ValueError(f"invalid model state: {card.state}")
        self._models[card.model_id] = card
        return card

    def transition(
        self,
        model_id: str,
        *,
        new_state: str,
        actor: str,
        ts: str,
        note: str = "",
        validation_evidence: str | None = None,
    ) -> ModelCard:
        card = self._models[model_id]
        allowed = ALLOWED_MODEL_TRANSITIONS.get(card.state, frozenset())
        if new_state not in allowed:
            raise ValueError(f"illegal model transition {card.state} -> {new_state}")
        if new_state in {"APPROVED", "PRODUCTION"} and (
            (validation_evidence or card.validation_evidence)
            in {
                MeasurementState.UNMEASURED.value,
                MeasurementState.EMPTY.value,
                MeasurementState.NOT_IMPLEMENTED.value,
            }
        ):
            raise ValueError("cannot approve/promote without validation evidence")
        card.history.append(
            {"from": card.state, "to": new_state, "actor": actor, "ts": ts, "note": note}
        )
        card.state = new_state
        if validation_evidence is not None:
            card.validation_evidence = validation_evidence
        return card

    def get(self, model_id: str) -> ModelCard | None:
        return self._models.get(model_id)

    def production_models(self) -> list[dict[str, Any]]:
        return [m.public_dict() for m in self._models.values() if m.state == "PRODUCTION"]

    def public_dict(self) -> dict[str, Any]:
        return {
            "models": [m.public_dict() for m in self._models.values()],
            "count": len(self._models),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def model_card_from_mapping(raw: Mapping[str, Any]) -> ModelCard:
    return ModelCard(
        model_id=str(raw.get("model_id") or raw.get("modelId") or ""),
        name=str(raw.get("name") or ""),
        version=str(raw.get("version") or "0"),
        owner=str(raw.get("owner") or ""),
        state=str(raw.get("state") or "CANDIDATE"),
        methodology=str(raw.get("methodology") or "UNMEASURED"),
        validation_evidence=str(
            raw.get("validation_evidence") or raw.get("validationEvidence") or MeasurementState.UNMEASURED.value
        ),
        limitations=list(raw.get("limitations") or []),
    )
