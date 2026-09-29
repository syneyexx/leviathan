"""Canonical trading-context assembly — ONE fabric, not a second Brain.

Assembles bounded, provenance-aware references for trade agents from:
BrainAccessFacade, TradingBrainAdapter, RoleAwareTradingKnowledge,
StrategyMemory, Evidence, MarketSim state.

Context never gains execution authority. RiskGuard remains deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class TradingContextRequest:
    """Unified request a trade agent uses to assemble intelligence."""

    role: str
    objective: str = ""
    symbols: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    asset_classes: list[str] = field(default_factory=list)
    timeframe: str | None = None
    regime: str | None = None
    decision_as_of: str | None = None
    strategy_family: str | None = None
    portfolio_id: str | None = None
    experiment_id: str | None = None
    lab_id: str | None = None
    max_refs_per_source: int = 6

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "symbols": list(self.symbols),
            "instruments": list(self.instruments),
            "assetClasses": list(self.asset_classes),
            "timeframe": self.timeframe,
            "regime": self.regime,
            "decisionAsOf": self.decision_as_of,
            "strategyFamily": self.strategy_family,
            "portfolioId": self.portfolio_id,
            "experimentId": self.experiment_id,
            "labId": self.lab_id,
            "maxRefsPerSource": self.max_refs_per_source,
            "truth": {
                "contextIsNotExecutionAuthority": True,
                "riskGuardRemainsDeterministic": True,
                "noFutureLeakage": True,
            },
        }


@dataclass
class TradingContextRef:
    """One provenance-bearing reference in the assembled context."""

    source_kind: str
    ref_id: str
    title: str = ""
    excerpt: str = ""
    available_at: str | None = None
    dataset_version: str | None = None
    trust: str | None = None
    score: float | None = None
    rejected: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceKind": self.source_kind,
            "refId": self.ref_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "availableAt": self.available_at,
            "datasetVersion": self.dataset_version,
            "trust": self.trust,
            "score": self.score,
            "rejected": self.rejected,
            "evidenceRefs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
            "provenance": {
                "sourceKind": self.source_kind,
                "refId": self.ref_id,
                "availableAt": self.available_at,
            },
        }


@dataclass
class TradingContextBundle:
    """Bounded role-scoped trading context — advisory only."""

    request: TradingContextRequest
    knowledge: list[TradingContextRef] = field(default_factory=list)
    books: list[TradingContextRef] = field(default_factory=list)
    datasets: list[TradingContextRef] = field(default_factory=list)
    research_reports: list[TradingContextRef] = field(default_factory=list)
    evidence: list[TradingContextRef] = field(default_factory=list)
    memory: list[TradingContextRef] = field(default_factory=list)
    strategy_memory: list[TradingContextRef] = field(default_factory=list)
    rejected_strategies: list[TradingContextRef] = field(default_factory=list)
    successful_strategies: list[TradingContextRef] = field(default_factory=list)
    market_data: list[TradingContextRef] = field(default_factory=list)
    regime_state: list[TradingContextRef] = field(default_factory=list)
    portfolio_risk: list[TradingContextRef] = field(default_factory=list)
    external_capability: list[TradingContextRef] = field(default_factory=list)
    fincept: list[TradingContextRef] = field(default_factory=list)
    postmortems: list[TradingContextRef] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)

    def all_refs(self) -> list[TradingContextRef]:
        buckets = (
            self.knowledge,
            self.books,
            self.datasets,
            self.research_reports,
            self.evidence,
            self.memory,
            self.strategy_memory,
            self.rejected_strategies,
            self.successful_strategies,
            self.market_data,
            self.regime_state,
            self.portfolio_risk,
            self.external_capability,
            self.fincept,
            self.postmortems,
        )
        out: list[TradingContextRef] = []
        for bucket in buckets:
            out.extend(bucket)
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.public_dict(),
            "knowledge": [r.public_dict() for r in self.knowledge],
            "books": [r.public_dict() for r in self.books],
            "datasets": [r.public_dict() for r in self.datasets],
            "researchReports": [r.public_dict() for r in self.research_reports],
            "evidence": [r.public_dict() for r in self.evidence],
            "memory": [r.public_dict() for r in self.memory],
            "strategyMemory": [r.public_dict() for r in self.strategy_memory],
            "rejectedStrategies": [r.public_dict() for r in self.rejected_strategies],
            "successfulStrategies": [r.public_dict() for r in self.successful_strategies],
            "marketData": [r.public_dict() for r in self.market_data],
            "regimeState": [r.public_dict() for r in self.regime_state],
            "portfolioRisk": [r.public_dict() for r in self.portfolio_risk],
            "externalCapability": [r.public_dict() for r in self.external_capability],
            "fincept": [r.public_dict() for r in self.fincept],
            "postmortems": [r.public_dict() for r in self.postmortems],
            "citations": list(self.citations),
            "notes": list(self.notes),
            "truth": {
                "contextIsNotExecutionAuthority": True,
                "riskGuardRemainsDeterministic": True,
                "citationsSurviveIntoDecisionRecord": True,
                "noSecondBrain": True,
            },
        }


def _hit_to_ref(hit: Any, *, source_kind: str | None = None) -> TradingContextRef:
    if isinstance(hit, dict):
        kind = source_kind or str(hit.get("sourceKind") or hit.get("source_kind") or "knowledge")
        return TradingContextRef(
            source_kind=kind,
            ref_id=str(hit.get("documentId") or hit.get("document_id") or hit.get("refId") or hit.get("ref_id") or ""),
            title=str(hit.get("title") or ""),
            excerpt=str(hit.get("contentExcerpt") or hit.get("content_excerpt") or hit.get("excerpt") or "")[:500],
            available_at=hit.get("availableAt") or hit.get("available_at"),
            dataset_version=str(hit.get("datasetVersion") or hit.get("dataset_version") or "") or None,
            trust=hit.get("trust"),
            score=hit.get("score"),
            rejected=bool(hit.get("rejected")),
            evidence_refs=list(hit.get("evidenceRefs") or hit.get("evidence_refs") or []),
            metadata={
                "strategyId": hit.get("strategyId") or hit.get("strategy_id"),
                "epistemicState": hit.get("epistemicState") or hit.get("epistemic_state"),
                "validationStage": hit.get("validationStage") or hit.get("validation_stage"),
            },
        )
    d = hit.public_dict() if hasattr(hit, "public_dict") else {}
    return _hit_to_ref(d, source_kind=source_kind or getattr(hit, "source_kind", None))


def _pit_keep(ref: TradingContextRef, *, decision_as_of: str | None) -> bool:
    if not decision_as_of or not ref.available_at:
        return True
    return str(ref.available_at) <= str(decision_as_of)


@dataclass
class TradingContextFabric:
    """Assembles TradingContextBundle from existing canonical owners.

    Does NOT create a second Brain, Agent Fleet, or Knowledge DB.
    """

    role_knowledge: Any | None = None
    trading_brain: Any | None = None
    brain_facade: Any | None = None
    strategy_memory_lister: Callable[..., Sequence[dict[str, Any]]] | None = None
    evidence_lister: Callable[..., Sequence[dict[str, Any]]] | None = None
    dataset_lister: Callable[..., Sequence[dict[str, Any]]] | None = None
    fincept_lister: Callable[..., Sequence[dict[str, Any]]] | None = None
    market_state_reader: Callable[..., dict[str, Any] | None] | None = None
    portfolio_reader: Callable[..., dict[str, Any] | None] | None = None
    lesson_retriever: Callable[..., Sequence[dict[str, Any]]] | None = None

    def assemble(self, request: TradingContextRequest) -> TradingContextBundle:
        from .role_knowledge import ROLE_KNOWLEDGE_INTENTS, RoleAwareTradingKnowledge

        bundle = TradingContextBundle(request=request)
        limit = max(1, min(int(request.max_refs_per_source), 24))
        as_of = request.decision_as_of
        role = str(request.role or "market_analyst")
        intent = ROLE_KNOWLEDGE_INTENTS.get(role)

        query_parts = [request.objective or role]
        query_parts.extend(request.symbols[:8])
        if request.regime:
            query_parts.append(f"regime:{request.regime}")
        if request.strategy_family:
            query_parts.append(f"strategy:{request.strategy_family}")
        query = " ".join(str(p) for p in query_parts if p)

        # Role-aware trading knowledge (preferred path)
        role_adapter = self.role_knowledge
        if role_adapter is None and self.trading_brain is not None:
            role_adapter = RoleAwareTradingKnowledge(self.trading_brain)
        if role_adapter is not None and hasattr(role_adapter, "retrieve_for_role"):
            try:
                result = role_adapter.retrieve_for_role(
                    role,
                    query,
                    symbols=list(request.symbols),
                    decision_as_of=as_of,
                    max_hits=limit,
                    regime=request.regime,
                    strategy_family=request.strategy_family,
                    extra_terms=list(request.asset_classes)[:4]
                    + ([request.timeframe] if request.timeframe else []),
                )
                # RoleAwareTradingKnowledge returns a public dict with citations + result.hits.
                if isinstance(result, dict):
                    hit_rows = list((result.get("result") or {}).get("hits") or [])
                    if not hit_rows:
                        hit_rows = list(result.get("hits") or [])
                    if not hit_rows:
                        for cite in list(result.get("citations") or []):
                            if isinstance(cite, dict) and cite.get("hit"):
                                hit_rows.append(cite["hit"])
                else:
                    hit_rows = list(getattr(result, "hits", None) or [])
                for hit in hit_rows[:limit]:
                    ref = _hit_to_ref(hit, source_kind="knowledge")
                    if not _pit_keep(ref, decision_as_of=as_of):
                        bundle.notes.append(f"dropped_future_leak:{ref.ref_id}")
                        continue
                    kind = (ref.metadata.get("epistemicState") or "").upper()
                    title_l = (ref.title + " " + ref.excerpt).lower()
                    src = str(
                        (hit.get("sourceKind") if isinstance(hit, dict) else getattr(hit, "source_kind", ""))
                        or ref.source_kind
                        or ""
                    ).lower()
                    if ref.rejected or "reject" in title_l or kind == "REJECTED":
                        bundle.rejected_strategies.append(ref)
                    elif "postmortem" in title_l or "lesson" in title_l:
                        bundle.postmortems.append(ref)
                    elif "memory" in src and "strategy" not in src:
                        bundle.memory.append(ref)
                    elif "strategy_memory" in src:
                        bundle.strategy_memory.append(ref)
                        if ref.rejected:
                            bundle.rejected_strategies.append(ref)
                        else:
                            bundle.successful_strategies.append(ref)
                    elif "book" in title_l or "chapter" in title_l:
                        bundle.books.append(ref)
                    elif "dataset" in title_l:
                        bundle.datasets.append(ref)
                    elif "research" in title_l or "report" in title_l:
                        bundle.research_reports.append(ref)
                    elif "fincept" in title_l:
                        bundle.fincept.append(ref)
                    else:
                        bundle.knowledge.append(ref)
                    bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"role_knowledge_error:{exc}")

        # BrainAccessFacade (general One-Brain) — optional enrichment
        if self.brain_facade is not None and hasattr(self.brain_facade, "gather"):
            try:
                from Data.modules.brain.contracts import BrainContextRequest

                brain_req = BrainContextRequest(
                    goal=request.objective or query,
                    domain="trading",
                    role=role,
                    queries=[query],
                    symbols=list(request.symbols),
                    result_limits={"knowledge": limit, "memory": limit, "evidence": limit, "experience": limit},
                    metadata={"decision_as_of": as_of, "regime": request.regime, "strategy_family": request.strategy_family},
                )
                brain_res = self.brain_facade.gather(brain_req)
                public = brain_res.public_dict() if hasattr(brain_res, "public_dict") else dict(brain_res or {})
                for key, bucket_name in (
                    ("knowledge", "knowledge"),
                    ("memory", "memory"),
                    ("evidence", "evidence"),
                    ("experience", "postmortems"),
                ):
                    for item in list(public.get(key) or [])[:limit]:
                        item_d = item if isinstance(item, dict) else (
                            item.public_dict() if hasattr(item, "public_dict") else {}
                        )
                        ref = _hit_to_ref(item_d, source_kind=key)
                        if not ref.ref_id:
                            ref.ref_id = str(item_d.get("refId") or item_d.get("ref_id") or "")
                            ref.title = str(item_d.get("title") or item_d.get("summary") or "")
                            ref.excerpt = str(
                                item_d.get("excerpt") or item_d.get("content") or item_d.get("statement") or ""
                            )[:500]
                        if not _pit_keep(ref, decision_as_of=as_of):
                            continue
                        getattr(bundle, bucket_name).append(ref)
                        bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"brain_facade_error:{exc}")

        # StrategyMemory direct (successes + rejected)
        if self.strategy_memory_lister is not None:
            try:
                rows = list(self.strategy_memory_lister(as_of_ts=as_of, limit=limit * 2) or [])
                for row in rows:
                    ref = TradingContextRef(
                        source_kind="strategy_memory",
                        ref_id=str(row.get("memory_id") or ""),
                        title=str(row.get("strategy_id") or "strategy"),
                        excerpt=str(row.get("outcome_summary") or "")[:500],
                        available_at=row.get("available_at"),
                        trust=str((row.get("metadata") or {}).get("epistemic_state") or ("REJECTED" if row.get("rejected") else "MEASURED")),
                        rejected=bool(row.get("rejected")),
                        evidence_refs=list((row.get("metadata") or {}).get("evidence_refs") or []),
                        metadata={"strategyVersion": row.get("strategy_version")},
                    )
                    if not _pit_keep(ref, decision_as_of=as_of):
                        continue
                    bundle.strategy_memory.append(ref)
                    if ref.rejected:
                        bundle.rejected_strategies.append(ref)
                    else:
                        bundle.successful_strategies.append(ref)
                    bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"strategy_memory_error:{exc}")

        # Prior postmortem lessons
        if self.lesson_retriever is not None:
            try:
                for lesson in list(self.lesson_retriever() or [])[:limit]:
                    ref = TradingContextRef(
                        source_kind="postmortem",
                        ref_id=str(lesson.get("lesson_id") or ""),
                        title="lesson",
                        excerpt=str(lesson.get("claim") or "")[:500],
                        available_at=lesson.get("available_at"),
                        trust=str(lesson.get("trust") or "AGENT_PROPOSED"),
                        rejected=bool(lesson.get("rejected")),
                        evidence_refs=list(lesson.get("evidence_refs") or []),
                        metadata={"failureCategories": lesson.get("failure_categories") or []},
                    )
                    if not _pit_keep(ref, decision_as_of=as_of):
                        continue
                    bundle.postmortems.append(ref)
                    bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"lesson_error:{exc}")

        if self.evidence_lister is not None:
            try:
                for row in list(self.evidence_lister(limit=limit) or [])[:limit]:
                    ref = TradingContextRef(
                        source_kind="evidence",
                        ref_id=str(row.get("evidence_id") or row.get("ref_id") or ""),
                        title=str(row.get("kind") or "evidence"),
                        excerpt=str(row.get("summary") or "")[:500],
                        available_at=row.get("available_at") or row.get("created_at"),
                        trust=str(row.get("status") or ""),
                    )
                    if _pit_keep(ref, decision_as_of=as_of):
                        bundle.evidence.append(ref)
                        bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"evidence_error:{exc}")

        if self.dataset_lister is not None:
            try:
                for row in list(self.dataset_lister(limit=limit) or [])[:limit]:
                    ref = TradingContextRef(
                        source_kind="dataset",
                        ref_id=str(row.get("dataset_id") or ""),
                        title=str(row.get("symbol") or row.get("dataset_id") or "dataset"),
                        excerpt=f"version={row.get('version')} bars={row.get('bar_count')}",
                        available_at=row.get("sealed_at") or row.get("created_at"),
                        dataset_version=str(row.get("version") or ""),
                        trust=str(row.get("quality_state") or ""),
                    )
                    if _pit_keep(ref, decision_as_of=as_of):
                        bundle.datasets.append(ref)
                        bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"dataset_error:{exc}")

        if self.fincept_lister is not None:
            try:
                for row in list(self.fincept_lister(limit=limit) or [])[:limit]:
                    ref = TradingContextRef(
                        source_kind="fincept",
                        ref_id=str(row.get("artifact_id") or row.get("ref_id") or ""),
                        title=str(row.get("module") or "fincept"),
                        excerpt=str(row.get("summary") or "")[:500],
                        available_at=row.get("available_at") or row.get("created_at"),
                        trust=str(row.get("result_state") or "EXTERNAL"),
                        metadata={
                            "moduleVersion": row.get("module_version"),
                            "command": row.get("command"),
                        },
                    )
                    if _pit_keep(ref, decision_as_of=as_of):
                        bundle.fincept.append(ref)
                        bundle.external_capability.append(ref)
                        bundle.citations.append(ref.public_dict()["provenance"])
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"fincept_error:{exc}")

        if self.market_state_reader is not None:
            try:
                state = self.market_state_reader()
                if state:
                    bundle.regime_state.append(
                        TradingContextRef(
                            source_kind="regime",
                            ref_id=str(state.get("regime_id") or "regime"),
                            title=str(state.get("regime") or "unknown"),
                            excerpt=str(state.get("summary") or state)[:500],
                            available_at=state.get("as_of") or as_of,
                            trust="OBSERVED",
                        )
                    )
                    if state.get("symbol") or request.symbols:
                        bundle.market_data.append(
                            TradingContextRef(
                                source_kind="market_data",
                                ref_id=str(state.get("symbol") or (request.symbols[0] if request.symbols else "market")),
                                title="market_state",
                                excerpt=str(state.get("last_price") or state.get("snapshot") or "")[:500],
                                available_at=state.get("as_of") or as_of,
                                trust="OBSERVED",
                            )
                        )
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"market_state_error:{exc}")

        if self.portfolio_reader is not None:
            try:
                port = self.portfolio_reader()
                if port:
                    bundle.portfolio_risk.append(
                        TradingContextRef(
                            source_kind="portfolio_risk",
                            ref_id=str(port.get("portfolio_id") or request.portfolio_id or "portfolio"),
                            title="portfolio",
                            excerpt=str(port.get("summary") or port)[:500],
                            available_at=port.get("as_of") or as_of,
                            trust="OBSERVED",
                            metadata={"exposure": port.get("exposure"), "drawdown": port.get("drawdown")},
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                bundle.notes.append(f"portfolio_error:{exc}")

        if intent is not None and intent.prefer_negative_experience and not bundle.rejected_strategies:
            bundle.notes.append("prefer_negative_experience_but_none_available")

        # Bound each bucket
        for attr in (
            "knowledge",
            "books",
            "datasets",
            "research_reports",
            "evidence",
            "memory",
            "strategy_memory",
            "rejected_strategies",
            "successful_strategies",
            "market_data",
            "regime_state",
            "portfolio_risk",
            "external_capability",
            "fincept",
            "postmortems",
        ):
            setattr(bundle, attr, list(getattr(bundle, attr))[:limit])

        return bundle
