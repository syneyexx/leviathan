"""Specialist delegation handlers — connect coding/research without a second runtime."""

from __future__ import annotations

from typing import Any, Callable

from .delegation import DelegateRequest, DelegateResult, DelegationService


def build_coding_handler(coding_service: Any) -> Callable[[DelegateRequest], DelegateResult]:
    """Create a coding session under parent authority; do not bypass gateway/approvals."""

    def handler(request: DelegateRequest) -> DelegateResult:
        prior = (request.metadata or {}).get("existing_session_id")
        if prior:
            try:
                session = coding_service.get_session(str(prior))
                child_status = getattr(
                    getattr(session, "status", None), "value", str(getattr(session, "status", "RUNNING"))
                )
                # Reuse is not completion unless the child is already terminal-success.
                if child_status == "COMPLETED":
                    status = "COMPLETED"
                elif child_status in {"FAILED", "CANCELLED", "DISABLED"}:
                    status = child_status
                elif child_status in {"UNVERIFIED", "PARTIAL", "RESOURCE_EXHAUSTED"}:
                    status = child_status
                elif child_status == "WAITING_APPROVAL":
                    status = "WAITING_APPROVAL"
                else:
                    status = "RUNNING"
                return DelegateResult(
                    delegation_id=request.delegation_id,
                    status=status,
                    summary=f"reused coding session {session.session_id} ({child_status})",
                    artifact_refs=[f"coding_session:{session.session_id}"],
                    evidence_refs=[],
                    resource_use={"reused": True},
                    metadata={
                        "session_id": session.session_id,
                        "child_status": child_status,
                        "idempotent": True,
                        "side_effect_duplicated": False,
                        "started_is_not_completed": True,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            session = coding_service.create_session(
                goal=request.goal,
                conversation_id=(request.metadata or {}).get("conversation_id"),
                title=f"delegated:{request.goal[:60]}",
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", type(exc).__name__)
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="FAILED",
                summary="coding session create failed",
                error=f"{code}: {exc}",
                unresolved_issues=["coding_create_failed"],
            )
        status = getattr(getattr(session, "status", None), "value", str(getattr(session, "status", "")))
        if status == "DISABLED":
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="UNAVAILABLE",
                summary="coding feature disabled",
                error="CODING_DISABLED",
                unresolved_issues=["coding_disabled"],
                artifact_refs=[f"coding_session:{session.session_id}"],
                metadata={"session_id": session.session_id},
            )
        # Start a non-blocking turn so the specialist is actually scheduled.
        # ACCEPTED/RUNNING — never COMPLETED merely because work was started.
        try:
            coding_service.start_turn(session.session_id, message=request.goal)
        except Exception as exc:  # noqa: BLE001
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="PARTIAL",
                summary=f"coding session created; turn start failed: {exc}",
                artifact_refs=[f"coding_session:{session.session_id}"],
                unresolved_issues=["coding_turn_start_failed"],
                error=str(exc),
                metadata={"session_id": session.session_id, "started_is_not_completed": True},
            )
        return DelegateResult(
            delegation_id=request.delegation_id,
            status="ACCEPTED",
            summary=f"coding session {session.session_id} accepted and scheduled under parent authority",
            artifact_refs=[f"coding_session:{session.session_id}"],
            evidence_refs=[],
            resource_use={"sessions_created": 1},
            metadata={
                "session_id": session.session_id,
                "child_status": "RUNNING",
                "authority_ceiling": request.authority_ceiling,
                "parent_trace_id": request.parent_trace_id,
                "side_effect_duplicated": False,
                "started_is_not_completed": True,
            },
        )

    return handler


