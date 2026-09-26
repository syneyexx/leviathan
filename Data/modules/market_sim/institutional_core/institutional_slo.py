"""W62 — Institutional SLOs and honest health rollup (no fake green)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH, rollup_states, is_green_claim


@dataclass(frozen=True)
class SloDefinition:
    slo_id: str
    name: str
    objective: str
    target: float
    unit: str
    window: str = "30d"

    def public_dict(self) -> dict[str, Any]:
        return {
            "sloId": self.slo_id,
            "name": self.name,
            "objective": self.objective,
            "target": self.target,
            "unit": self.unit,
            "window": self.window,
        }


DEFAULT_SLOS: tuple[SloDefinition, ...] = (
    SloDefinition("slo_job_success", "job_success_ratio", "JobRuntime success ratio", 0.99, "ratio"),
    SloDefinition("slo_data_fresh", "dataset_freshness_hours", "Max dataset lag hours", 24.0, "hours"),
    SloDefinition("slo_recon_open", "open_breaks", "Open reconciliation breaks", 0.0, "count"),
    SloDefinition("slo_live_blocked", "live_trading_blocked", "Live trading remains blocked", 1.0, "bool"),
)


@dataclass
class SloObservation:
    slo_id: str
    value: float | None
    state: str
    meets_target: bool | None = None
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "sloId": self.slo_id,
            "value": self.value,
            "state": self.state,
            "meetsTarget": self.meets_target,
            "notes": list(self.notes),
        }


@dataclass
class HealthRollup:
    overall: str
    observations: list[SloObservation]
    components: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "observations": [o.public_dict() for o in self.observations],
            "components": dict(self.components),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "unmeasured_is_not_healthy": True,
                "no_fake_green": not is_green_claim(self.overall),
            },
        }


def evaluate_slo(
    definition: SloDefinition,
    *,
    value: float | None,
    state: str = MeasurementState.OBSERVED.value,
    higher_is_better: bool | None = None,
) -> SloObservation:
    if value is None or state in {
        MeasurementState.UNMEASURED.value,
        MeasurementState.UNAVAILABLE.value,
        MeasurementState.NOT_IMPLEMENTED.value,
        MeasurementState.EMPTY.value,
    }:
        return SloObservation(
            slo_id=definition.slo_id,
            value=value,
            state=state if value is None else state,
            meets_target=None,
            notes=["cannot_claim_meet_target_without_measurement"],
        )

    hib = higher_is_better
    if hib is None:
        hib = definition.unit in {"ratio", "bool"} and "fresh" not in definition.slo_id
        if definition.slo_id in {"slo_data_fresh", "slo_recon_open"}:
            hib = False
        if definition.slo_id == "slo_live_blocked":
            hib = True

    meets = value >= definition.target if hib else value <= definition.target
    return SloObservation(
        slo_id=definition.slo_id,
        value=value,
        state=state,
        meets_target=meets,
        notes=[] if meets else ["target_missed"],
    )


def health_rollup(
    observations: Sequence[SloObservation],
    *,
    components: Mapping[str, str] | None = None,
) -> HealthRollup:
    states: list[str] = []
    for obs in observations:
        if obs.state in {
            MeasurementState.UNMEASURED.value,
            MeasurementState.UNAVAILABLE.value,
            MeasurementState.NOT_IMPLEMENTED.value,
            MeasurementState.EMPTY.value,
        }:
            states.append(MeasurementState.UNMEASURED.value)
        elif obs.meets_target is False:
            states.append(MeasurementState.FAIL.value)
        elif obs.meets_target is True:
            states.append(MeasurementState.PASS.value)
        else:
            states.append(obs.state)

    for st in (components or {}).values():
        states.append(st)

    overall = rollup_states(states).value
    # Never promote UNMEASURED absence into PASS/OK.
    if not observations and not components:
        overall = MeasurementState.EMPTY.value
    return HealthRollup(
        overall=overall,
        observations=list(observations),
        components=dict(components or {}),
    )


def institutional_slo_snapshot(
    measured: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    definitions: Sequence[SloDefinition] = DEFAULT_SLOS,
    live_trading_blocked: bool = True,
) -> dict[str, Any]:
    measured = measured or {}
    observations: list[SloObservation] = []
    for slo in definitions:
        raw = measured.get(slo.slo_id) or {}
        if slo.slo_id == "slo_live_blocked" and "value" not in raw:
            observations.append(
                evaluate_slo(
                    slo,
                    value=1.0 if live_trading_blocked else 0.0,
                    state=MeasurementState.OBSERVED.value,
                )
            )
            continue
        observations.append(
            evaluate_slo(
                slo,
                value=(None if raw.get("value") is None else float(raw["value"])),
                state=str(raw.get("state") or MeasurementState.UNMEASURED.value),
            )
        )
    rollup = health_rollup(observations)
    return {
        "slos": [s.public_dict() for s in definitions],
        "health": rollup.public_dict(),
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "extends_observability_snapshot": True,
        },
    }
