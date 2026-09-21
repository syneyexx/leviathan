"""Conservative feature modes for cognitive adaptive behavior.

OFF     — no behavioral influence; may still expose read-only diagnostics.
SHADOW  — compute/log recommendations; do not change outcomes.
ACTIVE  — may influence decisions within deterministic policy bounds.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class CognitiveMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"


DEFAULT_MODE = CognitiveMode.OFF

# Per-pillar defaults remain conservative even when the runtime is ACTIVE.
PILLAR_DEFAULT_MODES: dict[str, CognitiveMode] = {
    "self_model": CognitiveMode.ACTIVE,  # read-only evidence snapshot; safe
    "epistemic": CognitiveMode.SHADOW,
    "homeostasis": CognitiveMode.SHADOW,
    "perception": CognitiveMode.SHADOW,
    "immune": CognitiveMode.ACTIVE,  # fail-closed quarantine is safety-critical
    "ontology": CognitiveMode.SHADOW,
    "mental_models": CognitiveMode.SHADOW,
    "credit": CognitiveMode.SHADOW,
    "scientific_method": CognitiveMode.OFF,
    "self_repair": CognitiveMode.OFF,
}


def parse_mode(value: Any, *, default: CognitiveMode = DEFAULT_MODE) -> CognitiveMode:
    if isinstance(value, CognitiveMode):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    # Accept "CognitiveMode.ACTIVE" style from accidental str(enum)
    if raw.startswith("cognitivemode."):
        raw = raw.split(".", 1)[-1]
    try:
        return CognitiveMode(raw)
    except ValueError:
        return default


def mode_allows_influence(mode: CognitiveMode) -> bool:
    return mode is CognitiveMode.ACTIVE


def mode_allows_observe(mode: CognitiveMode) -> bool:
    return mode in {CognitiveMode.SHADOW, CognitiveMode.ACTIVE}
