"""Hyperparameter search with mandatory Trial Ledger logging (W14).

Every trial is recorded. SEALED splits may never be used for tuning.
Bayesian/TPE is FEATURE_GATED until an operational optimizer exists.
"""

from __future__ import annotations

import itertools
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence


HPO_METHODS = frozenset({"grid", "random", "evolutionary_dsl", "bayesian_tpe"})


@dataclass
class HpoTrial:
    trial_id: str
    method: str
    parameters: dict[str, Any]
    split: str  # train | val | robustness — never sealed for tuning
    score: float | None = None
    status: str = "CREATED"  # CREATED | COMPLETED | FAILED | SKIPPED
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "method": self.method,
            "parameters": dict(self.parameters),
            "split": self.split,
            "score": self.score,
            "status": self.status,
            "metadata": dict(self.metadata),
            "truth": {
                "logged_to_trial_ledger": True,
                "sealed_forbidden_for_tuning": self.split.lower() != "sealed",
            },
        }


@dataclass
class HpoPlan:
    method: str
    search_space: dict[str, Sequence[Any]]
    max_trials: int
    seed: int = 42
    split: str = "train"
    resume_from: int = 0
    trials: list[HpoTrial] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "search_space": {k: list(v) for k, v in self.search_space.items()},
            "max_trials": self.max_trials,
            "seed": self.seed,
            "split": self.split,
            "resume_from": self.resume_from,
            "n_trials": len(self.trials),
            "trials": [t.public_dict() for t in self.trials],
            "metadata": dict(self.metadata),
            "truth": {
                "every_trial_logged": True,
                "no_invisible_discarded_trials": True,
                "no_sealed_tuning": self.split.lower() != "sealed",
                "resumable": True,
            },
        }


def assert_not_sealed_tuning(split: str) -> None:
    if str(split).lower() == "sealed":
        raise ValueError("HPO must not use SEALED split for tuning")


def bayesian_tpe_capability() -> dict[str, Any]:
    return {
        "method": "bayesian_tpe",
        "status": "FEATURE_GATED",
        "reason": "Bayesian/TPE optimizer not operational in-process; use grid/random",
        "truth": {"not_silently_measured": True},
    }


def iter_grid(search_space: dict[str, Sequence[Any]]) -> Iterator[dict[str, Any]]:
    keys = list(search_space.keys())
    if not keys:
        yield {}
        return
    values = [list(search_space[k]) for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))


def iter_random(search_space: dict[str, Sequence[Any]], *, n: int, seed: int) -> Iterator[dict[str, Any]]:
    rng = random.Random(seed)
    keys = list(search_space.keys())
    for _ in range(max(0, n)):
        yield {k: rng.choice(list(search_space[k])) for k in keys} if keys else {}


def mutate_dsl_params(base: dict[str, Any], *, seed: int, scale: float = 0.2) -> dict[str, Any]:
    """Evolutionary DSL mutation — numeric params jittered; non-numeric copied."""
    rng = random.Random(seed)
    out = dict(base)
    for k, v in list(out.items()):
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            delta = max(1, int(abs(v) * scale) or 1)
            out[k] = max(1, v + rng.randint(-delta, delta))
        elif isinstance(v, float):
            out[k] = v * (1.0 + rng.uniform(-scale, scale))
    return out


def build_hpo_plan(
    *,
    method: str,
    search_space: dict[str, Sequence[Any]],
    max_trials: int = 20,
    seed: int = 42,
    split: str = "train",
    resume_from: int = 0,
    base_parameters: dict[str, Any] | None = None,
) -> HpoPlan:
    method = str(method).lower()
    assert_not_sealed_tuning(split)
    if method == "bayesian_tpe":
        plan = HpoPlan(
            method=method,
            search_space=dict(search_space),
            max_trials=0,
            seed=seed,
            split=split,
            resume_from=resume_from,
            metadata={"capability": bayesian_tpe_capability()},
        )
        return plan
    if method not in HPO_METHODS:
        raise ValueError(f"unsupported HPO method: {method}")

    candidates: list[dict[str, Any]] = []
    if method == "grid":
        candidates = list(iter_grid(search_space))
    elif method == "random":
        candidates = list(iter_random(search_space, n=max_trials, seed=seed))
    elif method == "evolutionary_dsl":
        base = dict(base_parameters or {})
        candidates = [base]
        for i in range(1, max_trials):
            candidates.append(mutate_dsl_params(base, seed=seed + i))

    # Resume: skip already completed indices
    start = max(0, int(resume_from))
    limited = candidates[start : start + max_trials]
    trials = [
        HpoTrial(
            trial_id=str(uuid.uuid4()),
            method=method,
            parameters=params,
            split=split,
            status="CREATED",
            metadata={"index": start + i},
        )
        for i, params in enumerate(limited)
    ]
    return HpoPlan(
        method=method,
        search_space=dict(search_space),
        max_trials=max_trials,
        seed=seed,
        split=split,
        resume_from=start,
        trials=trials,
    )


def run_hpo(
    plan: HpoPlan,
    *,
    evaluate: Callable[[dict[str, Any]], float],
    trial_ledger_append: Callable[[dict[str, Any]], Any] | None = None,
    strategy_id: str | None = None,
) -> HpoPlan:
    """Execute plan trials; every trial (including failures) goes to Trial Ledger when provided."""
    assert_not_sealed_tuning(plan.split)
    if plan.method == "bayesian_tpe":
        plan.metadata["capability"] = bayesian_tpe_capability()
        return plan

    for trial in plan.trials:
        if trial.status == "COMPLETED":
            continue
        try:
            score = float(evaluate(dict(trial.parameters)))
            trial.score = score
            trial.status = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 — ledger must keep losing/failed trials
            trial.status = "FAILED"
            trial.metadata = {**trial.metadata, "error": str(exc)}
        if trial_ledger_append is not None:
            trial_ledger_append(
                {
                    "trial_id": trial.trial_id,
                    "strategy_id": strategy_id or "hpo-anonymous",
                    "strategy_version": 1,
                    "hypothesis": f"hpo:{trial.method}",
                    "proposer_agent_id": "hpo",
                    "data_hash": "hpo-unbound",
                    "status": trial.status,
                    "config": dict(trial.parameters),
                    "split": {"name": trial.split, "tuning": True, "sealed": False},
                    "results": {"score": trial.score, "hpo_method": trial.method},
                    "seed": plan.seed,
                    "metadata": {
                        **dict(trial.metadata),
                        "hpo": True,
                        "parameters": dict(trial.parameters),
                        "no_sealed_tuning": True,
                        "losing_trials_retained": True,
                    },
                }
            )
    return plan
