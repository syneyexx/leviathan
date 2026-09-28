"""Durable Memory worker handler — consolidation/enrichment ownership."""

from __future__ import annotations

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
            # Preserve trust_state field name for consolidator.
            if "trust" in d and "trust_state" not in d:
                d["trust_state"] = d["trust"]
            out.append(d)
        else:
            out.append({"content": str(item)})
    return out


def process_memory_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    """Execute memory.consolidate / memory.enrich / memory.reconcile."""
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
        # Also include NOTE when consolidating sparse episodic sets.
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
        # Existing derived semantic candidates are stored as SUMMARY with consolidation tag.
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
            result = {
                "action": "reconcile",
                "dry_run": dry_run,
                "episodic_count": len(episodic),
                "semantic_count": len(existing),
                "scope": scope,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "truth": {
                    "no_cross_scope_merge": True,
                    "model_confidence_is_not_memory_truth": True,
                },
            }
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
                # Never promote AGENT_PROPOSED to VERIFIED via consolidation.
                # Store as SUMMARY (no SEMANTIC kind in taxonomy) with trust gate intact.
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
        return _complete(store, job, result, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            store,
            job,
            f"MEMORY_{action.upper()}_FAILED: {type(exc).__name__}: {exc}"[:500],
            metadata={"memory_action": action},
            ctx=ctx,
        )
