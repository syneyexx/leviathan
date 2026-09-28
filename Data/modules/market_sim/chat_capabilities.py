"""READ-only MarketSim chat capabilities — composition over control-plane owners.

Chat may inspect lab / learning / lessons / paper-drift state. Mutations remain
behind ExecutionGateway worker capabilities. Live trading is never enabled.
"""

from __future__ import annotations

from typing import Any

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect

# Canonical READ capability ids (prefer these when extending chat tools).
CHAT_READ_CAPABILITY_IDS: tuple[str, ...] = (
    "market_sim.lab.status",
    "market_sim.research_lab.overview",
    "market_sim.lab.best_candidate",
    "market_sim.lab.hypotheses",
    "market_sim.lessons.summary",
    "market_sim.paper.drift",
)

_ACTIVE_HYPOTHESIS = frozenset({"PROPOSED", "TESTING", "UNDER_TEST", "FRAGILE"})

_BOUND_PLANE: Any | None = None


def bind_market_sim_plane(plane: Any | None) -> None:
    global _BOUND_PLANE
    _BOUND_PLANE = plane


def get_bound_market_sim_plane() -> Any | None:
    return _BOUND_PLANE


def register_market_sim_chat_capabilities(catalog: CapabilityCatalog) -> list[str]:
    """Register INLINE_SAFE READ capabilities into the shared CapabilityCatalog."""
    specs: list[tuple[str, str, str, str, list[str]]] = [
        (
            "market_sim.lab.status",
            "Research Lab Status",
            "Read Research Lab / learning-run status (READ-only). Live trading stays BLOCKED.",
            "market_sim_lab_status",
            ["lab_id"],
        ),
        (
            "market_sim.research_lab.overview",
            "Research Lab Overview",
            "Alias of market_sim.lab.status — lab + learning overview without mutations.",
            "market_sim_lab_status",
            ["lab_id"],
        ),
        (
            "market_sim.lab.best_candidate",
            "Research Lab Best Candidate",
            "Summarize best train/validation/qualified candidate from a lab learning run.",
            "market_sim_lab_best_candidate",
            ["lab_id"],
        ),
        (
            "market_sim.lab.hypotheses",
            "Research Lab Hypotheses",
            "List research hypotheses bound to a lab (public statements only).",
            "market_sim_lab_hypotheses",
            ["lab_id"],
        ),
        (
            "market_sim.lessons.summary",
            "Research Lab Lessons Summary",
            "Summarize AGENT_PROPOSED lessons for a lab — not proof of profitability.",
            "market_sim_lessons_summary",
            ["lab_id"],
        ),
        (
            "market_sim.paper.drift",
            "Paper-Forward Drift",
            "Read paper-deployment drift tickets / continual research hooks (READ-only).",
            "market_sim_paper_drift",
            [],
        ),
    ]
    registered: list[str] = []
    for cap_id, name, description, provider_ref, required in specs:
        if cap_id in catalog:
            registered.append(cap_id)
            continue
        props: dict[str, Any] = {
            "lab_id": {"type": "string"},
            "limit": {"type": "integer"},
            "deployment_id": {"type": "string"},
            "portfolio_id": {"type": "string"},
        }
        catalog.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=description,
                side_effects=(SideEffect.READ,),
                provider_kind=CapabilityProviderKind.FUNCTION,
                provider_ref=provider_ref,
                input_schema={
                    "type": "object",
                    "required": list(required),
                    "properties": props,
                },
                output_schema={"type": "object", "additionalProperties": True},
                required_permissions=(),
                metadata={
                    "tags": ["market_sim", "research", "chat", "read_only"],
                    "domains": ["market_sim"],
                    "aliases": [],
                    "worker_kind": "general",
                    "execution_class": "INLINE_SAFE",
                    "chat_visible": True,
                    "live_trading": "BLOCKED",
                    "mutations": False,
                    "alias_of": "market_sim.lab.status"
                    if cap_id == "market_sim.research_lab.overview"
                    else None,
                },
            )
        )
        registered.append(cap_id)
    return registered


