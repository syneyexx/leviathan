"""Trading statistical honesty — bootstrap CIs, PBO, Deflated Sharpe, FDR (W13D)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class BootstrapCI:
    mean: float
    ci_low: float
    ci_high: float
    n: int
    samples: int
    method: str = "block_bootstrap"

    def public_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n": self.n,
            "samples": self.samples,
            "method": self.method,
        }


def block_bootstrap_mean(
    returns: Sequence[float],
    *,
    block_size: int = 5,
    samples: int = 500,
    alpha: float = 0.05,
    seed: int = 42,
) -> BootstrapCI:
    """Block bootstrap of mean return (stationary blocks approximated by fixed length)."""
    n = len(returns)
    if n == 0:
        return BootstrapCI(0.0, 0.0, 0.0, 0, 0)
    mean = sum(returns) / n
    if n == 1:
        return BootstrapCI(mean, mean, mean, 1, samples)
    bs = max(1, min(int(block_size), n))
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(max(1, samples)):
        drawn: list[float] = []
        while len(drawn) < n:
            start = rng.randrange(0, n)
            for j in range(bs):
                drawn.append(returns[(start + j) % n])
                if len(drawn) >= n:
                    break
        boots.append(sum(drawn[:n]) / n)
    boots.sort()
    lo = boots[int(math.floor((alpha / 2) * len(boots)))]
    hi = boots[min(len(boots) - 1, int(math.ceil((1 - alpha / 2) * len(boots))) - 1)]
    return BootstrapCI(mean=mean, ci_low=lo, ci_high=hi, n=n, samples=samples)


def sharpe_ratio(returns: Sequence[float], *, risk_free: float = 0.0) -> float | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n - risk_free
    var = sum((r - mean - risk_free) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_trials: int,
    n_observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> dict[str, Any]:
    """Simplified Deflated Sharpe Ratio vs expected max Sharpe under n_trials.

    Trial Ledger count MUST feed n_trials (selection-bias adjustment).
    """
    if n_trials < 1 or n_observations < 2:
        return {
            "dsr": None,
            "measurement": "UNMEASURED",
            "reason": "insufficient_sample_or_trials",
            "n_trials": n_trials,
            "n_observations": n_observations,
        }
    # Expected max Sharpe under independent nulls (approx).
    # E[max Z] ≈ (1-γ)Φ^{-1}(1-1/N) + γΦ^{-1}(1-1/(N*e)) with γ≈0.5772
    # Use a simple normal-order-statistic approximation.
    gamma = 0.5772156649
    if n_trials == 1:
        e_max = 0.0
    else:
        # Inverse CDF approx via Beasley-Springer/Moro not available — use erfinv-like.
        def _norm_ppf(p: float) -> float:
            # Acklam approximation (compact)
            p = min(max(p, 1e-12), 1 - 1e-12)
            a = [ -3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
                  1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00 ]
            b = [ -5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
                  6.680131188771972e+01, -1.328068155288572e+01 ]
            c = [ -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
                  -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00 ]
            d = [ 7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
                  3.754408661907416e+00 ]
            plow = 0.02425
            if p < plow:
                q = math.sqrt(-2 * math.log(p))
                return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
            if p > 1 - plow:
                q = math.sqrt(-2 * math.log(1 - p))
                return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
            q = p - 0.5
            r = q * q
            return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

        e_max = (1 - gamma) * _norm_ppf(1 - 1 / n_trials) + gamma * _norm_ppf(
            1 - 1 / (n_trials * math.e)
        )
    # Standard error of Sharpe under non-normality (Lo 2002 / Bailey-Lopez de Prado).
    se = math.sqrt(
        (1 + 0.5 * observed_sharpe**2 - skew * observed_sharpe + ((kurtosis - 3) / 4) * observed_sharpe**2)
        / max(1, n_observations - 1)
    )
    if se <= 0:
        return {
            "dsr": None,
            "measurement": "UNMEASURED",
            "reason": "nonpositive_se",
            "n_trials": n_trials,
        }
    dsr = (observed_sharpe - e_max) / se
    return {
        "dsr": dsr,
        "observed_sharpe": observed_sharpe,
        "expected_max_sharpe_null": e_max,
        "se": se,
        "n_trials": n_trials,
        "n_observations": n_observations,
        "measurement": "MEASURED",
        "truth": {
            "trial_ledger_count_used": True,
            "point_estimate_alone_is_not_acceptance": True,
        },
    }


def probability_of_backtest_overfitting(
    trial_sharpes: Sequence[float],
    *,
    seed: int = 42,
    samples: int = 200,
) -> dict[str, Any]:
    """Approximate PBO via random split of trials into IS/OOS rank performance.

    High PBO ⇒ selection pipeline suspect. Requires Trial Ledger of tried sharpes.
    """
    vals = [float(x) for x in trial_sharpes if x is not None]
    n = len(vals)
    if n < 4:
        return {
            "pbo": None,
            "measurement": "UNMEASURED",
            "reason": "need>=4_trials",
            "n_trials": n,
        }
    rng = random.Random(seed)
    half = n // 2
    overfit = 0
    for _ in range(max(1, samples)):
        idx = list(range(n))
        rng.shuffle(idx)
        is_set = idx[:half]
        oos_set = idx[half : half * 2]
        # Best IS trial
        best_is = max(is_set, key=lambda i: vals[i])
        # Rank of that trial in OOS (among oos set + the best_is if we evaluate its OOS proxy:
        # use complementary half performance as OOS for each).
        # Simpler: compare whether best_is underperforms median of oos.
        oos_vals = [vals[i] for i in oos_set]
        if vals[best_is] < (sum(oos_vals) / len(oos_vals)):
            overfit += 1
    pbo = overfit / samples
    return {
        "pbo": pbo,
        "n_trials": n,
        "samples": samples,
        "measurement": "MEASURED",
        "truth": {
            "losing_trials_must_remain_in_ledger": True,
            "high_pbo_means_selection_suspect": pbo >= 0.5,
        },
    }


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    q: float = 0.05,
) -> dict[str, Any]:
    """Benjamini–Hochberg FDR control — returns which indices reject null."""
    indexed = sorted([(float(p), i) for i, p in enumerate(p_values)], key=lambda t: t[0])
    m = len(indexed)
    if m == 0:
        return {"rejected": [], "measurement": "UNMEASURED", "q": q}
    rejected: list[int] = []
    max_k = -1
    for k, (p, _) in enumerate(indexed, start=1):
        if p <= (k / m) * q:
            max_k = k
    if max_k >= 0:
        rejected = [indexed[i][1] for i in range(max_k)]
    return {
        "rejected": rejected,
        "m": m,
        "q": q,
        "measurement": "MEASURED",
        "truth": {"multiple_testing_correction_applied": True},
    }


def minimum_useful_sample(
    *,
    effect_size: float,
    power: float = 0.8,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Rough two-sided z-test sample size for detecting effect_size on mean returns."""
    if effect_size <= 0:
        return {"n": None, "measurement": "UNMEASURED", "reason": "nonpositive_effect"}
    # z_{1-α/2} + z_{power}
    z_alpha = 1.96
    z_power = 0.8416 if power >= 0.8 else 0.5244
    n = math.ceil(((z_alpha + z_power) / effect_size) ** 2)
    return {
        "n": n,
        "effect_size": effect_size,
        "power": power,
        "alpha": alpha,
        "measurement": "ASSUMED",
        "truth": {"power_analysis_is_not_proof_of_edge": True},
    }


