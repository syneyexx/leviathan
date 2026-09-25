"""Science-layer helpers: FDR control and power analysis (G46)."""

from __future__ import annotations

import math
from typing import Any, Sequence


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    q: float = 0.05,
    labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Benjamini–Hochberg FDR procedure.

    Returns which hypotheses are discoveries at FDR level ``q``.
    """
    n = len(p_values)
    if n == 0:
        return {
            "q": q,
            "n": 0,
            "discoveries": [],
            "rejected": [],
            "adjusted_p": [],
            "truth": {"fdr_procedure": "benjamini_hochberg"},
        }
    labeled = []
    for i, p in enumerate(p_values):
        label = labels[i] if labels is not None and i < len(labels) else f"h{i}"
        labeled.append((float(p), i, str(label)))
    ordered = sorted(labeled, key=lambda x: x[0])
    # BH critical values and adjusted p-values (step-up)
    adjusted: list[float] = [0.0] * n
    prev = 1.0
    for rank_desc, (p, orig_i, _label) in enumerate(reversed(ordered), start=0):
        # rank from n down to 1
        rank = n - rank_desc
        adj = min(prev, p * n / rank)
        prev = adj
        adjusted[orig_i] = min(1.0, adj)

    threshold = None
    discoveries: list[dict[str, Any]] = []
    rejected: list[bool] = [False] * n
    for rank, (p, orig_i, label) in enumerate(ordered, start=1):
        crit = q * rank / n
        if p <= crit:
            threshold = p
    if threshold is not None:
        for p, orig_i, label in ordered:
            if p <= threshold:
                rejected[orig_i] = True
                discoveries.append(
                    {
                        "index": orig_i,
                        "label": label,
                        "p_value": p,
                        "adjusted_p": adjusted[orig_i],
                    }
                )
    return {
        "q": q,
        "n": n,
        "discoveries": discoveries,
        "n_discoveries": len(discoveries),
        "rejected": rejected,
        "adjusted_p": adjusted,
        "truth": {
            "fdr_procedure": "benjamini_hochberg",
            "controls_expected_false_discovery_rate": True,
            "not_familywise_error": True,
        },
    }


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_ppf(p: float) -> float:
    """Approximate inverse CDF of standard normal (Acklam/Beasley-Springer style)."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    # Coefficients for rational approximation
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def power_analysis(
    *,
    effect_size: float,
    n: int,
    alpha: float = 0.05,
    alternative: str = "two_sided",
) -> dict[str, Any]:
    """Approximate one-sample z-test power for a standardized effect size.

    ``effect_size`` is Cohen's d (mean / sigma). Honest about approximation.
    """
    n_obs = max(1, int(n))
    alpha = float(alpha)
    d = float(effect_size)
    se = 1.0 / math.sqrt(n_obs)
    if alternative == "greater":
        z_crit = _normal_ppf(1.0 - alpha)
        power = 1.0 - _normal_cdf(z_crit - d / se)
    elif alternative == "less":
        z_crit = _normal_ppf(alpha)
        power = _normal_cdf(z_crit - d / se)
    else:
        z_crit = _normal_ppf(1.0 - alpha / 2.0)
        power = (1.0 - _normal_cdf(z_crit - d / se)) + _normal_cdf(-z_crit - d / se)
    power = max(0.0, min(1.0, power))
    return {
        "effect_size": d,
        "n": n_obs,
        "alpha": alpha,
        "alternative": alternative,
        "power": power,
        "underpowered": power < 0.8,
        "truth": {
            "approximation": "one_sample_z",
            "not_exact_t": True,
            "use_for_planning_only": True,
        },
    }


def calibrate_trial_family(
    p_values: Sequence[float],
    *,
    q: float = 0.05,
    labels: Sequence[str] | None = None,
    effect_sizes: Sequence[float] | None = None,
    sample_sizes: Sequence[int] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Combine FDR discoveries with per-hypothesis power estimates (G46)."""
    fdr = benjamini_hochberg(p_values, q=q, labels=labels)
    powers: list[dict[str, Any]] = []
    if effect_sizes is not None and sample_sizes is not None:
        for i, (es, n) in enumerate(zip(effect_sizes, sample_sizes)):
            powers.append(power_analysis(effect_size=float(es), n=int(n), alpha=alpha))
    return {
        "fdr": fdr,
        "power": powers,
        "n_hypotheses": len(p_values),
        "truth": {
            "false_discovery_calibration": True,
            "power_is_approximate": True,
        },
    }
