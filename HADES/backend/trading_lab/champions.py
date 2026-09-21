"""Champion / challenger policy.

A Champion is the strongest currently *qualified* strategy for a scope. Development
performance alone never installs a Champion. Admission walks the existing registry
lifecycle: development evidence → independent validation → optional sealed confirmation
→ optional prospective paper evidence.

Replacement is deterministic and recorded. Diversity is a tie-break, not a licence to
ignore a failed validation.
"""

from __future__ import annotations

from typing import Any, Sequence

from trading_lab.contracts import stable_hash

CHAMPION_REQUIRED_STATES = {"validated", "paper"}
WEAK_VERDICTS = {"fail", "insufficient_evidence"}


def scope_key(
    *,
    instrument_id: str | None = None,
    asset_family: str | None = None,
    timeframe: str | None = None,
    regime_key: str | None = None,
    objective: str = "net_after_costs",
) -> str:
    return stable_hash(
        {
            "instrument_id": instrument_id or "",
            "asset_family": asset_family or "",
            "timeframe": timeframe or "",
            "regime_key": regime_key or "",
            "objective": objective,
        }
    )[:24]


def evaluate_challenger(
    *,
    challenger: dict[str, Any],
    champion: dict[str, Any] | None,
    challenger_evaluations: Sequence[dict[str, Any]],
    champion_evaluations: Sequence[dict[str, Any]] = (),
    paper_evidence: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Decide whether a challenger may replace the champion.

    Returns a structured decision with reasons. Never promotes on development numbers.
    """
    reasons: list[str] = []
    status = str(challenger.get("status") or "draft")
    if status not in CHAMPION_REQUIRED_STATES:
        return _refuse(
            "lifecycle_not_qualified",
            reasons=[f"status={status}; champion eligibility requires validated or paper"],
            challenger=challenger,
            champion=champion,
        )

    validation = _best_eval(challenger_evaluations, splits={"validation"})
    development = _best_eval(challenger_evaluations, splits={"development"})
    sealed = _best_eval(challenger_evaluations, splits={"sealed_test"})
    paper = _best_eval(paper_evidence, splits={"prospective_paper"}) or _best_eval(
        challenger_evaluations, splits={"prospective_paper"}
    )

    if validation is None:
        return _refuse(
            "missing_independent_validation",
            reasons=["a challenger needs an independent validation evaluation; development is not enough"],
            challenger=challenger,
            champion=champion,
            development=development,
        )
    if validation.get("verdict") in WEAK_VERDICTS:
        return _refuse(
            "weak_validation_blocks_replacement",
            reasons=[f"validation verdict={validation.get('verdict')}"] + list(validation.get("verdict_reasons") or [])[:4],
            challenger=challenger,
            champion=champion,
            validation=validation,
        )
    if validation.get("evaluator_role") not in {"independent_validator", "automatic_gate"}:
        return _refuse(
            "validation_not_independent",
            reasons=[f"evaluator_role={validation.get('evaluator_role')}"],
            challenger=challenger,
            champion=champion,
            validation=validation,
        )

    if champion is None:
        return {
            "decision": "install",
            "reason": "no_existing_champion",
            "reasons": ["first qualified strategy for this scope"],
            "challenger_score": _score(validation, sealed, paper),
            "champion_score": None,
            "validation": _brief(validation),
            "sealed": _brief(sealed),
            "paper": _brief(paper),
            "diversity": None,
        }

    champ_val = _best_eval(champion_evaluations, splits={"validation"})
    champ_sealed = _best_eval(champion_evaluations, splits={"sealed_test"})
    champ_paper = _best_eval(champion_evaluations, splits={"prospective_paper"})
    if champ_val is None:
        return {
            "decision": "install",
            "reason": "incumbent_missing_validation",
            "reasons": ["the recorded champion no longer has independent validation evidence"],
            "challenger_score": _score(validation, sealed, paper),
            "champion_score": None,
            "validation": _brief(validation),
        }

    challenger_score = _score(validation, sealed, paper)
    champion_score = _score(champ_val, champ_sealed, champ_paper)
    diversity = diversity_bonus(challenger, champion)

    if challenger_score["total"] + diversity <= champion_score["total"]:
        reasons.append(
            f"challenger score {challenger_score['total']:.3f} + diversity {diversity:.3f} "
            f"does not beat champion {champion_score['total']:.3f}"
        )
        return _refuse(
            "incumbent_retained",
            reasons=reasons + challenger_score["reasons"] + champion_score["reasons"],
            challenger=challenger,
            champion=champion,
            validation=validation,
            challenger_score=challenger_score,
            champion_score=champion_score,
            diversity=diversity,
        )

    return {
        "decision": "replace",
        "reason": "stronger_validated_evidence",
        "reasons": [
            f"challenger {challenger_score['total']:.3f} + diversity {diversity:.3f} > champion {champion_score['total']:.3f}",
            *challenger_score["reasons"][:4],
        ],
        "challenger_score": challenger_score,
        "champion_score": champion_score,
        "diversity": diversity,
        "validation": _brief(validation),
        "sealed": _brief(sealed),
        "paper": _brief(paper),
    }


def _score(
    validation: dict[str, Any] | None,
    sealed: dict[str, Any] | None,
    paper: dict[str, Any] | None,
) -> dict[str, Any]:
    """Explicit weighted score over existing evaluation fields. Not a magic scalar for promotion.

    Weights are documented here so they can be audited:
    - validation net return 0.20
    - validation Sharpe 0.20 (0 if missing)
    - inverse drawdown 0.20
    - cost drag (lower better) 0.10
    - verdict pass bonus 0.15
    - sealed pass bonus 0.10
    - paper evidence bonus 0.05
    """
    reasons: list[str] = []
    metrics = _metrics(validation)
    net = float(metrics.get("net_return") or 0.0)
    sharpe = metrics.get("sharpe")
    drawdown = float(metrics.get("max_drawdown") or 0.0)
    costs = float(metrics.get("costs_paid") or 0.0)
    total = 0.20 * _clip(net, -1.0, 1.0)
    reasons.append(f"net_return={net:.4f}")
    if sharpe is None:
        reasons.append("sharpe_missing")
    else:
        total += 0.20 * _clip(float(sharpe) / 3.0, -1.0, 1.0)
        reasons.append(f"sharpe={sharpe:.3f}")
    total += 0.20 * (1.0 - _clip(drawdown, 0.0, 1.0))
    reasons.append(f"drawdown={drawdown:.4f}")
    total += 0.10 * (1.0 - _clip(costs / 10000.0, 0.0, 1.0))
    if (validation or {}).get("verdict") == "pass":
        total += 0.15
        reasons.append("validation_pass")
    if (sealed or {}).get("verdict") == "pass":
        total += 0.10
        reasons.append("sealed_pass")
    elif sealed:
        reasons.append(f"sealed={sealed.get('verdict')}")
    if paper:
        total += 0.05
        reasons.append("paper_evidence_present")
    return {"total": round(total, 4), "reasons": reasons, "components": {"net": net, "sharpe": sharpe, "drawdown": drawdown}}


def diversity_bonus(challenger: dict[str, Any], champion: dict[str, Any]) -> float:
    """Small bonus when the challenger specialises a different regime or family.

    A slightly weaker independent specialist can add portfolio value. This never
    overrides a failed validation; it only participates after qualification.
    """
    bonus = 0.0
    if (challenger.get("family") or challenger.get("strategy_family")) and (
        (challenger.get("family") or challenger.get("strategy_family"))
        != (champion.get("family") or champion.get("strategy_family"))
    ):
        bonus += 0.04
    c_params = challenger.get("params") or {}
    h_params = champion.get("params") or {}
    if c_params.get("regime_filter") and c_params.get("regime_filter") != h_params.get("regime_filter"):
        bonus += 0.04
    if c_params.get("no_trade_regimes") and c_params.get("no_trade_regimes") != h_params.get("no_trade_regimes"):
        bonus += 0.03
    return round(bonus, 4)


def _best_eval(rows: Sequence[dict[str, Any]], *, splits: set[str]) -> dict[str, Any] | None:
    matched = []
    for row in rows:
        used = set(row.get("splits_used") or [])
        split = row.get("split")
        if split:
            used.add(split)
        report = row.get("report") or {}
        for item in report.get("splits_used") or []:
            used.add(item)
        if used & splits or (not used and "validation" in splits and row.get("evidence_class") == "historical_evaluation"):
            matched.append(row)
    if not matched:
        return None
    order = {"pass": 2, "fail": 0, "insufficient_evidence": 1}
    matched.sort(key=lambda row: (order.get(str(row.get("verdict")), -1), str(row.get("created_at") or "")), reverse=True)
    return matched[0]


def _metrics(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    if not evaluation:
        return {}
    report = evaluation.get("report") or evaluation
    aggregate = report.get("aggregate") or {}
    if isinstance(aggregate, dict):
        return aggregate
    return {}


def _brief(evaluation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not evaluation:
        return None
    metrics = _metrics(evaluation)
    return {
        "report_id": evaluation.get("report_id"),
        "verdict": evaluation.get("verdict"),
        "evaluator_role": evaluation.get("evaluator_role"),
        "net_return": metrics.get("net_return"),
        "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown"),
    }


def _refuse(reason: str, *, reasons: list[str], **extra: Any) -> dict[str, Any]:
    payload = {"decision": "reject", "reason": reason, "reasons": reasons}
    payload.update(extra)
    return payload


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


__all__ = [
    "CHAMPION_REQUIRED_STATES",
    "diversity_bonus",
    "evaluate_challenger",
    "scope_key",
]
