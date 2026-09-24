"""Specialist delegation handlers — connect coding/research without a second runtime."""

from __future__ import annotations

from typing import Any, Callable

from .delegation import DelegateRequest, DelegateResult, DelegationService


def build_coding_handler(coding_service: Any) -> Callable[[DelegateRequest], DelegateResult]:
    """Create a coding session under parent authority; do not bypass gateway/approvals."""

    def handler(request: DelegateRequest) -> DelegateResult:
        # Idempotency: if parent already recorded a session for this delegation, reuse.
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
            # Session exists — report partial rather than inventing success.
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
    """Create + plan a research project under parent authority."""

    def handler(request: DelegateRequest) -> DelegateResult:
        prior = (request.metadata or {}).get("existing_project_id")
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
        try:
            project = research_service.create_project(
                topic=request.goal,
                objective=request.expected_output or request.goal,
                allow_web=bool((request.metadata or {}).get("allow_web", False)),
            )
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
        return DelegateResult(
            delegation_id=request.delegation_id,
            status="COMPLETED",
            summary=f"research project {project.project_id} planned ({len(subqs)} subquestions)",
            artifact_refs=[f"research_project:{project.project_id}"],
            evidence_refs=[],
            observations=[
                {
                    "kind": "research_plan",
                    "subquestions": subqs[:8],
                    "project_id": project.project_id,
                }
            ],
            resource_use={"projects_created": 1},
            metadata={
                "project_id": project.project_id,
                "authority_ceiling": request.authority_ceiling,
                "parent_trace_id": request.parent_trace_id,
                "side_effect_duplicated": False,
                "plan_rounds": getattr(project, "total_rounds", None),
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
