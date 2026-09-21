"""Evidence-based mid-run steering. Reuses the existing understand→execute loop.

Does not introduce a second task state machine. Explicit product modes are never
silently replaced by Adaptive. A failed tool call is not an automatic model upgrade.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .understanding import maybe_escalate_profile


SteeringSignal = Literal[
    "invalid_tool_argument",
    "provider_transient",
    "missing_source",
    "acceptance_unmet",
    "contradictory_result",
    "context_mismatch",
    "repeated_no_new_info",
    "capability_missing",
    "",
]

SteeringAction = Literal[
    "repair_arguments",
    "add_context",
    "choose_alternative_tool",
    "replan_one_step",
    "adjust_budget",
    "report_block",
    "retry_same",
    "stop",
]


@dataclass(slots=True)
class AttemptRecord:
    kind: str
    fingerprint: str
    outcome: str
    signal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SteeringDecision:
    action: SteeringAction
    signal: str
    reason: str
    next_policy: str | None = None
    terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def action_fingerprint(plugin_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    blob = json.dumps(
        {"plugin_id": plugin_id, "tool_name": tool_name, "arguments": arguments or {}},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def classify_tool_signal(observation: dict[str, Any] | None) -> str:
    if not isinstance(observation, dict):
        return ""
    status = str(observation.get("status") or "").lower()
    error = str(observation.get("error") or "").lower()
    if status in {"completed", "succeeded", "success", "ok"}:
        return ""
    if "schema" in error or "argument" in error or "validation" in error or status == "rejected":
        if "niet in de actuele" in error or "not in" in error or "unknown tool" in error:
            return "capability_missing"
        return "invalid_tool_argument"
    if "timeout" in error or "temporar" in error or "unavailable" in error or "429" in error:
        return "provider_transient"
    if "not found" in error or "ontbreekt" in error or "missing" in error:
        return "missing_source"
    if status in {"blocked"}:
        return "capability_missing"
    return "acceptance_unmet" if status in {"failed", "error"} else ""


def next_steering_action(
    signal: str,
    *,
    attempts: list[AttemptRecord] | None = None,
    profile: str,
    selected_mode: str = "adaptive",
    fingerprint: str = "",
    max_identical: int = 1,
) -> SteeringDecision:
    history = list(attempts or [])
    identical = sum(1 for item in history if item.fingerprint == fingerprint and fingerprint)
    if identical >= max_identical and signal not in {"provider_transient"}:
        return SteeringDecision(
            action="stop",
            signal="repeated_no_new_info",
            reason="Identieke mislukte actie niet herhaald zonder gewijzigde voorwaarden.",
            terminal=True,
        )
    if signal == "capability_missing":
        return SteeringDecision(
            action="report_block",
            signal=signal,
            reason="Benodigde capability ontbreekt; geen eindeloze herhaling.",
            terminal=True,
        )
    if signal == "invalid_tool_argument":
        return SteeringDecision(
            action="repair_arguments",
            signal=signal,
            reason="Ongeldig toolargument: herstel argumenten, geen duurder model.",
        )
    if signal == "provider_transient":
        if identical >= 2:
            return SteeringDecision(
                action="report_block",
                signal=signal,
                reason="Tijdelijk providerprobleem na begrensde retries.",
                terminal=True,
            )
        return SteeringDecision(action="retry_same", signal=signal, reason="Tijdelijk providerprobleem: begrensde retry.")
    if signal == "missing_source":
        return SteeringDecision(action="add_context", signal=signal, reason="Ontbrekende bron: gerichte context aanvullen.")
    if signal == "context_mismatch":
        return SteeringDecision(action="add_context", signal=signal, reason="Context past niet: gerichte aanvulling.")
    if signal == "contradictory_result":
        return SteeringDecision(action="replan_one_step", signal=signal, reason="Tegenstrijdig resultaat: één deelstap herplannen.")
    if signal == "acceptance_unmet":
        next_policy = maybe_escalate_profile(
            profile,  # type: ignore[arg-type]
            observed_failure=True,
            evidence_gap=True,
            selected_mode=selected_mode,
            signal=signal,
        )
        return SteeringDecision(
            action="replan_one_step" if selected_mode == "adaptive" else "repair_arguments",
            signal=signal,
            reason="Acceptatiecriterium niet gehaald: gerichte reparatie.",
            next_policy=str(next_policy) if next_policy != profile else None,
        )
    if signal == "repeated_no_new_info":
        return SteeringDecision(
            action="stop",
            signal=signal,
            reason="Geen nieuwe informatie; stop.",
            terminal=True,
        )
    next_policy = maybe_escalate_profile(
        profile,  # type: ignore[arg-type]
        observed_failure=True,
        selected_mode=selected_mode,
        signal=signal or None,
    )
    return SteeringDecision(
        action="replan_one_step",
        signal=signal or "",
        reason="Gerichte bijsturing op observatie.",
        next_policy=str(next_policy) if next_policy != profile else None,
    )


@dataclass
class AttemptLog:
    records: list[AttemptRecord] = field(default_factory=list)

    def remember(self, kind: str, fingerprint: str, outcome: str, signal: str = "") -> None:
        self.records.append(AttemptRecord(kind=kind, fingerprint=fingerprint, outcome=outcome, signal=signal))

    def seen_failure(self, fingerprint: str) -> bool:
        return any(item.fingerprint == fingerprint and item.outcome not in {"completed", "ok", "success"} for item in self.records)

    def to_list(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.records]
