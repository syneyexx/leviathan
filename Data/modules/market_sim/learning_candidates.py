"""Candidate proposal engine — mutation, crossover, exploration over Strategy DSL v3."""

from __future__ import annotations

import copy
import random
import uuid
from typing import Any

from .learning_fitness import measure_strategy_complexity
from .learning_types import (
    CandidateProposal,
    FailureCategory,
    LearnerState,
    LearningObjectiveSpec,
    ProposalMethod,
    SUPPORTED_STRATEGY_FAMILIES,
)
from .strategy_dsl import SUPPORTED_KINDS, parse_strategy_spec, validate_strategy_spec
from .strategy_eval import strategy_content_hash
from .strategy_families import family_templates


# Structural mutation operation names (persisted on candidates)
MUTATION_OPS = (
    "ADD_FILTER",
    "REMOVE_FILTER",
    "REPLACE_FEATURE",
    "MODIFY_ENTRY",
    "MODIFY_EXIT",
    "MODIFY_RISK",
    "MODIFY_SIZING",
    "CHANGE_FAMILY",
    "NUMERIC_JITTER",
    "CATEGORICAL_SWAP",
)

# Canonical templates — driven by strategy_families registry (Wave 3).
FAMILY_TEMPLATES: dict[str, dict[str, Any]] = family_templates()


def _normalize_probs(probs: dict[str, float], *, floor: float = 0.02) -> dict[str, float]:
    keys = list(SUPPORTED_STRATEGY_FAMILIES)
    out = {k: max(floor, float(probs.get(k, floor))) for k in keys}
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def sample_family(state: LearnerState, rng: random.Random) -> str:
    probs = _normalize_probs(state.family_probabilities)
    families = list(probs.keys())
    weights = [probs[f] for f in families]
    return rng.choices(families, weights=weights, k=1)[0]


def _apply_param_distribution(
    params: dict[str, Any],
    state: LearnerState,
    rng: random.Random,
) -> dict[str, Any]:
    out = dict(params)
    for key, dist in (state.parameter_distributions or {}).items():
        if key not in out and key not in {"fast_ma", "slow_ma", "period", "lookback", "oversold", "overbought"}:
            continue
        mean = float(dist.get("mean", out.get(key) or 10))
        std = float(dist.get("std", max(1.0, abs(mean) * 0.2)))
        lo = float(dist.get("min", mean - 3 * std))
        hi = float(dist.get("max", mean + 3 * std))
        val = rng.gauss(mean, max(std, 1e-6))
        val = max(lo, min(hi, val))
        if isinstance(out.get(key), int) or key in {"fast_ma", "slow_ma", "period", "lookback"}:
            out[key] = max(2, int(round(val)))
        else:
            out[key] = float(val)
    return out


def build_family_spec(family: str, *, rng: random.Random, state: LearnerState) -> dict[str, Any]:
    fam = family if family in FAMILY_TEMPLATES else "ma_cross"
    base = copy.deepcopy(FAMILY_TEMPLATES[fam])
    params = _apply_param_distribution(dict(base["parameters"]), state, rng)
    entry = copy.deepcopy(base["entry_rules"])
    entry_params = dict(entry.get("parameters") or {})
    entry_params.update({k: params[k] for k in params if k in entry_params or k in {"fast_ma", "slow_ma", "period", "lookback", "oversold", "overbought", "z_entry", "z_exit"}})
    # Numeric jitter on template params
    for k, v in list(params.items()):
        if isinstance(v, int):
            params[k] = max(2, v + rng.randint(-2, 2))
        elif isinstance(v, float):
            params[k] = v * (1.0 + rng.uniform(-0.15, 0.15))
    entry["parameters"] = {**(entry.get("parameters") or {}), **{k: params[k] for k in params}}
    entry["kind"] = fam
    entry["version"] = 3
    exit_rules = copy.deepcopy(base["exit_rules"])
    risk_rules = {"max_position_pct": 25, "stop_loss": {"pct": round(rng.uniform(0.02, 0.08), 4)}}
    # Optional regime filter from failure learning
    if state.failure_statistics.get(FailureCategory.REGIME_BRITTLE.value, 0) > 2:
        filters = list(entry.get("filters") or [])
        if not any(str(f.get("kind")) == "regime_filter" for f in filters):
            filters.append({"kind": "regime_filter", "mode": "adx", "period": 14, "min_adx": 18})
            entry["filters"] = filters
    return {
        "family": fam,
        "entry_rules": entry,
        "exit_rules": exit_rules,
        "parameters": params,
        "risk_rules": risk_rules,
    }


