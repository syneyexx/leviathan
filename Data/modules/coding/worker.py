"""Background coding-session worker — JobRuntime lease executor.

Production execution owner is JobRuntime + the coding pool. This module
executes an *already-claimed* job directly. Session-store claiming and
API daemon threads are TEST-ONLY via execution_gate.
"""

from __future__ import annotations

import threading
from typing import Any

from Data.modules.jobs.leases import fenced_transition
from Data.modules.jobs.states import JobState

from .execution_gate import allow_inprocess_execution, runners_externalized
from .loop import CodingLoop
from .store import CodingStore
from .types import SessionStatus


def _fail_job(
    store: Any,
    job: Any,
    error: str,
    *,
    worker_id: str,
    ctx: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=error[:2000],
            result=result or {},
        )
    except Exception:  # noqa: BLE001 — never swallow silently without logging intent
        # Lease fencing failures must surface in result for operators.
        return {"error": error, "fencing_error": True}
    return {"error": error}


def _complete_job(
    store: Any,
    job: Any,
    result: dict[str, Any],
    *,
    worker_id: str,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        ctx=ctx,
        result=result,
    )
    return result


def _cancel_job(
    store: Any,
    job: Any,
    *,
    worker_id: str,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.CANCELLED,
            worker_id=worker_id,
            ctx=ctx,
        )
    except Exception:  # noqa: BLE001
        return {"cancelled": True, "fencing_error": True}
    return {"cancelled": True}


