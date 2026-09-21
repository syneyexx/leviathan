"""Local compute executor contract — reference implementation for Phase L.

Remote/distributed nodes must implement the same job contract; pairing is separate.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from typing import Any


def _new_id(prefix: str = "job") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class LocalExecutor:
    """Stable local job contract: submit / status / cancel / artifacts."""

    SUPPORTED_OPS = frozenset({"ping", "inspect", "echo", "local_info", "heartbeat"})

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "node": "local",
            "ops": sorted(self.SUPPORTED_OPS),
            "cancel": True,
            "artifacts": True,
            "distributed": False,
            "note": "Local reference executor. Distributed peering is optional and not required.",
        }

    def submit(self, spec: dict[str, Any]) -> dict[str, Any]:
        op = str((spec or {}).get("op") or "ping")
        payload = dict((spec or {}).get("payload") or {})
        job_id = _new_id()
        started = time.time()
        with self._lock:
            if op not in self.SUPPORTED_OPS:
                job = {
                    "id": job_id,
                    "op": op,
                    "status": "failed",
                    "error": f"unsupported_op:{op}",
                    "result": None,
                    "artifacts": [],
                    "started_at": started,
                    "finished_at": time.time(),
                }
                self._jobs[job_id] = job
                return dict(job)
            result = self._execute(op, payload)
            artifacts = []
            if "echo" in result:
                raw = str(result["echo"]).encode("utf-8")
                artifacts.append(
                    {
                        "name": "echo.txt",
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw),
                    }
                )
            job = {
                "id": job_id,
                "op": op,
                "status": "completed",
                "error": None,
                "result": result,
                "artifacts": artifacts,
                "started_at": started,
                "finished_at": time.time(),
                "node": "local",
            }
            self._jobs[job_id] = job
            return dict(job)

    def _execute(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        if op in {"ping", "inspect", "heartbeat"}:
            return {"ok": True, "op": op, "ts": time.time()}
        if op == "echo":
            return {"ok": True, "echo": payload.get("message", "")}
        if op == "local_info":
            return {"ok": True, "node": "local", "ops": sorted(self.SUPPORTED_OPS)}
        return {"ok": False}

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"ok": False, "status": "not_found", "id": job_id}
            return {"ok": True, **job}

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"ok": False, "status": "not_found", "id": job_id}
            if job.get("status") in {"completed", "failed", "cancelled"}:
                return {"ok": False, "status": job["status"], "id": job_id, "reason": "already_done"}
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
            return {"ok": True, "status": "cancelled", "id": job_id}


_LOCAL_EXECUTOR = LocalExecutor()


def get_local_executor() -> LocalExecutor:
    return _LOCAL_EXECUTOR
