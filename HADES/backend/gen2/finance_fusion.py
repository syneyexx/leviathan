"""Financial Intelligence Fusion — article → structural market events + graph edges.

Paper-only hypothesis surface; no live brokerage or order placement.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from gen2.store import Gen2Store, utc_now


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def classify_catalyst(text: str) -> str:
    t = text.lower()
    mapping = [
        (("merger", "acquisition", "overname", "m&a"), "m_and_a"),
        (("earnings", "kwartaalcijfers", "eps"), "earnings"),
        (("ceo", "cfo", "management", "benoem"), "management_change"),
        (("lawsuit", "rechtszaak", "litigation"), "litigation"),
        (("regulat", "sec", "compliance"), "regulation"),
        (("product", "launch", "aankondig"), "product_announcement"),
        (("crypto", "bitcoin", "ethereum"), "crypto"),
        (("oil", "commodity", "goud"), "commodities"),
        (("supply chain", "tekort", "fabriek"), "supply_chain"),
    ]
    for keys, label in mapping:
        if any(k in t for k in keys):
            return label
    return "general_market"


def horizon_for(event_type: str) -> str:
    return {
        "earnings": "days",
        "m_and_a": "weeks",
        "regulation": "months",
        "product_announcement": "weeks",
        "management_change": "weeks",
    }.get(event_type, "unknown")


def guess_company(title: str) -> str | None:
    m = re.search(r"\b([A-Z]{2,}(?:\s+[A-Z][a-z]+)?)\b", title)
    if m:
        return m.group(1)
    return None


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", text or "")}


def cross_verify_sources(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-source verification: shared entities/title tokens across sources."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for article in articles:
        source = str(article.get("source") or article.get("uri") or "unknown")
        by_source.setdefault(source, []).append(article)
    source_count = len(by_source)
    if source_count <= 1:
        return {
            "verified": False,
            "source_count": source_count,
            "agreement_ratio": 0.0,
            "note": "single_source_unverified",
        }
    token_sets = [_tokenize(str(a.get("title") or "") + " " + str(a.get("summary") or "")) for a in articles]
    if not token_sets:
        return {"verified": False, "source_count": source_count, "agreement_ratio": 0.0, "note": "empty"}
    shared = set.intersection(*token_sets) if token_sets else set()
    union = set.union(*token_sets) if token_sets else set()
    ratio = (len(shared) / len(union)) if union else 0.0
    return {
        "verified": ratio >= 0.15 and source_count >= 2,
        "source_count": source_count,
        "agreement_ratio": round(ratio, 4),
        "shared_tokens": sorted(shared)[:20],
        "note": "token_overlap_cross_source",
    }


def find_event_analogues(store: Gen2Store, event: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    """Find prior market_events with same type / overlapping entities (local, not embeddings)."""
    existing = store.list_market_events(limit=200) if hasattr(store, "list_market_events") else []
    et = str(event.get("event_type") or "")
    entities = {str(e).lower() for e in (event.get("entities") or event.get("affected_entities") or [])}
    title_tokens = _tokenize(str(event.get("title") or ""))
    scored: list[dict[str, Any]] = []
    for prior in existing:
        if prior.get("id") == event.get("id"):
            continue
        score = 0.0
        if prior.get("event_type") == et:
            score += 1.0
        prior_ents = {str(e).lower() for e in (prior.get("entities") or prior.get("affected_entities") or [])}
        score += 0.5 * len(entities & prior_ents)
        score += 0.25 * len(title_tokens & _tokenize(str(prior.get("title") or "")))
        if score <= 0:
            continue
        scored.append(
            {
                "event_id": prior.get("id"),
                "title": prior.get("title"),
                "event_type": prior.get("event_type"),
                "score": round(score, 4),
                "method": "type_entity_token_overlap",
            }
        )
    scored.sort(key=lambda r: -float(r["score"]))
    return scored[: max(1, min(int(limit), 20))]


def event_study_stub(event: dict[str, Any], *, window_days: int = 5) -> dict[str, Any]:
    """Honest event-study placeholder — no hindsight price fabrications.

    Returns a study *plan* and refuses synthetic alpha. Real bars require PAPER data.
    Prefer ``run_event_study`` when callers may supply bars.
    """
    return run_event_study(event, bars=None, window_days=window_days)


def run_event_study(
    event: dict[str, Any],
    *,
    bars: list[dict[str, Any]] | None = None,
    window_days: int = 5,
) -> dict[str, Any]:
    """PAPER event study. Refuses without bars; computes simple CAR when bars present.

    ``bars`` items: ``{date|t, close|adj_close}`` ordered around the event. Incomplete
    series returns ``status=incomplete`` — never invents returns.
    """
    base = {
        "event_id": event.get("id"),
        "window_days": int(window_days),
        "paper_only": True,
        "required_inputs": ["paper_ohlcv_bars", "event_timestamp"],
        "live_trading": False,
    }
    if not bars:
        return {
            **base,
            "status": "plan_only",
            "incomplete": True,
            "computed_abnormal_return": None,
            "note": "No hindsight theatre: abnormal returns are not invented without PAPER bars.",
        }
    closes: list[float] = []
    for bar in bars:
        raw = bar.get("close", bar.get("adj_close"))
        try:
            closes.append(float(raw))
        except (TypeError, ValueError):
            continue
    need = max(2, int(window_days) + 1)
    if len(closes) < need:
        return {
            **base,
            "status": "incomplete",
            "incomplete": True,
            "bars_received": len(closes),
            "bars_required": need,
            "computed_abnormal_return": None,
            "note": "Insufficient PAPER bars for event window — refused computation.",
        }
    # Simple cumulative return over window (not market-adjusted alpha — labeled honestly).
    start = closes[0]
    end = closes[min(len(closes) - 1, int(window_days))]
    if start == 0:
        return {
            **base,
            "status": "incomplete",
            "incomplete": True,
            "computed_abnormal_return": None,
            "note": "Invalid zero start close — refused.",
        }
    simple_return = (end - start) / start
    return {
        **base,
        "status": "computed_simple_return",
        "incomplete": False,
        "computed_abnormal_return": None,  # not claiming abnormal/alpha without benchmark
        "computed_simple_return": round(simple_return, 6),
        "bars_used": min(len(closes), need),
        "method": "paper_simple_window_return",
        "note": "Simple window return on PAPER bars only — not market-adjusted abnormal return.",
    }


def persist_thesis(store: Gen2Store, thesis: dict[str, Any], *, symbol: str | None = None) -> dict[str, Any]:
    """Persist a PAPER thesis as a market_event metadata record (additive, no live orders)."""
    statement = str(thesis.get("statement") or "").strip()
    if not statement:
        raise ValueError("thesis.statement required")
    event = store.save_market_event(
        {
            "event_type": "thesis",
            "title": f"PAPER thesis: {statement[:180]}",
            "summary": statement[:2000],
            "entities": [symbol] if symbol else list(thesis.get("event_ids") or [])[:8],
            "affected_entities": [symbol] if symbol else [],
            "source_count": 1,
            "confidence": float(thesis.get("confidence") or 0.5),
            "novelty": 0.5,
            "first_seen": utc_now(),
            "likely_horizon": "unknown",
            "historical_analogues": [],
            "supporting_evidence": [{"kind": "thesis", "event_ids": thesis.get("event_ids") or []}],
            "metadata": {
                "kind": "paper_thesis",
                "paper_only": True,
                "live_trading": False,
                "thesis": thesis,
                "symbol": symbol,
            },
            "content_hash": _sha("thesis|" + statement.lower() + "|" + str(symbol or "")),
        }
    )
    return {
        "ok": True,
        "thesis_event_id": event["id"],
        "paper_only": True,
        "event": event,
    }


def propose_paper_strategy(events: list[dict[str, Any]], *, symbol: str | None = None) -> dict[str, Any]:
    """Thesis → PAPER strategy proposal requiring human approval (never live orders)."""
    types = sorted({str(e.get("event_type") or "general_market") for e in events})
    thesis = {
        "statement": f"Structural catalysts observed: {', '.join(types)}"
        + (f" affecting {symbol}" if symbol else ""),
        "event_ids": [e.get("id") for e in events],
        "confidence": round(
            sum(float(e.get("confidence") or 0.5) for e in events) / max(1, len(events)),
            4,
        ),
        "paper_only": True,
    }
    return {
        "kind": "paper_strategy_proposal",
        "symbol": symbol,
        "action": "observe_then_paper_simulate",
        "requires_human_approval": True,
        "live_trading": False,
        "thesis": thesis,
        "status": "awaiting_approval",
        "note": "PAPER-only wall: proposal never places real-money orders (D011).",
    }


def evaluate_finance_claim(
    claim: str,
    *,
    evidence: list[str] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Eval harness for finance claims — marks unsupported without evidence; no hindsight."""
    evidence = evidence or []
    events = events or []
    claim_tokens = _tokenize(claim)
    evidence_blob = " ".join(evidence + [str(e.get("title") or "") for e in events]).lower()
    overlap = {t for t in claim_tokens if t in evidence_blob}
    supported = bool(overlap) and (bool(evidence) or bool(events))
    return {
        "claim": claim,
        "supported": supported,
        "support_ratio": round(len(overlap) / max(1, len(claim_tokens)), 4),
        "overlap_tokens": sorted(overlap)[:16],
        "hindsight_refused": True,
        "paper_only": True,
        "status": "supported" if supported else "unsupported_or_missing_evidence",
    }


