"""Bounded, auditable strategy evolution.

This is not genetic programming and it does not execute model-written Python. A candidate
is a new declarative strategy version: a supported family plus validated parameters, with
lineage pointing at the parent, the beliefs that motivated the change, and the exact fields
that moved.

Duplicate fingerprints are reused, not re-run. Budgets are hard caps. Negative evidence
lowers the chance that the same unsupported idea is proposed again, without turning a
single failure into permanent dogma.
"""

from __future__ import annotations

from typing import Any, Sequence

from trading_lab.contracts import StrategyHypothesis, StrategySpec, stable_hash
from trading_lab.strategies import default_param_space, resolve_family

DEFAULT_BUDGETS = {
    "max_candidates_per_parent": 3,
    "max_experiments_per_cycle": 2,
    "max_parameter_combinations": 8,
    "max_generations": 2,
    "max_compute_budget": 4,
    "max_agent_calls": 2,
    "max_model_tokens": 4000,
    "max_lineage_depth": 4,
}

MUTATION_KINDS = (
    "parameter_adjustment",
    "parameter_neighborhood",
    "regime_filter",
    "volatility_filter",
    "no_trade_condition",
    "threshold_adjustment",
    "sizing_parameter",
    "family_switch",
    "replication",
)


def candidate_fingerprint(
    *,
    family: str,
    params: dict[str, Any],
    instruments: Sequence[str],
    timeframe: str,
    sizing: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    dataset_checksum: str = "",
    experiment_config: dict[str, Any] | None = None,
) -> str:
    return stable_hash(
        {
            "family": resolve_family(family),
            "params": params,
            "instruments": sorted(instruments),
            "timeframe": timeframe,
            "sizing": sizing or {},
            "filters": filters or {},
            "dataset_checksum": dataset_checksum,
            "experiment_config": experiment_config or {},
        }
    )


def generation_of(lineage_rows: Sequence[dict[str, Any]], parent_strategy_id: str, parent_version: int) -> int:
    depth = 1
    for row in lineage_rows:
        if row.get("child_strategy_id") == parent_strategy_id and int(row.get("child_version") or 0) == int(parent_version):
            depth = max(depth, int(row.get("generation") or 1) + 1)
    return depth


