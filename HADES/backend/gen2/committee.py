"""Multi-Agent Intelligence Committee — heuristic + optional live specialist stances.

Default path is labeled ``heuristic_isolated``. Live LM calls require an async chat_fn;
unavailable LM falls back honestly without inventing live specialist scores.

Divergence (A7/C9): each role receives a distinct retrieval slice, role-specific prompt,
and optional dynamic ``model_id`` slot (never a hardcoded production model).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from gen2.output_contracts import ModelOutputValidationError, validate_committee_stance
from gen2.store import Gen2Store

RecordFn = Callable[..., dict[str, Any]]


def committee_roles(domain: str, *, topic: str = "", complexity: str | None = None) -> list[dict[str, Any]]:
    """Select specialist roles by domain and question complexity (G2)."""
    text = f"{domain} {topic}".lower()
    level = (complexity or "").strip().lower()
    if not level:
        tokens = re.findall(r"[a-z0-9]{3,}", text)
        financeish = domain == "finance" or any(
            k in text for k in ("earnings", "valuation", "portfolio", "ticker", "revenue", "guidance")
        )
        if financeish:
            level = "complex"
        elif len(tokens) <= 6 and not any(
            k in text for k in ("compare", "versus", "risk", "trade", "architect", "migration")
        ):
            level = "simple"
        elif any(k in text for k in ("architect", "multi", "trade-off", "portfolio", "migration")):
            level = "complex"
        else:
            level = "standard"

    if domain == "finance":
        core = [
            {"id": "fundamental_analyst", "title": "Fundamental Analyst", "focus": "filings/fundamentals", "slice": slice(0, 2)},
            {"id": "bear_case", "title": "Bear Case Analyst", "focus": "risks/downside", "slice": slice(2, 4)},
            {"id": "evidence_auditor", "title": "Evidence Auditor", "focus": "provenance", "slice": slice(0, 4)},
        ]
        extra = [
            {"id": "quant_analyst", "title": "Quant Analyst", "focus": "price/volume", "slice": slice(1, 3)},
            {"id": "macro_analyst", "title": "Macro Analyst", "focus": "macro/regulation", "slice": slice(0, 1)},
            {"id": "news_analyst", "title": "News Analyst", "focus": "catalysts", "slice": slice(0, 3)},
        ]
    else:
        core = [
            {"id": "primary_researcher", "title": "Primary Researcher", "focus": "broad retrieval", "slice": slice(0, 3)},
            {"id": "evidence_auditor", "title": "Evidence Auditor", "focus": "citations", "slice": slice(0, 2)},
            {"id": "skeptic", "title": "Skeptic", "focus": "challenge claims", "slice": slice(1, 3)},
        ]
        extra = [
            {"id": "contradiction_finder", "title": "Contradiction Finder", "focus": "conflicts", "slice": slice(2, 5)},
            {"id": "synthesizer", "title": "Synthesizer", "focus": "merge", "slice": slice(0, 5)},
            {"id": "independent_critic", "title": "Independent Critic", "focus": "acceptance", "slice": slice(0, 1)},
        ]
    if level == "simple":
        roles = core[:2]
    elif level == "complex":
        roles = core + extra
    else:
        roles = core + extra[:1]
    for role in roles:
        role["complexity"] = level
    return roles


def evidence_slice_for_role(role: dict[str, Any], evidence: list[str]) -> list[str]:
    """Return the role's retrieval slice (distinct windows → dissent when evidence differs)."""
    if not evidence:
        return []
    sl = role.get("slice")
    if isinstance(sl, slice):
        return list(evidence[sl])
    return list(evidence)


def resolve_model_slot(
    role_id: str,
    *,
    model_id: str | None = None,
    model_slots: dict[str, str] | None = None,
) -> str | None:
    """Pick a dynamic model id for a role. Never invent a production model id."""
    slots = model_slots or {}
    if role_id in slots and str(slots[role_id] or "").strip():
        return str(slots[role_id]).strip()
    if "*" in slots and str(slots["*"] or "").strip():
        return str(slots["*"]).strip()
    if model_id is not None and str(model_id).strip():
        return str(model_id).strip()
    return None


