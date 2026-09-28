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
        brain_access: Any | None = None,
        behavior_store: Any | None = None,
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.approvals = approvals
        self.settings = settings
        self.agents_enabled = agents_enabled
        self.coding_enabled = coding_enabled
        self.brain_access = brain_access
        self.behavior_store = behavior_store
        self.job_runtime = job_runtime
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
            brain_access=brain_access,
            behavior_store=behavior_store,
        )
        self.worker = worker or CodingWorker(
            store, self.loop, job_runtime=job_runtime, settings=settings
        )

    def bind_intelligence(
        self,
        *,
        llm: Any | None = None,
        context_builder: Any | None = None,
        brain_access: Any | None = None,
        behavior_store: Any | None = None,
        job_runtime: Any | None = None,
        reasoning: Any | None = None,
    ) -> None:
        """Wire shared One-Brain / Model / Context authorities after composition."""
        if llm is not None:
            self.loop.llm = llm
        if context_builder is not None:
            self.loop.context_builder = context_builder
        if brain_access is not None:
            self.brain_access = brain_access
            self.loop.brain_access = brain_access
        if behavior_store is not None:
            self.behavior_store = behavior_store
            self.loop.behavior_store = behavior_store
        if job_runtime is not None:
            self.job_runtime = job_runtime
            self.worker.bind_job_runtime(job_runtime)
        if reasoning is not None:
            self.loop.reasoning = reasoning

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
        brain_access: Any | None = None,
        behavior_store: Any | None = None,
        job_runtime: Any | None = None,
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
            brain_access=brain_access,
            behavior_store=behavior_store,
            job_runtime=job_runtime,
        )

    # --- lifecycle ----------------------------------------------------------

    def start_background(self) -> None:
        """Production: never start API daemon threads when workers are externalized.

        Heavy Coding execution is owned by the coding pool. Inprocess threads
        require the mechanical test allow gate (see execution_gate).
        """
        from .execution_gate import allow_inprocess_execution, runners_externalized

        if runners_externalized() and not allow_inprocess_execution(self.settings):
            return
        if not allow_inprocess_execution(self.settings):
            return
        self.worker.start_background()

    def stop_background(self) -> None:
        self.worker.stop_background()

    def enqueue_advance(
        self,
        session_id: str,
        *,
        approval_id: str | None = None,
        reason: str = "advance",
    ) -> Any:
        """Enqueue durable coding.advance — fail closed when JobRuntime missing in production."""
        from .execution_gate import allow_inprocess_execution, refuse_inline_coding, runners_externalized

        session = self.get_session(session_id)
        if self.job_runtime is None:
            if runners_externalized() and not allow_inprocess_execution(self.settings):
                refuse_inline_coding(reason="job_runtime_unavailable")
            # Test-only: wake inprocess worker / session claim.
            self.worker.wake()
            return None
        pending = session.pending_capability or {}
        phase = str((session.metadata or {}).get("phase") or reason or "advance")
        approval_gen = approval_id or pending.get("approval_id") or "none"
        args: dict[str, Any] = {"session_id": session_id}
        if approval_id:
            args["approval_id"] = approval_id
        return self.job_runtime.enqueue(
            capability_id="coding.advance",
            arguments=args,
            run_id=session.run_id,
            requested_by="coding",
            idempotency_key=(
                f"coding.advance:{session_id}:{session.round_count}:{phase}:{approval_gen}"
            ),
            worker_pool="coding",
            resource_class="CPU_HEAVY",
            domain="coding",
            domain_entity_type="session",
            domain_entity_id=session_id,
            metadata={"session_id": session_id, "reason": reason},
        )

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

        # Approval resume path — persist binding + enqueue; never run_round inline.
        if approval_id and session.status == SessionStatus.WAITING_APPROVAL:
            pending = dict(session.pending_capability or {})
            if capability_id and pending.get("capability_id") not in {None, capability_id}:
                raise CodingError(
                    "CAPABILITY_MISMATCH",
                    "approval capability_id does not match pending step",
                    http_status=409,
                )
            pending["approval_id"] = approval_id
            self.store.update_session(
                session_id,
                pending_capability=pending,
                status=SessionStatus.WAITING_APPROVAL,
            )
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
        job = self.enqueue_advance(session_id, reason="start")
        if job is not None:
            meta = dict(session.metadata or {})
            meta["kernel_job_id"] = getattr(job, "job_id", None)
            self.store.update_session(session_id, metadata=meta)
        self.worker.wake()
        return self.get_session(session_id)

    def _resume_with_approval(self, session_id: str, approval_id: str) -> None:
        """Persist approval binding and enqueue coding.advance — never run_round in API."""
        from .execution_gate import allow_inprocess_execution, refuse_inline_coding, runners_externalized

        self.store.update_session(session_id, status=SessionStatus.WAITING_APPROVAL)
        if self.job_runtime is not None:
            job = self.enqueue_advance(session_id, approval_id=approval_id, reason="approval_resume")
            if job is not None:
                session = self.store.get_session(session_id)
                if session is not None:
                    meta = dict(session.metadata or {})
                    meta["kernel_job_id"] = getattr(job, "job_id", None)
                    self.store.update_session(session_id, metadata=meta)
            self.worker.wake()
            return
        if runners_externalized() and not allow_inprocess_execution(self.settings):
            refuse_inline_coding(reason="approval_resume_requires_worker")
        # Explicit test-only inline path.
        self.loop.run_round(session_id, approval_ids=[approval_id])
        session = self.store.get_session(session_id)
        if session and session.status == SessionStatus.RUNNING:
            self.worker.wake()

    def cancel(self, session_id: str) -> CodingSession:
        session = self.get_session(session_id)
        if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED, SessionStatus.DISABLED}:
            return session
        kernel_job_id = (session.metadata or {}).get("kernel_job_id")
        session = self.store.update_session(
            session_id,
            cancel_requested=True,
            status=SessionStatus.CANCELLED,
            error="cancelled",
            worker_pid=None,
            pending_capability=None,
        )
        # Propagate cancel to JobRuntime / active worker subprocesses.
        if kernel_job_id and self.job_runtime is not None:
            try:
                cancel = getattr(self.job_runtime, "request_cancel", None) or getattr(
                    self.job_runtime, "cancel", None
                )
                if callable(cancel):
                    cancel(str(kernel_job_id))
            except Exception:  # noqa: BLE001
                pass
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

        # Request-aware: recursive/large trees → file_io; small non-recursive stays inline.
        arguments = {
            "path": path or ".",
            "recursive": bool(recursive),
            "max_entries": int(max_entries),
            "workspace_root": str(root),
        }
        if recursive or max_entries > 200:
            from Data.modules.execution.file_io_dispatch import classify_and_maybe_enqueue
            from Data.modules.execution.workload import ExecutionWorkloadClass

            decision = classify_and_maybe_enqueue(
                capability_id="workspace.list",
                arguments=arguments,
                job_runtime=self.job_runtime,
                filesystem_root=root,
                requested_by="api.coding.workspace_tree",
            )
            if decision.get("queued"):
                job = decision.get("job")
                return {
                    "root": str(root),
                    "entries": [],
                    "path": path or ".",
                    "queued": True,
                    "job_id": getattr(job, "job_id", None) if job is not None else None,
                    "execution_class": decision.get("execution_class"),
                    "refresh": {"queued": True, "job_id": getattr(job, "job_id", None) if job else None},
                }
            if decision.get("execution_class") == ExecutionWorkloadClass.EXTERNAL_REQUIRED.value:
                from .execution_gate import allow_inprocess_execution, refuse_inline_coding, runners_externalized

                if runners_externalized() and not allow_inprocess_execution(self.settings):
                    refuse_inline_coding(reason="workspace_tree_requires_file_io")

        try:
            entries = list_entries(root, path=path, recursive=recursive, max_entries=max_entries)
        except PathEscapeError as exc:
            raise CodingError("PATH_DENIED", str(exc), http_status=403) from exc
        return {"root": str(root), "entries": entries, "path": path or ".", "queued": False}

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

    # --- Wave 6 frontier coding helpers ------------------------------------

    def semantic_map(
        self,
        *,
        workspace_root: str | None = None,
        session_id: str | None = None,
        previous: Any | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return cached map when fresh; enqueue rebuild when missing/stale.

        Never blocks the API on full repository indexing in production.
        """
        from .execution_gate import allow_inprocess_execution, runners_externalized
        from .map_cache import get_cached_map
        from .workspace_gen import capture_workspace_generation

        root = self._resolve_workspace(workspace_root=workspace_root, session_id=session_id)
        root_key = str(root.resolve()) if root.exists() else str(root)
        cached = get_cached_map(self.store.db_path, root_key)
        gen = capture_workspace_generation(root)
        fresh = (
            cached is not None
            and cached.status == "ready"
            and cached.generation_fingerprint == gen.fingerprint
            and not force_refresh
        )
        if fresh and cached is not None:
            out: dict[str, Any] = {
                "map": cached.payload or cached.summary,
                "summary": cached.summary,
                "status": "ready",
                "cached": True,
                "artifact_id": cached.artifact_id,
                "refresh": {"queued": False, "job_id": None},
            }
            return out

        refresh: dict[str, Any] = {"queued": False, "job_id": None}
        if self.job_runtime is not None and (runners_externalized() or force_refresh or cached is None):
            try:
                from .map_cache import mark_cache_status

                if cached is not None:
                    mark_cache_status(self.store.db_path, root_key, "building")
                job = self.job_runtime.enqueue(
                    capability_id="coding.semantic_map.build",
                    arguments={
                        "workspace_root": root_key,
                        "session_id": session_id,
                        "action": "semantic_map_build",
                    },
                    requested_by="api.coding.semantic_map",
                    idempotency_key=f"coding.semantic_map.build:{root_key}:{gen.fingerprint}",
                    worker_pool="coding",
                    resource_class="CPU_HEAVY",
                    domain="coding",
                    metadata={"workspace_root": root_key},
                )
                refresh = {"queued": True, "job_id": getattr(job, "job_id", None)}
            except Exception:  # noqa: BLE001
                refresh = {"queued": False, "job_id": None, "error": "enqueue_failed"}

        if cached is not None:
            return {
                "map": cached.payload or cached.summary,
                "summary": cached.summary,
                "status": "stale" if cached.generation_fingerprint != gen.fingerprint else cached.status,
                "cached": True,
                "artifact_id": cached.artifact_id,
                "refresh": refresh,
            }

        # No cache: production returns queued state; tests may build inline.
        if runners_externalized() and not allow_inprocess_execution(self.settings):
            return {
                "map": None,
                "summary": None,
                "status": "queued" if refresh.get("queued") else "unavailable",
                "cached": False,
                "refresh": refresh,
            }

        # Explicit inprocess_test / developer path.
        from .semantic_map import SemanticMapBuilder

        smap = SemanticMapBuilder(root).build(previous=previous)
        return {
            "map": smap.public_dict(),
            "summary": {
                "file_count": len(smap.files),
                "symbol_count": sum(len(f.symbols) for f in smap.files.values()),
            },
            "status": "ready",
            "cached": False,
            "refresh": refresh,
        }

    def build_change_plan(
        self,
        *,
        goal: str,
        changes: list[dict[str, Any]],
        invariants: list[str] | None = None,
        expected_tests: list[str] | None = None,
        risk: str | None = None,
    ) -> dict[str, Any]:
        from .transaction import FileChange, build_change_plan

        parsed = [
            FileChange(
                path=str(item["path"]),
                kind=str(item.get("kind") or "rewrite"),
                unified_diff=item.get("unified_diff"),
                content=item.get("content"),
                rationale=str(item.get("rationale") or ""),
            )
            for item in changes
        ]
        plan = build_change_plan(
            goal=goal,
            changes=parsed,
            invariants=invariants,
            expected_tests=expected_tests,
            risk=risk,
        )
        return plan.public_dict()

    def apply_change_plan_transactional(
        self,
        plan_payload: dict[str, Any],
        *,
        workspace_root: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        from .transaction import ChangePlan, ChangeRisk, FileChange, WorkspaceTransaction

        root = self._resolve_workspace(workspace_root=workspace_root, session_id=session_id)
        changes = [
            FileChange(
                path=str(item["path"]),
                kind=str(item.get("kind") or "rewrite"),
                unified_diff=item.get("unified_diff"),
                content=item.get("content"),
                rationale=str(item.get("rationale") or ""),
            )
            for item in (plan_payload.get("changes") or [])
        ]
        plan = ChangePlan(
            plan_id=str(plan_payload.get("plan_id") or "adhoc"),
            goal=str(plan_payload.get("goal") or ""),
            affected_files=list(plan_payload.get("affected_files") or [c.path for c in changes]),
            changes=changes,
            invariants=list(plan_payload.get("invariants") or []),
            expected_tests=list(plan_payload.get("expected_tests") or []),
            risk=ChangeRisk(str(plan_payload.get("risk") or "low")),
        )
        tx = WorkspaceTransaction(root)
        try:
            snap = tx.apply_plan(plan, auto_rollback_on_error=True)
            return {"ok": True, "snapshot": snap.public_dict(), "plan": plan.public_dict()}
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(exc),
                "plan": plan.public_dict(),
                "truth": {"failed_verification_restores_snapshot": True},
            }

    def adaptive_verification(
        self,
        *,
        workspace_root: str | None = None,
        session_id: str | None = None,
        plan_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .map_cache import get_cached_map, map_summary
        from .semantic_map import SemanticMapBuilder, map_from_public_dict
        from .transaction import ChangePlan, ChangeRisk, FileChange
        from .verify import select_adaptive_verification
        from .workspace_gen import capture_workspace_generation
        from .execution_gate import allow_inprocess_execution, runners_externalized

        root = self._resolve_workspace(workspace_root=workspace_root, session_id=session_id)
        plan = None
        if plan_payload:
            changes = [
                FileChange(
                    path=str(item["path"]),
                    kind=str(item.get("kind") or "rewrite"),
                    unified_diff=item.get("unified_diff"),
                    content=item.get("content"),
                )
                for item in (plan_payload.get("changes") or [])
            ]
            plan = ChangePlan(
                plan_id=str(plan_payload.get("plan_id") or "adhoc"),
                goal=str(plan_payload.get("goal") or ""),
                affected_files=list(plan_payload.get("affected_files") or [c.path for c in changes]),
                changes=changes,
                expected_tests=list(plan_payload.get("expected_tests") or []),
                risk=ChangeRisk(str(plan_payload.get("risk") or "low")),
            )

        # Prefer cached semantic map; do not synchronously rebuild huge maps on API.
        root_key = str(root.resolve()) if root.exists() else str(root)
        cached = get_cached_map(self.store.db_path, root_key)
        smap = None
        if cached and cached.payload:
            try:
                smap = map_from_public_dict(cached.payload)
            except Exception:  # noqa: BLE001
                smap = None
        if smap is None:
            gen = capture_workspace_generation(root)
            if self.job_runtime is not None and runners_externalized():
                try:
                    self.job_runtime.enqueue(
                        capability_id="coding.semantic_map.build",
                        arguments={"workspace_root": root_key, "action": "semantic_map_build"},
                        requested_by="api.coding.adaptive_verification",
                        idempotency_key=f"coding.semantic_map.build:{root_key}:{gen.fingerprint}",
                        worker_pool="coding",
                        resource_class="CPU_HEAVY",
                        domain="coding",
                    )
                except Exception:  # noqa: BLE001
                    pass
            if allow_inprocess_execution(self.settings) or not runners_externalized():
                smap = SemanticMapBuilder(root, max_files=80).build()
            else:
                # Planning without full map — still return adaptive selection with empty map.
                from .semantic_map import RepoSemanticMap

                smap = RepoSemanticMap(workspace_root=root_key, generated_at="")
                if cached:
                    # Use summary counts only.
                    _ = map_summary(cached.summary)

        return select_adaptive_verification(root, plan=plan, semantic_map=smap).public_dict()

    def review_diff(
        self,
        *,
        plan_payload: dict[str, Any] | None = None,
        diffs: dict[str, str] | None = None,
        test_evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        from .review import build_diff_review, build_multi_agent_review_dag
        from .transaction import ChangePlan, ChangeRisk, FileChange

        plan = None
        if plan_payload:
            changes = [
                FileChange(
                    path=str(item["path"]),
                    kind=str(item.get("kind") or "patch"),
                    unified_diff=item.get("unified_diff"),
                    content=item.get("content"),
                )
                for item in (plan_payload.get("changes") or [])
            ]
            plan = ChangePlan(
                plan_id=str(plan_payload.get("plan_id") or "adhoc"),
                goal=str(plan_payload.get("goal") or ""),
                affected_files=list(plan_payload.get("affected_files") or [c.path for c in changes]),
                changes=changes,
                expected_tests=list(plan_payload.get("expected_tests") or []),
                risk=ChangeRisk(str(plan_payload.get("risk") or "low")),
            )
        review = build_diff_review(plan=plan, diffs=diffs, test_evidence=test_evidence)
        payload = review.public_dict()
        if plan is not None:
            payload["multi_agent_dag"] = build_multi_agent_review_dag(plan)
        return payload

    def _resolve_workspace(
        self,
        *,
        workspace_root: str | None = None,
        session_id: str | None = None,
    ) -> Path:
        if session_id:
            session = self.get_session(session_id)
            return Path(session.workspace_root)
        return resolve_root(self.settings, override=workspace_root)
