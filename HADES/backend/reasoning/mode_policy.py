"""Canonical product reasoning modes and compatibility mapping.

Product labels: Normal, Medium, High, Adaptive.
Internal execution profiles (agents, tasks, PROFILE_CONFIGS): fast, standard,
high, maximum. Those internal keys stay because agent/task profiles still need
the extra Maximum budget knob.

Compatibility (documented, not silent):
- stored/API ``fast``      → selected_mode normal  (same budget as Normal)
- stored/API ``standard``  → selected_mode medium  (same budget as Medium)
- stored/API ``maximum``   → selected_mode high, effective_policy maximum
  until the user picks a product mode (preserves former Maximum budget)
- stored/API product ids are kept as-is

Invalid *new* API values are rejected. Corrupt stored values fall back to
Adaptive with an explicit decision_reason — they do not crash Chat.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

POLICY_VERSION = "reasoning-modes-v1"

ProductMode = Literal["normal", "medium", "high", "adaptive"]
InternalPolicy = Literal["fast", "standard", "high", "maximum"]

PRODUCT_MODES: tuple[str, ...] = ("normal", "medium", "high", "adaptive")
INTERNAL_POLICIES: tuple[str, ...] = ("fast", "standard", "high", "maximum")

# Values accepted on settings/chat API (product + legacy). Anything else is invalid.
ACCEPTED_MODE_INPUTS: frozenset[str] = frozenset(
    (*PRODUCT_MODES, "fast", "standard", "maximum")
)

# Settings persistence writes product ids. Legacy aliases canonicalize here.
CANONICAL_STORAGE: dict[str, ProductMode] = {
    "normal": "normal",
    "medium": "medium",
    "high": "high",
    "adaptive": "adaptive",
    "fast": "normal",
    "standard": "medium",
    "maximum": "high",
}

PRODUCT_TO_INTERNAL: dict[str, InternalPolicy] = {
    "normal": "fast",
    "medium": "standard",
    "high": "high",
}

INTERNAL_TO_PRODUCT: dict[str, ProductMode] = {
    "fast": "normal",
    "standard": "medium",
    "high": "high",
    "maximum": "high",
    "normal": "normal",
    "medium": "medium",
    "adaptive": "adaptive",
}

COMPATIBILITY_REASON: dict[str, str] = {
    "fast": "legacy_fast_maps_to_normal",
    "standard": "legacy_standard_maps_to_medium",
    "maximum": "legacy_maximum_maps_to_high_with_maximum_budget",
}


class ModeValidationError(ValueError):
    """Invalid reasoning-mode input that callers must reject (API) or fall back (stored)."""


@dataclass(frozen=True, slots=True)
class ModeResolution:
    selected_mode: ProductMode
    effective_policy: InternalPolicy
    decision_reason: str
    policy_version: str
    requested_raw: str
    compatibility: str | None
    explicit: bool
    valid: bool
    persist_value: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(raw: str | None) -> str:
    return str(raw or "").strip().lower()


def is_accepted_mode_input(raw: str | None) -> bool:
    return _clean(raw) in ACCEPTED_MODE_INPUTS


def canonical_storage_value(raw: str | None) -> ProductMode:
    """Map a valid input onto the product id persisted in settings."""
    key = _clean(raw)
    if key not in CANONICAL_STORAGE:
        raise ModeValidationError(f"Invalid reasoning mode {raw!r}. Expected one of {sorted(ACCEPTED_MODE_INPUTS)}.")
    return CANONICAL_STORAGE[key]


def try_canonicalize_enum(storage_key: str, value: str) -> str | None:
    """Control-plane helper: only equivalent product aliases are rewritten.

    ``maximum`` stays ``maximum`` so the former Maximum budget is not silently
    collapsed to High until the user picks a product mode.
    """
    if storage_key != "reasoning_profile":
        return None
    key = _clean(value)
    if key == "maximum":
        return "maximum"
    if key in CANONICAL_STORAGE:
        return CANONICAL_STORAGE[key]
    return None


def internal_policy_for_product(mode: ProductMode, *, stored_raw: str = "") -> InternalPolicy:
    """Choose the PROFILE_CONFIGS key for a product mode.

    Legacy stored ``maximum`` keeps the Maximum budget so the preference is not
    silently downgraded. Explicit product High uses the High budget.
    """
    raw = _clean(stored_raw)
    if mode == "high" and raw == "maximum":
        return "maximum"
    if mode == "adaptive":
        return "fast"
    return PRODUCT_TO_INTERNAL.get(mode, "standard")


def parse_mode_input(
    raw: str | None,
    *,
    source: str = "api",
    allow_unknown: bool = False,
) -> ModeResolution:
    """Normalize a user/API/stored reasoning mode.

    ``source=api`` with ``allow_unknown=False`` raises on garbage.
    ``source=stored`` never raises: unknown values fall back to Adaptive.
    """
    requested_raw = str(raw or "").strip()
    key = _clean(raw)
    if not key:
        key = "adaptive"
        requested_raw = requested_raw or "adaptive"

    if key not in ACCEPTED_MODE_INPUTS:
        if source == "api" and not allow_unknown:
            raise ModeValidationError(
                f"Invalid reasoning mode {requested_raw!r}. "
                f"Expected Normal/Medium/High/Adaptive (legacy: fast/standard/maximum)."
            )
        return ModeResolution(
            selected_mode="adaptive",
            effective_policy="fast",
            decision_reason=f"invalid_stored_mode:{key or 'empty'};fallback_adaptive",
            policy_version=POLICY_VERSION,
            requested_raw=requested_raw or key,
            compatibility="invalid_fallback_adaptive",
            explicit=False,
            valid=False,
            persist_value="adaptive",
        )

    selected = CANONICAL_STORAGE[key]
    compatibility = COMPATIBILITY_REASON.get(key)
    explicit = selected != "adaptive"
    effective = internal_policy_for_product(selected, stored_raw=key)
    persist_value = "maximum" if key == "maximum" else selected
    if selected == "adaptive":
        reason = "adaptive_will_choose_from_task_structure"
    elif compatibility:
        reason = f"explicit_{selected};{compatibility}"
    else:
        reason = f"explicit_{selected}"
    return ModeResolution(
        selected_mode=selected,
        effective_policy=effective,
        decision_reason=reason,
        policy_version=POLICY_VERSION,
        requested_raw=requested_raw or key,
        compatibility=compatibility,
        explicit=explicit,
        valid=True,
        persist_value=persist_value,
    )


def profile_config_key(name: str | None) -> str:
    """Map a product or legacy name onto a PROFILE_CONFIGS key."""
    key = _clean(name)
    if key in PRODUCT_TO_INTERNAL:
        return PRODUCT_TO_INTERNAL[key]
    if key in INTERNAL_POLICIES or key == "adaptive":
        return "standard" if key == "adaptive" else key
    mapped = CANONICAL_STORAGE.get(key)
    if mapped and mapped in PRODUCT_TO_INTERNAL:
        return PRODUCT_TO_INTERNAL[mapped]
    return "standard"


def product_label(mode: str | None) -> str:
    labels = {
        "normal": "Normal",
        "medium": "Medium",
        "high": "High",
        "adaptive": "Adaptive",
        "fast": "Normal",
        "standard": "Medium",
        "maximum": "High",
    }
    return labels.get(_clean(mode), "Adaptive")
