"""Research Lab generation cycle — perception → hypothesis → critic → bounded DSL author.

Uses TradingModelAdapter-style messages lists via an optional ``model_complete``
callable ``(messages, role) -> dict``. Does not create private model clients.
When ``model_complete`` is None, emits deterministic heuristic proposals so
offline tests work without a model plane.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .research_hypothesis import ResearchHypothesisScope, new_research_hypothesis
from .research_roles import ResearchResponsibility, resolve_fleet_role
from .strategy_dsl import parse_strategy_spec, validate_strategy_spec
from .strategy_eval import strategy_content_hash
from .strategy_families import (
    family_templates,
    get_family,
    research_generatable_families,
)


ModelCompleteFn = Callable[[list[dict[str, str]], str], dict[str, Any]]
VisionCompleteFn = Callable[[list[dict[str, Any]], str], dict[str, Any]]

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_CODE_KEYS = frozenset({"eval", "exec", "code", "__import__", "compile", "bytecode"})

HYPOTHESIS_REQUIRED = ("statement",)
CRITIC_REQUIRED = ("verdict",)
AUTHOR_REQUIRED = ("family",)


@dataclass
class ResearchCycleResult:
    perception: dict[str, Any]
    hypothesis: dict[str, Any] | None
    critic: dict[str, Any] | None
    author_proposals: list[dict[str, Any]]
    rejected_proposals: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    chart_observation: dict[str, Any] | None
    chart_status: str  # MEASURED|UNAVAILABLE|UNMEASURED|SKIPPED
    evidence_refs: list[str]
    model_calls_used: int
    public_events: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "perception": dict(self.perception),
            "hypothesis": dict(self.hypothesis) if self.hypothesis else None,
            "critic": dict(self.critic) if self.critic else None,
            "author_proposals": list(self.author_proposals),
            "rejected_proposals": list(self.rejected_proposals),
            "conflicts": list(self.conflicts),
            "chart_observation": dict(self.chart_observation) if self.chart_observation else None,
            "chart_status": self.chart_status,
            "evidence_refs": list(self.evidence_refs),
            "model_calls_used": self.model_calls_used,
            "public_events": list(self.public_events),
            "metadata": dict(self.metadata),
            "truth": {
                "public_structured_reasoning_only": True,
                "no_private_model_client": True,
                "dsl_only_no_arbitrary_python": True,
            },
        }


class ResearchCycleSchemaError(ValueError):
    """Honest schema failure after optional one-shot repair."""


def _extract_json_object(text: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(text, dict):
        return dict(text)
    raw = str(text or "").strip()
    if not raw:
        raise ResearchCycleSchemaError("empty model output")
    match = _FENCE_RE.search(raw)
    candidate = match.group(1) if match else raw
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ResearchCycleSchemaError("no JSON object in model output")
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ResearchCycleSchemaError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ResearchCycleSchemaError("model output must be a JSON object")
    return data


def _coerce_model_dict(result: Any) -> dict[str, Any]:
    """Normalize model_complete return / adapter text into a dict."""
    if isinstance(result, dict):
        # Adapter-style wrappers
        if "text" in result and not any(k in result for k in ("statement", "family", "verdict", "entry_rules")):
            return _extract_json_object(str(result.get("text") or ""))
        return dict(result)
    if isinstance(result, (list, tuple)) and result:
        # TradingModelAdapter.complete → (text, model_id)
        return _extract_json_object(str(result[0]))
    return _extract_json_object(str(result or ""))


def _require_fields(data: dict[str, Any], required: tuple[str, ...], *, role: str) -> dict[str, Any]:
    missing = [k for k in required if not str(data.get(k) or "").strip() and data.get(k) not in (0, False)]
    # allow nested strategy keys for author
    if role == "strategy_author" and "family" in required:
        family = data.get("family") or (data.get("entry_rules") or {}).get("kind")
        if family:
            data = {**data, "family": str(family)}
            missing = [k for k in missing if k != "family"]
    if missing:
        raise ResearchCycleSchemaError(f"{role} missing fields: {missing}")
    return data


def _contains_code_keys(blob: Any) -> bool:
    if isinstance(blob, dict):
        for k, v in blob.items():
            if str(k).lower() in _CODE_KEYS:
                return True
            if _contains_code_keys(v):
                return True
    elif isinstance(blob, list):
        return any(_contains_code_keys(x) for x in blob)
    return False


def _spec_content_hash(spec: dict[str, Any]) -> str:
    entry = dict(spec.get("entry_rules") or {})
    exit_rules = dict(spec.get("exit_rules") or {})
    parameters = dict(spec.get("parameters") or {})
    risk_rules = dict(spec.get("risk_rules") or {"max_position_pct": 25})
    tfs = list(spec.get("required_timeframes") or entry.get("required_timeframes") or ["1h"])
    return strategy_content_hash(
        parameters=parameters,
        entry_rules=entry,
        exit_rules=exit_rules,
        risk_rules=risk_rules,
        required_timeframes=[str(t) for t in tfs],
        brain_dependencies=list(spec.get("brain_dependencies") or []),
    )


def deduplicate_candidate_specs(
    specs: list[dict[str, Any]],
    *,
    existing_hashes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (novel, duplicates) using strategy_content_hash."""
    seen: set[str] = set(existing_hashes or ())
    novel: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for raw in specs:
        spec = dict(raw or {})
        try:
            ch = str(spec.get("content_hash") or _spec_content_hash(spec))
        except Exception as exc:  # noqa: BLE001
            duplicates.append({**spec, "duplicate": True, "reason": f"hash_error:{exc}"})
            continue
        spec = {**spec, "content_hash": ch}
        if ch in seen:
            duplicates.append({**spec, "duplicate": True, "reason": "content_hash_seen"})
            continue
        seen.add(ch)
        novel.append(spec)
    return novel, duplicates