def process_coding_job(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    """Execute one already-claimed coding JobRuntime job. Never re-claims."""
    store = ctx["job_store"]
    worker_id = str(ctx.get("worker_id") or getattr(job, "lease_owner", None) or "")
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    cancel_check = ctx.get("job_cancel_check")
    lease_lost = ctx.get("lease_lost")

    def _fence() -> bool:
        if callable(cancel_check) and cancel_check():
            return True
        if lease_lost is not None and getattr(lease_lost, "is_set", lambda: False)():
            return True
        return False

    plane = ctx.get("coding_service")
    if plane is None:
        try:
            from Data.modules.coding.worker_context import build_coding_worker_context

            built = build_coding_worker_context(
                settings=ctx.get("settings"),
                job_runtime=ctx.get("job_runtime"),
            )
            plane = built["coding_service"]
            ctx["coding_service"] = plane
            ctx.setdefault("settings", built.get("settings"))
        except Exception as exc:  # noqa: BLE001
            return _fail_job(
                store,
                job,
                f"CodingControlPlane not constructible: {type(exc).__name__}: {exc}",
                worker_id=worker_id,
                ctx=ctx,
            )

    # Dispatch by capability / action.
    action = str(args.get("action") or "").strip().lower()
    if capability == "coding.semantic_map.build" or action == "semantic_map_build":
        return _process_semantic_map_build(ctx, job, plane, worker_id=worker_id, fence=_fence)
    if capability in {"coding.verify", "coding.run_tests", "coding.test"} or action in {
        "verify",
        "run_tests",
        "test",
        "lint",
        "typecheck",
        "build",
    }:
        return _process_verify(ctx, job, plane, worker_id=worker_id, fence=_fence)
    if capability.startswith("coding.git.") or action.startswith("git_"):
        return _process_git(ctx, job, plane, worker_id=worker_id, fence=_fence)
    if capability in {"coding.repo.analyze", "coding.repository.analyze"} or action == "repo_analyze":
        return _process_semantic_map_build(ctx, job, plane, worker_id=worker_id, fence=_fence)

    # Default: coding.advance session round.
    return _process_advance(ctx, job, plane, worker_id=worker_id, fence=_fence)


def _process_advance(
    ctx: dict[str, Any],
    job: Any,
    plane: Any,
    *,
    worker_id: str,
    fence: Any,
) -> dict[str, Any]:
    store = ctx["job_store"]
    runtime = ctx.get("job_runtime") or plane.job_runtime
    args = dict(getattr(job, "arguments", None) or {})
    session_id = str(args.get("session_id") or "")
    approval_id = args.get("approval_id")
    if not session_id:
        return _fail_job(store, job, "missing session_id", worker_id=worker_id, ctx=ctx)

    coding_store: CodingStore = plane.store
    session = coding_store.get_session(session_id)
    if session is None:
        return _fail_job(store, job, "session not found", worker_id=worker_id, ctx=ctx)

    if session.cancel_requested or (callable(fence) and fence()):
        coding_store.update_session(
            session_id,
            status=SessionStatus.CANCELLED,
            error="cancelled",
            worker_pid=None,
        )
        return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)

    # Bind kernel job id on session metadata for cancel propagation.
    meta = dict(session.metadata or {})
    meta["kernel_job_id"] = getattr(job, "job_id", None)
    coding_store.update_session(session_id, metadata=meta)

    try:
        approval_ids = [str(approval_id)] if approval_id else None
        result = plane.loop.run_round(session_id, approval_ids=approval_ids)
        if callable(fence) and fence():
            coding_store.update_session(
                session_id,
                status=SessionStatus.CANCELLED,
                error="cancelled",
                worker_pid=None,
            )
            return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)

        out = {
            "session_id": session_id,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "round_count": getattr(result.session, "round_count", None),
            "phase": (result.session.metadata or {}).get("phase") if result.session else None,
        }

        if result.status == SessionStatus.RUNNING:
            _complete_job(store, job, out, worker_id=worker_id, ctx=ctx)
            # Deterministic continuation — stable idempotency by session/round/phase.
            if runtime is not None:
                phase = out.get("phase") or "advance"
                approval_gen = (result.session.pending_capability or {}).get("approval_id") if result.session else None
                idem = (
                    f"coding.advance:{session_id}:{result.session.round_count}"
                    f":{phase}:{approval_gen or 'none'}"
                )
                try:
                    runtime.enqueue(
                        capability_id="coding.advance",
                        arguments={"session_id": session_id},
                        run_id=result.session.run_id if result.session else None,
                        requested_by="coding.worker",
                        idempotency_key=idem,
                        worker_pool="coding",
                        resource_class="CPU_HEAVY",
                        domain="coding",
                        domain_entity_type="session",
                        domain_entity_id=session_id,
                        metadata={"session_id": session_id, "continuation": True},
                    )
                except Exception as exc:  # noqa: BLE001
                    coding_store.update_session(
                        session_id,
                        status=SessionStatus.RUNNING,
                        worker_pid=None,
                        error=f"continuation_enqueue_failed: {exc}"[:500],
                    )
            return out

        # WAITING_APPROVAL / terminal — do not spin.
        coding_store.update_session(session_id, worker_pid=None)
        return _complete_job(store, job, out, worker_id=worker_id, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        coding_store.update_session(
            session_id,
            status=SessionStatus.FAILED,
            error=str(exc)[:2000],
            worker_pid=None,
        )
        return _fail_job(store, job, str(exc)[:2000], worker_id=worker_id, ctx=ctx)


def _process_semantic_map_build(
    ctx: dict[str, Any],
    job: Any,
    plane: Any,
    *,
    worker_id: str,
    fence: Any,
) -> dict[str, Any]:
    from pathlib import Path

    from Data.modules.coding.map_cache import get_cached_map, put_cached_map
    from Data.modules.coding.semantic_map import SemanticMapBuilder, map_from_public_dict
    from Data.modules.coding.workspace_gen import capture_workspace_generation

    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    workspace_root = str(args.get("workspace_root") or "").strip()
    session_id = str(args.get("session_id") or "").strip()
    if not workspace_root and session_id:
        session = plane.store.get_session(session_id)
        if session is None:
            return _fail_job(store, job, "session not found", worker_id=worker_id, ctx=ctx)
        workspace_root = session.workspace_root
    if not workspace_root:
        return _fail_job(store, job, "missing workspace_root", worker_id=worker_id, ctx=ctx)

    root = Path(workspace_root)
    if callable(fence) and fence():
        return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)

    gen_before = capture_workspace_generation(root)
    previous = None
    db_path = Path(plane.store.db_path)
    cached = get_cached_map(db_path, str(root.resolve()) if root.exists() else str(root))
    if cached and cached.payload:
        try:
            previous = map_from_public_dict(cached.payload)
        except Exception:  # noqa: BLE001
            previous = None

    max_files = int(args.get("max_files") or 2000)
    builder = SemanticMapBuilder(root, max_files=max_files, cancel_check=fence)
    smap = builder.build(previous=previous)
    if callable(fence) and fence():
        return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)

    gen_after = capture_workspace_generation(root)
    payload = smap.public_dict()
    payload["generation"] = gen_after.public_dict()
    status = "ready"
    if not gen_before.matches(gen_after):
        status = "stale"
        payload.setdefault("truth", {})["changed_during_scan"] = True
        payload["status"] = "CHANGED_DURING_SCAN"

    artifact_store = ctx.get("artifact_store")
    if artifact_store is None:
        try:
            from Data.modules.artifacts.store import ArtifactStore
            from Data.backend.config import PROJECT_ROOT

            artifacts_root = Path(
                getattr(getattr(ctx.get("settings"), "artifacts", None), "root", None)
                or (PROJECT_ROOT / "Data" / "artifacts")
            )
            artifact_store = ArtifactStore(db_path, artifacts_root)
            artifact_store.initialize()
        except Exception:  # noqa: BLE001
            artifact_store = None

    record = put_cached_map(
        db_path,
        workspace_root=str(root.resolve()) if root.exists() else str(root),
        generated_at=smap.generated_at,
        content_hash=smap.content_fingerprint(),
        payload=payload,
        generation_fingerprint=gen_after.fingerprint,
        status=status,
        artifact_store=artifact_store,
    )
    out = {
        "workspace_root": record.workspace_root,
        "status": record.status,
        "content_hash": record.content_hash,
        "generation_fingerprint": record.generation_fingerprint,
        "summary": record.summary,
        "artifact_id": record.artifact_id,
        "job_id": getattr(job, "job_id", None),
    }
    return _complete_job(store, job, out, worker_id=worker_id, ctx=ctx)