def maybe_knowledge_write_back_from_finance(
    events: list[dict[str, Any]],
    *,
    verification: dict[str, Any],
    symbol: str | None = None,
    allow_write_back: bool = False,
    knowledge_ingest: Any | None = None,
) -> dict[str, Any]:
    """J4/C15 — honest gated Knowledge write-back from finance fusion.

    Default is deny. Requires cross-source verification AND explicit allow + ingest hook.
    Graph edges from fuse remain separate (already written by fuse_market_intelligence).
    """
    from reasoning.autonomy_policies import evaluate_knowledge_write_back

    verified = bool(verification.get("verified"))
    decision = evaluate_knowledge_write_back(
        verified=verified,
        user_allowed=bool(allow_write_back),
        policy_allow=False,
        write_enabled=True,
    )
    if decision.action != "allow":
        return {
            "written": False,
            "decision": decision.to_dict(),
            "note": "knowledge_write_back_gated",
            "paper_only": True,
        }
    if knowledge_ingest is None:
        return {
            "written": False,
            "decision": decision.to_dict(),
            "note": "no_knowledge_ingest_hook",
            "paper_only": True,
        }
    title = f"Finance fusion learnings{f' ({symbol})' if symbol else ''}"
    lines = [
        f"- [{e.get('event_type')}] {e.get('title')} (confidence={e.get('confidence')})"
        for e in events[:20]
    ]
    text = "PAPER-only finance fusion events (verified):\n" + "\n".join(lines)
    try:
        result = knowledge_ingest(
            title=title,
            text=text,
            source_type="finance_fusion",
            uri=f"finance_fusion:{symbol or 'market'}:{_sha(text)}",
            metadata={
                "paper_only": True,
                "verified": True,
                "event_ids": [e.get("id") for e in events],
                "cross_verify": verification,
            },
        )
    except Exception as exc:  # noqa: BLE001 — surface honest failure, never fake write
        return {
            "written": False,
            "decision": decision.to_dict(),
            "error": str(exc),
            "note": "ingest_failed",
            "paper_only": True,
        }
    return {
        "written": True,
        "decision": decision.to_dict(),
        "knowledge": result,
        "paper_only": True,
    }


