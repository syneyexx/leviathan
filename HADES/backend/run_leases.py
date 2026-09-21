"""Execution leases and pause request state (Phase H + package I fencing/CAS).

In-memory store with optional JSON persistence for crash recovery across process restarts.
Lease acquire uses generation fencing so stale workers cannot renew after expiry or reclaim.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class ExecutionLeaseStore:
    def __init__(self, persist_path: Path | str | None = None) -> None:
        self._leases: dict[str, dict[str, Any]] = {}
        self._control: dict[str, dict[str, Any]] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.RLock()
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._load()

    def set_persist_path(self, path: Path | str | None) -> None:
        with self._lock:
            self._persist_path = Path(path) if path else None
            if self._persist_path:
                self._load()

    def _load(self) -> None:
        path = self._persist_path
        if not path or not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("lease persistence root must be an object")
            raw_leases = raw.get("leases") or {}
            raw_control = raw.get("control") or {}
            raw_generations = raw.get("generations") or {}
            if not isinstance(raw_leases, dict):
                raise ValueError("leases must be an object")
            if not isinstance(raw_control, dict):
                raise ValueError("control must be an object")
            if not isinstance(raw_generations, dict):
                raise ValueError("generations must be an object")
            leases = {str(k): dict(v) for k, v in raw_leases.items()}
            control = {str(k): dict(v) for k, v in raw_control.items()}
            generations = {str(k): int(v) for k, v in raw_generations.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Persisted execution lease state is unreadable or corrupt: {path}"
            ) from exc
        # Commit the recovered snapshot only after the full document validates.
        self._leases = leases
        self._control = control
        self._generations = generations

    def _save(self) -> None:
        path = self._persist_path
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = {
            "leases": self._leases,
            "control": self._control,
            "generations": self._generations,
            "saved_at": time.time(),
        }
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _restore_mapping_entry(mapping: dict[str, Any], key: str, previous: Any, existed: bool) -> None:
        if existed:
            mapping[key] = previous
        else:
            mapping.pop(key, None)

    def generation(self, resource_id: str) -> int:
        with self._lock:
            return int(self._generations.get(resource_id) or 0)

    def bump_generation(self, resource_id: str) -> int:
        with self._lock:
            existed = resource_id in self._generations
            previous = self._generations.get(resource_id)
            nxt = int(previous or 0) + 1
            self._generations[resource_id] = nxt
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._generations, resource_id, previous, existed)
                raise
            return nxt

    def acquire(self, resource_id: str, *, worker_id: str, ttl_s: float = 60.0) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            current = self._leases.get(resource_id)
            if current and current.get("expires_at", 0) > now and current.get("worker_id") != worker_id:
                return {
                    "ok": False,
                    "reason": "held",
                    "holder": current.get("worker_id"),
                    "fence_token": current.get("fence_token"),
                    "generation": current.get("generation"),
                }
            gen_existed = resource_id in self._generations
            previous_gen = self._generations.get(resource_id)
            lease_existed = resource_id in self._leases
            previous_lease = current
            gen = int(previous_gen or 0) + 1
            self._generations[resource_id] = gen
            fence = f"fence_{uuid.uuid4().hex[:12]}"
            lease = {
                "resource_id": resource_id,
                "worker_id": worker_id,
                "acquired_at": now,
                "expires_at": now + ttl_s,
                "fence_token": fence,
                "generation": gen,
            }
            self._leases[resource_id] = lease
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._generations, resource_id, previous_gen, gen_existed)
                self._restore_mapping_entry(self._leases, resource_id, previous_lease, lease_existed)
                raise
            return {"ok": True, "lease": lease, "fence_token": fence, "generation": gen}

    def release(self, resource_id: str, *, worker_id: str, fence_token: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = self._leases.get(resource_id)
            if not current:
                return {"ok": True, "status": "absent"}
            if current.get("worker_id") != worker_id:
                return {"ok": False, "reason": "not_holder"}
            if fence_token and current.get("fence_token") and fence_token != current.get("fence_token"):
                return {"ok": False, "reason": "stale_fence", "generation": current.get("generation")}
            self._leases.pop(resource_id, None)
            try:
                self._save()
            except OSError:
                self._leases[resource_id] = current
                raise
            return {"ok": True, "status": "released"}

    def renew(
        self,
        resource_id: str,
        *,
        worker_id: str,
        ttl_s: float = 60.0,
        fence_token: str | None = None,
        generation: int | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            current = self._leases.get(resource_id)
            if not current or current.get("worker_id") != worker_id:
                return {"ok": False, "reason": "not_holder"}
            if float(current.get("expires_at") or 0) <= now:
                return {"ok": False, "reason": "expired", "generation": current.get("generation")}
            if fence_token and current.get("fence_token") and fence_token != current.get("fence_token"):
                return {"ok": False, "reason": "stale_fence", "generation": current.get("generation")}
            if generation is not None and int(current.get("generation") or 0) != int(generation):
                return {"ok": False, "reason": "stale_generation", "generation": current.get("generation")}
            previous_expiry = current.get("expires_at")
            current["expires_at"] = now + ttl_s
            try:
                self._save()
            except OSError:
                current["expires_at"] = previous_expiry
                raise
            return {"ok": True, "lease": dict(current)}

    def compare_and_set_holder(
        self,
        resource_id: str,
        *,
        expected_worker_id: str | None,
        new_worker_id: str,
        ttl_s: float = 60.0,
    ) -> dict[str, Any]:
        """CAS: only take over when holder matches expectation (or absent/expired)."""
        now = time.time()
        with self._lock:
            current = self._leases.get(resource_id)
            live = bool(current and float(current.get("expires_at") or 0) > now)
            holder = current.get("worker_id") if live else None
            if holder != expected_worker_id:
                return {
                    "ok": False,
                    "reason": "cas_mismatch",
                    "holder": holder,
                    "expected": expected_worker_id,
                }
            gen_existed = resource_id in self._generations
            previous_gen = self._generations.get(resource_id)
            lease_existed = resource_id in self._leases
            previous_lease = current
            gen = int(previous_gen or 0) + 1
            self._generations[resource_id] = gen
            fence = f"fence_{uuid.uuid4().hex[:12]}"
            lease = {
                "resource_id": resource_id,
                "worker_id": new_worker_id,
                "acquired_at": now,
                "expires_at": now + ttl_s,
                "fence_token": fence,
                "generation": gen,
            }
            self._leases[resource_id] = lease
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._generations, resource_id, previous_gen, gen_existed)
                self._restore_mapping_entry(self._leases, resource_id, previous_lease, lease_existed)
                raise
            return {"ok": True, "lease": lease, "fence_token": fence, "generation": gen}

    def request_pause(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            existed = task_id in self._control
            previous = dict(self._control.get(task_id) or {})
            state = self._control.setdefault(task_id, {"pause_requested": False, "paused": False})
            state["pause_requested"] = True
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._control, task_id, previous, existed)
                raise
            return dict(state)

    def mark_paused(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            existed = task_id in self._control
            previous = dict(self._control.get(task_id) or {})
            state = self._control.setdefault(task_id, {"pause_requested": False, "paused": False})
            state["paused"] = True
            state["pause_requested"] = False
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._control, task_id, previous, existed)
                raise
            return dict(state)

    def clear_pause(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            existed = task_id in self._control
            previous = dict(self._control.get(task_id) or {})
            state = self._control.setdefault(task_id, {"pause_requested": False, "paused": False})
            state["pause_requested"] = False
            state["paused"] = False
            try:
                self._save()
            except OSError:
                self._restore_mapping_entry(self._control, task_id, previous, existed)
                raise
            return dict(state)

    def snapshot(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._control.get(task_id) or {"pause_requested": False, "paused": False})

    def should_start_new_step(self, task_id: str) -> bool:
        snap = self.snapshot(task_id)
        return not snap.get("pause_requested") and not snap.get("paused")

    def reclaim_stale(self, *, now: float | None = None) -> list[str]:
        now = now if now is not None else time.time()
        reclaimed: list[str] = []
        with self._lock:
            previous_leases = {key: dict(value) for key, value in self._leases.items()}
            previous_generations = dict(self._generations)
            for rid, lease in list(self._leases.items()):
                if float(lease.get("expires_at") or 0) <= now:
                    self._leases.pop(rid, None)
                    # Bump generation so a late renew from the dead holder fails CAS.
                    self._generations[rid] = int(self._generations.get(rid) or 0) + 1
                    reclaimed.append(rid)
            if reclaimed:
                try:
                    self._save()
                except OSError:
                    self._leases = previous_leases
                    self._generations = previous_generations
                    raise
        return reclaimed

    def lease_snapshot(self, resource_id: str) -> dict[str, Any] | None:
        with self._lock:
            lease = self._leases.get(resource_id)
            return dict(lease) if lease else None

    def restore_control_from_tasks(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """After process restart: rebuild pause flags from durable task.control_state."""
        restored = {"paused": 0, "pause_requested": 0}
        with self._lock:
            previous_control = {key: dict(value) for key, value in self._control.items()}
            for task in tasks:
                tid = str(task.get("id") or "")
                if not tid:
                    continue
                cs = str(task.get("control_state") or "active").lower()
                if cs == "paused":
                    self._control[tid] = {"pause_requested": False, "paused": True}
                    restored["paused"] += 1
                elif cs == "pause_requested":
                    self._control[tid] = {"pause_requested": True, "paused": False}
                    restored["pause_requested"] += 1
            try:
                self._save()
            except OSError:
                self._control = previous_control
                raise
        return restored

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "leases": {k: dict(v) for k, v in self._leases.items()},
                "control": {k: dict(v) for k, v in self._control.items()},
                "generations": dict(self._generations),
            }
