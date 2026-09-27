"""Real robustness harness — new perturbation experiments (Wave 8).

ROBUSTNESS must execute new runs. Re-scoring TRAIN/VAL metrics alone is
insufficient and is rejected as a qualification authority path.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import MarketSimError


@dataclass(frozen=True)
class RobustnessPerturbation:
    """One scheduled robustness experiment (immutable config)."""

    perturbation_id: str
    kind: str  # cost | slippage | spread | parameter | time | regime
    label: str
    fee_bps_factor: float = 1.0
    slippage_bps_factor: float = 1.0
    spread_bps_add: float = 0.0
    parameter_jitter: dict[str, float] = field(default_factory=dict)
    start_shift_bars: int = 0
    end_shift_bars: int = 0
    regime_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "perturbation_id": self.perturbation_id,
            "kind": self.kind,
            "label": self.label,
            "fee_bps_factor": self.fee_bps_factor,
            "slippage_bps_factor": self.slippage_bps_factor,
            "spread_bps_add": self.spread_bps_add,
            "parameter_jitter": dict(self.parameter_jitter),
            "start_shift_bars": self.start_shift_bars,
            "end_shift_bars": self.end_shift_bars,
            "regime_label": self.regime_label,
            "metadata": dict(self.metadata),
        }

    def config_hash(self) -> str:
        blob = json.dumps(self.public_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass
class RobustnessRunResult:
    perturbation: RobustnessPerturbation
    run_id: str | None
    metrics: dict[str, Any]
    accepted: bool
    failure_reason: str = ""
    seed: int = 0
    input_hashes: dict[str, str] = field(default_factory=dict)
    status: str = "completed"
    measurement: str = "MEASURED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "perturbation": self.perturbation.public_dict(),
            "perturbation_hash": self.perturbation.config_hash(),
            "run_id": self.run_id,
            "metrics": dict(self.metrics),
            "accepted": self.accepted,
            "failure_reason": self.failure_reason,
            "seed": self.seed,
            "input_hashes": dict(self.input_hashes),
            "status": self.status,
            "measurement": self.measurement,
            "truth": {
                "executed_new_run": self.run_id is not None,
                "not_train_val_rescore": True,
            },
        }


def default_perturbation_matrix(
    *,
    include_parameter: bool = True,
    include_time: bool = True,
    include_regime: bool = False,
    include_execution_stress: bool = True,
) -> list[RobustnessPerturbation]:
    """Canonical default robustness matrix — rule-based, frozen per objective.

    Wave 10 scenario library. Unsupported scenarios are returned with
    measurement NOT_IMPLEMENTED via metadata — never synthetic PASS.
    """
    out = [
        RobustnessPerturbation(
            perturbation_id="fee_x2",
            kind="cost",
            label="fees_x2",
            fee_bps_factor=2.0,
        ),
        RobustnessPerturbation(
            perturbation_id="slippage_x2",
            kind="slippage",
            label="slippage_x2",
            slippage_bps_factor=2.0,
        ),
        RobustnessPerturbation(
            perturbation_id="spread_widen",
            kind="spread",
            label="spread_+5bps",
            spread_bps_add=5.0,
            fee_bps_factor=1.25,
        ),
    ]
    if include_execution_stress:
        out.extend(
            [
                RobustnessPerturbation(
                    perturbation_id="execution_delay",
                    kind="execution",
                    label="execution_delay",
                    start_shift_bars=1,
                    metadata={"scenario": "execution_delay", "support": "MEASURED"},
                ),
                RobustnessPerturbation(
                    perturbation_id="missed_fill_probability",
                    kind="execution",
                    label="missed_fill_probability",
                    metadata={
                        "scenario": "missed_fill_probability",
                        "support": "NOT_IMPLEMENTED",
                        "honesty": "requires_stochastic_fill_model",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="order_rejection",
                    kind="execution",
                    label="order_rejection",
                    metadata={
                        "scenario": "order_rejection",
                        "support": "NOT_IMPLEMENTED",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="participation_reduction",
                    kind="liquidity",
                    label="participation_reduction",
                    metadata={
                        "scenario": "participation_reduction",
                        "max_participation_factor": 0.5,
                        "support": "MEASURED",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="liquidity_collapse",
                    kind="liquidity",
                    label="liquidity_collapse",
                    metadata={
                        "scenario": "liquidity_collapse",
                        "volume_factor": 0.1,
                        "support": "MEASURED",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="feature_noise",
                    kind="data",
                    label="feature_noise",
                    metadata={
                        "scenario": "feature_noise",
                        "support": "NOT_IMPLEMENTED",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="missing_bars",
                    kind="data",
                    label="missing_bars",
                    metadata={
                        "scenario": "missing_bars",
                        "support": "NOT_IMPLEMENTED",
                    },
                ),
                RobustnessPerturbation(
                    perturbation_id="market_gap",
                    kind="data",
                    label="market_gap",
                    metadata={"scenario": "market_gap", "support": "MEASURED"},
                ),
                RobustnessPerturbation(
                    perturbation_id="feed_staleness",
                    kind="data",
                    label="feed_staleness",
                    metadata={
                        "scenario": "feed_staleness",
                        "support": "NOT_IMPLEMENTED",
                    },
                ),
            ]
        )
    if include_parameter:
        out.append(
            RobustnessPerturbation(
                perturbation_id="parameter_jitter",
                kind="parameter",
                label="local_parameter_perturbation",
                parameter_jitter={"_relative": 0.05},
            )
        )
    if include_time:
        out.append(
            RobustnessPerturbation(
                perturbation_id="start_date_shift",
                kind="time",
                label="start_date_sensitivity",
                start_shift_bars=3,
            )
        )
        out.append(
            RobustnessPerturbation(
                perturbation_id="end_date_shift",
                kind="time",
                label="end_date_sensitivity",
                end_shift_bars=-3,
            )
        )
    if include_regime:
        out.append(
            RobustnessPerturbation(
                perturbation_id="regime_shift",
                kind="regime",
                label="high_vol_slice",
                regime_label="high_vol",
            )
        )
    return out


def institutional_scenario_ids() -> tuple[str, ...]:
    """Wave 10 required scenario library identifiers."""
    return (
        "fee_x2",
        "slippage_x2",
        "spread_widen",
        "execution_delay",
        "missed_fill_probability",
        "order_rejection",
        "participation_reduction",
        "liquidity_collapse",
        "parameter_jitter",
        "start_date_shift",
        "end_date_shift",
        "feature_noise",
        "missing_bars",
        "market_gap",
        "feed_staleness",
        "regime_shift",
    )

def apply_parameter_jitter(
    parameters: dict[str, Any],
    jitter: dict[str, float],
    *,
    seed: int,
) -> dict[str, Any]:
    """Deterministic local parameter perturbation around candidate params."""
    import random

    rng = random.Random(seed)
    out = copy.deepcopy(parameters)
    relative = float(jitter.get("_relative") or 0.0)
    for key, value in list(out.items()):
        if key.startswith("_"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            factor = 1.0 + relative * (rng.random() * 2.0 - 1.0)
            if key in jitter and key != "_relative":
                factor = 1.0 + float(jitter[key]) * (rng.random() * 2.0 - 1.0)
            new_val = float(value) * factor
            out[key] = int(round(new_val)) if isinstance(value, int) else new_val
    return out


def aggregate_robustness_verdict(
    results: list[RobustnessRunResult],
    *,
    min_pass_ratio: float = 0.67,
    require_cost_shock: bool = True,
    require_new_runs: bool = True,
) -> dict[str, Any]:
    """Rule-based aggregate — criteria frozen before evaluation."""
    if not results:
        return {
            "accepted": False,
            "reason": "no_robustness_runs",
            "measurement": "UNMEASURED",
            "pass_ratio": 0.0,
            "results": [],
        }
    if require_new_runs and any(r.run_id is None and r.status == "completed" for r in results):
        return {
            "accepted": False,
            "reason": "robustness_missing_executed_runs",
            "measurement": "INVALID",
            "pass_ratio": 0.0,
            "results": [r.public_dict() for r in results],
        }
    # Missing data must block.
    if any(r.measurement in {"UNMEASURED", "INVALID"} for r in results):
        return {
            "accepted": False,
            "reason": "robustness_missing_data_blocks",
            "measurement": "UNMEASURED",
            "pass_ratio": 0.0,
            "results": [r.public_dict() for r in results],
        }
    if require_cost_shock and not any(r.perturbation.kind == "cost" for r in results):
        return {
            "accepted": False,
            "reason": "cost_shock_required",
            "measurement": "INVALID",
            "pass_ratio": 0.0,
            "results": [r.public_dict() for r in results],
        }
    passed = sum(1 for r in results if r.accepted)
    ratio = passed / max(1, len(results))
    accepted = ratio + 1e-12 >= float(min_pass_ratio)
    return {
        "accepted": accepted,
        "reason": "pass_ratio_met" if accepted else "pass_ratio_below_threshold",
        "measurement": "MEASURED",
        "pass_ratio": ratio,
        "min_pass_ratio": min_pass_ratio,
        "n_results": len(results),
        "n_passed": passed,
        "results": [r.public_dict() for r in results],
        "truth": {
            "criteria_frozen_before_evaluation": True,
            "executed_new_runs": True,
        },
    }


def run_robustness_matrix(
    *,
    execute_episode: Callable[[RobustnessPerturbation, int], dict[str, Any]],
    evaluate_acceptance: Callable[[dict[str, Any]], dict[str, Any]],
    perturbations: list[RobustnessPerturbation] | None = None,
    base_seed: int = 0,
    min_pass_ratio: float = 0.67,
) -> dict[str, Any]:
    """Execute each perturbation as a new episode and aggregate.

    ``execute_episode(perturbation, seed) -> {run_id, metrics, input_hashes?, status?}``
    """
    matrix = list(perturbations or default_perturbation_matrix())
    if not matrix:
        raise MarketSimError("ROBUSTNESS_MATRIX_EMPTY", "no perturbations configured", http_status=409)
    results: list[RobustnessRunResult] = []
    for i, pert in enumerate(matrix):
        seed = int(base_seed) + 70_000 + i
        try:
            episode = execute_episode(pert, seed)
            metrics = dict(episode.get("metrics") or {})
            if not metrics:
                results.append(
                    RobustnessRunResult(
                        perturbation=pert,
                        run_id=episode.get("run_id"),
                        metrics={},
                        accepted=False,
                        failure_reason="missing_metrics",
                        seed=seed,
                        input_hashes=dict(episode.get("input_hashes") or {}),
                        status=str(episode.get("status") or "completed"),
                        measurement="UNMEASURED",
                    )
                )
                continue
            verdict = evaluate_acceptance(metrics)
            accepted = bool(verdict.get("passed"))
            results.append(
                RobustnessRunResult(
                    perturbation=pert,
                    run_id=episode.get("run_id"),
                    metrics=metrics,
                    accepted=accepted,
                    failure_reason="" if accepted else str(verdict.get("reason") or "acceptance_failed"),
                    seed=seed,
                    input_hashes=dict(episode.get("input_hashes") or {}),
                    status=str(episode.get("status") or "completed"),
                    measurement="MEASURED",
                )
            )
        except MarketSimError as exc:
            results.append(
                RobustnessRunResult(
                    perturbation=pert,
                    run_id=None,
                    metrics={},
                    accepted=False,
                    failure_reason=f"{exc.code}:{exc.message}",
                    seed=seed,
                    status="failed",
                    measurement="INVALID" if exc.code.endswith("MISSING") else "UNMEASURED",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                RobustnessRunResult(
                    perturbation=pert,
                    run_id=None,
                    metrics={},
                    accepted=False,
                    failure_reason=str(exc),
                    seed=seed,
                    status="failed",
                    measurement="INVALID",
                )
            )
    return aggregate_robustness_verdict(results, min_pass_ratio=min_pass_ratio)