def role_prompt(role_id: str, topic: str, evidence: list[str], *, focus: str = "") -> str:
    """Role-specific prompt — different instructions per specialist (not clone templates)."""
    stance_hint = {
        "skeptic": "Challenge optimism. Prefer falsification. Mark unsupported claims.",
        "bear_case": "Argue the downside case. Surface risks and missing hedges.",
        "contradiction_finder": "Hunt contradictions across evidence slices only.",
        "evidence_auditor": "Accept only claims with clear provenance in the evidence.",
        "independent_critic": "Independent acceptance review; do not echo the primary thesis.",
        "synthesizer": "Merge positions with explicit minority notes; avoid unanimous echo.",
        "fundamental_analyst": "Focus on fundamentals/filings language in the evidence.",
        "quant_analyst": "Focus on quantitative/price-volume implications if present.",
        "macro_analyst": "Focus on macro/regulatory angles only.",
        "news_analyst": "Focus on catalysts and timing language.",
        "primary_researcher": "Build a working hypothesis from your retrieval slice only.",
    }.get(role_id, f"Stay focused on: {focus or role_id}.")
    return (
        f"You are committee role `{role_id}` focused on {focus or role_id}.\n"
        f"Stance directive: {stance_hint}\n"
        f"Topic: {topic}\n"
        f"Evidence slice (role-private):\n- "
        + ("\n- ".join(evidence) if evidence else "(none)")
        + "\n"
        "Reply with JSON only: "
        '{"claim":"...","confidence":0.0,"supported":false,"rationale":"..."}'
        "\nDo not copy other roles. Base the claim only on this slice + directive."
    )