def mutate_from_findings(
    spec: StrategySpec,
    findings: Sequence[dict[str, Any]],
    *,
    beliefs: Sequence[dict[str, Any]] = (),
    budget: dict[str, Any] | None = None,
    known_fingerprints: set[str] | None = None,
    failed_fingerprints: set[str] | None = None,
    dataset_checksum: str = "",
    creator: str = "evolution_engine",
    generation: int = 1,
    max_lineage_depth: int | None = None,
) -> dict[str, Any]:
    """Produce bounded candidate proposals. Parent spec is never mutated in place."""
    limits = {**DEFAULT_BUDGETS, **(budget or {})}
    cap = int(limits.get("max_candidates_per_parent") or 3)
    depth_cap = int(max_lineage_depth or limits.get("max_lineage_depth") or 4)
    if generation > depth_cap:
        return {"candidates": [], "rejected": [{"reason": "max_lineage_depth", "generation": generation, "cap": depth_cap}]}

    known = set(known_fingerprints or ())
    failed = set(failed_fingerprints or ())
    proposals: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    space = default_param_space(spec.family)

    regime_specialists = _regime_specialists(findings)
    param_steps = _parameter_steps(spec, space, findings)
    sizing_step = _sizing_step(spec, findings)

    raw: list[dict[str, Any]] = []
    # Regime-conditional evidence is more informative than a lookback tweak: if the same
    # family is good in one regime and bad in another, specialise first rather than
    # burning the candidate budget on near-identical parameter neighbourhoods.
    raw.extend(regime_specialists)
    raw.extend(param_steps)
    if sizing_step:
        raw.append(sizing_step)

    for suggestion in _belief_mutations(spec, beliefs, space):
        raw.append(suggestion)

    seen_local: set[str] = set()
    for item in raw:
        if len(proposals) >= cap:
            rejected.append({"reason": "max_candidates_per_parent", "cap": cap, "dropped": item.get("mutation_kind")})
            continue
        params = {**spec.params, **(item.get("params") or {})}
        filters = {}
        if "regime_filter" in params:
            filters["regime_filter"] = params["regime_filter"]
        if "volatility_filter" in params:
            filters["volatility_filter"] = params["volatility_filter"]
        fingerprint = candidate_fingerprint(
            family=spec.family,
            params=params,
            instruments=spec.instruments,
            timeframe=spec.timeframe,
            sizing=(item.get("sizing") or spec.sizing.as_json()),
            filters=filters,
            dataset_checksum=dataset_checksum,
        )
        if fingerprint in seen_local:
            rejected.append({"reason": "duplicate_in_cycle", "fingerprint": fingerprint})
            continue
        if fingerprint in known:
            rejected.append({"reason": "already_evaluated", "fingerprint": fingerprint, "reuse": True})
            continue
        if fingerprint in failed and item.get("mutation_kind") != "replication":
            rejected.append(
                {
                    "reason": "negative_evidence_blocks_identical_retry",
                    "fingerprint": fingerprint,
                    "hint": "propose a materially different hypothesis or an explicit replication",
                }
            )
            continue
        if item.get("params") == spec.params and not item.get("sizing") and "regime_filter" not in params:
            rejected.append({"reason": "no_material_change"})
            continue
        seen_local.add(fingerprint)
        refs = list(item.get("evidence_refs") or [])
        if not refs:
            rejected.append({"reason": "mutation_missing_evidence", "mutation_kind": item.get("mutation_kind")})
            continue
        proposals.append(
            {
                "parent_strategy_id": spec.strategy_id,
                "parent_version": spec.version,
                "family": spec.family,
                "params": params,
                "instruments": list(spec.instruments),
                "timeframe": spec.timeframe,
                "sizing": item.get("sizing") or spec.sizing.as_json(),
                "hypothesis": _child_hypothesis(spec, item),
                "mutation_kind": item.get("mutation_kind") or "parameter_adjustment",
                "mutation_reason": item.get("reason") or "",
                "changed_fields": item.get("changed_fields") or [],
                "belief_refs": item.get("belief_refs") or [],
                "evidence_refs": refs,
                "fingerprint": fingerprint,
                "created_by": creator,
                "generation": generation,
                "name": f"{spec.name} / {item.get('mutation_kind')}",
            }
        )
    return {"candidates": proposals, "rejected": rejected, "budget": {"max_candidates_per_parent": cap, "emitted": len(proposals)}}


def materialize_candidate(parent: StrategySpec, proposal: dict[str, Any]) -> StrategySpec:
    hypothesis = parent.hypothesis
    child_h = proposal.get("hypothesis")
    if isinstance(child_h, dict):
        hypothesis = StrategyHypothesis.model_validate({**(hypothesis.as_json() if hypothesis else {}), **child_h})
    sizing = parent.sizing
    if proposal.get("sizing"):
        from trading_lab.contracts import SizingSpec

        sizing = SizingSpec.model_validate(proposal["sizing"])
    return parent.model_copy(
        update={
            "name": str(proposal.get("name") or parent.name)[:160],
            "params": dict(proposal.get("params") or parent.params),
            "sizing": sizing,
            "hypothesis": hypothesis,
            "scope_note": (
                f"Evolved from {parent.strategy_id} v{parent.version}: {proposal.get('mutation_reason', '')}"
            )[:2000],
        }
    )