def handle_lab_status(*, lab_id: str, **_: Any) -> dict[str, Any]:
    plane = _require_plane()
    if plane is None:
        return _unavailable("lab.status")
    try:
        lab = plane.get_agent_lab(str(lab_id))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "error": str(exc),
            "labId": lab_id,
            "liveTrading": "BLOCKED",
            "wrote": False,
        }
    meta = dict(lab.get("metadata") or {})
    learning = lab.get("learning") if isinstance(lab.get("learning"), dict) else None
    return {
        "status": "OK",
        "labId": lab.get("lab_id") or lab_id,
        "name": lab.get("name"),
        "labStatus": lab.get("status"),
        "outcome": lab.get("outcome"),
        "runMode": lab.get("run_mode") or meta.get("run_mode"),
        "stage": (learning or {}).get("stage") or meta.get("stage"),
        "learningRunId": lab.get("learning_run_id") or meta.get("learning_run_id"),
        "learningStatus": (learning or {}).get("status") if learning else None,
        "currentGeneration": (learning or {}).get("current_generation") if learning else None,
        "hypothesisId": meta.get("hypothesis_id"),
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {
            "read_only": True,
            "live_trading": "BLOCKED",
            "chat_cannot_enable_live": True,
        },
    }


def handle_lab_best_candidate(*, lab_id: str, **_: Any) -> dict[str, Any]:
    plane = _require_plane()
    if plane is None:
        return _unavailable("lab.best_candidate")
    try:
        payload = plane.get_lab_candidates(str(lab_id))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "error": str(exc),
            "labId": lab_id,
            "liveTrading": "BLOCKED",
            "wrote": False,
        }
    candidates = list(payload.get("candidates") or [])
    by_id = {
        str(c.get("candidate_id")): c
        for c in candidates
        if isinstance(c, dict) and c.get("candidate_id")
    }
    best_id = (
        payload.get("qualified_candidate")
        or payload.get("best_validation_candidate")
        or payload.get("best_train_candidate")
    )
    best = by_id.get(str(best_id)) if best_id else None
    summary = None
    if best:
        stages = ((best.get("metadata") or {}).get("stage_results") or {})
        val = stages.get("VAL") if isinstance(stages.get("VAL"), dict) else {}
        summary = {
            "candidateId": best.get("candidate_id"),
            "strategyId": best.get("strategy_id"),
            "strategyVersion": best.get("strategy_version"),
            "generation": best.get("generation"),
            "status": best.get("status"),
            "proposalMethod": best.get("proposal_method"),
            "hypothesis": best.get("hypothesis"),
            "hypothesisId": (best.get("metadata") or {}).get("hypothesis_id"),
            "validationFitness": val.get("fitness_score"),
            "validationAccepted": val.get("accepted"),
            "role": (
                "qualified"
                if best.get("candidate_id") == payload.get("qualified_candidate")
                else "best_validation"
                if best.get("candidate_id") == payload.get("best_validation_candidate")
                else "best_train"
            ),
        }
    return {
        "status": "OK",
        "labId": lab_id,
        "learningRunId": payload.get("learning_run_id"),
        "qualifiedCandidate": payload.get("qualified_candidate"),
        "bestValidationCandidate": payload.get("best_validation_candidate"),
        "bestTrainCandidate": payload.get("best_train_candidate"),
        "best": summary,
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {
            "read_only": True,
            "best_is_not_qualification_authority": True,
            "live_trading": "BLOCKED",
        },
    }


def handle_lab_hypotheses(*, lab_id: str, limit: int = 50, **_: Any) -> dict[str, Any]:
    plane = _require_plane()
    if plane is None:
        return _unavailable("lab.hypotheses")
    try:
        payload = plane.list_lab_hypotheses(str(lab_id), limit=int(limit))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "error": str(exc),
            "labId": lab_id,
            "liveTrading": "BLOCKED",
            "wrote": False,
        }
    hyps = [h for h in (payload.get("hypotheses") or []) if isinstance(h, dict)]
    active = [
        {
            "hypothesisId": h.get("hypothesis_id"),
            "status": h.get("status"),
            "trust": h.get("trust"),
            "statement": h.get("statement"),
        }
        for h in hyps
        if str(h.get("status") or "").upper() in _ACTIVE_HYPOTHESIS
    ]
    return {
        "status": "OK",
        "labId": lab_id,
        "count": payload.get("count", len(hyps)),
        "activeCount": len(active),
        "activeHypothesisIds": [h["hypothesisId"] for h in active if h.get("hypothesisId")],
        "hypotheses": [
            {
                "hypothesisId": h.get("hypothesis_id"),
                "status": h.get("status"),
                "trust": h.get("trust"),
                "statement": h.get("statement"),
                "parentHypothesisId": h.get("parent_hypothesis_id"),
            }
            for h in hyps[: int(limit)]
        ],
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {"read_only": True, "public_statements_only": True, "live_trading": "BLOCKED"},
    }


