"""One-Brain runtime access facade — gather bounded context from owners.

Not a second database. Not the graph projection. Authoritative stores remain
in knowledge / memory / evidence / cognition(experience) / execution.
"""

from __future__ import annotations

from typing import Any, Callable

from Data.modules.context.types import estimate_tokens

from .contracts import (
    BrainContext,
    BrainContextRequest,
    BrainEvidenceRef,
    BrainExperienceRef,
    BrainKnowledgeRef,
    BrainMemoryRef,
    BrainSourceRef,
)


class BrainAccessFacade:
    """Unified access fabric over shared LEVIATHAN intelligence owners."""

    def __init__(
        self,
        *,
        knowledge_search: Callable[..., list[Any]] | None = None,
        memory_search: Callable[..., list[Any]] | None = None,
        evidence_list: Callable[..., list[Any]] | None = None,
        experience_search: Callable[..., list[Any]] | None = None,
        capability_list: Callable[[], list[Any]] | None = None,
        run_lookup: Callable[[str], Any | None] | None = None,
    ) -> None:
        self.knowledge_search = knowledge_search
        self.memory_search = memory_search
        self.evidence_list = evidence_list
        self.experience_search = experience_search
        self.capability_list = capability_list
        self.run_lookup = run_lookup

    def gather(self, request: BrainContextRequest) -> BrainContext:
        queries = list(request.queries)
        if request.goal and request.goal.strip() and request.goal.strip() not in queries:
            queries.insert(0, request.goal.strip())
        for symbol in request.symbols[:6]:
            if symbol and symbol not in queries:
                queries.append(symbol)
        for entity in request.entities[:4]:
            if entity and entity not in queries:
                queries.append(entity)

        limits = {
            "knowledge": int(request.result_limits.get("knowledge", 6)),
            "memory": int(request.result_limits.get("memory", 4)),
            "evidence": int(request.result_limits.get("evidence", 4)),
            "experience": int(request.result_limits.get("experience", 3)),
            "capabilities": int(request.result_limits.get("capabilities", 12)),
        }
        dropped: list[str] = []
        provenance: list[BrainSourceRef] = []
        selection_trace: dict[str, Any] = {
            "queries": queries[:8],
            "domain": request.domain,
            "role": request.role,
            "reasons": [],
        }

        knowledge = self._gather_knowledge(queries, limits["knowledge"], request, provenance, dropped, selection_trace)
        memory = self._gather_memory(queries, limits["memory"], request, provenance, dropped, selection_trace)
        evidence: list[BrainEvidenceRef] = []
        if request.include_evidence:
            evidence = self._gather_evidence(queries, limits["evidence"], request, provenance, dropped, selection_trace)
        experience: list[BrainExperienceRef] = []
        if request.include_experience:
            experience = self._gather_experience(
                queries, limits["experience"], request, provenance, dropped, selection_trace
            )

        capabilities: list[dict[str, Any]] = []
        if request.include_capabilities and self.capability_list is not None:
            capabilities = self._gather_capabilities(limits["capabilities"], request, selection_trace)

        project_context: dict[str, Any] = {}
        if request.project_id:
            project_context["projectId"] = request.project_id
        if request.workspace_root:
            project_context["workspaceRoot"] = request.workspace_root
        if request.files:
            project_context["mentionedFiles"] = list(request.files)[:20]
        if request.symbols:
            project_context["mentionedSymbols"] = list(request.symbols)[:20]

        active_task_state: dict[str, Any] = {}
        if request.run_id and self.run_lookup is not None:
            try:
                run = self.run_lookup(request.run_id)
                if run is not None:
                    if hasattr(run, "public_dict"):
                        active_task_state = run.public_dict()
                    elif isinstance(run, dict):
                        active_task_state = dict(run)
            except Exception:  # noqa: BLE001
                dropped.append("run_lookup_failed")

        ctx = BrainContext(
            request=request,
            knowledge=knowledge,
            memory=memory,
            evidence=evidence,
            experience=experience,
            capabilities=capabilities,
            project_context=project_context,
            active_task_state=active_task_state,
            provenance=provenance,
            dropped=dropped,
            selection_trace=selection_trace,
        )
        ctx.token_estimate = self._estimate_tokens(ctx)
        if ctx.token_estimate > max(128, int(request.token_budget)):
            ctx = self._compact_to_budget(ctx, int(request.token_budget))
        return ctx

    def _gather_knowledge(
        self,
        queries: list[str],
        limit: int,
        request: BrainContextRequest,
        provenance: list[BrainSourceRef],
        dropped: list[str],
        trace: dict[str, Any],
    ) -> list[BrainKnowledgeRef]:
        if self.knowledge_search is None or limit <= 0:
            if self.knowledge_search is None:
                dropped.append("knowledge_unavailable")
            return []
        seen: set[str] = set()
        out: list[BrainKnowledgeRef] = []
        for query in queries[:5]:
            if len(out) >= limit:
                break
            try:
                hits = self.knowledge_search(query, limit=max(1, limit - len(out)))
            except TypeError:
                try:
                    hits = self.knowledge_search(query)
                except Exception:  # noqa: BLE001
                    dropped.append(f"knowledge_query_failed:{query[:40]}")
                    continue
            except Exception:  # noqa: BLE001
                dropped.append(f"knowledge_query_failed:{query[:40]}")
                continue
            for hit in hits or []:
                if len(out) >= limit:
                    break
                item = self._normalize_knowledge(hit, query)
                if item.ref_id in seen:
                    continue
                # Domain priority: prefer matching domain tags when present.
                domain_tag = str(item.metadata.get("domain") or item.metadata.get("scope") or "")
                if request.domain and domain_tag and request.domain.lower() not in domain_tag.lower():
                    # Keep but deprioritize — still useful cross-domain knowledge.
                    item.score = (item.score or 0.0) * 0.85
                seen.add(item.ref_id)
                out.append(item)
                provenance.append(
                    BrainSourceRef(
                        kind="knowledge",
                        ref_id=item.ref_id,
                        label=item.title or item.ref_id,
                        score=item.score,
                        reason="retrieval_hit",
                    )
                )
        trace["reasons"].append({"section": "knowledge", "selected": len(out), "limit": limit})
        return out

    def _normalize_knowledge(self, hit: Any, query: str) -> BrainKnowledgeRef:
        if isinstance(hit, BrainKnowledgeRef):
            return hit
        if hasattr(hit, "public_dict"):
            d = hit.public_dict()
        elif isinstance(hit, dict):
            d = hit
        else:
            d = {"id": str(getattr(hit, "id", hit)), "content": str(hit)}
        ref_id = str(d.get("id") or d.get("chunk_id") or d.get("document_id") or d.get("refId") or query)
        excerpt = str(d.get("content") or d.get("text") or d.get("excerpt") or d.get("snippet") or "")[:1200]
        title = str(d.get("title") or d.get("document_title") or d.get("source") or ref_id)[:200]
        score = d.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        return BrainKnowledgeRef(
            ref_id=ref_id,
            title=title,
            excerpt=excerpt,
            source=str(d.get("source") or d.get("corpus") or "knowledge"),
            score=score_f,
            trust=str(d.get("trust") or "knowledge"),
            metadata={k: v for k, v in d.items() if k not in {"content", "text", "excerpt", "snippet"}},
        )

    def _gather_memory(
        self,
        queries: list[str],
        limit: int,
        request: BrainContextRequest,
        provenance: list[BrainSourceRef],
        dropped: list[str],
        trace: dict[str, Any],
    ) -> list[BrainMemoryRef]:
        if self.memory_search is None or limit <= 0:
            if self.memory_search is None:
                dropped.append("memory_unavailable")
            return []
        out: list[BrainMemoryRef] = []
        seen: set[str] = set()
        for query in queries[:4]:
            if len(out) >= limit:
                break
            try:
                hits = self.memory_search(query, limit=max(1, limit - len(out)))
            except TypeError:
                try:
                    hits = self.memory_search(query)
                except Exception:  # noqa: BLE001
                    dropped.append(f"memory_query_failed:{query[:40]}")
                    continue
            except Exception:  # noqa: BLE001
                dropped.append(f"memory_query_failed:{query[:40]}")
                continue
            for hit in hits or []:
                if len(out) >= limit:
                    break
                item = self._normalize_memory(hit)
                if item.ref_id in seen:
                    continue
                if request.memory_scopes and item.scope and item.scope not in request.memory_scopes:
                    continue
                seen.add(item.ref_id)
                out.append(item)
                provenance.append(
                    BrainSourceRef(
                        kind="memory",
                        ref_id=item.ref_id,
                        label=item.content[:80],
                        score=item.score,
                        reason="memory_hit",
                    )
                )
        trace["reasons"].append({"section": "memory", "selected": len(out), "limit": limit})
        return out

    def _normalize_memory(self, hit: Any) -> BrainMemoryRef:
        if isinstance(hit, BrainMemoryRef):
            return hit
        if hasattr(hit, "public_dict"):
            d = hit.public_dict()
        elif isinstance(hit, dict):
            d = hit
        else:
            d = {"id": str(getattr(hit, "id", "mem")), "content": str(hit)}
        return BrainMemoryRef(
            ref_id=str(d.get("id") or d.get("memory_id") or d.get("refId") or "memory"),
            content=str(d.get("content") or d.get("text") or "")[:800],
            kind=str(d.get("kind") or d.get("memory_kind") or ""),
            scope=str(d.get("scope") or d.get("memory_scope") or ""),
            score=float(d["score"]) if d.get("score") is not None else None,
            metadata={k: v for k, v in d.items() if k not in {"content", "text"}},
        )

    def _gather_evidence(
        self,
        queries: list[str],
        limit: int,
        request: BrainContextRequest,
        provenance: list[BrainSourceRef],
        dropped: list[str],
        trace: dict[str, Any],
    ) -> list[BrainEvidenceRef]:
        if self.evidence_list is None or limit <= 0:
            if self.evidence_list is None:
                dropped.append("evidence_unavailable")
            return []
        try:
            raw = self.evidence_list(limit=limit * 2) if callable(self.evidence_list) else []
        except TypeError:
            try:
                raw = self.evidence_list()
            except Exception:  # noqa: BLE001
                dropped.append("evidence_list_failed")
                return []
        except Exception:  # noqa: BLE001
            dropped.append("evidence_list_failed")
            return []
        qblob = " ".join(queries).lower()
        out: list[BrainEvidenceRef] = []
        for hit in raw or []:
            if len(out) >= limit:
                break
            item = self._normalize_evidence(hit)
            hay = f"{item.summary} {item.kind} {item.ref_id}".lower()
            if qblob and not any(tok in hay for tok in qblob.split()[:8] if len(tok) > 2):
                continue
            out.append(item)
            provenance.append(
                BrainSourceRef(
                    kind="evidence",
                    ref_id=item.ref_id,
                    label=item.summary[:80],
                    reason="evidence_match",
                )
            )
        if not out and raw:
            # Fall back to newest evidence when lexical filter yields nothing.
            for hit in (raw or [])[:limit]:
                item = self._normalize_evidence(hit)
                out.append(item)
                provenance.append(
                    BrainSourceRef(
                        kind="evidence",
                        ref_id=item.ref_id,
                        label=item.summary[:80],
                        reason="evidence_recent",
                    )
                )
        _ = request  # reserved for future scope filters
        trace["reasons"].append({"section": "evidence", "selected": len(out), "limit": limit})
        return out

    def _normalize_evidence(self, hit: Any) -> BrainEvidenceRef:
        if isinstance(hit, BrainEvidenceRef):
            return hit
        if hasattr(hit, "public_dict"):
            d = hit.public_dict()
        elif isinstance(hit, dict):
            d = hit
        else:
            d = {"id": str(getattr(hit, "id", "ev")), "summary": str(hit)}
        return BrainEvidenceRef(
            ref_id=str(d.get("id") or d.get("evidence_id") or d.get("refId") or "evidence"),
            kind=str(d.get("kind") or d.get("evidence_kind") or ""),
            summary=str(d.get("summary") or d.get("content") or d.get("description") or "")[:600],
            status=str(d.get("status") or ""),
            metadata={k: v for k, v in d.items() if k not in {"summary", "content", "description"}},
        )

    def _gather_experience(
        self,
        queries: list[str],
        limit: int,
        request: BrainContextRequest,
        provenance: list[BrainSourceRef],
        dropped: list[str],
        trace: dict[str, Any],
    ) -> list[BrainExperienceRef]:
        if self.experience_search is None or limit <= 0:
            if self.experience_search is None:
                dropped.append("experience_unavailable")
            return []
        out: list[BrainExperienceRef] = []
        for query in queries[:3]:
            if len(out) >= limit:
                break
            try:
                hits = self.experience_search(
                    query,
                    domain=request.domain,
                    limit=max(1, limit - len(out)),
                )
            except TypeError:
                try:
                    hits = self.experience_search(query)
                except Exception:  # noqa: BLE001
                    dropped.append(f"experience_query_failed:{query[:40]}")
                    continue
            except Exception:  # noqa: BLE001
                dropped.append(f"experience_query_failed:{query[:40]}")
                continue
            for hit in hits or []:
                if len(out) >= limit:
                    break
                item = self._normalize_experience(hit)
                out.append(item)
                provenance.append(
                    BrainSourceRef(
                        kind="experience",
                        ref_id=item.ref_id,
                        label=item.statement[:80],
                        reason="experience_hint",
                    )
                )
        trace["reasons"].append({"section": "experience", "selected": len(out), "limit": limit})
        return out

    def _normalize_experience(self, hit: Any) -> BrainExperienceRef:
        if isinstance(hit, BrainExperienceRef):
            return hit
        if hasattr(hit, "public_dict"):
            d = hit.public_dict()
        elif isinstance(hit, dict):
            d = hit
        else:
            d = {"id": str(getattr(hit, "id", "xp")), "statement": str(hit)}
        return BrainExperienceRef(
            ref_id=str(d.get("id") or d.get("experience_id") or d.get("refId") or "experience"),
            statement=str(d.get("statement") or d.get("content") or d.get("summary") or "")[:500],
            domain=str(d.get("domain") or ""),
            admitted=bool(d.get("admitted", d.get("admitted_as_hint", False))),
            metadata={k: v for k, v in d.items() if k not in {"statement", "content", "summary"}},
        )

    def _gather_capabilities(
        self,
        limit: int,
        request: BrainContextRequest,
        trace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.capability_list is None:
            return []
        try:
            raw = self.capability_list()
        except Exception:  # noqa: BLE001
            return []
        domain = (request.domain or "").lower()
        role = (request.role or "").lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in raw or []:
            if hasattr(item, "public_dict"):
                d = item.public_dict()
            elif isinstance(item, dict):
                d = dict(item)
            else:
                d = {"id": str(getattr(item, "id", item))}
            cap_id = str(d.get("id") or d.get("capability_id") or "")
            score = 0
            if domain and domain in cap_id.lower():
                score += 3
            if role and role in cap_id.lower():
                score += 2
            if domain == "coding" and any(
                tok in cap_id for tok in ("file.", "workspace.", "git.", "coding.", "knowledge.search")
            ):
                score += 2
            scored.append((score, d))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
        selected = [d for s, d in scored if s > 0][:limit]
        if not selected:
            selected = [d for _, d in scored[: min(limit, 8)]]
        trace["reasons"].append({"section": "capabilities", "selected": len(selected), "limit": limit})
        return selected

    def _estimate_tokens(self, ctx: BrainContext) -> int:
        blob_parts = [
            *(k.excerpt for k in ctx.knowledge),
            *(m.content for m in ctx.memory),
            *(e.summary for e in ctx.evidence),
            *(x.statement for x in ctx.experience),
        ]
        return estimate_tokens("\n".join(blob_parts))

    def _compact_to_budget(self, ctx: BrainContext, budget: int) -> BrainContext:
        """Drop lowest-priority tails until under budget; never silently invent content."""
        # Priority: knowledge > evidence > memory > experience
        while self._estimate_tokens(ctx) > budget:
            if ctx.experience:
                dropped = ctx.experience.pop()
                ctx.dropped.append(f"experience:{dropped.ref_id}:budget")
                continue
            if len(ctx.memory) > 1:
                dropped = ctx.memory.pop()
                ctx.dropped.append(f"memory:{dropped.ref_id}:budget")
                continue
            if len(ctx.evidence) > 1:
                dropped = ctx.evidence.pop()
                ctx.dropped.append(f"evidence:{dropped.ref_id}:budget")
                continue
            if len(ctx.knowledge) > 1:
                dropped = ctx.knowledge.pop()
                ctx.dropped.append(f"knowledge:{dropped.ref_id}:budget")
                continue
            break
        ctx.token_estimate = self._estimate_tokens(ctx)
        return ctx