def purge_embargo_indices(
    n: int,
    *,
    train_end: int,
    test_start: int,
    purge_bars: int,
    embargo_bars: int,
) -> dict[str, Any]:
    """Return train/test index ranges with purge+embargo gaps (CPCV/WFA building block)."""
    train_hi = max(0, train_end - max(0, purge_bars))
    test_lo = min(n, test_start + max(0, embargo_bars))
    overlap = train_hi > test_start or test_lo < train_end
    return {
        "train": (0, train_hi),
        "test": (test_lo, n),
        "purge_bars": purge_bars,
        "embargo_bars": embargo_bars,
        "causal_gap_ok": train_hi <= test_lo,
        "overlap_detected": overlap and train_hi > test_lo,
        "measurement": "MEASURED",
    }


def monte_carlo_mean_resample(
    returns: Sequence[float],
    *,
    samples: int = 500,
    alpha: float = 0.05,
    seed: int = 42,
) -> BootstrapCI:
    """IID Monte Carlo resampling of mean return (complements block bootstrap)."""
    n = len(returns)
    if n == 0:
        return BootstrapCI(0.0, 0.0, 0.0, 0, 0, method="monte_carlo_iid")
    mean = sum(returns) / n
    if n == 1:
        return BootstrapCI(mean, mean, mean, 1, samples, method="monte_carlo_iid")
    rng = random.Random(seed)
    boots = [sum(rng.choices(list(returns), k=n)) / n for _ in range(max(1, samples))]
    boots.sort()
    lo = boots[int(math.floor((alpha / 2) * len(boots)))]
    hi = boots[min(len(boots) - 1, int(math.ceil((1 - alpha / 2) * len(boots))) - 1)]
    return BootstrapCI(mean=mean, ci_low=lo, ci_high=hi, n=n, samples=samples, method="monte_carlo_iid")


