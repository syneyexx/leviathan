"""Null-safe limit helpers: explicit None means Unlimited, never coerced via int()."""

from __future__ import annotations

from typing import Any


def coerce_optional_positive_int(value: Any, *, default: int, minimum: int = 1) -> int | None:
    """Return None for Unlimited, otherwise a positive int.

    Distinguishes:
    - missing / use default when ``value`` is the sentinel ``...`` is not used;
      callers pass ``settings.get(key, default)`` so missing yields ``default``.
    - explicit ``None`` → Unlimited (``None``)
    - concrete int/str → clamped int
    """
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"expected int or null, got {value!r}") from exc
    if parsed < minimum:
        raise ValueError(f"expected >= {minimum}, got {parsed}")
    return parsed


def effective_bound(value: int | None, *, fallback_when_unlimited: int) -> int:
    """Materialize a concrete bound for loop/slice sizes without inventing a fake product ceiling.

    Unlimited uses the caller-provided situational fallback (e.g. wave length),
    not a hardcoded magic product limit.
    """
    if value is None:
        return max(1, int(fallback_when_unlimited))
    return max(1, int(value))


def allows_parallel(model_concurrency: int | None, wave_size: int) -> bool:
    """Whether a work-wave may run gather() instead of sequential execution."""
    if wave_size <= 1:
        return False
    if model_concurrency is None:
        return True
    return int(model_concurrency) > 1
