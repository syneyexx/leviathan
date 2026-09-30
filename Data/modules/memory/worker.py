"""Durable Memory worker handler — consolidation/enrichment/indexing ownership."""

from __future__ import annotations

import re
from typing import Any


def _fail(
    store: Any,
    job: Any,
    error: str,
    *,
    metadata: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=error,
            metadata_update=metadata or {},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"error": error}


def _complete(
    store: Any,
    job: Any,
    result: dict[str, Any],
    *,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        ctx=ctx,
        result=result,
    )
    return result


def _memory_store(ctx: dict[str, Any]) -> Any:
    bound = ctx.get("memory_store")
    if bound is not None:
        return bound
    from Data.modules.common.database_domains import resolve_control_database_path
    from Data.modules.memory import MemoryStore

    settings = ctx.get("settings")
    explicit = None
    if settings is not None:
        explicit = (
            getattr(settings, "control_database_path", None)
            or getattr(settings, "database_path", None)
        )
    # Memory lives on CONTROL domain (existing ownership — no memory.db).
    db_path = resolve_control_database_path(explicit=explicit)
    store = MemoryStore(db_path)
    store.initialize()
    ctx["memory_store"] = store
    return store


def _records_as_dicts(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
            continue
        if hasattr(item, "public_dict"):
            d = dict(item.public_dict())
            if "trust" in d and "trust_state" not in d:
                d["trust_state"] = d["trust"]
            out.append(d)
        else:
            out.append({"content": str(item)})
    return out


def _extract_entities(text: str) -> list[dict[str, str]]:
    """Bounded heuristic entity extraction — projection metadata, not a Knowledge graph."""
    entities: list[dict[str, str]] = []
    # Capitalized multi-word phrases and tickers-ish tokens.
    for match in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        entities.append({"text": match, "type": "PHRASE"})
    for match in re.findall(r"\b([A-Z]{2,6})\b", text):
        if match not in {"NOTE", "FACT", "HTTP", "JSON", "UUID", "TRUE", "FALSE"}:
            entities.append({"text": match, "type": "SYMBOL"})
    # Dedup preserve order, bound.
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for ent in entities:
        key = ent["text"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ent)
        if len(out) >= 24:
            break
    return out


def _index_memories(
    memory: Any,
    ctx: dict[str, Any],
    job: Any,
    *,
    targets: list[Any],
    fence: Any,
) -> dict[str, Any]:
    """Embed eligible memories via embedding provider / child embedding.batch."""
    if not targets:
        return {
            "action": "index",
            "indexed": 0,
            "pending": 0,
            "truth": {"no_work": True},
        }

    from Data.modules.knowledge.embeddings import build_embedding_provider

    settings = ctx.get("settings")
    kind = "auto"
    model_id = None
    if settings is not None:
        knowledge = getattr(settings, "knowledge", None)
        if knowledge is not None:
            kind = str(
                getattr(knowledge, "embedding_provider", None)
                or getattr(knowledge, "embedding_kind", None)
                or "auto"
            )
            model_id = getattr(knowledge, "embedding_model", None)

    provider = ctx.get("embedding_provider") or build_embedding_provider(
        kind=kind, model_name=model_id
    )
    status = provider.status() if hasattr(provider, "status") else {}
    if not provider.available():
        return _fail(
            ctx["job_store"],
            job,
            f"EMBEDDING_BACKEND_UNAVAILABLE: {status.get('reason') or status.get('error') or 'unavailable'}",
            metadata={"memory_action": "index"},
            ctx=ctx,
        )

    is_semantic = bool(getattr(provider, "is_semantic", False) or status.get("is_semantic"))
    # Still index with available provider, but label honesty in result.
    texts = [t.content for t in targets]
    ids = [t.memory_id for t in targets]
    hashes = [memory.content_hash(t.content) for t in targets]

    # Prefer child embedding.batch when JobRuntime is present (production path).
    runtime = ctx.get("job_runtime")
    vectors: list[list[float]] | None = None
    child_job_id = None
    if runtime is not None and hasattr(runtime, "enqueue"):
        try:
            child = runtime.enqueue(
                capability_id="embedding.batch",
                arguments={
                    "texts": texts,
                    "content_hashes": hashes,
                    "model_id": model_id,
                    "memory_ids": ids,
                },
                requested_by=f"memory.index:{getattr(job, 'job_id', '')}",
                domain="embedding",
                worker_pool="embedding",
                resource_class="CPU_HEAVY",
                latency_class="background",
                parent_job_id=getattr(job, "job_id", None),
                metadata={
                    "execution_class": "EXTERNAL_REQUIRED",
                    "memory_index": True,
                },
            )
            child_job_id = getattr(child, "job_id", None)
            # If runtime executes inline in tests, result may already be present.
            result = getattr(child, "result", None) or {}
            if isinstance(result, dict) and result.get("vectors"):
                vectors = result["vectors"]
        except Exception:  # noqa: BLE001 — fall through to direct provider
            child_job_id = None

    if vectors is None:
        if fence():
            return _fail(
                ctx["job_store"],
                job,
                "MEMORY_CANCELLED",
                metadata={"memory_action": "index"},
                ctx=ctx,
            )
        try:
            vectors = provider.embed_documents(texts)
        except Exception as exc:  # noqa: BLE001
            return _fail(
                ctx["job_store"],
                job,
                f"EMBEDDING_FAILED: {type(exc).__name__}: {exc}"[:500],
                metadata={"memory_action": "index"},
                ctx=ctx,
            )

    if vectors is None:
        # Child enqueued asynchronously — commit will happen when child completes
        # via a follow-up enrich, or when inline result arrives. Record pending.
        return {
            "action": "index",
            "queued_embedding_batch": True,
            "child_job_id": child_job_id,
            "pending_memory_ids": ids,
            "count": len(ids),
            "is_semantic": is_semantic,
            "truth": {
                "executed_via": "memory_worker",
                "embedding_owner": "embedding_worker",
                "fastapi_does_not_embed": True,
            },
        }

    if len(vectors) != len(texts):
        return _fail(
            ctx["job_store"],
            job,
            "EMBEDDING_FAILED: vector count mismatch",
            metadata={"memory_action": "index"},
            ctx=ctx,
        )

    committed: list[dict[str, Any]] = []
    provider_id = str(getattr(provider, "provider_id", None) or status.get("provider_id") or "unknown")
    for i, vec in enumerate(vectors):
        if fence():
            return _fail(
                ctx["job_store"],
                job,
                "MEMORY_CANCELLED",
                metadata={"memory_action": "index", "partial": len(committed)},
                ctx=ctx,
            )
        try:
            receipt = memory.upsert_embedding(
                ids[i],
                vector=[float(x) for x in vec],
                provider_id=provider_id,
                model_id=str(model_id) if model_id else None,
                content_hash=hashes[i],
            )
            committed.append(receipt)
        except Exception as exc:  # noqa: BLE001
            committed.append({"memory_id": ids[i], "error": f"{type(exc).__name__}: {exc}"})

    return {
        "action": "index",
        "indexed": len([c for c in committed if "error" not in c]),
        "committed": committed,
        "child_job_id": child_job_id,
        "provider_id": provider_id,
        "is_semantic": is_semantic,
        "truth": {
            "executed_via": "memory_worker",
            "hash_vectors_are_not_semantic_embeddings": not is_semantic,
            "no_second_vector_database": True,
        },
    }


def process_memory_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    """Execute memory.consolidate / memory.enrich / memory.reconcile / index / optimize."""
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    action = str(
        args.get("action")
        or (capability.rsplit(".", 1)[-1] if capability.startswith("memory.") else "")
        or "consolidate"
    ).strip().lower()

    cancel_check = ctx.get("job_cancel_check")
    lease_lost = ctx.get("lease_lost")

    def _fence() -> bool:
        if callable(cancel_check) and cancel_check():
            return True
        if lease_lost is not None and getattr(lease_lost, "is_set", lambda: False)():
            return True
        return False

    try:
        memory = _memory_store(ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"MEMORY_STORE_UNAVAILABLE: {type(exc).__name__}: {exc}",
            metadata={"memory_action": action},
            ctx=ctx,
        )

    if _fence():
        return _fail(
            store,
            job,
            "MEMORY_CANCELLED",
            metadata={"memory_action": action},
            ctx=ctx,
        )

    try:
        from Data.modules.memory import MemoryConsolidator, MemoryKind, MemoryStatus

        limit = min(max(int(args.get("limit") or 500), 1), 5000)
        scope = args.get("scope")
        project_id = args.get("project_id")
        conversation_id = args.get("conversation_id")
        min_cluster = max(int(args.get("min_cluster_size") or 2), 2)
        persist = bool(args.get("persist", True))

        # --- Semantic index / optimize ---
        if action in {"index", "embed", "reindex"}:
            memory_ids = [str(x) for x in (args.get("memory_ids") or []) if x]
            only_missing = bool(args.get("only_missing", False))
            if memory_ids:
                targets = []
                for mid in memory_ids[:limit]:
                    rec = memory.get(mid)
                    if rec is not None and rec.status == MemoryStatus.ACTIVE:
                        targets.append(rec)
            else:
                targets = memory.list_embedding_targets(
                    limit=min(limit, 200),
                    only_missing=only_missing,
                    include_stale=not only_missing,
                )
            result = _index_memories(memory, ctx, job, targets=targets, fence=_fence)
            if "error" in result and len(result) == 1:
                return result
            return _complete(store, job, result, ctx=ctx)

        if action in {"optimize_index", "optimize"}:
            dry_run = bool(args.get("dry_run", False))
            orphans = 0 if dry_run else memory.delete_orphan_embeddings()
            targets = memory.list_embedding_targets(limit=min(limit, 200), only_missing=False)
            indexed = None
            if not dry_run and targets:
                indexed = _index_memories(memory, ctx, job, targets=targets, fence=_fence)
                if "error" in indexed and len(indexed) == 1:
                    return indexed
            result = {
                "action": "optimize_index",
                "dry_run": dry_run,
                "orphans_removed": orphans,
                "pending_reindex": len(targets),
                "index_result": indexed,
                "truth": {
                    "executed_via": "memory_worker",
                    "no_fake_optimize": True,
                },
            }
            memory.record_event(
                "memory.index_optimized",
                actor="Memory Worker",
                detail={"orphans_removed": orphans, "pending": len(targets)},
            )
            return _complete(store, job, result, ctx=ctx)

        list_kwargs: dict[str, Any] = {
            "status": MemoryStatus.ACTIVE,
            "limit": limit,
        }
        if project_id:
            list_kwargs["project_id"] = str(project_id)
        if conversation_id:
            list_kwargs["conversation_id"] = str(conversation_id)
        if scope:
            from Data.modules.memory import MemoryScope

            try:
                list_kwargs["scope"] = MemoryScope(str(scope).upper())
            except ValueError:
                pass

        episodic_raw = list(memory.list(kind=MemoryKind.EPISODIC, **list_kwargs))
        try:
            episodic_raw.extend(list(memory.list(kind=MemoryKind.NOTE, **list_kwargs)))
        except Exception:  # noqa: BLE001
            pass
        if action in {"enrich", "reconcile"}:
            for kind in (MemoryKind.SUMMARY, MemoryKind.FACT):
                try:
                    episodic_raw.extend(list(memory.list(kind=kind, **list_kwargs)))
                except Exception:  # noqa: BLE001
                    pass
        episodic = _records_as_dicts(episodic_raw)
        semantic_raw = list(memory.list(kind=MemoryKind.SUMMARY, **list_kwargs))
        existing = _records_as_dicts(semantic_raw)

        if _fence():
            return _fail(
                store,
                job,
                "MEMORY_CANCELLED",
                metadata={"memory_action": action, "input_count": len(episodic)},
                ctx=ctx,
            )

        if action == "reconcile":
            dry_run = bool(args.get("dry_run", True))
            missing = memory.list_embedding_targets(limit=min(limit, 200), only_missing=True)
            stale = memory.list_embedding_targets(limit=min(limit, 200), only_missing=False)
            duplicates = memory.find_exact_duplicates(limit=100)
            orphans = 0
            if not dry_run:
                orphans = memory.delete_orphan_embeddings()
            result = {
                "action": "reconcile",
                "dry_run": dry_run,
                "episodic_count": len(episodic),
                "semantic_count": len(existing),
                "missing_embeddings": len(missing),
                "stale_or_missing_embeddings": len(stale),
                "duplicate_groups": len(duplicates),
                "orphans_removed": orphans,
                "scope": scope,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "truth": {
                    "no_cross_scope_merge": True,
                    "model_confidence_is_not_memory_truth": True,
                },
            }
            memory.record_event(
                "memory.reconciled",
                actor="Memory Worker",
                detail={"dry_run": dry_run, "missing": len(missing)},
            )
            return _complete(store, job, result, ctx=ctx)

        if action == "enrich":
            # Enrichment: entities, duplicate flags, optional index enqueue, brain projection meta.
            enriched: list[dict[str, Any]] = []
            dup_groups = memory.find_exact_duplicates(limit=50)
            dup_ids = {mid for g in dup_groups for mid in g.get("memory_ids") or []}
            for rec in episodic_raw[: min(limit, 200)]:
                if _fence():
                    return _fail(
                        store,
                        job,
                        "MEMORY_CANCELLED",
                        metadata={"memory_action": action, "partial": len(enriched)},
                        ctx=ctx,
                    )
                entities = _extract_entities(rec.content)
                meta_patch = {
                    "enrichment": {
                        "entities": entities,
                        "duplicate_candidate": rec.memory_id in dup_ids,
                        "enriched_at": __import__(
                            "datetime"
                        ).datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
                    }
                }
                try:
                    memory.update(rec.memory_id, metadata_patch=meta_patch)
                except Exception:  # noqa: BLE001
                    pass
                enriched.append(
                    {
                        "memory_id": rec.memory_id,
                        "entity_count": len(entities),
                        "duplicate_candidate": rec.memory_id in dup_ids,
                    }
                )
            # Optionally index after enrich.
            index_result = None
            if bool(args.get("also_index", True)):
                targets = memory.list_embedding_targets(limit=min(50, limit), only_missing=False)
                if targets:
                    index_result = _index_memories(
                        memory, ctx, job, targets=targets[:50], fence=_fence
                    )
            result = {
                "action": "enrich",
                "enriched": enriched,
                "enriched_count": len(enriched),
                "duplicate_groups": len(dup_groups),
                "index_result": index_result,
                "truth": {
                    "entities_are_projection_not_knowledge_graph": True,
                    "model_confidence_is_not_memory_truth": True,
                    "executed_via": "memory_worker",
                },
            }
            memory.record_event(
                "memory.enriched",
                actor="Memory Worker",
                detail={"count": len(enriched)},
            )
            return _complete(store, job, result, ctx=ctx)

        consolidator = MemoryConsolidator()
        consolidation = consolidator.consolidate(
            episodic,
            existing_semantic=existing,
            min_cluster_size=min_cluster,
        )

        persisted: list[dict[str, Any]] = []
        if persist and action == "consolidate":
            for cand in consolidation.candidates:
                if _fence():
                    return _fail(
                        store,
                        job,
                        "MEMORY_CANCELLED",
                        metadata={
                            "memory_action": action,
                            "partial_candidates": len(persisted),
                        },
                        ctx=ctx,
                    )
                if not cand.admitted:
                    continue
                trust = cand.trust_state.value
                create_kwargs: dict[str, Any] = {
                    "content": cand.content,
                    "kind": MemoryKind.SUMMARY,
                    "source": "consolidation",
                    "trust": trust,
                    "tags": ["consolidation", "derived", "semantic_candidate"],
                    "metadata": {
                        "candidate_id": cand.candidate_id,
                        "source_episodic_ids": list(cand.source_episodic_ids),
                        "provenance": dict(cand.provenance),
                        "contradictions": list(cand.contradictions),
                        "evidence_refs": list(cand.evidence_refs),
                        "admission_reason": cand.admission_reason,
                        "truth": {
                            "model_confidence_is_not_memory_truth": True,
                            "derived_from_consolidation": True,
                        },
                    },
                }
                if conversation_id:
                    create_kwargs["conversation_id"] = str(conversation_id)
                if project_id:
                    create_kwargs["project_id"] = str(project_id)
                if scope:
                    create_kwargs["scope"] = scope
                try:
                    record = memory.create(**create_kwargs)
                    persisted.append(record.public_dict())
                except Exception as exc:  # noqa: BLE001 — skip bad candidate
                    persisted.append(
                        {
                            "error": f"{type(exc).__name__}: {exc}",
                            "candidate_id": cand.candidate_id,
                        }
                    )

        result = {
            "action": action,
            "input_count": len(episodic),
            "existing_semantic_count": len(existing),
            "clusters": len(consolidation.clusters),
            "candidates": [c.public_dict() for c in consolidation.candidates],
            "persisted": persisted if persist else [],
            "persisted_count": len([p for p in persisted if "memory_id" in p or "id" in p]),
            "scope": scope,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "truth": {
                "model_confidence_is_not_memory_truth": True,
                "agent_proposed_until_verified": True,
                "executed_via": "memory_worker",
                "no_fastapi_inline_batch": True,
            },
        }
        memory.record_event(
            "memory.consolidated",
            actor="Memory Worker",
            detail={"persisted": result["persisted_count"]},
        )
        return _complete(store, job, result, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"MEMORY_{action.upper()}_FAILED: {type(exc).__name__}: {exc}"[:500],
            metadata={"memory_action": action},
            ctx=ctx,
        )