def _validate_dsl_spec(spec: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate a candidate strategy dict; reject arbitrary Python / code keys."""
    if _contains_code_keys(spec):
        return False, "arbitrary code keys forbidden in strategy spec", None
    family = str(spec.get("family") or (spec.get("entry_rules") or {}).get("kind") or "").strip()
    templates = family_templates()
    if not family:
        return False, "missing strategy family", None
    if family not in templates and get_family(family) is None:
        return False, f"unsupported family {family!r}", None

    entry = dict(spec.get("entry_rules") or {})
    exit_rules = dict(spec.get("exit_rules") or {})
    parameters = dict(spec.get("parameters") or {})
    risk_rules = dict(spec.get("risk_rules") or {"max_position_pct": 25})

    # Fill from family template when author omitted structure
    if not entry or not entry.get("kind"):
        tpl = templates.get(family) or {}
        entry = dict(tpl.get("entry_rules") or entry)
        exit_rules = dict(tpl.get("exit_rules") or exit_rules)
        parameters = {**dict(tpl.get("parameters") or {}), **parameters}

    entry.setdefault("kind", family)
    entry.setdefault("version", 3)
    if "parameters" not in entry:
        entry["parameters"] = dict(parameters)

    try:
        parsed = parse_strategy_spec(entry, exit_rules=exit_rules, parameters=parameters)
        ok, reason = validate_strategy_spec(parsed)
    except Exception as exc:  # noqa: BLE001
        return False, f"parse_error:{exc}", None
    if not ok:
        return False, reason, None

    normalized = {
        "family": family,
        "entry_rules": entry,
        "exit_rules": exit_rules or {"kind": family},
        "parameters": parameters,
        "risk_rules": risk_rules,
    }
    normalized["content_hash"] = _spec_content_hash(normalized)
    return True, "ok", normalized


def _call_structured(
    model_complete: ModelCompleteFn,
    messages: list[dict[str, str]],
    *,
    role: str,
    required: tuple[str, ...],
    budget: dict[str, int],
    model_budget: int,
) -> dict[str, Any]:
    """Call → schema check → one repair → honest failure. Counts against budget."""
    if budget["used"] >= model_budget:
        raise ResearchCycleSchemaError(f"MODEL_BUDGET_EXHAUSTED: {model_budget} calls")
    budget["used"] += 1
    first = _coerce_model_dict(model_complete(messages, role))
    try:
        return _require_fields(first, required, role=role)
    except ResearchCycleSchemaError as err:
        if budget["used"] >= model_budget:
            raise ResearchCycleSchemaError(f"schema repair budget exhausted ({err})") from err
        repair_msgs = list(messages) + [
            {"role": "assistant", "content": json.dumps(first, sort_keys=True)[:4000]},
            {
                "role": "user",
                "content": (
                    f"Your previous answer violated the output schema: {err}. "
                    "Reply with ONLY a corrected JSON object, no prose."
                ),
            },
        ]
        budget["used"] += 1
        second = _coerce_model_dict(model_complete(repair_msgs, role))
        try:
            return _require_fields(second, required, role=role)
        except ResearchCycleSchemaError as err2:
            raise ResearchCycleSchemaError(
                f"schema repair failed: {err2} (first: {err})"
            ) from err2


def _perception_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    snap = dict(snapshot or {})
    regime = (
        snap.get("regime")
        or snap.get("regime_label")
        or (snap.get("features") or {}).get("regime")
        or "unknown"
    )
    symbols = list(snap.get("symbols") or snap.get("universe") or [])
    timeframe = str(snap.get("timeframe") or snap.get("bar_timeframe") or "1h")
    features = dict(snap.get("features") or {})
    return {
        "regime": str(regime),
        "symbols": symbols,
        "timeframe": timeframe,
        "features": features,
        "volatility": snap.get("volatility") or features.get("volatility"),
        "trend": snap.get("trend") or features.get("trend"),
        "as_of": snap.get("as_of") or "",
        "source": "perception_snapshot",
    }


def _pick_family(
    *,
    perception: dict[str, Any],
    family_preferences: list[str] | None,
    objective_text: str,
) -> str:
    generatable = list(research_generatable_families())
    prefs = [str(p).strip() for p in (family_preferences or []) if str(p).strip()]
    for p in prefs:
        if p in generatable:
            return p
    regime = str(perception.get("regime") or "").lower()
    trend = str(perception.get("trend") or "").lower()
    vol = str(perception.get("volatility") or "").lower()
    obj = (objective_text or "").lower()
    if any(k in obj for k in ("mean reversion", "mean_reversion", "revert", "z-score", "zscore")):
        if "mean_reversion" in generatable:
            return "mean_reversion"
    if any(k in obj for k in ("breakout", "donchian")):
        if "breakout" in generatable:
            return "breakout"
    if any(k in obj for k in ("rsi",)):
        if "rsi" in generatable:
            return "rsi"
    if "mean" in regime or "range" in regime or "revert" in regime:
        if "mean_reversion" in generatable:
            return "mean_reversion"
    if "high" in vol or "expand" in vol:
        if "breakout" in generatable:
            return "breakout"
        if "volatility" in generatable:
            return "volatility"
    if "up" in trend or "down" in trend or "trend" in regime:
        if "ma_cross" in generatable:
            return "ma_cross"
        if "momentum" in generatable:
            return "momentum"
    return generatable[0] if generatable else "ma_cross"


def _heuristic_hypothesis(
    *,
    perception: dict[str, Any],
    objective_text: str,
    family: str,
    prior_lessons: list[dict[str, Any]] | None,
    lab_id: str | None,
    learning_run_id: str | None,
    as_of: str,
    now: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    regime = perception.get("regime") or "unknown"
    symbols = list(perception.get("symbols") or [])
    statement = (
        objective_text.strip()
        or f"In regime={regime}, a {family} strategy may show positive net expectancy after costs."
    )
    lessons = list(prior_lessons or [])
    failure_modes = ["cost_sensitivity", "regime_brittleness", "overfit_to_train"]
    for lesson in lessons[:5]:
        claim = str(lesson.get("claim") or lesson.get("lesson") or "").strip()
        if claim:
            failure_modes.append(claim[:200])
    hyp = new_research_hypothesis(
        statement=statement,
        mechanism=f"Heuristic regime-conditioned {family} edge under {regime}.",
        rationale_summary=(
            f"Deterministic offline proposal from perception (regime={regime}, "
            f"family={family}); model_complete was not supplied."
        ),
        created_at=now or as_of or "",
        as_of=as_of or now or "",
        lab_id=lab_id,
        learning_run_id=learning_run_id,
        scope=ResearchHypothesisScope(
            symbols=symbols,
            timeframes=[str(perception.get("timeframe") or "1h")],
            regime_scope=[str(regime)],
        ),
        expected_edge="Positive net expectancy after fees/slippage within drawdown constraints.",
        expected_failure_modes=failure_modes[:12],
        falsification_criteria=[
            "net_expectancy_after_costs <= 0 on validation",
            "max_drawdown exceeds acceptance policy",
            "fails regime matrix or robustness gates",
        ],
        evidence_refs=list(evidence_refs),
        strategy_family_preferences=[family],
        required_features=["ohlcv"],
        proposer_role=resolve_fleet_role(ResearchResponsibility.STRATEGY_RESEARCHER.value),
        trust="AGENT_PROPOSED",
        status="PROPOSED",
        metadata={"origin": "heuristic_research_cycle", "regime": regime},
    )
    return hyp.public_dict()


def _heuristic_critic(hypothesis: dict[str, Any] | None, perception: dict[str, Any]) -> dict[str, Any]:
    statement = str((hypothesis or {}).get("statement") or "")
    regime = str(perception.get("regime") or "unknown")
    return {
        "verdict": "weaken",
        "counterargument": (
            f"Heuristic critic: hypothesis may be regime-brittle under {regime}; "
            f"require cost-aware validation before promotion. claim={statement[:240]}"
        ),
        "riskFlags": ["regime_brittleness", "unvalidated_heuristic"],
        "confidenceAdjustment": -0.1,
        "role": resolve_fleet_role(ResearchResponsibility.CRITIC.value),
    }


def _family_proposal(family: str, *, hypothesis_id: str | None = None) -> dict[str, Any]:
    templates = family_templates()
    tpl = templates.get(family) or templates.get("ma_cross") or next(iter(templates.values()))
    spec = {
        "family": family if family in templates else str(tpl.get("entry_rules", {}).get("kind") or "ma_cross"),
        "entry_rules": copy.deepcopy(tpl.get("entry_rules") or {}),
        "exit_rules": copy.deepcopy(tpl.get("exit_rules") or {}),
        "parameters": copy.deepcopy(tpl.get("parameters") or {}),
        "risk_rules": {"max_position_pct": 25},
    }
    if hypothesis_id:
        spec["hypothesis_id"] = hypothesis_id
    ok, reason, normalized = _validate_dsl_spec(spec)
    if not ok or normalized is None:
        raise ResearchCycleSchemaError(f"heuristic family template invalid: {reason}")
    if hypothesis_id:
        normalized["hypothesis_id"] = hypothesis_id
    normalized["origin"] = "heuristic_family_template"
    return normalized


def _resolve_chart_status(
    *,
    enable_chart_vision: bool,
    chart_render_result: dict[str, Any] | None,
    vision_complete: VisionCompleteFn | None,
    vision_capability_status: str,
) -> tuple[str, dict[str, Any] | None]:
    if not enable_chart_vision:
        return "SKIPPED", None
    status = str(vision_capability_status or "UNMEASURED").upper()
    if status in {"UNAVAILABLE", "UNSUPPORTED", "DISABLED"}:
        return "UNAVAILABLE", {
            "status": "UNAVAILABLE",
            "reason": "vision_capability_unavailable",
            "vision_capability_status": status,
        }
    if chart_render_result is None and vision_complete is None:
        if status == "MEASURED":
            return "UNMEASURED", {
                "status": "UNMEASURED",
                "reason": "no_chart_render_or_vision_fn",
            }
        return status if status in {"UNMEASURED", "MEASURED", "UNAVAILABLE", "SKIPPED"} else "UNMEASURED", {
            "status": status,
            "reason": "chart_vision_not_supplied",
        }
    observation: dict[str, Any] = {
        "status": "MEASURED" if chart_render_result else status,
        "render": dict(chart_render_result or {}),
    }
    if vision_complete is not None and chart_render_result is not None:
        try:
            vision_out = vision_complete(
                [{"role": "user", "content": json.dumps(chart_render_result)[:8000]}],
                "chart_vision",
            )
            if isinstance(vision_out, dict):
                observation["vision"] = vision_out
            else:
                observation["vision_text"] = str(vision_out)[:4000]
            observation["status"] = "MEASURED"
        except Exception as exc:  # noqa: BLE001
            observation["vision_error"] = str(exc)[:200]
            observation["status"] = "UNAVAILABLE"
            return "UNAVAILABLE", observation
    return str(observation.get("status") or "MEASURED"), observation


def run_research_generation_cycle(
    *,
    perception_snapshot: dict[str, Any],
    prior_lessons: list[dict[str, Any]] | None = None,
    prior_hypotheses: list[dict[str, Any]] | None = None,
    objective_text: str = "",
    family_preferences: list[str] | None = None,
    model_complete: ModelCompleteFn | None = None,
    model_budget: int = 6,
    enable_chart_vision: bool = False,
    chart_render_result: dict[str, Any] | None = None,
    vision_complete: VisionCompleteFn | None = None,
    vision_capability_status: str = "UNMEASURED",
    lab_id: str | None = None,
    learning_run_id: str | None = None,
    as_of: str = "",
    now: str = "",
) -> ResearchCycleResult:
    """Run PERCEPTION → hypothesis → critic → author (bounded DSL) generation cycle.

    Returns validated author proposals for MarketSim evaluation. Does not create
    private model clients — inject ``model_complete`` or use deterministic heuristics.
    """
    perception = _perception_summary(perception_snapshot)
    if as_of and not perception.get("as_of"):
        perception["as_of"] = as_of

    evidence_refs: list[str] = []
    for ref in list((perception_snapshot or {}).get("evidence_refs") or []):
        if ref and str(ref) not in evidence_refs:
            evidence_refs.append(str(ref))
    for hyp in prior_hypotheses or []:
        for ref in list(hyp.get("evidence_refs") or []):
            if ref and str(ref) not in evidence_refs:
                evidence_refs.append(str(ref))
    for lesson in prior_lessons or []:
        for ref in list(lesson.get("evidence_refs") or lesson.get("evidenceRefs") or []):
            if ref and str(ref) not in evidence_refs:
                evidence_refs.append(str(ref))

    public_events: list[dict[str, Any]] = [
        {
            "type": "research_cycle.perception",
            "role": resolve_fleet_role(ResearchResponsibility.MARKET_REGIME_ANALYST.value),
            "regime": perception.get("regime"),
            "as_of": perception.get("as_of") or as_of,
        }
    ]

    chart_status, chart_observation = _resolve_chart_status(
        enable_chart_vision=enable_chart_vision,
        chart_render_result=chart_render_result,
        vision_complete=vision_complete,
        vision_capability_status=vision_capability_status,
    )
    if chart_status == "UNAVAILABLE":
        public_events.append(
            {
                "type": "research_cycle.chart",
                "chart_status": chart_status,
                "note": "continuing_with_numeric_perception",
            }
        )
    elif enable_chart_vision:
        public_events.append({"type": "research_cycle.chart", "chart_status": chart_status})

    budget = {"used": 0}
    conflicts: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    author_proposals: list[dict[str, Any]] = []
    hypothesis_public: dict[str, Any] | None = None
    critic_public: dict[str, Any] | None = None

    family = _pick_family(
        perception=perception,
        family_preferences=family_preferences,
        objective_text=objective_text,
    )

    analyst_role = resolve_fleet_role(ResearchResponsibility.MARKET_REGIME_ANALYST.value)
    researcher_role = resolve_fleet_role(ResearchResponsibility.STRATEGY_RESEARCHER.value)
    critic_role = resolve_fleet_role(ResearchResponsibility.CRITIC.value)
    author_role = "strategy_author"  # orchestra-native authoring role

    if model_complete is None:
        hypothesis_public = _heuristic_hypothesis(
            perception=perception,
            objective_text=objective_text,
            family=family,
            prior_lessons=prior_lessons,
            lab_id=lab_id,
            learning_run_id=learning_run_id,
            as_of=as_of or str(perception.get("as_of") or ""),
            now=now or as_of or "",
            evidence_refs=evidence_refs,
        )
        public_events.append(
            {
                "type": "research_cycle.hypothesis",
                "role": researcher_role,
                "hypothesis_id": hypothesis_public.get("hypothesis_id"),
                "mode": "heuristic",
            }
        )
        critic_public = _heuristic_critic(hypothesis_public, perception)
        public_events.append(
            {"type": "research_cycle.critic", "role": critic_role, "verdict": critic_public.get("verdict")}
        )
        try:
            proposal = _family_proposal(
                family,
                hypothesis_id=str(hypothesis_public.get("hypothesis_id") or "") or None,
            )
            author_proposals.append(proposal)
            public_events.append(
                {
                    "type": "research_cycle.author",
                    "role": author_role,
                    "family": proposal.get("family"),
                    "content_hash": proposal.get("content_hash"),
                    "mode": "heuristic",
                }
            )
        except ResearchCycleSchemaError as exc:
            rejected.append({"family": family, "reason": str(exc), "stage": "heuristic_author"})
    else:
        # --- market / regime analyst ---
        try:
            analyst_out = _call_structured(
                model_complete,
                [
                    {
                        "role": "system",
                        "content": (
                            "You are the market regime analyst. Return ONLY JSON with keys: "
                            "regime (str), rationale (str), features (object). Public structured reasoning only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "perception": perception,
                                "objective": objective_text,
                                "prior_lessons": list(prior_lessons or [])[:8],
                                "chart_status": chart_status,
                                "chart_observation": chart_observation,
                            },
                            sort_keys=True,
                            default=str,
                        )[:12000],
                    },
                ],
                role=analyst_role,
                required=("regime",),
                budget=budget,
                model_budget=model_budget,
            )
            perception = {
                **perception,
                "regime": analyst_out.get("regime") or perception.get("regime"),
                "analyst_rationale": str(analyst_out.get("rationale") or "")[:2000],
                "analyst_features": dict(analyst_out.get("features") or {}),
            }
            family = _pick_family(
                perception=perception,
                family_preferences=family_preferences,
                objective_text=objective_text,
            )
            public_events.append(
                {"type": "research_cycle.analyst", "role": analyst_role, "regime": perception.get("regime")}
            )
        except ResearchCycleSchemaError as exc:
            conflicts.append({"stage": "analyst", "error": str(exc)})
            public_events.append({"type": "research_cycle.analyst_failed", "error": str(exc)[:300]})

        # --- hypothesis proposal (strategy researcher) ---
        try:
            hyp_raw = _call_structured(
                model_complete,
                [
                    {
                        "role": "system",
                        "content": (
                            "You are the strategy researcher. Return ONLY JSON with keys: "
                            "statement, mechanism, rationale_summary, expected_edge, "
                            "expected_failure_modes (list), falsification_criteria (list), "
                            "strategy_family_preferences (list). No private chain-of-thought."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "perception": perception,
                                "objective": objective_text,
                                "family_hint": family,
                                "prior_hypotheses": list(prior_hypotheses or [])[:5],
                                "prior_lessons": list(prior_lessons or [])[:8],
                            },
                            sort_keys=True,
                            default=str,
                        )[:12000],
                    },
                ],
                role=researcher_role,
                required=HYPOTHESIS_REQUIRED,
                budget=budget,
                model_budget=model_budget,
            )
            prefs = list(hyp_raw.get("strategy_family_preferences") or family_preferences or [family])
            if prefs:
                family = _pick_family(
                    perception=perception,
                    family_preferences=[str(p) for p in prefs],
                    objective_text=objective_text,
                )
            hyp_obj = new_research_hypothesis(
                statement=str(hyp_raw.get("statement") or ""),
                mechanism=str(hyp_raw.get("mechanism") or ""),
                rationale_summary=str(hyp_raw.get("rationale_summary") or hyp_raw.get("rationale") or ""),
                created_at=now or as_of or "",
                as_of=as_of or now or "",
                lab_id=lab_id,
                learning_run_id=learning_run_id,
                scope=ResearchHypothesisScope(
                    symbols=list(perception.get("symbols") or []),
                    timeframes=[str(perception.get("timeframe") or "1h")],
                    regime_scope=[str(perception.get("regime") or "unknown")],
                ),
                expected_edge=str(hyp_raw.get("expected_edge") or ""),
                expected_failure_modes=list(hyp_raw.get("expected_failure_modes") or []),
                falsification_criteria=list(hyp_raw.get("falsification_criteria") or []),
                evidence_refs=list(evidence_refs),
                strategy_family_preferences=prefs or [family],
                required_features=list(hyp_raw.get("required_features") or ["ohlcv"]),
                proposer_role=researcher_role,
                trust="AGENT_PROPOSED",
                status="PROPOSED",
                metadata={"origin": "model_research_cycle"},
            )
            hypothesis_public = hyp_obj.public_dict()
            public_events.append(
                {
                    "type": "research_cycle.hypothesis",
                    "role": researcher_role,
                    "hypothesis_id": hypothesis_public.get("hypothesis_id"),
                    "mode": "model",
                }
            )
        except ResearchCycleSchemaError as exc:
            conflicts.append({"stage": "hypothesis", "error": str(exc)})
            # Fall back to heuristic so cycle can still emit a DSL candidate
            hypothesis_public = _heuristic_hypothesis(
                perception=perception,
                objective_text=objective_text,
                family=family,
                prior_lessons=prior_lessons,
                lab_id=lab_id,
                learning_run_id=learning_run_id,
                as_of=as_of or str(perception.get("as_of") or ""),
                now=now or as_of or "",
                evidence_refs=evidence_refs,
            )
            hypothesis_public["metadata"] = {
                **dict(hypothesis_public.get("metadata") or {}),
                "model_failed": str(exc)[:300],
                "fallback": "heuristic",
            }
            public_events.append(
                {
                    "type": "research_cycle.hypothesis_fallback",
                    "error": str(exc)[:300],
                    "hypothesis_id": hypothesis_public.get("hypothesis_id"),
                }
            )

        # --- critic falsification ---
        try:
            critic_raw = _call_structured(
                model_complete,
                [
                    {
                        "role": "system",
                        "content": (
                            "You are the strategy critic. Falsify or weaken the hypothesis. "
                            "Return ONLY JSON with keys: verdict (support|weaken|reject), "
                            "counterargument (str), riskFlags (list), confidenceAdjustment (float)."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"hypothesis": hypothesis_public, "perception": perception},
                            sort_keys=True,
                            default=str,
                        )[:12000],
                    },
                ],
                role=critic_role,
                required=CRITIC_REQUIRED,
                budget=budget,
                model_budget=model_budget,
            )
            verdict = str(critic_raw.get("verdict") or "weaken").lower()
            if verdict not in {"support", "weaken", "reject"}:
                verdict = "weaken"
            critic_public = {
                "verdict": verdict,
                "counterargument": str(critic_raw.get("counterargument") or "")[:4000],
                "riskFlags": list(critic_raw.get("riskFlags") or critic_raw.get("risk_flags") or []),
                "confidenceAdjustment": float(critic_raw.get("confidenceAdjustment") or 0.0),
                "role": critic_role,
            }
            public_events.append(
                {"type": "research_cycle.critic", "role": critic_role, "verdict": verdict}
            )
            if verdict == "reject":
                conflicts.append(
                    {
                        "stage": "critic",
                        "verdict": "reject",
                        "counterargument": critic_public.get("counterargument"),
                    }
                )
        except ResearchCycleSchemaError as exc:
            conflicts.append({"stage": "critic", "error": str(exc)})
            critic_public = _heuristic_critic(hypothesis_public, perception)
            critic_public["metadata"] = {"model_failed": str(exc)[:300], "fallback": "heuristic"}

        # --- strategy author emits bounded DSL (skip emit on hard reject unless budget allows refine) ---
        skip_author = bool(critic_public and critic_public.get("verdict") == "reject")
        if skip_author:
            rejected.append(
                {
                    "stage": "author_skipped",
                    "reason": "critic_rejected_hypothesis",
                    "counterargument": (critic_public or {}).get("counterargument"),
                }
            )
            public_events.append({"type": "research_cycle.author_skipped", "reason": "critic_reject"})
        else:
            try:
                author_raw = _call_structured(
                    model_complete,
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are the strategy author. Emit a bounded Strategy DSL spec ONLY. "
                                "Return JSON with keys: family, entry_rules, exit_rules, parameters, risk_rules. "
                                "No eval/exec/code keys. family must be a supported research family."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "hypothesis": hypothesis_public,
                                    "critic": critic_public,
                                    "family_hint": family,
                                    "allowed_families": list(research_generatable_families()),
                                    "templates": {
                                        k: family_templates()[k]
                                        for k in list(research_generatable_families())[:8]
                                    },
                                },
                                sort_keys=True,
                                default=str,
                            )[:14000],
                        },
                    ],
                    role=author_role,
                    required=AUTHOR_REQUIRED,
                    budget=budget,
                    model_budget=model_budget,
                )
                ok, reason, normalized = _validate_dsl_spec(author_raw)
                if ok and normalized is not None:
                    hid = str((hypothesis_public or {}).get("hypothesis_id") or "")
                    if hid:
                        normalized["hypothesis_id"] = hid
                    normalized["origin"] = "model_strategy_author"
                    author_proposals.append(normalized)
                    public_events.append(
                        {
                            "type": "research_cycle.author",
                            "role": author_role,
                            "family": normalized.get("family"),
                            "content_hash": normalized.get("content_hash"),
                            "mode": "model",
                        }
                    )
                else:
                    rejected.append(
                        {"stage": "author_validate", "reason": reason, "raw_family": author_raw.get("family")}
                    )
                    # One family-template repair path (not a second model call)
                    fallback = _family_proposal(
                        family,
                        hypothesis_id=str((hypothesis_public or {}).get("hypothesis_id") or "") or None,
                    )
                    fallback["origin"] = "author_validate_fallback_template"
                    fallback["reject_reason"] = reason
                    author_proposals.append(fallback)
                    public_events.append(
                        {
                            "type": "research_cycle.author_fallback",
                            "reason": reason,
                            "family": fallback.get("family"),
                        }
                    )
            except ResearchCycleSchemaError as exc:
                rejected.append({"stage": "author", "reason": str(exc)})
                try:
                    fallback = _family_proposal(
                        family,
                        hypothesis_id=str((hypothesis_public or {}).get("hypothesis_id") or "") or None,
                    )
                    fallback["origin"] = "author_model_failed_fallback_template"
                    author_proposals.append(fallback)
                    public_events.append(
                        {
                            "type": "research_cycle.author_fallback",
                            "error": str(exc)[:300],
                            "family": fallback.get("family"),
                        }
                    )
                except ResearchCycleSchemaError as exc2:
                    conflicts.append({"stage": "author_fallback", "error": str(exc2)})

    # Dedup proposals (and against prior hypothesis-linked hashes if present)
    existing_hashes: set[str] = set()
    for hyp in prior_hypotheses or []:
        for h in list(hyp.get("candidate_hashes") or []):
            existing_hashes.add(str(h))
    novel, dups = deduplicate_candidate_specs(author_proposals, existing_hashes=existing_hashes or None)
    for d in dups:
        rejected.append({**d, "stage": "dedup"})
    author_proposals = novel

    if hypothesis_public and hypothesis_public.get("evidence_refs"):
        for ref in hypothesis_public["evidence_refs"]:
            if ref and str(ref) not in evidence_refs:
                evidence_refs.append(str(ref))

    return ResearchCycleResult(
        perception=perception,
        hypothesis=hypothesis_public,
        critic=critic_public,
        author_proposals=author_proposals,
        rejected_proposals=rejected,
        conflicts=conflicts,
        chart_observation=chart_observation,
        chart_status=chart_status,
        evidence_refs=evidence_refs,
        model_calls_used=int(budget["used"]),
        public_events=public_events,
        metadata={
            "lab_id": lab_id,
            "learning_run_id": learning_run_id,
            "as_of": as_of or perception.get("as_of") or "",
            "now": now,
            "model_budget": model_budget,
            "family_preferences": list(family_preferences or []),
        },
    )


__all__ = [
    "ResearchCycleResult",
    "ResearchCycleSchemaError",
    "deduplicate_candidate_specs",
    "run_research_generation_cycle",
]
