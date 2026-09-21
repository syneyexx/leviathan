"""Typed semantic clients for native RPC methods."""

from __future__ import annotations

from typing import Any, Protocol


class SupportsNativeCall(Protocol):
    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None) -> dict[str, Any]: ...


class NativeProcessClient:
    def __init__(self, rpc: SupportsNativeCall) -> None:
        self._rpc = rpc

    def run(
        self,
        *,
        executable: str,
        argv: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_ms: int | None = None,
        max_stdout_bytes: int | None = None,
        max_stderr_bytes: int | None = None,
        job_id: str | None = None,
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"executable": executable, "argv": list(argv or [])}
        if cwd:
            params["cwd"] = cwd
        if env is not None:
            params["env"] = env
        if timeout_ms is not None:
            params["timeout_ms"] = int(timeout_ms)
        if max_stdout_bytes is not None:
            params["max_stdout_bytes"] = int(max_stdout_bytes)
        if max_stderr_bytes is not None:
            params["max_stderr_bytes"] = int(max_stderr_bytes)
        if job_id:
            params["job_id"] = job_id
        if deadline_ms is not None:
            params["deadline_ms"] = int(deadline_ms)
        wait = None if timeout_ms is None else max(5.0, (timeout_ms / 1000.0) + 5.0)
        return self._rpc.call("process.run", params, timeout_s=wait)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._rpc.call("process.cancel", {"job_id": job_id}, timeout_s=10)


class NativeServiceClient:
    def __init__(self, rpc: SupportsNativeCall) -> None:
        self._rpc = rpc

    def start(self, **params: Any) -> dict[str, Any]:
        return self._rpc.call("service.start", params)

    def status(self, service_id: str) -> dict[str, Any]:
        return self._rpc.call("service.status", {"id": service_id})

    def stop(self, service_id: str) -> dict[str, Any]:
        return self._rpc.call("service.stop", {"id": service_id})

    def logs(self, service_id: str, *, max_bytes: int = 100_000) -> dict[str, Any]:
        return self._rpc.call("service.logs", {"id": service_id, "max_bytes": max_bytes})

    def probe(self, service_id: str, creation_time: float | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"id": service_id}
        if creation_time is not None:
            params["creation_time"] = creation_time
        return self._rpc.call("service.probe", params)


class NativeFilesystemClient:
    def __init__(self, rpc: SupportsNativeCall) -> None:
        self._rpc = rpc

    def scan(self, path: str, *, max_entries: int = 10_000) -> dict[str, Any]:
        return self._rpc.call("fs.scan", {"path": path, "max_entries": max_entries})

    def hash(self, path: str) -> dict[str, Any]:
        return self._rpc.call("fs.hash", {"path": path})

    def hash_many(self, paths: list[str], *, max_files: int = 1000) -> dict[str, Any]:
        return self._rpc.call("fs.hash_many", {"paths": paths, "max_files": max_files})

    def snapshot(
        self,
        path: str,
        *,
        max_entries: int = 10_000,
        include_hash: bool = False,
        ignore: list[str] | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "path": path,
            "max_entries": max_entries,
            "include_hash": include_hash,
            "offset": offset,
        }
        if ignore:
            params["ignore"] = ignore
        return self._rpc.call("fs.snapshot", params)

    def repo_search(self, path: str, query: str, *, max_matches: int = 200) -> dict[str, Any]:
        return self._rpc.call("repo.search", {"path": path, "query": query, "max_matches": max_matches})


class NativeMetricsClient:
    def __init__(self, rpc: SupportsNativeCall) -> None:
        self._rpc = rpc

    def system_metrics(self) -> dict[str, Any]:
        return self._rpc.call("system.metrics", {})

    def health(self) -> dict[str, Any]:
        return self._rpc.call("runtime.health", {})

    def capabilities(self) -> dict[str, Any]:
        return self._rpc.call("runtime.capabilities", {})
