"""CodingControlPlane — public façade for API and AgentRuntime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.paths import PathEscapeError

from .loop import CodingLoop, FakeLLM
from .planner import build_initial_plan, mission_from_text
from .store import CodingStore
from .types import (
    ACTIVE_STATUSES,
    CodingError,
    CodingSession,
    DEFAULT_FEATURE_TRUTH,
    Mission,
    SessionStatus,
    StepKind,
    StepStatus,
)
from .worker import CodingWorker
from .workspace import ensure_workspace, list_entries, resolve_root


class CodingControlPlane:
    def __init__(
        self,
        store: CodingStore,
        *,
        gateway: Any,
        approvals: Any | None = None,
        loop: CodingLoop | None = None,
        worker: CodingWorker | None = None,
        settings: Any | None = None,
        llm: Any | None = None,
        context_builder: Any | None = None,
        reasoning: Any | None = None,
        neuro: Any | None = None,
        verification: Any | None = None,
        agents_enabled: bool = False,
        coding_enabled: bool = False,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.approvals = approvals
        self.settings = settings
        self.agents_enabled = agents_enabled
        self.coding_enabled = coding_enabled
        self.loop = loop or CodingLoop(
            store,
            gateway=gateway,
            approvals=approvals,
            llm=llm,
            context_builder=context_builder,
            reasoning=reasoning,
            neuro=neuro,
            verification=verification,
            settings=settings,
            agents_enabled=agents_enabled,
            coding_enabled=coding_enabled,
        )
        self.worker = worker or CodingWorker(store, self.loop)

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        db_path: Path,
        gateway: Any,
        approvals: Any | None = None,
        llm: Any | None = None,
        context_builder: Any | None = None,
        reasoning: Any | None = None,
        neuro: Any | None = None,
        verification: Any | None = None,
    ) -> "CodingControlPlane":
        store = CodingStore(db_path)
        store.initialize()
        return cls(
            store,
            gateway=gateway,
            approvals=approvals,
            settings=settings,
            llm=llm,
            context_builder=context_builder,
            reasoning=reasoning,
            neuro=neuro,
            verification=verification,
            agents_enabled=bool(settings.features.agents_enabled),
            coding_enabled=bool(settings.features.coding_enabled),
        )

    # --- lifecycle ----------------------------------------------------------

    def start_background(self) -> None:
        self.worker.start_background()

    def stop_background(self) -> None:
        self.worker.stop_background()

    # --- status -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        catalog_ids: list[str] = []
        if self.gateway is not None:
            catalog_ids = sorted(item.id for item in self.gateway.list_capabilities())
        residual_supported = False
        return {
            "enabled": self.coding_enabled,
            "agents_enabled": self.agents_enabled,
            "workspace_configured": bool(
                str(getattr(getattr(self.settings, "coding", None), "workspace", "") or "").strip()
            ),
            "residual_supported": residual_supported,
            "catalog_ids": catalog_ids,
            "truth": {
                "gateway_only": True,
                "hades_excluded": True,
                "no_private_execution": True,
            },
        }

    # --- sessions -----------------------------------------------------------

    def create_session(
        self,
        *,
        goal: str,
        mission: str | Mission | None = None,
        workspace_root: str | None = None,
        model_id: str | None = None,
        conversation_id: str | None = None,
        title: str | None = None,
    ) -> CodingSession:
        goal_clean = (goal or "").strip()
        if not goal_clean:
            raise CodingError("VALIDATION_ERROR", "goal is required", http_status=422)

        if not self.agents_enabled or not self.coding_enabled:
            flag = "LEVIATHAN_FEATURE_AGENTS" if not self.agents_enabled else "LEVIATHAN_FEATURE_CODING"
            root = str(resolve_root(self.settings, override=workspace_root))
            session = self.store.create_session(
                mission=mission_from_text(mission) if not isinstance(mission, Mission) else mission,
                workspace_root=root,
                title=title or goal_clean[:80],
                user_goal=goal_clean,
                conversation_id=conversation_id,
                model_id=model_id,
                status=SessionStatus.DISABLED,
                feature_truth=dict(DEFAULT_FEATURE_TRUTH),
                metadata={"disabled_flag": flag},
            )
            self.store.update_session(session.session_id, error=f"Coding disabled ({flag}=false)")
            return self.store.get_session(session.session_id)  # type: ignore[return-value]

        root_path = resolve_root(self.settings, override=workspace_root)
        ensure_workspace(root_path)
        root = str(root_path)

        existing = self.store.find_running_for_workspace(root)
        if existing is not None:
            raise CodingError(
                "SESSION_BUSY",
                f"Another coding session is active for this workspace: {existing.session_id}",
                http_status=409,
                details={"session_id": existing.session_id},
            )

        mission_enum = mission if isinstance(mission, Mission) else mission_from_text(mission)
        session = self.store.create_session(
            mission=mission_enum,
            workspace_root=root,
            title=title or goal_clean[:80],
            user_goal=goal_clean,
            conversation_id=conversation_id,
            model_id=model_id,
            status=SessionStatus.CREATED,
        )
        plan = build_initial_plan(goal_clean, mission_enum)
        self.store.add_step(
            session.session_id,
            kind=StepKind.PLAN,
            status=StepStatus.COMPLETED,
            output={"plan": plan},
        )
        return session

    def get_session(self, session_id: str) -> CodingSession:
        session = self.store.get_session(session_id)
        if session is None:
            raise CodingError("SESSION_NOT_FOUND", f"Unknown session: {session_id}", http_status=404)
        return session

    def list_sessions(self, *, limit: int = 100) -> list[CodingSession]:
        return self.store.list_sessions(limit=limit)

    def session_detail(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        return {
            "session": session.public_dict(),
            "turns": [t.public_dict() for t in self.store.list_turns(session_id)],
            "steps": [s.public_dict() for s in self.store.list_steps(session_id)],
            "patches": [p.public_dict() for p in self.store.list_patches(session_id)],
            "verification": {"verification_id": session.verification_id} if session.verification_id else None,
            "neuro": session.neuro,
        }

    def start_turn(
        self,
        session_id: str,
        *,
        message: str | None = None,
        approval_id: str | None = None,
        capability_id: str | None = None,
    ) -> CodingSession:
        """Persist user turn / bind approval, set RUNNING, wake worker. Non-blocking."""
        session = self.get_session(session_id)

        if session.status == SessionStatus.DISABLED:
            return session

        if not self.agents_enabled or not self.coding_enabled:
            return self.store.update_session(
                session_id,
                status=SessionStatus.DISABLED,
                error="Coding disabled",
            )

        # Approval resume path.
        if approval_id and session.status == SessionStatus.WAITING_APPROVAL:
            pending = dict(session.pending_capability or {})
            if capability_id and pending.get("capability_id") not in {None, capability_id}:
                raise CodingError(
                    "CAPABILITY_MISMATCH",
                    "approval capability_id does not match pending step",
                    http_status=409,
                )
            pending["approval_id"] = approval_id
            self.store.update_session(session_id, pending_capability=pending)
            self._resume_with_approval(session_id, approval_id)
            return self.get_session(session_id)

        if message and message.strip():
            self.store.add_turn(session_id, role="user", content=message.strip())
            if not session.user_goal:
                self.store.update_session(session_id, user_goal=message.strip())

        # ENFORCE-10 already checked at create; re-check if somehow RUNNING elsewhere.
        other = self.store.find_running_for_workspace(session.workspace_root)
        if other is not None and other.session_id != session_id:
            raise CodingError(
                "SESSION_BUSY",
                f"Another coding session is active: {other.session_id}",
                http_status=409,
                details={"session_id": other.session_id},
            )

        session = self.store.update_session(
            session_id,
            status=SessionStatus.RUNNING,
            cancel_requested=False,
            error=None,
        )
        self.worker.wake()
        return session

    def _resume_with_approval(self, session_id: str, approval_id: str) -> None:
        """Resume pending capability; non-blocking relative to HTTP (sync but fast path)."""
        # Keep WAITING_APPROVAL so run_round takes the resume branch.
        self.store.update_session(session_id, status=SessionStatus.WAITING_APPROVAL)
        self.loop.run_round(session_id, approval_ids=[approval_id])
        # If still runnable after resume, wake worker for subsequent rounds.
        session = self.store.get_session(session_id)
        if session and session.status == SessionStatus.RUNNING:
            self.worker.wake()

    def cancel(self, session_id: str) -> CodingSession:
        session = self.get_session(session_id)
        if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED, SessionStatus.DISABLED}:
            return session
        session = self.store.update_session(
            session_id,
            cancel_requested=True,
            status=SessionStatus.CANCELLED,
            error="cancelled",
            worker_pid=None,
            pending_capability=None,
        )
        self.worker.wake()
        return session

    def workspace_tree(
        self,
        *,
        path: str | None = None,
        recursive: bool = False,
        max_entries: int = 200,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id:
            session = self.get_session(session_id)
            root = Path(session.workspace_root)
        else:
            root = resolve_root(self.settings)
        try:
            entries = list_entries(root, path=path, recursive=recursive, max_entries=max_entries)
        except PathEscapeError as exc:
            raise CodingError("PATH_DENIED", str(exc), http_status=403) from exc
        return {"root": str(root), "entries": entries, "path": path or "."}

    def request_approval_for_pending(self, session_id: str) -> dict[str, Any]:
        """Thin wrapper: ensure a PENDING approval exists for the pending capability."""
        session = self.get_session(session_id)
        pending = session.pending_capability
        if not pending:
            raise CodingError("NO_PENDING", "No pending capability awaiting approval", http_status=404)
        if self.approvals is None:
            raise CodingError("NO_APPROVALS", "ApprovalService not configured", http_status=503)
        approval_id = pending.get("approval_id")
        if approval_id:
            record = self.approvals.get(approval_id)
            if record is not None:
                return {"approval": record.public_dict(), "pending": pending}
        # Create fresh
        from Data.modules.function_runtime.types import SideEffect

        cap_id = str(pending.get("capability_id"))
        definition = self.gateway.get_capability(cap_id) if self.gateway else None
        side_effects = (
            tuple(e.value for e in definition.side_effects)
            if definition
            else (SideEffect.WRITE.value,)
        )
        record = self.approvals.request(
            capability_id=cap_id,
            side_effects=side_effects,
            requested_by="agent:coding",
            arguments=pending.get("arguments") or {},
            metadata={"session_id": session_id},
        )
        pending = {**pending, "approval_id": record.approval_id}
        self.store.update_session(session_id, pending_capability=pending)
        return {"approval": record.public_dict(), "pending": pending}
