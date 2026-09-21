"""Bounded retry with exponential backoff, jitter, and Retry-After support."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 8
    base_seconds: float = 1.0
    max_seconds: float = 60.0
    jitter_ratio: float = 0.25


def compute_backoff_seconds(
    attempt: int,
    *,
    policy: RetryPolicy | None = None,
    retry_after: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Compute sleep duration for 0-indexed failed attempt number."""
    policy = policy or RetryPolicy()
    if retry_after is not None and retry_after >= 0:
        base = float(retry_after)
    else:
        base = min(policy.max_seconds, policy.base_seconds * (2 ** max(0, attempt)))
    jitter = base * policy.jitter_ratio
    roller = rng or random.Random()
    return max(0.0, base + roller.uniform(-jitter, jitter))