def _process_verify(
    ctx: dict[str, Any],
    job: Any,
    plane: Any,
    *,
    worker_id: str,
    fence: Any,
) -> dict[str, Any]:
    from pathlib import Path

    from Data.modules.coding.verify_ops import run_verification
    from Data.modules.coding.workspace_gen import capture_workspace_generation

    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    phase = str(args.get("phase") or args.get("action") or "test").strip().lower()
    if capability in {"coding.run_tests", "coding.test"}:
        phase = "test"
    workspace_root = str(args.get("workspace_root") or args.get("cwd") or "").strip()
    session_id = str(args.get("session_id") or "").strip()
    if not workspace_root and session_id:
        session = plane.store.get_session(session_id)
        if session is not None:
            workspace_root = session.workspace_root
    if not workspace_root:
        # Fall back to settings workspace.
        try:
            from Data.modules.coding.workspace import resolve_root

            workspace_root = str(resolve_root(ctx.get("settings") or plane.settings))
        except Exception:  # noqa: BLE001
            return _fail_job(store, job, "missing workspace_root", worker_id=worker_id, ctx=ctx)

    root = Path(workspace_root)
    gen = capture_workspace_generation(root)
    if callable(fence) and fence():
        return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)

    receipt = run_verification(
        phase=phase,
        workspace_root=root,
        selector=args.get("selector"),
        tool=args.get("tool"),
        timeout_seconds=int(args.get("timeout_seconds") or 120),
        cancel_check=fence,
        cwd=args.get("cwd"),
    )
    receipt["generation"] = gen.public_dict()
    receipt["capability"] = capability or f"coding.verify:{phase}"
    receipt["executed"] = True
    # Tool failures are valid execution results — complete the job with receipt.
    return _complete_job(store, job, receipt, worker_id=worker_id, ctx=ctx)


def _process_git(
    ctx: dict[str, Any],
    job: Any,
    plane: Any,
    *,
    worker_id: str,
    fence: Any,
) -> dict[str, Any]:
    from Data.modules.coding import git_ops

    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    action = str(args.get("action") or capability.rsplit(".", 1)[-1]).strip().lower()
    if callable(fence) and fence():
        return _cancel_job(store, job, worker_id=worker_id, ctx=ctx)
    try:
        result = git_ops.dispatch_git_op(action, args, cancel_check=fence, settings=plane.settings)
    except Exception as exc:  # noqa: BLE001
        from Data.modules.coding.types import CodingError

        if isinstance(exc, CodingError):
            # Typed Git failures are completed observations, not platform crashes.
            return _complete_job(
                store,
                job,
                {"ok": False, "error_code": exc.code, "error": str(exc), **(exc.details or {})},
                worker_id=worker_id,
                ctx=ctx,
            )
        return _fail_job(store, job, str(exc)[:2000], worker_id=worker_id, ctx=ctx)
    return _complete_job(store, job, result, worker_id=worker_id, ctx=ctx)