def handle_lessons_summary(*, lab_id: str, **_: Any) -> dict[str, Any]:
    plane = _require_plane()
    if plane is None:
        return _unavailable("lessons.summary")
    try:
        payload = plane.get_lab_lessons(str(lab_id))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "error": str(exc),
            "labId": lab_id,
            "liveTrading": "BLOCKED",
            "wrote": False,
        }
    lessons = [l for l in (payload.get("lessons") or []) if isinstance(l, dict)]
    by_trust: dict[str, int] = {}
    for lesson in lessons:
        trust = str(lesson.get("trust") or lesson.get("trust_state") or "UNKNOWN")
        by_trust[trust] = by_trust.get(trust, 0) + 1
    return {
        "status": "OK",
        "labId": lab_id,
        "count": len(lessons),
        "byTrust": by_trust,
        "recent": [
            {
                "lessonId": l.get("lesson_id") or l.get("id"),
                "claim": l.get("claim") or l.get("statement"),
                "trust": l.get("trust") or l.get("trust_state"),
                "appliesTo": l.get("applies_to") or l.get("appliesTo"),
            }
            for l in lessons[:12]
        ],
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {
            "read_only": True,
            "agent_proposed_is_not_proof": True,
            "live_trading": "BLOCKED",
        },
    }


def handle_paper_drift(
    *,
    deployment_id: str | None = None,
    portfolio_id: str | None = None,
    limit: int = 20,
    **_: Any,
) -> dict[str, Any]:
    plane = _require_plane()
    if plane is None:
        return _unavailable("paper.drift")
    deployments: list[dict[str, Any]] = []
    try:
        if deployment_id:
            deployments = [plane.get_paper_deployment(str(deployment_id))]
        else:
            deployments = list(plane.list_paper_deployments(limit=int(limit)) or [])
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "error": str(exc),
            "liveTrading": "BLOCKED",
            "wrote": False,
        }
    if portfolio_id:
        filtered = []
        for row in deployments:
            meta = dict(row.get("metadata") or row.get("metadata_json") or {})
            payload = dict(row.get("payload") or row.get("payload_json") or {})
            loop = dict(row.get("loop") or row.get("loop_state_json") or {})
            refs = {
                str(meta.get("portfolio_id") or ""),
                str(payload.get("portfolio_id") or ""),
                str(loop.get("portfolio_id") or ""),
            }
            if str(portfolio_id) in refs:
                filtered.append(row)
        deployments = filtered
    tickets: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for dep in deployments:
        if not isinstance(dep, dict):
            continue
        loop = dict(dep.get("loop") or dep.get("loop_state_json") or {})
        drift = loop.get("drift_review") if isinstance(loop.get("drift_review"), dict) else None
        ticket = None
        if drift:
            ticket = drift.get("continualResearch")
            if isinstance(ticket, dict):
                tickets.append(
                    {
                        "ticketId": ticket.get("ticketId"),
                        "reason": ticket.get("reason"),
                        "deploymentId": dep.get("deployment_id"),
                        "status": drift.get("status"),
                        "researchQuestion": ticket.get("researchQuestion"),
                    }
                )
        rows.append(
            {
                "deploymentId": dep.get("deployment_id"),
                "status": dep.get("status"),
                "mode": dep.get("mode"),
                "strategyAssetId": dep.get("strategy_asset_id"),
                "driftStatus": (drift or {}).get("status") if drift else None,
                "hasDriftTicket": bool(ticket),
            }
        )
    return {
        "status": "OK",
        "deploymentCount": len(rows),
        "deployments": rows,
        "driftTickets": tickets,
        "portfolioId": portfolio_id,
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {
            "read_only": True,
            "does_not_auto_promote": True,
            "live_trading": "BLOCKED",
            "paper_forward_continual_research": True,
        },
    }


def _require_plane() -> Any | None:
    return _BOUND_PLANE


def _unavailable(kind: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "error": "MARKET_SIM_PLANE_UNBOUND",
        "kind": kind,
        "liveTrading": "BLOCKED",
        "wrote": False,
        "truth": {"read_only": True, "live_trading": "BLOCKED"},
    }