def _slice_fingerprint(evidence: list[str]) -> str:
    blob = "\n".join(evidence)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def role_stance(role_id: str, topic: str, evidence: list[str]) -> dict[str, Any]:
    """Heuristic committee stance — labeled, not a live specialist model run.

    ``supported`` requires topical overlap between claim keywords and evidence text,
    not merely a non-empty evidence list.
    """
    mode = "heuristic_isolated"
    topic_tokens = {t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", topic or "")}
    evidence_blob = " ".join(evidence).lower()
    evidence_tokens = {t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", evidence_blob)}
    overlap = topic_tokens & evidence_tokens
    topical = bool(overlap) or any(tok in evidence_blob for tok in list(topic_tokens)[:5])

    base = f"Beoordeling van: {topic}"
    if role_id in {"skeptic", "bear_case", "contradiction_finder"}:
        claim = f"Claim is onvoldoende onderbouwd of te optimistisch: {topic}"
        confidence = 0.55 if topical else 0.35
        rationale = "Zoekt tegenspraak en ontbrekende bewijzen; deelt niet automatisch de primaire thesis."
        supported = topical and bool(evidence)
    elif role_id in {"evidence_auditor", "independent_critic"}:
        claim = f"Alleen evidence-backed deelclaims accepteren voor: {topic}"
        confidence = 0.7 if topical else 0.3
        rationale = "Accepteert geen claim zonder provenance; markeert gaps."
        supported = topical and bool(evidence)
    elif role_id == "synthesizer":
        claim = f"Gewogen synthese met expliciete onzekerheid over: {topic}"
        confidence = 0.6 if topical else 0.4
        rationale = "Combineert posities zonder unanieme echo."
        supported = topical and bool(evidence)
    else:
        claim = f"Werkhypothese: {topic}"
        confidence = 0.65 if topical else 0.45
        rationale = f"{base}; focusrol produceert een eigen tussenresultaat."
        supported = topical and bool(evidence)
    if evidence:
        rationale += f" Evidence slice ({len(evidence)}): " + "; ".join(evidence[:2])
        if not topical:
            rationale += " | Evidence niet topicaal genoeg voor claim-ondersteuning."
            supported = False
    else:
        rationale += " Geen evidence slice — lagere confidence."
        supported = False
    return {
        "claim": claim,
        "confidence": confidence,
        "supported": supported,
        "rationale": rationale,
        "mode": mode,
        "evidence_overlap_tokens": sorted(overlap)[:12],
        "model_invoked": False,
        "prompt_fingerprint": hashlib.sha256(
            role_prompt(role_id, topic, evidence).encode("utf-8")
        ).hexdigest()[:12],
    }


def role_stance_live_sync(
    role_id: str,
    topic: str,
    evidence: list[str],
    *,
    chat_fn: Any = None,
    model_id: str | None = None,
    focus: str = "",
) -> dict[str, Any]:
    """Sync wrapper — prefer async live path from routes. Never invent live scores."""
    fallback = role_stance(role_id, topic, evidence)
    fallback["mode"] = "heuristic_fallback_lm_unavailable"
    fallback["model_invoked"] = False
    fallback["model_id_slot"] = model_id
    fallback["rationale"] = (
        f"{fallback['rationale']} | live_blocked: use async committee path with LM client"
    )
    return fallback


async def role_stance_live_async(
    role_id: str,
    topic: str,
    evidence: list[str],
    *,
    chat_fn: Any,
    model_id: str | None,
    focus: str,
) -> dict[str, Any]:
    """Live specialist stance via LM client. Falls back honestly on failure."""
    prompt = role_prompt(role_id, topic, evidence, focus=focus)
    try:
        response = await chat_fn(
            {
                "model": model_id or "local",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 220,
            }
        )
        content = (
            ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        parsed = None
        try:
            parsed = json.loads(content)
        except Exception:
            match = re.search(r"\{.*\}", content, re.S)
            if match:
                parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("non_json_live_stance")
        try:
            validated = validate_committee_stance(parsed)
        except ModelOutputValidationError as exc:
            raise ValueError(exc.to_dict()) from exc
        claim = validated["claim"]
        confidence = float(validated["confidence"])
        supported = bool(validated["supported"]) and bool(evidence)
        rationale = validated["rationale"]
        return {
            "claim": claim,
            "confidence": confidence,
            "supported": supported,
            "rationale": rationale,
            "mode": "live_specialist",
            "model_invoked": True,
            "model_id_slot": model_id,
            "evidence_overlap_tokens": [],
            "validation": "strict_contract",
            "prompt_fingerprint": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
        }
    except Exception as exc:
        fallback = role_stance(role_id, topic, evidence)
        fallback["mode"] = "heuristic_fallback_lm_unavailable"
        fallback["model_invoked"] = False
        fallback["model_id_slot"] = model_id
        fallback["rationale"] = f"{fallback['rationale']} | live_blocked: {exc}"
        return fallback



def mark_claims(positions: list[dict[str, Any]], evidence: list[str]) -> list[dict[str, Any]]:
    """Critic-style claim marking: supported / unsupported / missing_evidence."""
    evidence_joined = " ".join(evidence).lower()
    marks: list[dict[str, Any]] = []
    for p in positions:
        claim = str(p.get("claim") or "")
        tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", claim.lower())][:8]
        overlap = [t for t in tokens if t in evidence_joined] if evidence else []
        if not evidence:
            status = "missing_evidence"
        elif overlap:
            status = "supported"
        else:
            status = "unsupported"
        marks.append(
            {
                "agent": p.get("agent"),
                "claim": claim,
                "status": status,
                "overlap_tokens": overlap[:6],
                "confidence": p.get("confidence"),
            }
        )
    return marks


def finalize_committee(
    store: Gen2Store,
    record: RecordFn,
    topic_clean: str,
    domain: str,
    evidence: list[str],
    positions: list[dict[str, Any]],
    *,
    live_requested: bool,
    model_id: str | None = None,
    model_slots: dict[str, str] | None = None,
) -> dict[str, Any]:
    agreements: list[str] = []
    disagreements: list[str] = []
    minority: list[str] = []
    evidence_checks: list[dict[str, Any]] = []
    evidence_joined = " ".join(evidence).lower()
    for p in positions:
        claim = str(p.get("claim") or "")
        tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", claim.lower())][:8]
        overlap = [t for t in tokens if t in evidence_joined] if evidence else []
        model_supported = bool(p.get("supported"))
        externally_supported = bool(evidence) and len(overlap) >= max(1, min(2, len(tokens) // 3))
        evidence_checks.append(
            {
                "agent": p.get("agent"),
                "claim": claim,
                "model_supported_proposal": model_supported,
                "external_support_status": (
                    "supported" if externally_supported else "unsupported" if evidence else "no_evidence"
                ),
                "overlap_tokens": overlap[:6],
            }
        )
        if evidence:
            p["supported"] = externally_supported
            p["model_supported_proposal"] = model_supported
    unsupported = [p["claim"] for p in positions if not p["supported"]]
    supported_positions = [p for p in positions if p["supported"]]
    claim_marks = mark_claims(positions, evidence)
    primary = next(
        (
            p
            for p in positions
            if "primary" in p["agent"]
            or "fundamental" in p["agent"]
            or (p["agent"].endswith("_analyst") and "bear" not in p["agent"])
        ),
        positions[0],
    )
    critics = [
        p
        for p in positions
        if p["agent"]
        in {"skeptic", "bear_case", "contradiction_finder", "independent_critic", "evidence_auditor"}
    ]
    for critic in critics:
        if critic["claim"] != primary["claim"]:
            disagreements.append(f"{primary['agent']} vs {critic['agent']}")
        else:
            agreements.append(f"{primary['agent']} agrees with {critic['agent']}")
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for p in positions:
        by_claim.setdefault(p["claim"], []).append(p)
    for claim, group in by_claim.items():
        if len(group) == 1 and len(by_claim) > 1:
            minority.append(f"{group[0]['agent']}: {claim}")
        elif len(group) > 1:
            agreements.append(claim)
    missing = []
    if not evidence:
        missing.append("No external evidence provided; positions may be weakly grounded.")
    if unsupported:
        missing.append("Some agents made unsupported claims relative to provided evidence.")
    unique_claims = {str(p.get("claim") or "") for p in positions}
    unique_slices = {str(p.get("evidence_slice_fingerprint") or "") for p in positions}
    unique_prompts = {str(p.get("prompt_fingerprint") or "") for p in positions}
    clone_risk = len(unique_claims) <= 1 and len(positions) > 1
    weight_pool = supported_positions or positions
    avg_conf = round(sum(p["confidence"] for p in weight_pool) / max(1, len(weight_pool)), 3)
    support_ratio = round(len(supported_positions) / max(1, len(positions)), 4)
    modes = {str(p.get("mode") or "") for p in positions}
    consensus_mode = (
        "live_specialist"
        if modes == {"live_specialist"}
        else "mixed_live_heuristic"
        if any("live" in m or "fallback" in m for m in modes)
        else "heuristic_isolated"
    )
    consensus = {
        "basis": "position_results_plus_external_evidence",
        "mode": consensus_mode,
        "live_requested": live_requested,
        "model_id": model_id,
        "model_slots": dict(model_slots or {}),
        "agreements": sorted(set(agreements))[:12],
        "disagreements": sorted(set(disagreements))[:12],
        "minority_positions": minority[:8],
        "unsupported_claims": unsupported[:8],
        "supported_count": len(supported_positions),
        "position_count": len(positions),
        "support_ratio": support_ratio,
        "confidence": avg_conf,
        "missing_evidence": missing,
        "evidence_checks": evidence_checks,
        "claim_marks": claim_marks,
        "divergence": {
            "unique_claims": len(unique_claims),
            "unique_evidence_slices": len(unique_slices),
            "unique_prompt_fingerprints": len(unique_prompts),
            "clone_risk": clone_risk,
            "note": "clone_risk true means positions share one claim text — dissent failed.",
        },
        "note": "model_supported_proposal is not final; external_support_status decides consensus support.",
        "agent_rationale_summaries": [
            {
                "agent": p["agent"],
                "rationale": p["rationale"],
                "confidence": p["confidence"],
                "supported": p["supported"],
                "model_supported_proposal": p.get("model_supported_proposal", p.get("supported")),
                "mode": p.get("mode"),
                "model_invoked": p.get("model_invoked"),
                "model_id_slot": p.get("model_id_slot"),
                "evidence_slice_fingerprint": p.get("evidence_slice_fingerprint"),
            }
            for p in positions
        ],
    }
    session = store.save_committee(
        {
            "topic": topic_clean,
            "domain": domain,
            "status": "completed",
            "positions": positions,
            "consensus": consensus,
            "claim_marks": claim_marks,
        }
    )
    session["claim_marks"] = claim_marks
    record(session["id"], "RUN_CREATED", {"kind": "committee", "live_requested": live_requested}, component="committee")
    record(session["id"], "VERIFICATION", consensus, component="committee")
    return session


def run_committee(
    store: Gen2Store,
    record: RecordFn,
    topic: str,
    *,
    domain: str = "research",
    evidence: list[str] | None = None,
    chat_fn: Any | None = None,
    model_id: str | None = None,
    model_slots: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Heuristic committee (default). For live specialists use ``run_committee_live``."""
    topic_clean = (topic or "").strip()
    if not topic_clean:
        raise ValueError("topic is required")
    evidence_list = [e.strip() for e in (evidence or []) if str(e).strip()]
    roles = committee_roles(domain, topic=topic_clean)
    positions = []
    for role in roles:
        slice_ev = evidence_slice_for_role(role, evidence_list)
        slot = resolve_model_slot(role["id"], model_id=model_id, model_slots=model_slots)
        if callable(chat_fn):
            stance = role_stance_live_sync(
                role["id"],
                topic_clean,
                slice_ev,
                chat_fn=chat_fn,
                model_id=slot,
                focus=str(role.get("focus") or ""),
            )
        else:
            stance = role_stance(role["id"], topic_clean, slice_ev)
        positions.append(
            {
                "agent": role["id"],
                "title": role["title"],
                "retrieval_focus": role["focus"],
                "evidence_used": slice_ev,
                "evidence_slice_fingerprint": _slice_fingerprint(slice_ev),
                "claim": stance["claim"],
                "confidence": stance["confidence"],
                "supported": stance["supported"],
                "rationale": stance["rationale"],
                "mode": stance.get("mode") or "heuristic_isolated",
                "evidence_overlap_tokens": stance.get("evidence_overlap_tokens") or [],
                "model_invoked": bool(stance.get("model_invoked")),
                "model_id_slot": stance.get("model_id_slot", slot),
                "prompt_fingerprint": stance.get("prompt_fingerprint")
                or hashlib.sha256(
                    role_prompt(
                        role["id"], topic_clean, slice_ev, focus=str(role.get("focus") or "")
                    ).encode("utf-8")
                ).hexdigest()[:12],
                "role_complexity": role.get("complexity"),
            }
        )
    session = finalize_committee(
        store,
        record,
        topic_clean,
        domain,
        evidence_list,
        positions,
        live_requested=callable(chat_fn),
        model_id=model_id,
        model_slots=model_slots,
    )
    consensus = dict(session.get("consensus") or {})
    consensus["role_selection"] = {
        "complexity": roles[0].get("complexity") if roles else "standard",
        "role_count": len(roles),
        "roles": [r["id"] for r in roles],
    }
    session["consensus"] = consensus
    return session


async def run_committee_live(
    store: Gen2Store,
    record: RecordFn,
    topic: str,
    *,
    domain: str = "research",
    evidence: list[str] | None = None,
    chat_fn: Any | None = None,
    model_id: str | None = None,
    model_slots: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Committee with live specialist calls when ``chat_fn`` is available."""
    if not callable(chat_fn):
        session = run_committee(
            store,
            record,
            topic,
            domain=domain,
            evidence=evidence,
            model_id=model_id,
            model_slots=model_slots,
        )
        consensus = dict(session.get("consensus") or {})
        consensus["mode"] = "heuristic_isolated"
        consensus["live_requested"] = True
        consensus["live_blocked_reason"] = "lm_client_unavailable"
        session["consensus"] = consensus
        session["status"] = "completed_heuristic_fallback"
        return session
    topic_clean = (topic or "").strip()
    if not topic_clean:
        raise ValueError("topic is required")
    evidence_list = [e.strip() for e in (evidence or []) if str(e).strip()]
    roles = committee_roles(domain, topic=topic_clean)
    positions = []
    for role in roles:
        slice_ev = evidence_slice_for_role(role, evidence_list)
        slot = resolve_model_slot(role["id"], model_id=model_id, model_slots=model_slots)
        stance = await role_stance_live_async(
            role["id"],
            topic_clean,
            slice_ev,
            chat_fn=chat_fn,
            model_id=slot,
            focus=str(role.get("focus") or ""),
        )
        positions.append(
            {
                "agent": role["id"],
                "title": role["title"],
                "retrieval_focus": role["focus"],
                "evidence_used": slice_ev,
                "evidence_slice_fingerprint": _slice_fingerprint(slice_ev),
                "claim": stance["claim"],
                "confidence": stance["confidence"],
                "supported": stance["supported"],
                "rationale": stance["rationale"],
                "mode": stance.get("mode") or "heuristic_isolated",
                "evidence_overlap_tokens": stance.get("evidence_overlap_tokens") or [],
                "model_invoked": bool(stance.get("model_invoked")),
                "model_id_slot": stance.get("model_id_slot", slot),
                "prompt_fingerprint": stance.get("prompt_fingerprint")
                or hashlib.sha256(
                    role_prompt(
                        role["id"], topic_clean, slice_ev, focus=str(role.get("focus") or "")
                    ).encode("utf-8")
                ).hexdigest()[:12],
                "role_complexity": role.get("complexity"),
            }
        )
    session = finalize_committee(
        store,
        record,
        topic_clean,
        domain,
        evidence_list,
        positions,
        live_requested=True,
        model_id=model_id,
        model_slots=model_slots,
    )
    consensus = dict(session.get("consensus") or {})
    consensus["role_selection"] = {
        "complexity": roles[0].get("complexity") if roles else "standard",
        "role_count": len(roles),
        "roles": [r["id"] for r in roles],
    }
    session["consensus"] = consensus
    return session