def build_research_handler(research_service: Any) -> Callable[[DelegateRequest], DelegateResult]:
    """Create + plan (+ optionally run) a research project under parent authority.

    Chat → CognitiveRuntime → research specialist → ResearchService — the real
    research subsystem, not a lightweight fake path.
    """

    def handler(request: DelegateRequest) -> DelegateResult:
        meta = dict(request.metadata or {})
        prior = meta.get("existing_project_id")
        if prior:
            try:
                project = research_service.get_project(str(prior))
                return DelegateResult(
                    delegation_id=request.delegation_id,
                    status="COMPLETED",
                    summary=f"reused research project {project.project_id}",
                    artifact_refs=[f"research_project:{project.project_id}"],
                    metadata={
                        "project_id": project.project_id,
                        "idempotent": True,
                        "side_effect_duplicated": False,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        research_mode = str(meta.get("research_mode") or "none").lower()
        allow_web = bool(meta.get("allow_web", False))
        hard_constraints = list(meta.get("hard_constraints") or [])
        # Only auto-run when parent explicitly requests assisted/deep research.
        run_now = bool(
            meta.get(
                "run_now",
                research_mode in {"deep", "assisted", "maximum"},
            )
        )

        try:
            create_kwargs: dict[str, Any] = {
                "topic": request.goal,
                "objective": request.expected_output or request.goal,
                "allow_web": allow_web,
            }
            # Prefer deeper presets for deep research when service accepts depth.
            if research_mode in {"deep", "maximum", "assisted"}:
                try:
                    from Data.modules.research.types import ResearchDepth

                    if research_mode == "maximum":
                        create_kwargs["depth"] = ResearchDepth.EXPERT
                    elif research_mode == "deep":
                        create_kwargs["depth"] = ResearchDepth.DEEP
                    else:
                        create_kwargs["depth"] = ResearchDepth.QUICK
                except Exception:  # noqa: BLE001
                    pass
            project = research_service.create_project(**create_kwargs)
            edits: dict[str, Any] = {}
            if hard_constraints:
                edits["exclusion_criteria"] = [
                    *(getattr(getattr(project, "plan", None), "exclusion_criteria", None) or []),
                    *[f"Hard constraint: {c}" for c in hard_constraints],
                ]
                edits["assumptions"] = [
                    "Hard constraints from parent cognitive task must be preserved",
                    *hard_constraints,
                ]
            if edits:
                project = research_service.plan(project.project_id, edits=edits)
            else:
                project = research_service.plan(project.project_id)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", type(exc).__name__)
            return DelegateResult(
                delegation_id=request.delegation_id,
                status="FAILED",
                summary="research project create/plan failed",
                error=f"{code}: {exc}",
                unresolved_issues=["research_create_failed"],
            )

        plan = getattr(project, "plan", None)
        subqs = list(getattr(plan, "subquestions", None) or []) if plan is not None else []
        observations: list[dict[str, Any]] = [
            {
                "kind": "research_plan",
                "subquestions": subqs[:8],
                "project_id": project.project_id,
                "research_mode": research_mode,
            }
        ]
        evidence_refs: list[str] = []
        report_summary = None
        status = "COMPLETED"
        unresolved: list[str] = []

        if run_now:
            try:
                # Synchronous run through ResearchService — prefer durable enqueue when
                # external workers are enabled (never block cognition on deep Research).
                if hasattr(research_service, "run") and callable(research_service.run):
                    project = research_service.run(project.project_id, background=True)
                project = research_service.get_project(project.project_id)
                st = getattr(getattr(project, "status", None), "value", str(getattr(project, "status", "")))
                if st == "completed":
                    status = "COMPLETED"
                elif st in {"failed", "cancelled"}:
                    status = "FAILED" if st == "failed" else "PARTIAL"
                    unresolved.append(f"research_{st}")
                elif st in {"queued", "researching", "synthesizing", "planned", "draft"}:
                    status = "WAITING"
                    unresolved.append("research_external_pending")
                    observations.append(
                        {
                            "kind": "research_queued",
                            "project_id": project.project_id,
                            "status": st,
                        }
                    )
                else:
                    status = "PARTIAL"
                    unresolved.append("research_incomplete")

                if hasattr(research_service, "get_report"):
                    try:
                        report = research_service.get_report(project.project_id)
                        if report is not None:
                            body = getattr(report, "body_markdown", None) or ""
                            report_summary = body[:4000]
                            observations.append(
                                {
                                    "kind": "research_report",
                                    "report_id": getattr(report, "report_id", None),
                                    "excerpt": body[:1500],
                                }
                            )
                    except Exception:  # noqa: BLE001
                        pass

                if hasattr(research_service, "list_evidence"):
                    try:
                        ev = research_service.list_evidence(project.project_id) or []
                        for item in ev[:20]:
                            eid = getattr(item, "evidence_id", None) or (
                                item.get("evidence_id") if isinstance(item, dict) else None
                            )
                            if eid:
                                evidence_refs.append(f"e:{eid}")
                    except Exception:  # noqa: BLE001
                        pass

                if hasattr(research_service, "coverage"):
                    try:
                        cov = research_service.coverage(project.project_id)
                        cov_dict = cov.public_dict() if hasattr(cov, "public_dict") else dict(cov or {})
                        observations.append({"kind": "research_coverage", "coverage": cov_dict})
                        unresolved.extend(list(cov_dict.get("unresolved_questions") or [])[:6])
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                status = "PARTIAL"
                unresolved.append("research_run_failed")
                observations.append({"kind": "research_error", "error": str(exc)})

        summary = f"research project {project.project_id} planned ({len(subqs)} subquestions)"
        if run_now:
            summary = (
                f"research project {project.project_id} {status.lower()} "
                f"via real ResearchService (mode={research_mode})"
            )
            if report_summary:
                summary = report_summary[:500]

        return DelegateResult(
            delegation_id=request.delegation_id,
            status=status,
            summary=summary,
            artifact_refs=[f"research_project:{project.project_id}"],
            evidence_refs=evidence_refs,
            observations=observations,
            unresolved_issues=unresolved,
            resource_use={"projects_created": 1, "research_run": run_now},
            metadata={
                "project_id": project.project_id,
                "authority_ceiling": request.authority_ceiling,
                "parent_trace_id": request.parent_trace_id,
                "side_effect_duplicated": False,
                "plan_rounds": getattr(project, "total_rounds", None),
                "research_mode": research_mode,
                "allow_web": allow_web,
                "hard_constraints": hard_constraints,
                "report_excerpt": (report_summary or "")[:2000] or None,
            },
        )

    return handler


def register_specialist_handlers(
    delegation: DelegationService,
    *,
    coding_service: Any | None = None,
    research_service: Any | None = None,
) -> list[str]:
    """Register available specialist handlers. Returns registered kinds."""
    registered: list[str] = []
    if coding_service is not None:
        handler = build_coding_handler(coding_service)
        for kind in ("coding", "coding_agent", "coder"):
            delegation.register(kind, handler)
            registered.append(kind)
    if research_service is not None:
        handler = build_research_handler(research_service)
        for kind in ("research", "research_agent", "researcher"):
            delegation.register(kind, handler)
            registered.append(kind)
    return registered
