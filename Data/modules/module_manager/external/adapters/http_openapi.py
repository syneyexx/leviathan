"""Generic HTTP / OpenAPI capability adapter.

Exposes semantically meaningful operations from config — not a god http_request capability.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..types import ExternalFailureCode, ExternalRuntimeState, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb


class HttpOpenApiAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self._state = ExternalRuntimeState.READY
        self._base_url = ctx.config.runtime.base_url
        self._ops = {str(op.get("name") or op.get("operation")): op for op in ctx.config.runtime.operations}

    def runtime_state(self) -> ExternalRuntimeState:
        return self._state

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        # Remote-only HTTP needs no local install. Git/path + venv packages still install.
        strategies = [s.value if hasattr(s, "value") else str(s) for s in (self.config.install.strategies or [])]
        needs_local = any(s not in {"NONE", ""} for s in strategies) or self.config.source.source_type in {
            "git",
            "path",
        }
        if needs_local and self.ctx.data_root:
            from pathlib import Path

            from ..install import InstallationService

            service = InstallationService(Path(self.ctx.data_root))
            result = service.ensure_installed(
                module_id=self.ctx.module_id,
                config=self.config,
                progress=progress,
                cancel_check=cancel_check,
            )
            self._state = ExternalRuntimeState.INSTALLED
            if self.ctx.store is not None:
                self.ctx.store.add_version(
                    version_id=result.version_id,
                    module_id=self.ctx.module_id,
                    install_root=result.install_root,
                    source_ref=result.source_ref,
                    resolved_commit=result.resolved_commit,
                    content_hash=result.content_hash,
                    install_strategies=result.strategies,
                    dependency_versions=result.dependency_versions,
                    activate=True,
                )
                self.ctx.store.set_runtime_state(self.ctx.module_id, ExternalRuntimeState.INSTALLED.value)
            # Resolve base_url from install root placeholders when configured.
            if self._base_url and "$INSTALL_ROOT" in self._base_url and result.install_root:
                self._base_url = self._base_url.replace("$INSTALL_ROOT", result.install_root)
            return result.public_dict()
        self._state = ExternalRuntimeState.INSTALLED
        return {"status": "INSTALLED", "detail": "http_no_local_install"}

    def start(self) -> dict[str, Any]:
        self._state = ExternalRuntimeState.READY
        return {"status": "READY"}

    def stop(self) -> dict[str, Any]:
        self._state = ExternalRuntimeState.STOPPED
        return {"status": "STOPPED"}

    def restart(self) -> dict[str, Any]:
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        if not self._base_url and not self._ops:
            return {"ready": False, "code": ExternalFailureCode.NOT_INSTALLED.value}
        probe = self.config.runtime.health_probe or self.config.runtime.ready_probe
        if probe and str(probe.get("kind") or "http") == "http":
            url = str(probe.get("url") or self._base_url or "")
            if url:
                try:
                    req = urllib.request.Request(url, method=str(probe.get("method") or "GET"))
                    with urllib.request.urlopen(req, timeout=float(probe.get("timeout") or 5.0)) as resp:
                        if int(getattr(resp, "status", 200)) == int(probe.get("expect_status") or 200):
                            self._state = ExternalRuntimeState.READY
                            return {"ready": True}
                except Exception as exc:  # noqa: BLE001
                    self._state = ExternalRuntimeState.DEGRADED
                    return {"ready": False, "code": ExternalFailureCode.HEALTH_FAILED.value, "detail": str(exc)}
        self._state = ExternalRuntimeState.READY
        return {"ready": True, "base_url": self._base_url}

    def health(self) -> ModuleHealth:
        ready = self.ensure_ready()
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=ModuleStatus.READY if ready.get("ready") else ModuleStatus.ERROR,
            detail="http_ready" if ready.get("ready") else str(ready.get("code")),
            telemetry={"runtime_state": self._state.value, "adapter": "HTTP_OPENAPI", "operations": list(self._ops)},
        )

    def logs(self, *, limit: int = 200) -> list[str]:
        if self.ctx.store is not None:
            return self.ctx.store.get_logs(self.ctx.module_id, limit=limit)
        return []

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        op = self._ops.get(operation)
        if op is None:
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.CAPABILITY_NOT_FOUND.value,
                output={"error": {"code": ExternalFailureCode.CAPABILITY_NOT_FOUND.value}},
            )
        if cancel_check and cancel_check():
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="CANCELLED",
                error=ExternalFailureCode.CANCELLED.value,
            )
        method = str(op.get("method") or "GET").upper()
        path = str(op.get("path") or "/")
        for key, value in arguments.items():
            if isinstance(value, (str, int, float)):
                path = path.replace("{" + str(key) + "}", urllib.parse.quote(str(value), safe=""))
        base = str(op.get("base_url") or self._base_url or "").rstrip("/")
        url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
        query = op.get("query")
        if isinstance(query, Mapping):
            q = {str(k): str(arguments.get(k, v)) for k, v in query.items()}
            url = f"{url}?{urllib.parse.urlencode(q)}"
        body_obj = None
        if method in {"POST", "PUT", "PATCH"}:
            body_keys = op.get("body_from") or list(arguments.keys())
            if isinstance(body_keys, list):
                body_obj = {str(k): arguments.get(k) for k in body_keys if k in arguments}
            else:
                body_obj = dict(arguments)
        data = None if body_obj is None else json.dumps(body_obj).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update({str(k): str(v) for k, v in dict(op.get("headers") or {}).items()})
        timeout = float(op.get("timeout_seconds") or self.config.runtime.timeout_seconds)
        if progress:
            progress(0.1, "http", f"{method} {url}")
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status_code = int(getattr(resp, "status", 200))
            text = raw.decode("utf-8", errors="replace")
            structured: Any
            try:
                structured = json.loads(text) if text else None
            except json.JSONDecodeError:
                structured = None
            if status_code >= 400:
                return ModuleResult(
                    module_id=self.ctx.module_id,
                    operation=operation,
                    status="FAILED",
                    error=ExternalFailureCode.REMOTE_ERROR.value,
                    output=normalize_capability_parts(
                        summary=f"HTTP {status_code}",
                        raw_text=text[:4000],
                        error={"code": ExternalFailureCode.REMOTE_ERROR.value, "status_code": status_code},
                    ),
                )
            sources = []
            if isinstance(structured, dict):
                maybe = structured.get("sources") or structured.get("results") or structured.get("items")
                if isinstance(maybe, list):
                    from ..results import normalize_osint_items

                    sources = normalize_osint_items(maybe, provider=self.ctx.module_id)
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(
                    summary=f"{operation} ok",
                    structured_data=structured if isinstance(structured, (dict, list)) else None,
                    sources=sources or None,
                    raw_text=None if structured is not None else text[:4000],
                    metadata={"http_status": status_code, "url": url},
                ),
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.REMOTE_ERROR.value,
                output=normalize_capability_parts(
                    summary=f"HTTP {exc.code}",
                    raw_text=body[:4000],
                    error={"code": ExternalFailureCode.REMOTE_ERROR.value, "status_code": exc.code},
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.REMOTE_ERROR.value,
                output={"error": {"code": ExternalFailureCode.REMOTE_ERROR.value, "detail": str(exc)}},
            )
