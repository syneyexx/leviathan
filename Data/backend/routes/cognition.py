"""FastAPI routes for the Cognitive Runtime operator surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.cognition import CognitionError, CognitiveRuntime


class CognitionSubmitRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    has_knowledge: bool = False
    shadow: bool | None = None
    constraints: list[str] = Field(default_factory=list)
    run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Optional: pass the same effective BehaviorProfile snapshot Chat uses.
    # When omitted, CognitiveRuntime resolves via Settings behavior_resolver.
    behavior_profile_prompt: str | None = None
    behavior_profile_id: str | None = None
    behavior_profile_version: str | None = None
    behavior_settings_hash: str | None = None
    behavior_source: str | None = None


class CognitionSteerRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


class CandidateGovernRequest(BaseModel):
    operator: str = Field(..., min_length=1, max_length=120)
    note: str = ""


class CandidateIngestRequest(BaseModel):
    operator: str = Field(..., min_length=1, max_length=120)
    mixture_ref: str | None = None
    note: str = ""


def build_cognition_router(
    runtime: CognitiveRuntime,
    *,
    candidate_lifecycle: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["cognition"])

    def _raise(exc: Exception) -> None:
        if isinstance(exc, CognitionError):
            raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc
        if isinstance(exc, KeyError):
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": str(exc)}) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=422, detail={"error": "INVALID", "message": str(exc)}) from exc
        raise

    @router.get("/api/cognition/health")
    def cognition_health() -> dict:
        return {"cognition": runtime.health()}

    @router.post("/api/cognition/submit")
    def cognition_submit(payload: CognitionSubmitRequest) -> dict:
        try:
            return runtime.submit(
                payload.message,
                conversation_id=payload.conversation_id,
                history=payload.history,
                has_knowledge=payload.has_knowledge,
                shadow=payload.shadow,
                constraints=payload.constraints,
                metadata=payload.metadata,
                behavior_profile_prompt=payload.behavior_profile_prompt,
                behavior_profile_id=payload.behavior_profile_id,
                behavior_profile_version=payload.behavior_profile_version,
                behavior_settings_hash=payload.behavior_settings_hash,
                behavior_source=payload.behavior_source,
                run=payload.run,
            )
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/runs/{run_id}")
    def cognition_status(run_id: str) -> dict:
        try:
            return runtime.status(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/runs/{run_id}/events")
    def cognition_events(run_id: str) -> dict:
        try:
            return {"run_id": run_id, "events": runtime.events(run_id)}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/runs/{run_id}/trace")
    def cognition_trace(run_id: str) -> dict:
        """Structured high-level run trace — not private chain-of-thought."""
        try:
            status = runtime.status(run_id)
            events = runtime.events(run_id)
            return {
                "run_id": run_id,
                "trace": {
                    "task": status.get("task"),
                    "mode": (status.get("decision") or {}).get("mode"),
                    "strategy": (status.get("decision") or {}).get("strategy"),
                    "budgets": (status.get("decision") or {}).get("budgets"),
                    "plan": status.get("plan"),
                    "actions": status.get("actions"),
                    "observations": status.get("observations"),
                    "beliefs": status.get("beliefs"),
                    "verification": status.get("verification"),
                    "completion": status.get("completion"),
                    "usage": status.get("usage"),
                    "status": status.get("status"),
                    "events": events,
                },
                "truth": {
                    "trace_is_not_private_cot": True,
                    "rationale_is_orchestration_metadata": True,
                },
            }
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/cancel")
    def cognition_cancel(run_id: str) -> dict:
        try:
            return runtime.cancel(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/steer")
    def cognition_steer(run_id: str, payload: CognitionSteerRequest) -> dict:
        try:
            return runtime.steer(run_id, payload.instruction)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/runs/{run_id}/resume")
    def cognition_resume(run_id: str) -> dict:
        try:
            return runtime.resume(run_id)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/training-export")
    def cognition_training_export(
        include_excluded: bool = False,
        include_active_learning: bool = True,
    ) -> dict:
        """Structured public trajectory bridge — export is not training."""
        try:
            bundle = runtime.export_training_bundle(
                include_excluded=include_excluded,
                include_active_learning=include_active_learning,
            )
            return {"export": bundle}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/training-candidates/sync")
    def cognition_training_candidates_sync() -> dict:
        """Wire export bundle into candidate lifecycle (pending only — not trained)."""
        if candidate_lifecycle is None:
            raise HTTPException(
                status_code=501,
                detail={"reason": "candidate_lifecycle_not_wired"},
            )
        try:
            bundle = runtime.export_training_bundle()
            created = candidate_lifecycle.accept_export_bundle(bundle)
            return {
                "created": [c.public_dict() for c in created],
                "summary": candidate_lifecycle.public_summary(),
                "truth": {
                    "wired_from_cognition_trajectories": True,
                    "auto_promote_forbidden": True,
                    "sync_does_not_train": True,
                },
            }
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.get("/api/cognition/training-candidates")
    def cognition_training_candidates_list(
        phase: str | None = None,
        limit: int = 100,
    ) -> dict:
        if candidate_lifecycle is None:
            raise HTTPException(
                status_code=501,
                detail={"reason": "candidate_lifecycle_not_wired"},
            )
        items = candidate_lifecycle.list_candidates(phase=phase, limit=limit)
        return {
            "candidates": [c.public_dict() for c in items],
            "summary": candidate_lifecycle.public_summary(),
        }

    @router.post("/api/cognition/training-candidates/{candidate_id}/govern")
    def cognition_training_candidate_govern(
        candidate_id: str, payload: CandidateGovernRequest
    ) -> dict:
        if candidate_lifecycle is None:
            raise HTTPException(
                status_code=501,
                detail={"reason": "candidate_lifecycle_not_wired"},
            )
        try:
            cand = candidate_lifecycle.govern(
                candidate_id, operator=payload.operator, note=payload.note
            )
            return {"candidate": cand.public_dict()}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.post("/api/cognition/training-candidates/{candidate_id}/ingest")
    def cognition_training_candidate_ingest(
        candidate_id: str, payload: CandidateIngestRequest
    ) -> dict:
        """Mark governed candidate mixture-ready — does not start training."""
        if candidate_lifecycle is None:
            raise HTTPException(
                status_code=501,
                detail={"reason": "candidate_lifecycle_not_wired"},
            )
        try:
            cand = candidate_lifecycle.mark_ingested(
                candidate_id,
                operator=payload.operator,
                mixture_ref=payload.mixture_ref,
                note=payload.note,
            )
            return {
                "candidate": cand.public_dict(),
                "truth": {
                    "ingested_is_not_trained": True,
                    "auto_promote_forbidden": True,
                },
            }
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    return router
