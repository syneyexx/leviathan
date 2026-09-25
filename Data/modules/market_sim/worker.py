"""Market simulation worker — JobStore lease path (default) + legacy soft claim.

Default production path: durable ``market_sim.advance`` jobs claimed by the
``market_sim`` worker pool with JobStore leases + heartbeats. Soft ``worker_pid``
claiming remains for local drain/tests when JobRuntime is unbound.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from Data.modules.jobs.store import JobStore

from .engine import SimulationEngine
from .multi_engine import MultiAgentEngine
from .store import MarketSimStore, utc_now
from .types import RunStatus, TERMINAL_RUN_STATUSES


class MarketSimWorker:
    """Polls runnable simulations and advances the engine outside the HTTP path."""

    def __init__(
        self,
        store: MarketSimStore,
        engine: SimulationEngine,
        *,
        resolve_bars_path: Callable[[Any], str],
        resolve_strategy: Callable[[Any], dict[str, Any]] | None = None,
        bars_per_slice: int = 50,
        multi_engine: MultiAgentEngine | None = None,
        job_store: JobStore | None = None,
    ) -> None:
        self.store = store
        self.engine = engine
        self.multi_engine = multi_engine or MultiAgentEngine(store)
        self.resolve_bars_path = resolve_bars_path
        self.resolve_strategy = resolve_strategy
        self.bars_per_slice = bars_per_slice
        self.job_store = job_store
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._states: dict[str, Any] = {}
        lease_model = "jobstore_lease" if job_store is not None else "soft_worker_pid"
        self.telemetry: dict[str, Any] = {
            "slices": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "worker_mode": "daemon_thread",
            "worker_pid": os.getpid(),
            "isolated_subprocess": False,
            "lease_model": lease_model,
            "heartbeat": 0,
        }

    def bind_job_store(self, job_store: JobStore | None) -> None:
        self.job_store = job_store
        if job_store is not None:
            self.telemetry["lease_model"] = "jobstore_lease"

    def mark_subprocess(self) -> None:
        self.telemetry["worker_mode"] = "subprocess"
        self.telemetry["isolated_subprocess"] = True
        self.telemetry["worker_pid"] = os.getpid()

    def start_background(self, *, poll_seconds: float = 0.25) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def _loop() -> None:
                while not self._stop.is_set():
                    worked = self.process_next()
                    if not worked:
                        self._wake.wait(poll_seconds)
                        self._wake.clear()

            self._thread = threading.Thread(
                target=_loop,
                name="market-sim-worker",
                daemon=True,
            )
            self._thread.start()

    def stop_background(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def _heartbeat(self, job_id: str | None, *, worker_id: str | None = None) -> None:
        if not job_id or self.job_store is None:
            return
        try:
            self.job_store.heartbeat_lease(
                job_id,
                worker_id=worker_id or f"market-sim-{os.getpid()}",
                ttl_seconds=30.0,
            )
            self.telemetry["heartbeat"] = int(self.telemetry.get("heartbeat") or 0) + 1
            self.telemetry["lease_model"] = "jobstore_lease"
        except Exception:  # noqa: BLE001
            pass

    def _use_multi(self, run: Any) -> bool:
        meta = dict(run.metadata or {})
        if meta.get("engine") == "legacy":
            return False
        if meta.get("game_mode") or meta.get("multi_agent") or meta.get("commit_reveal"):
            return True
        agents = list(run.agents or [])
        traders = [
            a
            for a in agents
            if str(a.get("role"))
            not in {
                "trading_orchestrator",
                "orchestrator",
                "evaluator",
                "risk_agent",
                "risk_officer",
                "critic",
            }
        ]
        return len(traders) >= 2 and bool(meta.get("multi_wallet", False))

    def process_next(self) -> bool:
        run = self.store.claim_next_runnable()
        if run is None:
            return False
        return self._advance_run(run)

    def process_run(
        self,
        run_id: str,
        *,
        job_id: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """Advance one slice for a specific simulation (durable JobStore path)."""
        self._heartbeat(job_id, worker_id=worker_id)
        run = self.store.get_run(run_id)
        if run is None:
            return False
        if run.status not in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
            RunStatus.STEPPING.value,
        }:
            return False
        # Soft stamp still used as a secondary back-off signal for local drain.
        run.worker_pid = os.getpid()
        self.store.update_run(run)
        try:
            return self._advance_run(run, job_id=job_id, worker_id=worker_id)
        finally:
            self._heartbeat(job_id, worker_id=worker_id)

    def _advance_run(
        self,
        run: Any,
        *,
        job_id: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        try:
            if run.status == RunStatus.QUEUED.value:
                run.status = RunStatus.RUNNING.value
                run.started_at = run.started_at or utc_now()
                self.store.update_run(run)

            if run.status == RunStatus.PAUSED.value:
                run.worker_pid = None
                self.store.update_run(run)
                return True

            strategy = {}
            if self.resolve_strategy:
                strategy = self.resolve_strategy(run) or {}

            use_multi = self._use_multi(run)
            engine: Any = self.multi_engine if use_multi else self.engine
            state = self._states.get(run.run_id)
            if state is None:
                bars_path = self.resolve_bars_path(run)
                state = engine.prepare(
                    run,
                    bars_path=bars_path,
                    strategy_params=strategy.get("parameters"),
                    entry_rules=strategy.get("entry_rules"),
                    exit_rules=strategy.get("exit_rules"),
                    brain_dependencies=strategy.get("brain_dependencies"),
                )
                self._states[run.run_id] = state

            fresh = self.store.get_run(run.run_id)
            if fresh and fresh.cancel_requested:
                run.cancel_requested = True

            def cancel_check() -> bool:
                self._heartbeat(job_id, worker_id=worker_id)
                latest = self.store.get_run(run.run_id)
                if latest is None:
                    return True
                if latest.cancel_requested:
                    return True
                if latest.status == RunStatus.PAUSED.value:
                    state.run.status = RunStatus.PAUSED.value
                    return True
                return False

            max_bars = 1 if run.status == RunStatus.STEPPING.value else self.bars_per_slice
            if run.status == RunStatus.STEPPING.value:
                state.run.status = RunStatus.STEPPING.value

            engine.run_bars(
                state,
                max_bars=max_bars,
                cancel_check=cancel_check,
            )
            self.telemetry["slices"] += 1
            self.telemetry["last_engine"] = "multi" if use_multi else "legacy"

            out = state.run
            if out.status in TERMINAL_RUN_STATUSES:
                out.worker_pid = None
                self._states.pop(run.run_id, None)
                if out.status == RunStatus.COMPLETED.value:
                    self.telemetry["completed"] += 1
                elif out.status == RunStatus.CANCELLED.value:
                    self.telemetry["cancelled"] += 1
                self.store.add_event(
                    out.run_id,
                    kind="run_finished",
                    payload={"status": out.status, "metrics": out.metrics},
                )
            elif out.status == RunStatus.PAUSED.value:
                out.worker_pid = None
            else:
                out.status = RunStatus.RUNNING.value
                out.worker_pid = None
            self.store.update_run(out)
            return True
        except Exception as exc:  # noqa: BLE001
            run.status = RunStatus.FAILED.value
            run.error = str(exc)[:2000]
            run.worker_pid = None
            run.finished_at = utc_now()
            self.store.update_run(run)
            self.store.add_event(
                run.run_id,
                kind="run_failed",
                payload={"error": run.error},
            )
            self._states.pop(run.run_id, None)
            self.telemetry["failed"] += 1
            return True

    def drain(self, *, max_slices: int = 100) -> int:
        count = 0
        for _ in range(max_slices):
            if not self.process_next():
                break
            count += 1
        return count