class CodingWorker:
    """Domain executor for Coding sessions.

    Production: JobRuntime / coding pool claims jobs; ``process_coding_job``
    executes them. This class retains TEST-ONLY drain / background helpers
    behind the mechanical inprocess gate.
    """

    def __init__(
        self,
        store: CodingStore,
        loop: CodingLoop,
        *,
        job_runtime: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self.store = store
        self.loop = loop
        self.job_runtime = job_runtime
        self.settings = settings
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def start_background(self, *, poll_seconds: float = 0.25) -> None:
        """Start API-local daemon ONLY when inprocess_test is explicitly allowed.

        Production externalization must never fall through here because of a
        typo, missing JobRuntime, or disabled supervisor.
        """
        if runners_externalized() and not allow_inprocess_execution(self.settings):
            # Enqueue-only posture — do not spawn threads.
            return
        if not allow_inprocess_execution(self.settings):
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def _loop() -> None:
                while not self._stop.is_set():
                    advanced = self.process_next()
                    if not advanced:
                        self._wake.wait(poll_seconds)
                        self._wake.clear()

            self._thread = threading.Thread(target=_loop, name="coding-worker", daemon=True)
            self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def process_next(self) -> bool:
        """TEST-ONLY: claim and advance one unit of work.

        Production fabric handlers must call ``process_coding_job`` on the
        already-claimed job instead.
        """
        if not allow_inprocess_execution(self.settings):
            return False
        if self.job_runtime is not None and self._process_job_lease():
            return True
        return self._process_session_claim()

    def _process_job_lease(self) -> bool:
        """Test-only claim path — production uses fabric-claimed jobs."""
        if not allow_inprocess_execution(self.settings):
            return False
        runtime = self.job_runtime
        if runtime is None:
            return False
        store = getattr(runtime, "store", None)
        if store is None:
            return False
        job = None
        worker_id = f"coding-inprocess-{id(self)}"
        try:
            if hasattr(store, "claim_next_queued"):
                job = store.claim_next_queued(
                    worker_id=worker_id,
                    capability_ids={
                        "coding.advance",
                        "coding.semantic_map.build",
                        "coding.run_tests",
                        "coding.test",
                        "coding.verify",
                    },
                    worker_pool="coding",
                )
        except Exception:  # noqa: BLE001
            job = None
        if job is None:
            return False
        ctx = {
            "job_store": store,
            "job_runtime": runtime,
            "worker_id": worker_id,
            "coding_service": getattr(self.loop, "_plane", None),
            "settings": self.settings,
        }
        # Minimal plane wrapper so process_coding_job can use store/loop.
        if ctx["coding_service"] is None:

            class _Plane:
                store = self.store
                loop = self.loop
                job_runtime = runtime
                settings = self.settings

            ctx["coding_service"] = _Plane()
        process_coding_job(ctx, job)
        return True

    def _process_session_claim(self) -> bool:
        """TEST-ONLY compatibility path — never production claim authority."""
        if not allow_inprocess_execution(self.settings):
            return False
        session = self.store.claim_next_runnable()
        if session is None:
            return False
        if session.cancel_requested:
            self.store.update_session(
                session.session_id,
                status=SessionStatus.CANCELLED,
                error="cancelled",
                worker_pid=None,
            )
            return True
        try:
            result = self.loop.run_round(session.session_id)
            if result.status != SessionStatus.RUNNING:
                self.store.update_session(session.session_id, worker_pid=None)
            return True
        except Exception as exc:  # noqa: BLE001
            self.store.update_session(
                session.session_id,
                status=SessionStatus.FAILED,
                error=str(exc)[:2000],
                worker_pid=None,
            )
            return True

    def drain(self, *, max_rounds: int = 50) -> int:
        """Synchronously process up to max_rounds (tests / foreground)."""
        if not allow_inprocess_execution(self.settings):
            return 0
        count = 0
        for _ in range(max_rounds):
            if not self.process_next():
                break
            count += 1
        return count
