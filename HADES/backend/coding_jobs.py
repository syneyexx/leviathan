"""Background coding-run jobs with executable control contract.

Preserves sync /build/goal and existing job APIs. Extends Milestone 1 WP9 with:
cooperative pause checkpoints, real resume dispatch, versioned instructions,
cancellable runners, recovery payloads, sequenced events, and transition guards.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from coding_job_control import (
    CONTROL_OWNER,
    CodingJobCancelled,
    CodingJobPaused,
    JobInstruction,
    TERMINAL_STATUSES,
    control_contract_doc,
    empty_checkpoint,
    is_terminal,
    validate_transition,
)
from run_leases import ExecutionLeaseStore

RunnerFn = Callable[[dict[str, Any]], dict[str, Any]]
RunnerFactory = Callable[[dict[str, Any]], RunnerFn]


class CodingJobStore:
    """Persistent JSON job status + in-process worker pool with control contract."""

    def __init__(
        self,
        root: Path | str,
        *,
        lease_store: ExecutionLeaseStore | None = None,
        max_workers: int = 2,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.leases = lease_store or ExecutionLeaseStore(self.root / "coding_job_leases.json")
        self._lock = threading.RLock()
        self._disk_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hades-coding-job")
        self._futures: dict[str, Future[Any]] = {}
        self._runners: dict[str, RunnerFn] = {}
        self._runner_factory = runner_factory
        self._redirects: dict[str, list[str]] = {}  # preserved for compatibility
        self._dispatch_tokens: dict[str, str] = {}
        # Jobs currently between dispatch claim and future registration.
        # Prevents concurrent resume() from double-submitting workers.
        self._dispatch_claims: set[str] = set()

    def set_runner_factory(self, factory: RunnerFactory | None) -> None:
        with self._lock:
            self._runner_factory = factory

    def control_contract(self) -> dict[str, Any]:
        return control_contract_doc()

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _write(self, job_id: str, payload: dict[str, Any]) -> None:
        """Atomic status write. Retries replace on Windows Access-denied races."""
        path = self._job_dir(job_id)
        path.mkdir(parents=True, exist_ok=True)
        target = path / "status.json"
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._disk_lock:
            tmp = path / f"status.json.tmp.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
            tmp.write_text(body, encoding="utf-8")
            last_exc: Exception | None = None
            for attempt in range(16):
                try:
                    os.replace(str(tmp), str(target))
                    return
                except PermissionError as exc:
                    last_exc = exc
                    time.sleep(0.02 * (attempt + 1))
                except OSError as exc:
                    # WinError 5 / sharing violation variants
                    if getattr(exc, "winerror", None) not in {5, 32} and not isinstance(exc, PermissionError):
                        tmp.unlink(missing_ok=True)
                        raise
                    last_exc = exc
                    time.sleep(0.02 * (attempt + 1))
            # Never overwrite the live status.json in place: a failed atomic
            # replace must preserve the last valid file and surface failure.
            tmp.unlink(missing_ok=True)
            if last_exc is not None:
                raise OSError(
                    f"Kon coding-job status niet atomair wegschrijven voor {job_id}: {last_exc}"
                ) from last_exc
            raise OSError(f"Kon coding-job status niet atomair wegschrijven voor {job_id}.")

    def _read(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "status.json"
        if not path.is_file():
            raise FileNotFoundError(f"Coding job niet gevonden: {job_id}")
        with self._disk_lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def _next_event_seq(self, job_id: str) -> int:
        with self._lock:
            try:
                status = self._read(job_id)
            except FileNotFoundError:
                return 1
            seq = int(status.get("event_seq") or 0) + 1
            status["event_seq"] = seq
            self._write(job_id, status)
            return seq

    def _append_event(self, job_id: str, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self._job_dir(job_id)
        path.mkdir(parents=True, exist_ok=True)
        events_path = path / "events.jsonl"
        seq = self._next_event_seq(job_id)
        row = {
            "id": f"evt_{job_id}_{seq}",
            "seq": seq,
            "ts": time.time(),
            "kind": kind,
            "data": data or {},
        }
        with self._lock:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            try:
                status = self._read(job_id)
            except FileNotFoundError:
                return row
            status.setdefault("events_tail", [])
            status["events_tail"] = (status.get("events_tail") or [])[-40:]
            status["events_tail"].append(row)
            status["updated_at"] = time.time()
            status["last_event_seq"] = seq
            self._write(job_id, status)
        return row

    def list_events(
        self,
        job_id: str,
        *,
        limit: int = 100,
        after_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        path = self._job_dir(job_id) / "events.jsonl"
        if not path.is_file():
            return []
        # Prefer incremental read via events_index.json when present.
        index_path = self._job_dir(job_id) / "events_index.json"
        out: list[dict[str, Any]] = []
        # Stream line-by-line; for reconnect use after_seq filter without loading whole file into UI.
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seq = int(row.get("seq") or 0)
                if after_seq is not None and seq <= int(after_seq):
                    continue
                out.append(row)
        if after_seq is None:
            out = out[-limit:]
        else:
            out = out[:limit]
        # Maintain optional offset index for large files (best-effort, additive).
        try:
            if path.stat().st_size > 256_000:
                index_path.write_text(
                    json.dumps({"last_seq": out[-1]["seq"] if out else after_seq or 0, "updated_at": time.time()}),
                    encoding="utf-8",
                )
        except OSError:
            pass
        return out

    def _update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            record = self._read(job_id)
            record.update({k: v for k, v in fields.items() if v is not None or k in {"result", "error", "run_id"}})
            record["updated_at"] = time.time()
            self._write(job_id, record)
            return record

    def _set_status(self, job_id: str, target: str, *, evidence: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        with self._lock:
            record = self._read(job_id)
            current = str(record.get("status") or "queued")
            check = validate_transition(current, target)
            if not check.get("ok"):
                raise ValueError(f"invalid_status_transition:{current}->{target}:{check.get('reason')}")
            record["status"] = target
            if evidence:
                trail = list(record.get("status_evidence") or [])
                trail.append({"at": time.time(), "from": current, "to": target, **evidence})
                record["status_evidence"] = trail[-30:]
            for key, value in fields.items():
                if value is not None or key in {"result", "error", "run_id"}:
                    record[key] = value
            record["updated_at"] = time.time()
            self._write(job_id, record)
            return record

    def get(self, job_id: str) -> dict[str, Any]:
        record = self._read(job_id)
        after = None
        if str(record.get("status")) == "cancelled" or record.get("cancel_requested"):
            from reasoning.long_task_resume import default_side_effect_ledger

            default_side_effect_ledger.request_cancel(str(record.get("run_id") or job_id))
        record["events"] = self.list_events(job_id, limit=50, after_seq=after)
        record["control"] = self.leases.snapshot(job_id)
        lease = self.leases.lease_snapshot(f"coding_job:{job_id}")
        with self._lock:
            fut = self._futures.get(job_id)
            live = bool(fut is not None and not fut.done())
        from reasoning.long_task_resume import RunIdentity, is_worker_live

        live_info = is_worker_live(
            status=str(record.get("status")),
            worker_live=live,
            lease_holder=(lease or {}).get("worker_id"),
            own_worker_id=str(record.get("worker_id") or ""),
            lease_expired=bool(lease and float(lease.get("expires_at") or 0) <= time.time()),
        )
        identity = RunIdentity(
            mission_id=(record.get("params") or {}).get("mission_id"),
            task_id=(record.get("params") or {}).get("task_id"),
            run_id=str(record.get("run_id") or record.get("id") or job_id),
            step_id=(record.get("checkpoint") or {}).get("phase"),
            artifact_ids=list((record.get("result") or {}).get("artifact_ids") or []),
            fence_token=(lease or {}).get("fence_token") or record.get("dispatch_token"),
            plan_version=int(record.get("plan_version") or 1),
            generation=int((lease or {}).get("generation") or record.get("generation") or 1),
        )
        record["run_identity"] = identity.to_dict()
        record["worker_liveness"] = live_info
        record["control_contract"] = {
            "status_owner": CONTROL_OWNER.get(str(record.get("status"))),
            "is_terminal": is_terminal(record.get("status")),
            "can_resume": str(record.get("status")) in {"paused", "interrupted"},
            "can_pause": str(record.get("status")) in {"queued", "running", "pause_requested"},
            "can_cancel": str(record.get("status")) not in TERMINAL_STATUSES,
            "worker_live": live_info["worker_live"],
            "status_label_stale": live_info["status_label_stale"],
        }
        record["worker_live"] = live_info["worker_live"]
        with self._lock:
            record["dispatch_token"] = self._dispatch_tokens.get(job_id) or record.get("dispatch_token")
        return record

    def list_jobs(self, *, limit: int = 40, include_terminal: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*/status.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            status = str(record.get("status") or "")
            if not include_terminal and status in TERMINAL_STATUSES:
                continue
            rows.append(
                {
                    "id": record.get("id") or path.parent.name,
                    "status": status,
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("updated_at"),
                    "goal": (record.get("params") or {}).get("goal"),
                    "source_repo": (record.get("params") or {}).get("source_repo"),
                    "strategy": (record.get("params") or {}).get("strategy"),
                    "run_id": record.get("run_id"),
                    "error": record.get("error"),
                    "last_event_seq": record.get("last_event_seq") or record.get("event_seq"),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _resolve_runner(self, job_id: str, params: dict[str, Any], runner: RunnerFn | None) -> RunnerFn:
        if runner is not None:
            with self._lock:
                self._runners[job_id] = runner
            return runner
        with self._lock:
            cached = self._runners.get(job_id)
            if cached is not None:
                return cached
            factory = self._runner_factory
        if factory is None:
            raise RuntimeError("no_runner_factory: cannot dispatch job without runner")
        built = factory(params)
        with self._lock:
            self._runners[job_id] = built
        return built

    def _persist_execution_payload(self, job_id: str, params: dict[str, Any], *, checkpoint: dict[str, Any] | None = None) -> None:
        """Durable rebuild info — do not rely solely on in-memory closures."""
        with self._lock:
            record = self._read(job_id)
            payload = dict(record.get("execution_payload") or {})
            payload.update(
                {
                    "params": {
                        "source_repo": params.get("source_repo"),
                        "goal": params.get("goal"),
                        "original_goal": params.get("original_goal") or params.get("goal"),
                        "test_suite": params.get("test_suite"),
                        "test_args": params.get("test_args"),
                        "max_attempts": params.get("max_attempts"),
                        "strategy": params.get("strategy"),
                        "selector_mode": params.get("selector_mode"),
                        "model_id": params.get("model_id"),
                        "use_omniroute": bool(params.get("use_omniroute") or False),
                        "auto_repair": params.get("auto_repair", True),
                        "autonomy_profile": params.get("autonomy_profile"),
                        "task_type": params.get("task_type"),
                        "task_intent": params.get("task_intent"),
                        "project_id": params.get("project_id"),
                        "edits": params.get("edits"),
                        "repair_waves": params.get("repair_waves"),
                        "config_snapshot": params.get("config_snapshot") or {},
                        "routing_snapshot": params.get("routing_snapshot"),
                    },
                    "checkpoint": checkpoint or record.get("checkpoint") or empty_checkpoint(),
                    "processed_instruction_version": int(
                        (checkpoint or {}).get("processed_instruction_version")
                        or record.get("processed_instruction_version")
                        or 0
                    ),
                    "work_root": (checkpoint or {}).get("work_root") or record.get("work_root"),
                    "baseline_commit": (checkpoint or {}).get("baseline_commit") or record.get("baseline_commit"),
                    "updated_at": time.time(),
                }
            )
            record["execution_payload"] = payload
            record["checkpoint"] = payload["checkpoint"]
            record["processed_instruction_version"] = payload["processed_instruction_version"]
            if payload.get("work_root"):
                record["work_root"] = payload["work_root"]
            if payload.get("baseline_commit"):
                record["baseline_commit"] = payload["baseline_commit"]
            self._write(job_id, record)

    def checkpoint(
        self,
        job_id: str,
        *,
        phase: str,
        action_index: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cooperative control point before a new investigate/model/edit/test action.

        Raises CodingJobCancelled or CodingJobPaused. Returns control snapshot with
        any newly received instructions for the runner to apply.
        """
        self.leases.renew(f"coding_job:{job_id}", worker_id=self._worker_id(job_id), ttl_s=600)
        with self._lock:
            record = self._read(job_id)
        if record.get("cancel_requested") or str(record.get("status")) in {"cancel_requested", "cancelled"}:
            self._append_event(job_id, "CANCEL_HONORED", {"phase": phase, "action_index": action_index})
            try:
                self._set_status(job_id, "cancelled", evidence={"phase": phase, "from": "checkpoint"})
            except ValueError:
                self._update(job_id, status="cancelled")
            self._append_event(job_id, "JOB_CANCELLED", {"phase": phase, "action_index": action_index})
            raise CodingJobCancelled(phase=phase)

        lease_snap = self.leases.snapshot(job_id)
        pause_wanted = bool(lease_snap.get("pause_requested")) or str(record.get("status")) == "pause_requested"
        if pause_wanted:
            cp = dict(record.get("checkpoint") or empty_checkpoint(phase=phase))
            cp.update(
                {
                    "phase": phase,
                    "action_index": action_index if action_index is not None else cp.get("action_index") or 0,
                    "saved_at": time.time(),
                    "evidence": "cooperative_checkpoint",
                    **(extra or {}),
                }
            )
            self._persist_execution_payload(job_id, record.get("params") or {}, checkpoint=cp)
            try:
                self._set_status(
                    job_id,
                    "paused",
                    evidence={"phase": phase, "checkpoint": cp, "worker_released": True},
                )
            except ValueError:
                # Already paused / transitional — force durable paused with evidence.
                self._update(job_id, status="paused", checkpoint=cp)
            self.leases.mark_paused(job_id)
            self._append_event(job_id, "JOB_PAUSED", {"phase": phase, "checkpoint": cp})
            raise CodingJobPaused(checkpoint=cp)

        # Pull pending instructions for runner adaptation.
        instructions = list(record.get("instructions") or [])
        pending = [i for i in instructions if str(i.get("status")) == "received"]
        return {
            "ok": True,
            "phase": phase,
            "pending_instructions": pending,
            "processed_instruction_version": int(record.get("processed_instruction_version") or 0),
            "cancel_requested": False,
            "pause_requested": False,
        }

    def mark_instructions_processed(
        self,
        job_id: str,
        versions: list[int],
        *,
        action_index: int | None = None,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._read(job_id)
            instr = list(record.get("instructions") or [])
            max_ver = int(record.get("processed_instruction_version") or 0)
            for item in instr:
                ver = int(item.get("version") or 0)
                if ver in versions and item.get("status") == "received":
                    item["status"] = "processed"
                    item["processed_at"] = time.time()
                    item["effective_from_action"] = action_index
                    item["effective_from_checkpoint"] = checkpoint_id or f"cp_{phase_safe(action_index)}"
                    max_ver = max(max_ver, ver)
            record["instructions"] = instr
            # Keep legacy redirect_notes in sync for older UI.
            record["redirect_notes"] = [
                {"ts": i.get("received_at"), "note": i.get("note"), "version": i.get("version"), "status": i.get("status")}
                for i in instr
            ]
            record["processed_instruction_version"] = max_ver
            record["updated_at"] = time.time()
            self._write(job_id, record)
        self._append_event(
            job_id,
            "INSTRUCTIONS_PROCESSED",
            {"versions": versions, "action_index": action_index, "processed_instruction_version": max_ver},
        )
        return self.get(job_id)

    def _worker_id(self, job_id: str) -> str:
        try:
            return str(self._read(job_id).get("worker_id") or f"worker-{job_id}")
        except FileNotFoundError:
            return f"worker-{job_id}"

    def _dispatch(self, job_id: str, *, runner: RunnerFn | None = None, reason: str = "start") -> dict[str, Any]:
        """Schedule exactly one worker for this job; idempotent under concurrent resume."""
        with self._lock:
            record = self._read(job_id)
            live = self._futures.get(job_id)
            if live is not None and not live.done():
                return self.get(job_id)
            # Claim before releasing the lock so a parallel resume cannot also submit.
            if job_id in self._dispatch_claims:
                return self.get(job_id)
            if is_terminal(record.get("status")) and reason != "recover":
                raise ValueError(f"cannot_dispatch_terminal:{record.get('status')}")
            token = f"disp_{uuid.uuid4().hex[:12]}"
            self._dispatch_tokens[job_id] = token
            self._dispatch_claims.add(job_id)
            params = dict(record.get("params") or {})
            # Prefer execution_payload params (includes edits) when present.
            payload_params = ((record.get("execution_payload") or {}).get("params")) or {}
            if payload_params:
                params = {**params, **payload_params}
            worker_id = str(record.get("worker_id") or f"worker-{job_id}")
            record["dispatch_token"] = token
            record["dispatch_reason"] = reason
            record["updated_at"] = time.time()
            self._write(job_id, record)

        claimed = True
        try:
            lease = self.leases.acquire(f"coding_job:{job_id}", worker_id=worker_id, ttl_s=600)
            if not lease.get("ok"):
                # Another worker may hold lease briefly; if our future is live, ok.
                with self._lock:
                    live = self._futures.get(job_id)
                if live is not None and not live.done():
                    return self.get(job_id)
                self._update(job_id, status="failed", error=f"lease_unavailable:{lease.get('reason')}")
                self._append_event(job_id, "JOB_FAILED", {"error": f"lease_unavailable:{lease.get('reason')}"})
                return self.get(job_id)

            try:
                resolved = self._resolve_runner(job_id, params, runner)
            except Exception as exc:
                self.leases.release(f"coding_job:{job_id}", worker_id=worker_id)
                self._update(job_id, status="failed", error=str(exc))
                self._append_event(job_id, "JOB_FAILED", {"error": str(exc), "phase": "resolve_runner"})
                return self.get(job_id)

            # Bail if a newer dispatch claimed the token while we resolved the runner.
            with self._lock:
                if self._dispatch_tokens.get(job_id) != token:
                    self.leases.release(f"coding_job:{job_id}", worker_id=worker_id)
                    return self.get(job_id)

            def _work() -> dict[str, Any]:
                # Guard against superseded dispatch tokens (before and at runner entry).
                with self._lock:
                    if self._dispatch_tokens.get(job_id) != token:
                        return self.get(job_id)
                try:
                    self._set_status(job_id, "running", evidence={"dispatch_token": token, "reason": reason})
                except ValueError:
                    # From queued after resume, or pause_requested cleared — force running with evidence.
                    self._update(job_id, status="running")
                self._append_event(job_id, "JOB_STARTED", {"dispatch_token": token, "reason": reason})
                self.leases.renew(f"coding_job:{job_id}", worker_id=worker_id, ttl_s=600)

                # Pre-start cooperative gates.
                snap = self.get(job_id)
                if snap.get("cancel_requested"):
                    self._update(job_id, status="cancelled")
                    self._append_event(job_id, "JOB_CANCELLED", {"phase": "before_run"})
                    return self.get(job_id)
                if not self.leases.should_start_new_step(job_id) or snap.get("status") == "pause_requested":
                    cp = empty_checkpoint(phase="before_run")
                    self._persist_execution_payload(job_id, params, checkpoint=cp)
                    self._update(job_id, status="paused", checkpoint=cp)
                    self.leases.mark_paused(job_id)
                    self._append_event(job_id, "JOB_PAUSED", {"phase": "before_run", "checkpoint": cp})
                    return self.get(job_id)

                try:

                    def progress(kind: str, data: dict[str, Any] | None = None) -> None:
                        self.leases.renew(f"coding_job:{job_id}", worker_id=worker_id, ttl_s=600)
                        payload = dict(data or {})
                        # Map result-like completions honestly.
                        if kind == "JOB_COMPLETED" and payload.get("status") in {"failed", "tests_failed"}:
                            kind = "JOB_RESULT"
                        if kind == "MODEL_ROUTING":
                            from coding_omniroute import public_routing_snapshot

                            payload = public_routing_snapshot(payload)
                        self._append_event(job_id, kind, payload)
                        if kind == "MODEL_ROUTING":
                            self._update(job_id, omniroute=payload)
                        # Checkpoint before further work when runner signals action boundaries.
                        phase = str(payload.get("phase") or kind)
                        if payload.get("checkpoint") or kind in {
                            "BEFORE_ACTION",
                            "BEFORE_MODEL",
                            "BEFORE_EDIT",
                            "BEFORE_TEST",
                            "INVESTIGATE_STEP",
                        }:
                            self.checkpoint(
                                job_id,
                                phase=phase,
                                action_index=payload.get("action_index"),
                                extra=payload.get("checkpoint_extra") or {},
                            )
                        elif self.get(job_id).get("cancel_requested"):
                            raise CodingJobCancelled(phase=phase)

                    # Always pass live instruction fetch — not a start-time snapshot only.
                    def fetch_instructions() -> list[dict[str, Any]]:
                        return list(self._read(job_id).get("instructions") or [])

                    def apply_instructions(versions: list[int], *, action_index: int | None = None) -> None:
                        self.mark_instructions_processed(job_id, versions, action_index=action_index)

                    with self._lock:
                        if self._dispatch_tokens.get(job_id) != token:
                            return self.get(job_id)

                    result = resolved(
                        {
                            **params,
                            "job_id": job_id,
                            "progress": progress,
                            "redirect_notes": list(self._read(job_id).get("redirect_notes") or []),
                            "instructions": fetch_instructions(),
                            "fetch_instructions": fetch_instructions,
                            "apply_instructions": apply_instructions,
                            "job_checkpoint": lambda **kw: self.checkpoint(job_id, **kw),
                            "checkpoint": self._read(job_id).get("checkpoint"),
                        }
                    )
                    if self.get(job_id).get("cancel_requested"):
                        self._update(
                            job_id,
                            status="cancelled",
                            result=result,
                            run_id=result.get("id") or result.get("run_id"),
                        )
                        self._append_event(job_id, "JOB_CANCELLED", {"phase": "after_run"})
                    else:
                        runner_status = str(result.get("status") or "").strip()
                        terminal = runner_status or "completed"
                        if runner_status and terminal not in TERMINAL_STATUSES:
                            terminal = "failed"
                        try:
                            self._set_status(
                                job_id,
                                terminal,
                                evidence={"runner_status": result.get("status"), "run_id": result.get("id") or result.get("run_id")},
                                result=result,
                                run_id=result.get("id") or result.get("run_id"),
                            )
                        except ValueError:
                            self._update(
                                job_id,
                                status=terminal,
                                result=result,
                                run_id=result.get("id") or result.get("run_id"),
                            )
                        # Honest event kind for failures.
                        if terminal in {"failed", "tests_failed"}:
                            self._append_event(job_id, "JOB_FAILED", {"status": terminal, "result_status": result.get("status")})
                        elif terminal == "cancelled":
                            self._append_event(job_id, "JOB_CANCELLED", {"status": terminal})
                        else:
                            self._append_event(job_id, "JOB_COMPLETED", {"status": terminal})
                    return self.get(job_id)
                except CodingJobPaused as exc:
                    # Already marked paused in checkpoint().
                    return self.get(job_id)
                except CodingJobCancelled as exc:
                    self._update(job_id, status="cancelled", error=str(exc))
                    self._append_event(job_id, "JOB_CANCELLED", {"error": str(exc), "phase": getattr(exc, "phase", None)})
                    return self.get(job_id)
                except Exception as exc:
                    # Do not treat cancel as investigate failure.
                    if isinstance(exc, CodingJobCancelled) or str(exc) == "cancel_requested" or self.get(job_id).get(
                        "cancel_requested"
                    ):
                        self._update(job_id, status="cancelled", error=str(exc))
                        self._append_event(job_id, "JOB_CANCELLED", {"error": str(exc)})
                    else:
                        self._update(job_id, status="failed", error=str(exc))
                        self._append_event(job_id, "JOB_FAILED", {"error": str(exc)})
                    return self.get(job_id)
                finally:
                    self.leases.release(f"coding_job:{job_id}", worker_id=worker_id)

            future = self._executor.submit(_work)
            with self._lock:
                if self._dispatch_tokens.get(job_id) != token:
                    # Superseded after submit — best-effort cancel; claim clears in finally.
                    future.cancel()
                    self.leases.release(f"coding_job:{job_id}", worker_id=worker_id)
                    return self.get(job_id)
                self._futures[job_id] = future
            return self.get(job_id)
        finally:
            if claimed:
                with self._lock:
                    self._dispatch_claims.discard(job_id)

    def start(
        self,
        *,
        runner: RunnerFn | None = None,
        params: dict[str, Any],
        job_id: str | None = None,
    ) -> dict[str, Any]:
        jid = job_id or f"cjob_{uuid.uuid4().hex[:12]}"
        worker_id = f"worker-{jid}"
        now = time.time()
        original_goal = params.get("original_goal") or params.get("goal")
        capability_intel: dict[str, Any] | None = params.get("capability_intel") if isinstance(params.get("capability_intel"), dict) else None
        if capability_intel is None and original_goal:
            try:
                from capability_intel.service import get_service

                capability_intel = get_service().observe(str(original_goal), persist=False)
            except Exception:
                capability_intel = None
        use_omniroute = bool(params.get("use_omniroute") or False)
        if use_omniroute and isinstance(capability_intel, dict):
            capability_intel = {
                **capability_intel,
                "omniroute": {
                    "requested": True,
                    "inventory": "runtime_discovery",
                    "not_in_canonical_registry": True,
                },
            }
        record = {
            "id": jid,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "params": {
                "source_repo": params.get("source_repo"),
                "goal": params.get("goal"),
                "original_goal": original_goal,
                "test_suite": params.get("test_suite"),
                "test_args": params.get("test_args"),
                "max_attempts": params.get("max_attempts"),
                "strategy": params.get("strategy"),
                "selector_mode": params.get("selector_mode"),
                "model_id": params.get("model_id"),
                "use_omniroute": use_omniroute,
                "auto_repair": params.get("auto_repair", True),
                "autonomy_profile": params.get("autonomy_profile"),
                "task_type": params.get("task_type"),
                "task_intent": params.get("task_intent"),
                "project_id": params.get("project_id"),
                "edits": params.get("edits"),
                "repair_waves": params.get("repair_waves"),
                "config_snapshot": params.get("config_snapshot") or {},
                "routing_snapshot": params.get("routing_snapshot"),
                "capability_intel": capability_intel,
            },
            "result": None,
            "error": None,
            "cancel_requested": False,
            "redirect_notes": [],
            "instructions": [],
            "processed_instruction_version": 0,
            "events_tail": [],
            "event_seq": 0,
            "run_id": None,
            "worker_id": worker_id,
            "checkpoint": empty_checkpoint(phase="queued"),
            "execution_payload": {},
            "status_evidence": [{"at": now, "from": None, "to": "queued", "evidence": "job_accepted"}],
        }
        if use_omniroute:
            record["omniroute"] = {
                "omniroute_requested": True,
                "omniroute_used": False,
                "fallback_used": False,
                "extra_routing_llm_calls": 0,
                "catalog_injected_into_prompt": False,
            }
        self._write(jid, record)
        self._persist_execution_payload(jid, record["params"], checkpoint=record["checkpoint"])
        self._append_event(jid, "JOB_QUEUED", {"worker_id": worker_id})
        if runner is not None:
            with self._lock:
                self._runners[jid] = runner
        return self._dispatch(jid, runner=runner, reason="start")

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        record = self._read(job_id)
        status = str(record.get("status") or "")
        if is_terminal(status) and status != "cancel_requested":
            # Idempotent: already done.
            return self.get(job_id)
        self._update(job_id, cancel_requested=True)
        from reasoning.long_task_resume import default_side_effect_ledger

        cancel_fence = default_side_effect_ledger.request_cancel(str(record.get("run_id") or job_id))
        self._update(job_id, cancel_fence=cancel_fence)
        # Cancel active Coding model Tasks (owner-loop safe) and fence LM Studio.
        try:
            from coding_model_runtime import cancel_coding_run
            from lm_studio import remember_cancelled_run

            remember_cancelled_run(job_id)
            model_cancel = cancel_coding_run(job_id, wait_s=2.0)
            self._append_event(job_id, "MODEL_CANCEL_SIGNALED", {"model_cancel": model_cancel})
        except Exception as exc:
            self._append_event(job_id, "MODEL_CANCEL_SIGNALED", {"error": str(exc)[:200]})
        if status in {"queued", "pause_requested", "paused"}:
            # No live work — cancel immediately with evidence.
            with self._lock:
                live = self._futures.get(job_id)
            if live is None or live.done():
                try:
                    self._set_status(job_id, "cancelled", evidence={"phase": "immediate", "no_live_worker": True})
                except ValueError:
                    self._update(job_id, status="cancelled")
                self._append_event(job_id, "JOB_CANCELLED", {"phase": "immediate", "cancel_fence": cancel_fence})
                return self.get(job_id)
        if status not in {"cancel_requested", "cancelled"}:
            try:
                self._set_status(job_id, "cancel_requested", evidence={"api": "request_cancel", "cancel_fence": cancel_fence})
            except ValueError:
                pass
        self._append_event(job_id, "CANCEL_REQUESTED", {"processing": True, "cancel_fence": cancel_fence})
        return self.get(job_id)

    def accept_late_artifact(self, job_id: str, artifact_id: str) -> dict[str, Any]:
        """Cancel stops subprocesses and prevents late artifacts from being accepted."""
        record = self._read(job_id)
        from reasoning.long_task_resume import default_side_effect_ledger

        run_id = str(record.get("run_id") or job_id)
        if record.get("cancel_requested") or str(record.get("status")) in {"cancelled", "cancel_requested"}:
            default_side_effect_ledger.request_cancel(run_id)
        result = default_side_effect_ledger.accept_artifact(run_id=run_id, artifact_id=artifact_id)
        if result.get("accepted"):
            arts = list((record.get("result") or {}).get("artifact_ids") or [])
            if artifact_id not in arts:
                arts.append(artifact_id)
            merged = dict(record.get("result") or {})
            merged["artifact_ids"] = arts
            self._update(job_id, result=merged)
        else:
            self._append_event(job_id, "LATE_ARTIFACT_REJECTED", {"artifact_id": artifact_id, **result})
        return result

    def request_pause(self, job_id: str) -> dict[str, Any]:
        record = self._read(job_id)
        status = str(record.get("status") or "")
        if is_terminal(status):
            raise ValueError(f"cannot_pause_terminal:{status}")
        self.leases.request_pause(job_id)
        if status != "paused":
            try:
                self._set_status(job_id, "pause_requested", evidence={"api": "request_pause"})
            except ValueError:
                self._update(job_id, status="pause_requested")
        self._append_event(job_id, "PAUSE_REQUESTED", {"awaiting_checkpoint": status == "running"})
        # If no live worker yet (queued), the worker will pause at before_run.
        return self.get(job_id)

    def resume(self, job_id: str, *, runner: RunnerFn | None = None) -> dict[str, Any]:
        record = self._read(job_id)
        status = str(record.get("status") or "")
        if status not in {"paused", "interrupted", "queued"}:
            if status == "running":
                with self._lock:
                    live = self._futures.get(job_id)
                if live is not None and not live.done():
                    return self.get(job_id)  # already running — idempotent
            if is_terminal(status):
                raise ValueError(f"cannot_resume_terminal:{status}")
            raise ValueError(f"cannot_resume_from:{status}")

        self.leases.clear_pause(job_id)
        self._append_event(job_id, "RESUME_REQUESTED", {"from_status": status})
        if status in {"paused", "interrupted"}:
            try:
                self._set_status(job_id, "queued", evidence={"api": "resume", "from": status})
            except ValueError:
                self._update(job_id, status="queued")
        # Actually dispatch a worker from persisted execution payload.
        return self._dispatch(job_id, runner=runner, reason="resume")

    def redirect(self, job_id: str, note: str) -> dict[str, Any]:
        note_clean = (note or "").strip()
        if not note_clean:
            raise ValueError("redirect note required")
        with self._lock:
            record = self._read(job_id)
            instructions = list(record.get("instructions") or [])
            next_ver = (max((int(i.get("version") or 0) for i in instructions), default=0) + 1)
            instr = JobInstruction(version=next_ver, note=note_clean, received_at=time.time())
            instructions.append(instr.to_dict())
            notes = list(record.get("redirect_notes") or [])
            notes.append(
                {
                    "ts": instr.received_at,
                    "note": note_clean,
                    "version": next_ver,
                    "status": "received",
                    "id": instr.id,
                }
            )
            record["instructions"] = instructions
            record["redirect_notes"] = notes
            record["updated_at"] = time.time()
            self._write(job_id, record)
        self._append_event(job_id, "REDIRECT", {"note": note_clean, "version": next_ver, "status": "received"})
        return self.get(job_id)

    def recover_stale(self, *, max_age_s: float = 7200.0, auto_resume: bool = False) -> dict[str, Any]:
        """Mark running jobs without live future as interrupted; optionally re-queue."""
        recovered = []
        resumed = []
        reasons: dict[str, str] = {}
        now = time.time()
        for path in self.root.glob("*/status.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            jid = str(record.get("id") or path.parent.name)
            status = record.get("status")
            if status not in {"running", "queued", "pause_requested", "cancel_requested"}:
                continue
            with self._lock:
                live = self._futures.get(jid)
            if live is not None and not live.done():
                continue
            age = now - float(record.get("updated_at") or record.get("created_at") or now)
            if status == "queued" and age < 30:
                continue
            if age > max_age_s or status in {"running", "pause_requested", "cancel_requested"}:
                payload = record.get("execution_payload") or {}
                has_payload = bool((payload.get("params") or {}).get("goal") or (payload.get("params") or {}).get("source_repo"))
                if status == "cancel_requested":
                    self._update(jid, status="cancelled", error="worker_unavailable_while_cancelling")
                    self._append_event(jid, "JOB_CANCELLED", {"reason": "worker_unavailable"})
                    recovered.append(jid)
                    reasons[jid] = "cancelled_after_worker_loss"
                    continue
                self._update(jid, status="interrupted", error="worker_unavailable")
                self._append_event(
                    jid,
                    "JOB_INTERRUPTED",
                    {
                        "reason": "worker_unavailable",
                        "recoverable": has_payload,
                        "checkpoint": record.get("checkpoint"),
                        "processed_instruction_version": record.get("processed_instruction_version"),
                    },
                )
                recovered.append(jid)
                reasons[jid] = "interrupted_recoverable" if has_payload else "interrupted_missing_payload"
                if auto_resume and has_payload and self._runner_factory is not None:
                    try:
                        self.resume(jid)
                        resumed.append(jid)
                    except Exception as exc:
                        reasons[jid] = f"resume_failed:{exc}"
        return {"recovered": recovered, "resumed": resumed, "reasons": reasons, "count": len(recovered)}


def phase_safe(action_index: int | None) -> str:
    return f"action_{action_index if action_index is not None else 0}"


_STORE: CodingJobStore | None = None
_STORE_LOCK = threading.Lock()


def get_coding_job_store(data_root: Path | str | None = None) -> CodingJobStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            root = Path(data_root) if data_root else Path.cwd() / "data" / "coding_jobs"
            _STORE = CodingJobStore(Path(root) / "coding_jobs")
        return _STORE


def reset_coding_job_store_for_tests(data_root: Path | str) -> CodingJobStore:
    global _STORE
    with _STORE_LOCK:
        _STORE = CodingJobStore(Path(data_root) / "coding_jobs")
        return _STORE