def mutate_spec(
    spec: dict[str, Any],
    *,
    rng: random.Random,
    state: LearnerState,
) -> tuple[dict[str, Any], list[str]]:
    out = {
        "family": spec.get("family") or str((spec.get("entry_rules") or {}).get("kind") or "ma_cross"),
        "entry_rules": copy.deepcopy(spec.get("entry_rules") or {}),
        "exit_rules": copy.deepcopy(spec.get("exit_rules") or {}),
        "parameters": copy.deepcopy(spec.get("parameters") or {}),
        "risk_rules": copy.deepcopy(spec.get("risk_rules") or {}),
    }
    ops: list[str] = []
    rates = state.mutation_rates or {}

    if rng.random() < float(rates.get("numeric", 0.35)):
        for k, v in list(out["parameters"].items()):
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                delta = max(1, abs(v) // 5 or 1)
                out["parameters"][k] = max(2, v + rng.randint(-delta, delta))
                ops.append("NUMERIC_JITTER")
            elif isinstance(v, float):
                out["parameters"][k] = v * (1.0 + rng.uniform(-0.2, 0.2))
                ops.append("NUMERIC_JITTER")
        # Sync into entry parameters
        ep = dict(out["entry_rules"].get("parameters") or {})
        ep.update(out["parameters"])
        out["entry_rules"]["parameters"] = ep

    if rng.random() < float(rates.get("categorical", 0.2)):
        # Swap oversold/overbought style categoricals when present
        entry = out["entry_rules"]
        if "entry" in entry and isinstance(entry["entry"], dict):
            if "oversold" in entry["entry"]:
                entry["entry"]["oversold"] = max(10, min(40, int(entry["entry"]["oversold"]) + rng.choice([-5, 5])))
                ops.append("CATEGORICAL_SWAP")
            if "overbought" in entry["entry"]:
                entry["entry"]["overbought"] = max(60, min(90, int(entry["entry"]["overbought"]) + rng.choice([-5, 5])))
                ops.append("MODIFY_ENTRY")

    if rng.random() < float(rates.get("structure", 0.15)):
        filters = list(out["entry_rules"].get("filters") or [])
        if filters and rng.random() < 0.5:
            filters.pop(rng.randrange(len(filters)))
            ops.append("REMOVE_FILTER")
        else:
            filters.append({"kind": "regime_filter", "mode": "trend", "fast": 10, "slow": 30, "require": "bullish"})
            ops.append("ADD_FILTER")
        out["entry_rules"]["filters"] = filters

    if rng.random() < float(rates.get("feature", 0.15)):
        # Feature substitution for feature_compare / period tweaks
        if out["family"] == "feature_compare":
            entry = out["entry_rules"].setdefault("entry", {})
            entry["left_period"] = max(3, int(entry.get("left_period") or 10) + rng.choice([-3, -1, 1, 3]))
            entry["right_period"] = max(5, int(entry.get("right_period") or 30) + rng.choice([-5, -2, 2, 5]))
            ops.append("REPLACE_FEATURE")
        else:
            out["parameters"]["period"] = max(5, int(out["parameters"].get("period") or 20) + rng.choice([-5, -2, 2, 5]))
            ops.append("MODIFY_ENTRY")

    if rng.random() < float(rates.get("risk", 0.2)):
        stop = dict((out["risk_rules"] or {}).get("stop_loss") or {"pct": 0.05})
        pct = float(stop.get("pct") or 0.05) * (1.0 + rng.uniform(-0.3, 0.3))
        stop["pct"] = max(0.01, min(0.2, pct))
        out["risk_rules"]["stop_loss"] = stop
        # Mirror into DSL v3 entry field
        out["entry_rules"]["stop_loss"] = {"pct": stop["pct"]}
        if rng.random() < 0.5:
            out["entry_rules"]["take_profit"] = {"pct": max(0.02, stop["pct"] * rng.uniform(1.5, 3.0))}
        ops.append("MODIFY_RISK")

    # Structural exit / horizon variation — not param-only.
    if rng.random() < float(rates.get("exit", 0.2)):
        exit_rules = dict(out.get("exit_rules") or {})
        modes = ("signal", "stop", "signal_or_stop", "time_stop")
        exit_rules["mode"] = rng.choice(modes)
        exit_rules["kind"] = out.get("family") or exit_rules.get("kind") or "ma_cross"
        if exit_rules["mode"] == "time_stop":
            max_bars = int(rng.choice([5, 10, 20, 40]))
            exit_rules["max_bars"] = max_bars
            out["entry_rules"]["time_stop"] = {"max_bars": max_bars}
        out["exit_rules"] = exit_rules
        ops.append("MODIFY_EXIT")

    if rng.random() < float(rates.get("horizon", 0.15)):
        horizons = ("intrabar", "bars", "session", "multi_day")
        hz = rng.choice(horizons)
        out["entry_rules"]["horizon"] = hz
        out["exit_rules"] = dict(out.get("exit_rules") or {})
        out["exit_rules"]["horizon"] = hz
        ops.append("MODIFY_EXIT")

    if rng.random() < float(rates.get("features", rates.get("feature", 0.15))):
        feature_sets = (
            ["close", "volume"],
            ["close", "high", "low"],
            ["returns", "volatility"],
            ["close", "volume", "atr"],
        )
        out["entry_rules"]["features"] = list(rng.choice(feature_sets))
        ops.append("REPLACE_FEATURE")

    if rng.random() < 0.08:
        new_fam = sample_family(state, rng)
        rebuilt = build_family_spec(new_fam, rng=rng, state=state)
        out = rebuilt
        ops.append("CHANGE_FAMILY")

    # Ensure versioned DSL document
    out["entry_rules"]["version"] = 3
    out["entry_rules"]["kind"] = out["family"]
    return out, list(dict.fromkeys(ops))


def crossover_specs(
    parent_a: dict[str, Any],
    parent_b: dict[str, Any],
    *,
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lineage-aware crossover: entry A + exit B + risk A/B mix."""
    child = {
        "family": parent_a.get("family") if rng.random() < 0.5 else parent_b.get("family"),
        "entry_rules": copy.deepcopy(parent_a.get("entry_rules") or {}),
        "exit_rules": copy.deepcopy(parent_b.get("exit_rules") or {}),
        "parameters": {
            **dict(parent_b.get("parameters") or {}),
            **dict(parent_a.get("parameters") or {}),
        },
        "risk_rules": copy.deepcopy(parent_a.get("risk_rules") or parent_b.get("risk_rules") or {}),
    }
    # Mix filters
    fa = list((parent_a.get("entry_rules") or {}).get("filters") or [])
    fb = list((parent_b.get("entry_rules") or {}).get("filters") or [])
    child["entry_rules"]["filters"] = (fa[:1] + fb[:1]) if (fa or fb) else []
    child["entry_rules"]["version"] = 3
    child["entry_rules"]["kind"] = child["family"]
    # Risk from B sometimes
    if rng.random() < 0.5:
        child["risk_rules"] = copy.deepcopy(parent_b.get("risk_rules") or child["risk_rules"])
        if (parent_b.get("entry_rules") or {}).get("stop_loss"):
            child["entry_rules"]["stop_loss"] = copy.deepcopy(parent_b["entry_rules"]["stop_loss"])
    meta = {
        "entry_from": "parent_a",
        "exit_from": "parent_b",
        "risk_from": "parent_a_or_b",
        "filter_mix": True,
    }
    return child, meta


def _validate_or_raise(spec: dict[str, Any]) -> None:
    parsed = parse_strategy_spec(
        spec.get("entry_rules"),
        exit_rules=spec.get("exit_rules"),
        parameters=spec.get("parameters"),
    )
    ok, reason = validate_strategy_spec(parsed)
    if not ok:
        raise ValueError(f"INVALID_SPEC: {reason}")
    if parsed.kind not in SUPPORTED_KINDS:
        raise ValueError(f"INVALID_SPEC: unsupported kind {parsed.kind}")


def proposal_from_spec(
    spec: dict[str, Any],
    *,
    generation: int,
    strategy_id: str,
    strategy_version: int,
    method: str,
    parent_refs: list[dict[str, Any]] | None = None,
    mutations: list[str] | None = None,
    crossover_metadata: dict[str, Any] | None = None,
    learner_state_hash: str = "",
    objective_hash: str = "",
    hypothesis: str = "",
    hypothesis_id: str | None = None,
) -> CandidateProposal:
    entry = dict(spec.get("entry_rules") or {})
    exit_rules = dict(spec.get("exit_rules") or {})
    parameters = dict(spec.get("parameters") or {})
    risk_rules = dict(spec.get("risk_rules") or {"max_position_pct": 25})
    ch = strategy_content_hash(
        parameters=parameters,
        entry_rules=entry,
        exit_rules=exit_rules,
        risk_rules=risk_rules,
        required_timeframes=["1h"],
        brain_dependencies=["knowledge", "memory", "neuro"],
    )
    family = str(spec.get("family") or entry.get("kind") or "ma_cross")
    complexity = measure_strategy_complexity(entry, exit_rules, parameters)
    meta: dict[str, Any] = {}
    hid = str(hypothesis_id or spec.get("hypothesis_id") or "").strip()
    if hid:
        meta["hypothesis_id"] = hid
    return CandidateProposal(
        candidate_id=str(uuid.uuid4()),
        generation=generation,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parent_refs=list(parent_refs or []),
        proposal_method=method,
        mutations=list(mutations or []),
        crossover_metadata=dict(crossover_metadata or {}),
        hypothesis=hypothesis or f"{method.lower()} {family} gen={generation}",
        content_hash=ch,
        family=family,
        entry_rules=entry,
        exit_rules=exit_rules,
        parameters=parameters,
        risk_rules=risk_rules,
        complexity=complexity,
        status="PROPOSED",
        learner_state_hash=learner_state_hash,
        objective_hash=objective_hash,
        metadata=meta,
    )


def generate_population(
    *,
    state: LearnerState,
    objective: LearningObjectiveSpec,
    generation: int,
    parent_strategy_id: str,
    rng: random.Random,
    elite_specs: list[dict[str, Any]] | None = None,
    prior_candidates: list[CandidateProposal] | None = None,
    agent_proposals: list[dict[str, Any]] | None = None,
    agent_proposal_slots: int = 0,
) -> list[dict[str, Any]]:
    """Generate bounded population specs (not yet versioned).

    Returns list of dicts with keys: spec, method, parent_refs, mutations, crossover_metadata, hypothesis
    """
    size = max(1, int(objective.population_size))
    elite_n = min(int(objective.elite_count), size)
    out: list[dict[str, Any]] = []
    elites = list(elite_specs or [])
    priors = list(prior_candidates or [])
    seen_hashes: set[str] = set()

    def _spec_hash(spec: dict[str, Any]) -> str:
        try:
            return strategy_content_hash(
                parameters=dict(spec.get("parameters") or {}),
                entry_rules=dict(spec.get("entry_rules") or {}),
                exit_rules=dict(spec.get("exit_rules") or {}),
                risk_rules=dict(spec.get("risk_rules") or {"max_position_pct": 25}),
                required_timeframes=list(
                    spec.get("required_timeframes")
                    or (spec.get("entry_rules") or {}).get("required_timeframes")
                    or ["1h"]
                ),
                brain_dependencies=list(spec.get("brain_dependencies") or []),
            )
        except Exception:  # noqa: BLE001
            return ""

    def _append_unique(item: dict[str, Any]) -> bool:
        if len(out) >= size:
            return False
        ch = _spec_hash(item.get("spec") or {})
        if ch and ch in seen_hashes:
            return False
        if ch:
            seen_hashes.add(ch)
        out.append(item)
        return True

    # Elitism
    for i, espec in enumerate(elites[:elite_n]):
        _append_unique(
            {
                "spec": copy.deepcopy(espec),
                "method": ProposalMethod.ELITE.value,
                "parent_refs": [{"strategy_id": parent_strategy_id, "role": "elite", "index": i}],
                "mutations": [],
                "crossover_metadata": {},
                "hypothesis": f"elite preserve gen={generation}",
            }
        )

    # Agent-proposed slots (bounded) — inserted early so budget is respected
    agent_slots = max(0, min(int(agent_proposal_slots or 0), size - len(out)))
    if agent_slots > 0 and agent_proposals:
        merged = merge_agent_proposals_into_population(
            [],
            agent_proposals=agent_proposals,
            slots=agent_slots,
            parent_strategy_id=parent_strategy_id,
            generation=generation,
        )
        for item in merged:
            if not _append_unique(item):
                if len(out) >= size:
                    break

    # Exploration quota
    explore_n = max(1, int(round(size * float(state.exploration_rate or objective.exploration_rate))))
    while len(out) < size and explore_n > 0 and len(out) < size:
        # Leave room — compute remaining slots later
        break

    remaining = size - len(out)
    explore_slots = min(explore_n, remaining)
    mutate_slots = 0
    cross_slots = 0
    rest = remaining - explore_slots
    if rest > 0:
        cross_slots = int(round(rest * float(state.crossover_rate or objective.crossover_rate)))
        mutate_slots = rest - cross_slots

    for _ in range(explore_slots):
        fam = sample_family(state, rng)
        # Lesson priors can nudge away from penalized families
        for lesson_fam, penalty in (state.lesson_priors or {}).items():
            if penalty < 0 and fam == lesson_fam and rng.random() < min(0.8, abs(penalty)):
                fam = sample_family(state, rng)
        spec = build_family_spec(fam, rng=rng, state=state)
        _validate_or_raise(spec)
        _append_unique(
            {
                "spec": spec,
                "method": ProposalMethod.EXPLORATION.value,
                "parent_refs": [{"strategy_id": parent_strategy_id, "role": "root"}],
                "mutations": ["CHANGE_FAMILY"] if generation > 0 else [],
                "crossover_metadata": {},
                "hypothesis": f"explore {fam} gen={generation}",
            }
        )

    def _parent_spec() -> dict[str, Any]:
        if elites:
            return copy.deepcopy(rng.choice(elites))
        if priors:
            p = rng.choice(priors)
            return {
                "family": p.family,
                "entry_rules": dict(p.entry_rules),
                "exit_rules": dict(p.exit_rules),
                "parameters": dict(p.parameters),
                "risk_rules": dict(p.risk_rules),
            }
        fam = sample_family(state, rng)
        return build_family_spec(fam, rng=rng, state=state)

    for _ in range(mutate_slots):
        base = _parent_spec()
        mutated, ops = mutate_spec(base, rng=rng, state=state)
        try:
            _validate_or_raise(mutated)
        except ValueError:
            mutated = build_family_spec(sample_family(state, rng), rng=rng, state=state)
            ops = ["CHANGE_FAMILY"]
        _append_unique(
            {
                "spec": mutated,
                "method": ProposalMethod.MUTATION.value,
                "parent_refs": [{"strategy_id": parent_strategy_id, "role": "mutation_parent"}],
                "mutations": ops,
                "crossover_metadata": {},
                "hypothesis": f"mutate ops={ops} gen={generation}",
            }
        )

    for _ in range(cross_slots):
        a = _parent_spec()
        b = _parent_spec()
        child, meta = crossover_specs(a, b, rng=rng)
        try:
            _validate_or_raise(child)
        except ValueError:
            child = build_family_spec(sample_family(state, rng), rng=rng, state=state)
            meta = {"fallback": "exploration_after_invalid_crossover"}
        _append_unique(
            {
                "spec": child,
                "method": ProposalMethod.CROSSOVER.value,
                "parent_refs": [
                    {"strategy_id": parent_strategy_id, "role": "parent_a"},
                    {"strategy_id": parent_strategy_id, "role": "parent_b"},
                ],
                "mutations": [],
                "crossover_metadata": meta,
                "hypothesis": f"crossover gen={generation}",
            }
        )

    # Generation 0 seed fill
    while len(out) < size:
        fam = sample_family(state, rng)
        spec = build_family_spec(fam, rng=rng, state=state)
        if not _append_unique(
            {
                "spec": spec,
                "method": ProposalMethod.SEED.value if generation == 0 else ProposalMethod.EXPLORATION.value,
                "parent_refs": [{"strategy_id": parent_strategy_id, "role": "root"}],
                "mutations": [],
                "crossover_metadata": {},
                "hypothesis": f"seed {fam} gen={generation}",
            }
        ):
            # Forced append when hash collision / empty hash to avoid infinite loop
            out.append(
                {
                    "spec": spec,
                    "method": ProposalMethod.SEED.value if generation == 0 else ProposalMethod.EXPLORATION.value,
                    "parent_refs": [{"strategy_id": parent_strategy_id, "role": "root"}],
                    "mutations": [],
                    "crossover_metadata": {},
                    "hypothesis": f"seed {fam} gen={generation}",
                }
            )
            if len(out) >= size:
                break

    population = out[:size]
    # Attach measurable novelty (structural + parameter) vs elite/prior references.
    refs: list[dict[str, Any]] = []
    for espec in elites:
        refs.append(espec if isinstance(espec, dict) else {})
    for prior in priors:
        if hasattr(prior, "public_dict"):
            refs.append(prior.public_dict())
        elif isinstance(prior, dict):
            refs.append(prior)
    explore_rate = float(state.exploration_rate or objective.exploration_rate or 0.0)
    for item in population:
        novelty = measure_spec_novelty(item.get("spec") or {}, reference_pool=refs)
        item["novelty"] = novelty
        item["structural_novelty"] = novelty.get("structural_novelty")
        item["parameter_novelty"] = novelty.get("parameter_novelty")
        item["exploration_rate"] = explore_rate
        meta = dict(item.get("metadata") or {})
        meta["novelty"] = novelty
        meta["exploration_rate"] = explore_rate
        item["metadata"] = meta
    return population


def measure_spec_novelty(
    spec: dict[str, Any],
    *,
    reference_pool: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expose measurable structural + parameter novelty for a candidate spec."""
    from .strategy_search_grammar import measure_candidate_novelty

    payload = {
        "family": spec.get("family"),
        "entry_rules": dict(spec.get("entry_rules") or {}),
        "exit_rules": dict(spec.get("exit_rules") or {}),
        "parameters": dict(spec.get("parameters") or {}),
        "risk_rules": dict(spec.get("risk_rules") or {}),
        "metadata": dict(spec.get("metadata") or {}),
    }
    refs = []
    for ref in reference_pool or []:
        if not isinstance(ref, dict):
            continue
        if "entry_rules" in ref or "parameters" in ref:
            refs.append(ref)
        elif "spec" in ref and isinstance(ref["spec"], dict):
            refs.append(ref["spec"])
    return measure_candidate_novelty(payload, reference_pool=refs)


def merge_agent_proposals_into_population(
    population: list[dict[str, Any]],
    *,
    agent_proposals: list[dict[str, Any]] | None,
    slots: int,
    parent_strategy_id: str,
    generation: int,
) -> list[dict[str, Any]]:
    """Insert validated AGENT_PROPOSED specs into a population (bounded by slots).

    Each agent proposal may be a full population item or a raw strategy spec
    (family/entry_rules/...). Deduplicates by content hash against existing items.
    """
    out = list(population or [])
    if not agent_proposals or slots <= 0:
        return out

    def _hash_of(spec: dict[str, Any]) -> str:
        try:
            return strategy_content_hash(
                parameters=dict(spec.get("parameters") or {}),
                entry_rules=dict(spec.get("entry_rules") or {}),
                exit_rules=dict(spec.get("exit_rules") or {}),
                risk_rules=dict(spec.get("risk_rules") or {"max_position_pct": 25}),
                required_timeframes=list(
                    spec.get("required_timeframes")
                    or (spec.get("entry_rules") or {}).get("required_timeframes")
                    or ["1h"]
                ),
                brain_dependencies=list(spec.get("brain_dependencies") or []),
            )
        except Exception:  # noqa: BLE001
            return ""

    seen = {_hash_of(item.get("spec") or {}) for item in out}
    seen.discard("")
    added = 0
    for raw in agent_proposals:
        if added >= slots:
            break
        item = dict(raw or {})
        if "spec" in item and isinstance(item["spec"], dict):
            spec = dict(item["spec"])
            method = str(item.get("method") or ProposalMethod.AGENT_PROPOSED.value)
            parent_refs = list(item.get("parent_refs") or [])
            mutations = list(item.get("mutations") or [])
            crossover_metadata = dict(item.get("crossover_metadata") or {})
            hypothesis = str(item.get("hypothesis") or "")
            meta_extra = dict(item.get("metadata") or {})
        else:
            spec = {
                "family": item.get("family") or (item.get("entry_rules") or {}).get("kind"),
                "entry_rules": dict(item.get("entry_rules") or {}),
                "exit_rules": dict(item.get("exit_rules") or {}),
                "parameters": dict(item.get("parameters") or {}),
                "risk_rules": dict(item.get("risk_rules") or {"max_position_pct": 25}),
            }
            method = ProposalMethod.AGENT_PROPOSED.value
            parent_refs = [{"strategy_id": parent_strategy_id, "role": "agent_author"}]
            mutations = []
            crossover_metadata = {}
            hypothesis = str(item.get("hypothesis") or item.get("statement") or f"agent proposed gen={generation}")
            meta_extra = {
                k: v
                for k, v in item.items()
                if k
                not in {
                    "family",
                    "entry_rules",
                    "exit_rules",
                    "parameters",
                    "risk_rules",
                    "content_hash",
                    "hypothesis",
                    "statement",
                }
            }
            if item.get("hypothesis_id"):
                meta_extra["hypothesis_id"] = item["hypothesis_id"]
            if item.get("content_hash"):
                meta_extra["agent_content_hash"] = item["content_hash"]
        try:
            _validate_or_raise(spec)
        except ValueError:
            continue
        ch = _hash_of(spec)
        if ch and ch in seen:
            continue
        if ch:
            seen.add(ch)
        out.append(
            {
                "spec": spec,
                "method": method,
                "parent_refs": parent_refs
                or [{"strategy_id": parent_strategy_id, "role": "agent_author"}],
                "mutations": mutations,
                "crossover_metadata": crossover_metadata,
                "hypothesis": hypothesis or f"agent proposed gen={generation}",
                "metadata": meta_extra,
            }
        )
        added += 1
    return out


def update_learner_from_outcomes(
    state: LearnerState,
    *,
    outcomes: list[dict[str, Any]],
    objective: LearningObjectiveSpec,
    rng: random.Random,
    split_role: str = "TRAIN",
) -> LearnerState:
    """Update proposal distributions from TRAIN outcomes only.

    ``outcomes`` items: {candidate_id, family, fitness_score, failure_categories, parameters, complexity}
    SEALED/VAL must not call this for distribution updates (VAL may bump exposure count separately).
    """
    if str(split_role).upper() != "TRAIN":
        raise ValueError("learner distribution updates allowed only on TRAIN outcomes")

    state = LearnerState.from_dict(state.public_dict())  # copy
    if not outcomes:
        state.generation_number += 1
        state.rng_state = list(rng.getstate()[1]) if hasattr(rng, "getstate") else state.rng_state
        return state

    # Rank by fitness (None last)
    def _score(o: dict[str, Any]) -> float:
        s = o.get("fitness_score")
        if s is None:
            return float("-inf")
        try:
            v = float(s)
        except (TypeError, ValueError):
            return float("-inf")
        if math_isnan(v):
            return float("-inf")
        return v

    ranked = sorted(outcomes, key=_score, reverse=True)
    elite_n = max(1, min(int(objective.elite_count), len(ranked)))
    elites = [o for o in ranked[:elite_n] if o.get("fitness_score") is not None]
    state.elite_refs = [str(o.get("candidate_id")) for o in elites]
    state.population_refs = [str(o.get("candidate_id")) for o in ranked]
    if elites:
        state.best_candidate_ref = str(elites[0].get("candidate_id"))

    # Family probability update — winners up, failures down
    fam_scores: dict[str, list[float]] = {f: [] for f in SUPPORTED_STRATEGY_FAMILIES}
    for o in ranked:
        fam = str(o.get("family") or "ma_cross")
        if fam not in fam_scores:
            fam_scores[fam] = []
        sc = o.get("fitness_score")
        if sc is not None:
            try:
                fam_scores[fam].append(float(sc))
            except (TypeError, ValueError):
                pass
        for cat in o.get("failure_categories") or []:
            state.failure_statistics[str(cat)] = int(state.failure_statistics.get(str(cat), 0)) + 1

    # Softmax-ish update from mean family fitness
    import math

    logits = {}
    for fam in SUPPORTED_STRATEGY_FAMILIES:
        scores = fam_scores.get(fam) or []
        mean = sum(scores) / len(scores) if scores else -0.1
        prior = float(state.family_probabilities.get(fam, 1.0 / len(SUPPORTED_STRATEGY_FAMILIES)))
        logits[fam] = math.log(max(prior, 1e-6)) + mean

    # Failure penalties
    fail_map = {
        FailureCategory.INSUFFICIENT_TRADES.value: -0.05,
        FailureCategory.EXCESSIVE_DRAWDOWN.value: -0.08,
        FailureCategory.HIGH_COMPLEXITY.value: -0.03,
        FailureCategory.REGIME_BRITTLE.value: -0.05,
        FailureCategory.NEGATIVE_RETURN.value: -0.04,
    }
    # Penalize families that failed often this generation
    for o in ranked:
        fam = str(o.get("family") or "")
        for cat in o.get("failure_categories") or []:
            if cat in fail_map and fam in logits:
                logits[fam] += fail_map[cat]

    max_logit = max(logits.values())
    exps = {f: math.exp(logits[f] - max_logit) for f in logits}
    total = sum(exps.values()) or 1.0
    state.family_probabilities = _normalize_probs({f: exps[f] / total for f in exps})

    # Parameter distributions from elites
    param_acc: dict[str, list[float]] = {}
    for o in elites:
        for k, v in dict(o.get("parameters") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                param_acc.setdefault(k, []).append(float(v))
    for k, vals in param_acc.items():
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / max(len(vals), 1)
        std = max(var ** 0.5, abs(mean) * 0.05, 0.5)
        state.parameter_distributions[k] = {
            "mean": mean,
            "std": std,
            "min": min(vals) - std,
            "max": max(vals) + std,
        }

    # Diversity
    families = {str(o.get("family")) for o in ranked}
    hashes = {str(o.get("content_hash") or o.get("candidate_id")) for o in ranked}
    state.diversity_score = (len(families) / max(len(SUPPORTED_STRATEGY_FAMILIES), 1) + len(hashes) / max(len(ranked), 1)) / 2.0

    # Exploration boost on collapse
    collapse_min = float((objective.early_stop_rules or {}).get("diversity_collapse_min", 0.05))
    if state.diversity_score < collapse_min:
        state.exploration_rate = min(0.5, float(state.exploration_rate) + 0.1)

    # Fitness history
    best = _score(ranked[0]) if ranked else None
    prev_best = None
    if state.fitness_history:
        prev_best = state.fitness_history[-1].get("best_train_fitness")
    improved = best is not None and best != float("-inf") and (prev_best is None or best > float(prev_best) + 1e-9)
    if improved:
        state.generations_without_improvement = 0
    else:
        state.generations_without_improvement += 1

    state.fitness_history.append(
        {
            "generation": state.generation_number + 1,
            "best_train_fitness": None if best == float("-inf") else best,
            "median_train_fitness": _median([o.get("fitness_score") for o in ranked]),
            "diversity_score": state.diversity_score,
            "family_entropy": _entropy(state.family_probabilities),
            "n_outcomes": len(ranked),
        }
    )
    state.generation_number += 1
    # Persist RNG state for resume
    try:
        state.rng_state = list(rng.getstate()[1])
        state.metadata["rng_version"] = int(rng.getstate()[0])
        state.metadata["rng_gauss"] = rng.getstate()[2]
    except Exception:  # noqa: BLE001
        pass
    return state


def math_isnan(v: float) -> bool:
    import math

    return math.isnan(v)


def _median(vals: list[Any]) -> float | None:
    xs = []
    for v in vals:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math_isnan(f) or abs(f) == float("inf"):
            continue
        xs.append(f)
    if not xs:
        return None
    xs.sort()
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def _entropy(probs: dict[str, float]) -> float:
    import math

    h = 0.0
    for p in probs.values():
        if p > 0:
            h -= p * math.log(p + 1e-12)
    return h


def restore_rng(seed: int, rng_state: list[Any] | None) -> random.Random:
    rng = random.Random(seed)
    if rng_state is not None:
        try:
            # getstate = (version, internalstate, gauss_next)
            version = 3
            gauss = None
            rng.setstate((version, tuple(rng_state), gauss))
        except Exception:  # noqa: BLE001 — fall back to seeded RNG
            rng = random.Random(seed)
    return rng