def combinatorial_purged_cv_paths(
    n: int,
    *,
    n_groups: int = 5,
    n_test_groups: int = 1,
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> dict[str, Any]:
    """Combinatorial purged CV path generator (index ranges only — no shuffle of time).

    Full CPCV scoring stays with experiment harness; this returns causal train/test
    index sets with purge+embargo gaps. Status is MEASURED for geometry, not for edge.
    """
    if n < 2 or n_groups < 2 or n_test_groups < 1 or n_test_groups >= n_groups:
        return {
            "paths": [],
            "measurement": "UNMEASURED",
            "reason": "insufficient_groups_or_sample",
            "n": n,
            "n_groups": n_groups,
        }
    # Equal-ish contiguous groups along time.
    boundaries = [int(round(i * n / n_groups)) for i in range(n_groups + 1)]
    groups = [(boundaries[i], boundaries[i + 1]) for i in range(n_groups) if boundaries[i + 1] > boundaries[i]]
    if len(groups) < 2:
        return {"paths": [], "measurement": "UNMEASURED", "reason": "degenerate_groups", "n": n}

    from itertools import combinations

    paths: list[dict[str, Any]] = []
    for test_idxs in combinations(range(len(groups)), n_test_groups):
        test_set = set(test_idxs)
        train_ranges: list[tuple[int, int]] = []
        test_ranges: list[tuple[int, int]] = []
        for gi, (lo, hi) in enumerate(groups):
            if gi in test_set:
                # Embargo expands test away from train edges.
                t_lo = min(n, lo + max(0, embargo_bars)) if embargo_bars else lo
                test_ranges.append((t_lo, hi))
            else:
                # Purge shrinks train near test neighbors.
                t_hi = hi
                t_lo = lo
                for tj in test_idxs:
                    tlo, thi = groups[tj]
                    if hi <= tlo:
                        t_hi = min(t_hi, max(lo, tlo - purge_bars))
                    if lo >= thi:
                        t_lo = max(t_lo, min(hi, thi + purge_bars))
                if t_hi > t_lo:
                    train_ranges.append((t_lo, t_hi))
        if not train_ranges or not test_ranges:
            continue
        paths.append(
            {
                "train_ranges": train_ranges,
                "test_ranges": test_ranges,
                "test_groups": list(test_idxs),
                "purge_bars": purge_bars,
                "embargo_bars": embargo_bars,
            }
        )
    return {
        "paths": paths,
        "n": n,
        "n_groups": len(groups),
        "n_test_groups": n_test_groups,
        "n_paths": len(paths),
        "measurement": "MEASURED" if paths else "UNMEASURED",
        "truth": {
            "no_time_shuffle": True,
            "cpcv_geometry_only": True,
            "selection_bias_still_requires_trial_ledger": True,
        },
    }