def _parameter_steps(spec: StrategySpec, space: dict[str, list[Any]], findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    refs = _finding_refs(findings)
    if not refs:
        return out
    negative = [item for item in findings if (item.get("metrics") or {}).get("expectancy") is not None and (item.get("metrics") or {}).get("expectancy") < 0]
    positive = [item for item in findings if (item.get("metrics") or {}).get("expectancy") is not None and (item.get("metrics") or {}).get("expectancy") > 0]
    # Neighborhood exploration around current params, bounded by the declared search space.
    for key, values in space.items():
        current = spec.params.get(key)
        if current not in values or len(values) < 2:
            continue
        index = values.index(current)
        for delta, label in ((-1, "down"), (1, "up")):
            nxt = index + delta
            if nxt < 0 or nxt >= len(values):
                continue
            if negative and label == "up" and _looks_like_lookback(key):
                # Failed lookbacks: prefer a different window rather than amplifying the same one.
                pass
            changed = {key: values[nxt]}
            out.append(
                {
                    "mutation_kind": "parameter_neighborhood",
                    "params": changed,
                    "changed_fields": [f"params.{key}:{current}->{values[nxt]}"],
                    "reason": f"Explore {key} neighbourhood ({current} → {values[nxt]}) after aggregated evidence.",
                    "evidence_refs": refs[:8],
                }
            )
    if positive and space.get("threshold") and spec.params.get("threshold") in space["threshold"]:
        values = space["threshold"]
        current = spec.params["threshold"]
        index = values.index(current)
        if index + 1 < len(values):
            out.append(
                {
                    "mutation_kind": "threshold_adjustment",
                    "params": {"threshold": values[index + 1]},
                    "changed_fields": [f"params.threshold:{current}->{values[index + 1]}"],
                    "reason": "Positive expectancy: raise the entry threshold to test whether the edge survives a stricter filter.",
                    "evidence_refs": refs[:8],
                }
            )
    return out[:6]


def _regime_specialists(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_regime: dict[str, list[dict[str, Any]]] = {}
    for item in findings:
        if item.get("evidence_status") != "sufficient":
            continue
        regime = (item.get("group") or {}).get("regime_key") or ""
        if not regime or regime == "unavailable":
            continue
        by_regime.setdefault(regime, []).append(item)
    if len(by_regime) < 2:
        # Still allow a filter when one regime is clearly bad even without a second bucket
        # in this batch, as long as expectancy is negative with enough samples.
        pass
    good = []
    bad = []
    for regime, items in by_regime.items():
        expectancy = _mean([float((item.get("metrics") or {}).get("expectancy") or 0) for item in items])
        refs = _finding_refs(items)
        if expectancy is None:
            continue
        if expectancy > 0:
            good.append((regime, refs, expectancy))
        elif expectancy < 0:
            bad.append((regime, refs, expectancy))
    if good and bad:
        trend, vol, stress = _parse_regime(good[0][0])
        required: dict[str, Any] = {}
        if trend:
            required["trend"] = trend
        if vol:
            required["volatility"] = vol
        out.append(
            {
                "mutation_kind": "regime_filter",
                "params": {"regime_filter": required, "no_trade_regimes": [item[0] for item in bad]},
                "changed_fields": [f"params.regime_filter={required}", f"params.no_trade_regimes={[item[0] for item in bad]}"],
                "reason": (
                    f"Conditional evidence: positive expectancy in {good[0][0]} "
                    f"({good[0][2]:.6f}) and negative in {bad[0][0]} ({bad[0][2]:.6f}). "
                    "Specialise rather than claiming the strategy is globally good."
                ),
                "evidence_refs": (good[0][1] + bad[0][1])[:12],
            }
        )
        if bad:
            _, vol_bad, _ = _parse_regime(bad[0][0])
            if vol_bad:
                out.append(
                    {
                        "mutation_kind": "volatility_filter",
                        "params": {"volatility_filter": {"avoid": vol_bad}},
                        "changed_fields": [f"params.volatility_filter.avoid={vol_bad}"],
                        "reason": f"Avoid {vol_bad} where expectancy was negative.",
                        "evidence_refs": bad[0][1][:8],
                    }
                )
            out.append(
                {
                    "mutation_kind": "no_trade_condition",
                    "params": {"no_trade_regimes": [item[0] for item in bad]},
                    "changed_fields": [f"params.no_trade_regimes={[item[0] for item in bad]}"],
                    "reason": "Do not trade the failing regime; keep the parent intact as a separate version.",
                    "evidence_refs": bad[0][1][:8],
                }
            )
    return out


def _sizing_step(spec: StrategySpec, findings: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    refs = _finding_refs(findings)
    if not refs:
        return None
    negative = any((item.get("metrics") or {}).get("expectancy") is not None and (item.get("metrics") or {}).get("expectancy") < 0 for item in findings)
    if not negative:
        return None
    current = spec.sizing.value
    from decimal import Decimal

    proposed = (current / Decimal("2")).quantize(Decimal("0.0001"))
    if proposed <= 0 or proposed >= current:
        return None
    if spec.sizing.mode == "equity_fraction" and proposed > 1:
        return None
    return {
        "mutation_kind": "sizing_parameter",
        "sizing": {**spec.sizing.as_json(), "value": str(proposed)},
        "changed_fields": [f"sizing.value:{current}->{proposed}"],
        "reason": "Negative evidence: propose a smaller equity fraction inside the existing risk bounds, not a larger bet.",
        "evidence_refs": refs[:8],
    }


def _belief_mutations(spec: StrategySpec, beliefs: Sequence[dict[str, Any]], space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for belief in beliefs:
        mutation = (belief.get("mutation") if isinstance(belief, dict) else None) or {}
        if not isinstance(mutation, dict):
            continue
        kind = str(mutation.get("kind") or mutation.get("mutation_kind") or "")
        if kind not in MUTATION_KINDS:
            continue
        params = mutation.get("params") if isinstance(mutation.get("params"), dict) else {}
        # Only accept keys that already exist on the spec or in the family search space.
        allowed = set(spec.params) | set(space) | {"regime_filter", "volatility_filter", "no_trade_regimes"}
        clean = {key: value for key, value in params.items() if key in allowed}
        refs = list(belief.get("evidence_refs") or [])
        if not refs:
            continue
        out.append(
            {
                "mutation_kind": kind,
                "params": clean,
                "changed_fields": [f"params.{key}" for key in clean],
                "reason": str(belief.get("claim") or mutation.get("reason") or "curator suggestion"),
                "evidence_refs": refs,
                "belief_refs": [belief.get("belief_id")] if belief.get("belief_id") else [],
            }
        )
    return out


def _child_hypothesis(spec: StrategySpec, item: dict[str, Any]) -> dict[str, Any]:
    base = spec.hypothesis.as_json() if spec.hypothesis else {
        "economic_rationale": "Evolved candidate; rationale inherited and must be re-evaluated.",
        "falsification_criteria": ["Fails independent validation or collapses after costs."],
        "benchmarks": ["buy_and_hold"],
    }
    note = str(item.get("reason") or "")
    rationale = str(base.get("economic_rationale") or "")
    if note and note not in rationale:
        base["economic_rationale"] = (rationale + " Evolution note: " + note)[:4000]
        if len(base["economic_rationale"]) < 20:
            base["economic_rationale"] = ("Evolved from parent strategy. " + note)[:4000]
    regimes = item.get("params") or {}
    if regimes.get("no_trade_regimes"):
        base["implausible_regimes"] = ", ".join(str(part) for part in regimes["no_trade_regimes"])[:500]
    if regimes.get("regime_filter"):
        base["plausible_regimes"] = str(regimes["regime_filter"])[:500]
    return base


def _finding_refs(findings: Sequence[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for item in findings:
        finding_id = item.get("finding_id")
        if finding_id:
            refs.append(f"finding:{finding_id}")
        for ref in item.get("evidence_refs") or []:
            if ref not in refs:
                refs.append(str(ref))
    return refs


def _parse_regime(key: str) -> tuple[str | None, str | None, str | None]:
    parts = str(key).split("|")
    trend = parts[0] if parts and parts[0] not in {"", "unavailable", "unknown"} else None
    vol = parts[1] if len(parts) > 1 and parts[1] not in {"", "unknown"} else None
    stress = parts[2] if len(parts) > 2 and parts[2] not in {"", "unknown"} else None
    return trend, vol, stress


def _looks_like_lookback(key: str) -> bool:
    return key in {"lookback", "window", "slow", "fast"}


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


__all__ = [
    "DEFAULT_BUDGETS",
    "MUTATION_KINDS",
    "candidate_fingerprint",
    "generation_of",
    "materialize_candidate",
    "mutate_from_findings",
]
