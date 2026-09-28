"""Structured candidate explainability — evidence only, no LLM storytelling.

Returns answers from persisted candidate / learning-run fields: proposal reason,
hypothesis binding, parents, method, critic notes, killing split, regime failures,
cost sensitivity, and sealed/qualification blockers.
"""

from __future__ import annotations

from typing import Any


_ACTIVE_KILL_SPLITS = ("TRAIN", "VAL", "ROBUSTNESS", "SEALED")


def explain_candidate(
    store: Any,
    *,
    candidate_id: str | None = None,
    candidate: dict[str, Any] | None = None,
    learning_run: dict[str, Any] | None = None,
    learning_run_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured, evidence-backed explanation for one candidate.

    Prefer an explicit ``candidate`` dict; otherwise resolve via ``candidate_id``
    against ``learning_run`` / store. Never invent critic notes or KPIs.
    """
    run = _resolve_learning_run(store, learning_run=learning_run, learning_run_id=learning_run_id)
    resolved = _resolve_candidate(
        store,
        candidate=candidate,
        candidate_id=candidate_id,
        learning_run=run,
    )
    if resolved is None:
        return {
            "present": False,
            "candidateId": candidate_id,
            "error": "CANDIDATE_NOT_FOUND",
            "liveTrading": "BLOCKED",
            "truth": {
                "evidence_only": True,
                "no_llm_storytelling": True,
                "live_trading": "BLOCKED",
            },
        }

    meta = dict(resolved.get("metadata") or {})
    stage_results = dict(meta.get("stage_results") or {})
    hypothesis_id = (
        resolved.get("hypothesis_id")
        or meta.get("hypothesis_id")
        or (run or {}).get("metadata", {}).get("hypothesis_id")
    )
    parents = list(resolved.get("parent_refs") or meta.get("parent_refs") or [])
    method = str(resolved.get("proposal_method") or meta.get("proposal_method") or "") or None
    why_proposed = _why_proposed(resolved, meta, method=method)
    critic_notes = _critic_notes(meta)
    killed = _split_that_killed(stage_results, status=str(resolved.get("status") or ""))
    regime_failures = _regime_failures(meta, stage_results)
    cost_sensitivity = _cost_sensitivity(stage_results)
    blockers = _sealed_qualification_blockers(resolved, meta, stage_results, run=run)

    return {
        "present": True,
        "candidateId": resolved.get("candidate_id") or candidate_id,
        "strategyId": resolved.get("strategy_id"),
        "strategyVersion": resolved.get("strategy_version"),
        "generation": resolved.get("generation"),
        "status": resolved.get("status"),
        "whyProposed": why_proposed,
        "hypothesisId": hypothesis_id,
        "hypothesis": (str(resolved.get("hypothesis") or "").strip() or None),
        "parents": parents,
        "method": method,
        "mutations": list(resolved.get("mutations") or meta.get("mutations") or []),
        "criticNotes": critic_notes,
        "splitThatKilled": killed,
        "regimeFailures": regime_failures,
        "costSensitivity": cost_sensitivity,
        "sealedQualificationBlockers": blockers,
        "stageResults": {
            key: _public_stage(stage_results.get(key))
            for key in _ACTIVE_KILL_SPLITS
            if key in stage_results
        },
        "learningRunId": (run or {}).get("learning_run_id") or learning_run_id,
        "liveTrading": "BLOCKED",
        "truth": {
            "evidence_only": True,
            "no_llm_storytelling": True,
            "from_persisted_fields": True,
            "live_trading": "BLOCKED",
            "historical_profitability_is_not_future_guarantee": True,
        },
    }


def _resolve_learning_run(
    store: Any,
    *,
    learning_run: dict[str, Any] | None,
    learning_run_id: str | None,
) -> dict[str, Any] | None:
    if isinstance(learning_run, dict) and learning_run:
        return learning_run
    if not learning_run_id or store is None:
        return None
    getter = getattr(store, "get_learning_run", None)
    if not callable(getter):
        return None
    try:
        row = getter(str(learning_run_id))
    except Exception:  # noqa: BLE001
        return None
    return row if isinstance(row, dict) else None


def _resolve_candidate(
    store: Any,
    *,
    candidate: dict[str, Any] | None,
    candidate_id: str | None,
    learning_run: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(candidate, dict) and candidate:
        out = dict(candidate)
        if candidate_id and not out.get("candidate_id"):
            out["candidate_id"] = candidate_id
        return out
    cid = str(candidate_id or "").strip()
    if not cid:
        return None
    if learning_run:
        for row in learning_run.get("candidates") or []:
            if isinstance(row, dict) and str(row.get("candidate_id") or "") == cid:
                return dict(row)
    # Optional store helpers — never invent rows.
    if store is not None:
        for attr in ("get_learning_candidate", "get_candidate"):
            getter = getattr(store, attr, None)
            if callable(getter):
                try:
                    row = getter(cid)
                except Exception:  # noqa: BLE001
                    row = None
                if isinstance(row, dict):
                    return dict(row)
    return None


def _why_proposed(
    candidate: dict[str, Any],
    meta: dict[str, Any],
    *,
    method: str | None,
) -> dict[str, Any]:
    hypothesis = str(candidate.get("hypothesis") or "").strip()
    rationale = str(meta.get("rationale") or meta.get("proposal_rationale") or "").strip()
    family = candidate.get("family") or meta.get("family")
    parts: list[str] = []
    if method:
        parts.append(f"proposal_method={method}")
    if family:
        parts.append(f"family={family}")
    if hypothesis:
        parts.append(f"hypothesis={hypothesis[:300]}")
    if rationale:
        parts.append(f"rationale={rationale[:300]}")
    if not parts:
        return {
            "summary": None,
            "measurement": "UNMEASURED",
            "note": "no_proposal_rationale_recorded",
        }
    return {
        "summary": "; ".join(parts),
        "measurement": "MEASURED",
        "note": "from_candidate_fields",
        "family": family,
        "hypothesis": hypothesis or None,
        "rationale": rationale or None,
    }


def _critic_notes(meta: dict[str, Any]) -> list[dict[str, Any]]:
    raw = meta.get("critic_notes") or meta.get("criticNotes") or meta.get("critiques") or []
    out: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"text": item.strip(), "source": "metadata.critic_notes"})
        elif isinstance(item, dict):
            text = str(
                item.get("text")
                or item.get("note")
                or item.get("counterargument")
                or item.get("summary")
                or ""
            ).strip()
            if text:
                out.append(
                    {
                        "text": text,
                        "verdict": item.get("verdict"),
                        "role": item.get("role"),
                        "source": "metadata.critic_notes",
                    }
                )
    return out


def _split_that_killed(
    stage_results: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    for split in _ACTIVE_KILL_SPLITS:
        stage = stage_results.get(split)
        if not isinstance(stage, dict):
            continue
        accepted = stage.get("accepted")
        failed = str(stage.get("status") or "").lower() in {"failed", "rejected", "killed"}
        if accepted is False or failed:
            reasons = []
            if isinstance(stage.get("acceptance"), dict):
                reasons.extend(list((stage.get("acceptance") or {}).get("failures") or []))
                reasons.extend(list((stage.get("acceptance") or {}).get("blockers") or []))
            if stage.get("error"):
                reasons.append(str(stage.get("error")))
            if isinstance(stage.get("verdict"), dict):
                reasons.extend(list((stage.get("verdict") or {}).get("failures") or []))
            return {
                "split": split,
                "status": stage.get("status"),
                "accepted": accepted,
                "reasons": [r for r in reasons if r][:12],
                "measurement": "MEASURED",
            }
    if status and status.upper() in {"REJECTED", "FAILED", "KILLED", "ELIMINATED"}:
        return {
            "split": None,
            "status": status,
            "accepted": False,
            "reasons": ["candidate_status_terminal_without_stage_kill_record"],
            "measurement": "UNMEASURED",
            "note": "status_implies_failure_but_no_stage_result",
        }
    return {
        "split": None,
        "status": None,
        "accepted": None,
        "reasons": [],
        "measurement": "EMPTY",
        "note": "no_killing_split_recorded",
    }


def _regime_failures(meta: dict[str, Any], stage_results: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    regime = meta.get("regime_failures") or meta.get("regimeFailures") or []
    if isinstance(regime, dict):
        for name, detail in regime.items():
            out.append({"regime": name, "detail": detail, "source": "metadata.regime_failures"})
    elif isinstance(regime, list):
        for item in regime:
            if isinstance(item, dict):
                out.append({**item, "source": item.get("source") or "metadata.regime_failures"})
            elif item:
                out.append({"regime": str(item), "source": "metadata.regime_failures"})
    # Robustness verdict may carry regime labels
    robust = stage_results.get("ROBUSTNESS") if isinstance(stage_results.get("ROBUSTNESS"), dict) else {}
    verdict = robust.get("verdict") if isinstance(robust.get("verdict"), dict) else {}
    for result in verdict.get("results") or []:
        if not isinstance(result, dict):
            continue
        if result.get("accepted") is False and (
            "regime" in str(result.get("perturbation_id") or "").lower()
            or result.get("regime")
        ):
            out.append(
                {
                    "regime": result.get("regime") or result.get("perturbation_id"),
                    "detail": result.get("reason") or result.get("error"),
                    "source": "stage_results.ROBUSTNESS",
                }
            )
    return out[:20]


def _cost_sensitivity(stage_results: dict[str, Any]) -> dict[str, Any]:
    robust = stage_results.get("ROBUSTNESS") if isinstance(stage_results.get("ROBUSTNESS"), dict) else {}
    if not robust:
        return {"measurement": "UNMEASURED", "note": "no_robustness_stage", "rows": []}
    verdict = robust.get("verdict") if isinstance(robust.get("verdict"), dict) else {}
    rows: list[dict[str, Any]] = []
    for result in verdict.get("results") or []:
        if not isinstance(result, dict):
            continue
        pert = str(result.get("perturbation_id") or result.get("id") or "")
        if any(token in pert.lower() for token in ("cost", "fee", "slip", "spread")):
            rows.append(
                {
                    "perturbationId": pert,
                    "accepted": result.get("accepted"),
                    "metrics": result.get("metrics"),
                    "reason": result.get("reason") or result.get("error"),
                }
            )
    if not rows and robust.get("accepted") is not None:
        return {
            "measurement": "MEASURED",
            "accepted": robust.get("accepted"),
            "note": "robustness_present_without_labeled_cost_rows",
            "rows": [],
        }
    if not rows:
        return {"measurement": "EMPTY", "note": "no_cost_perturbation_rows", "rows": []}
    return {"measurement": "MEASURED", "accepted": robust.get("accepted"), "rows": rows}


def _sealed_qualification_blockers(
    candidate: dict[str, Any],
    meta: dict[str, Any],
    stage_results: dict[str, Any],
    *,
    run: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    sealed = stage_results.get("SEALED") if isinstance(stage_results.get("SEALED"), dict) else {}
    if sealed:
        if sealed.get("accepted") is False:
            blockers.append(
                {
                    "kind": "SEALED_FAILED",
                    "detail": sealed.get("error") or sealed.get("reason") or "sealed_not_accepted",
                    "source": "stage_results.SEALED",
                }
            )
        if sealed.get("status") == "failed":
            blockers.append(
                {
                    "kind": "SEALED_STATUS_FAILED",
                    "detail": sealed.get("error") or "sealed_stage_failed",
                    "source": "stage_results.SEALED",
                }
            )
    run_meta = dict((run or {}).get("metadata") or {})
    if run_meta.get("qualification_required") and not run_meta.get("institutional_qualified"):
        blockers.append(
            {
                "kind": "QUALIFICATION_REQUIRED",
                "detail": run_meta.get("note") or "institutional_qualified_false",
                "source": "learning_run.metadata",
            }
        )
    if run_meta.get("ready_for_shadow") is False:
        blockers.append(
            {
                "kind": "NOT_READY_FOR_SHADOW",
                "detail": "ready_for_shadow=false",
                "source": "learning_run.metadata",
            }
        )
    for key in ("qualification_blockers", "sealed_blockers", "blockers"):
        raw = meta.get(key) or run_meta.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    blockers.append({**item, "source": item.get("source") or f"metadata.{key}"})
                elif item:
                    blockers.append({"kind": str(item), "source": f"metadata.{key}"})
    # Deduplicate by kind+detail
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in blockers:
        token = f"{item.get('kind')}|{item.get('detail')}"
        if token in seen:
            continue
        seen.add(token)
        unique.append(item)
    return unique[:20]


def _public_stage(stage: Any) -> dict[str, Any] | None:
    if not isinstance(stage, dict):
        return None
    return {
        "status": stage.get("status"),
        "accepted": stage.get("accepted"),
        "fitnessScore": stage.get("fitness_score"),
        "measurementStatus": stage.get("measurement_status") or stage.get("measurement"),
        "error": stage.get("error"),
    }