def fuse_market_intelligence(
    store: Gen2Store,
    *,
    articles: list[dict[str, Any]] | None = None,
    symbol: str | None = None,
    allow_knowledge_write_back: bool = False,
    knowledge_ingest: Any | None = None,
) -> dict[str, Any]:
    articles = articles or []
    verification = cross_verify_sources(articles)
    # Normalize + dedupe by title hash
    seen: set[str] = set()
    events: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        # Batch near-dedupe by title; persistent store still keys exact content_hash.
        digest = _sha(title.lower())
        content_hash = _sha(title.lower() + "|" + str(article.get("summary") or "")[:200].lower())
        if digest in seen:
            continue
        seen.add(digest)
        event_type = classify_catalyst(title + " " + str(article.get("summary") or ""))
        entities = list(article.get("entities") or [])
        if symbol and symbol not in entities:
            entities.append(symbol)
        company = guess_company(title)
        if company and company not in entities:
            entities.append(company)
        base_conf = float(article.get("confidence") or 0.55)
        if verification.get("verified"):
            base_conf = min(1.0, base_conf + 0.1 * float(verification.get("agreement_ratio") or 0))
        event = store.save_market_event(
            {
                "event_type": event_type,
                "title": title,
                "summary": str(article.get("summary") or "")[:2000],
                "entities": entities,
                "affected_entities": entities,
                "source_count": int(article.get("source_count") or 1),
                "confidence": base_conf,
                "novelty": float(article.get("novelty") or 0.5),
                "first_seen": article.get("first_seen") or utc_now(),
                "likely_horizon": article.get("likely_horizon") or horizon_for(event_type),
                "historical_analogues": article.get("analogues") or [],
                "supporting_evidence": [
                    {
                        "title": title,
                        "uri": article.get("uri") or article.get("url"),
                        "source": article.get("source"),
                    }
                ],
                "metadata": {
                    "symbol": symbol,
                    "raw_impact": article.get("impact"),
                    "cross_verify": verification,
                    "paper_only": True,
                },
                "content_hash": content_hash,
            }
        )
        analogues = find_event_analogues(store, event, limit=5)
        if analogues:
            event = {**event, "historical_analogues": analogues, "analogues_computed": True}
        # Mirror into temporal graph
        for ent in entities[:8]:
            store.add_graph_edge(
                {
                    "source_id": f"event:{event['id']}",
                    "target_id": f"entity:{ent}",
                    "relation": "affected_by",
                    "relation_kind": "affected_by",
                    "observed_at": event["first_seen"],
                    "confidence": event["confidence"],
                    "provenance": f"finance_fusion:{event['id']}",
                    "source_ref": article.get("uri") or "",
                }
            )
        event["event_study"] = event_study_stub(event)
        events.append(event)

    if not events:
        return {
            "ok": False,
            "error": "no_articles_to_fuse",
            "events": [],
            "count": 0,
            "note": "no_articles_to_fuse",
            "cross_verify": verification,
            "paper_only": True,
        }

    hypothesis = {
        "statement": f"{len(events)} structurele events geëxtraheerd" + (f" voor {symbol}" if symbol else ""),
        "top_event_types": sorted({e["event_type"] for e in events}),
        "paper_only": True,
        "cross_verify": verification,
    }
    proposal = propose_paper_strategy(events, symbol=symbol)
    claim_eval = evaluate_finance_claim(
        hypothesis["statement"],
        evidence=[str(e.get("title") or "") for e in events],
        events=events,
    )
    thesis_row = persist_thesis(store, proposal["thesis"], symbol=symbol)
    knowledge_write = maybe_knowledge_write_back_from_finance(
        events,
        verification=verification,
        symbol=symbol,
        allow_write_back=bool(allow_knowledge_write_back),
        knowledge_ingest=knowledge_ingest,
    )
    return {
        "ok": True,
        "events": events,
        "count": len(events),
        "hypothesis": hypothesis,
        "paper_strategy_proposal": proposal,
        "thesis_persisted": thesis_row,
        "claim_evaluation": claim_eval,
        "cross_verify": verification,
        "knowledge_write_back": knowledge_write,
        "paper_only": True,
    }
