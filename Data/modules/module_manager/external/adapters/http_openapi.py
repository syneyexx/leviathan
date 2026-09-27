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
        # Declarative gate: ops that require an optional upstream feature return
        # NOT_AVAILABLE instead of opaque upstream 404s.
        gated = self._agent_runtime_gate(op)
        if gated is not None:
            return gated
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
            # Declarative arg→body field rename (e.g. topic → requirement).
            aliases = op.get("body_aliases")
            if isinstance(aliases, Mapping) and body_obj is not None:
                for src, dest in aliases.items():
                    src_k, dest_k = str(src), str(dest)
                    if src_k in arguments and (dest_k not in body_obj or body_obj.get(dest_k) in (None, "")):
                        body_obj[dest_k] = arguments.get(src_k)
                        body_obj.pop(src_k, None)
        data = None if body_obj is None else json.dumps(body_obj).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update({str(k): str(v) for k, v in dict(op.get("headers") or {}).items()})
        timeout = float(op.get("timeout_seconds") or self.config.runtime.timeout_seconds)
        accept_statuses = {
            int(x)
            for x in (op.get("accept_statuses") or [200, 201, 202, 204])
            if str(x).isdigit() or isinstance(x, int)
        }
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
            if status_code not in accept_statuses and status_code >= 400:
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
            output = normalize_capability_parts(
                summary=f"{operation} ok",
                structured_data=structured if isinstance(structured, (dict, list)) else None,
                sources=sources or None,
                raw_text=None if structured is not None else text[:4000],
                metadata={"http_status": status_code, "url": url},
            )
            try:
                from ..artifacts_materialize import materialize_large_http_body

                output = materialize_large_http_body(
                    output,
                    raw_text=text,
                    artifact_store=self.ctx.artifact_store,
                    module_id=self.ctx.module_id,
                    operation=operation,
                    max_inline_bytes=int(self.config.result.max_inline_bytes or 64_000),
                )
            except Exception:  # noqa: BLE001
                pass
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=output,
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

    def _agent_runtime_gate(self, op: Mapping[str, Any]) -> ModuleResult | None:
        """Return NOT_AVAILABLE when op.metadata.requires_agent_runtime and probe says disabled."""
        meta = op.get("metadata") if isinstance(op.get("metadata"), Mapping) else {}
        if not bool(meta.get("requires_agent_runtime")):
            return None
        base = str(op.get("base_url") or self._base_url or "").rstrip("/")
        if not base:
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=str(op.get("name") or "unknown"),
                status="FAILED",
                error=ExternalFailureCode.NOT_AVAILABLE.value,
                output=normalize_capability_parts(
                    summary="agent runtime unavailable (no base_url)",
                    error={"code": ExternalFailureCode.NOT_AVAILABLE.value, "reason": "no_base_url"},
                ),
            )
        probe_path = str(meta.get("preflight_path") or "/api/agent/runtime")
        if not probe_path.startswith("/"):
            probe_path = f"/{probe_path}"
        url = f"{base}{probe_path}"
        try:
            req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status_code = int(getattr(resp, "status", 200))
        except Exception as exc:  # noqa: BLE001
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=str(op.get("name") or "unknown"),
                status="FAILED",
                error=ExternalFailureCode.NOT_AVAILABLE.value,
                output=normalize_capability_parts(
                    summary="agent runtime preflight failed",
                    error={
                        "code": ExternalFailureCode.NOT_AVAILABLE.value,
                        "reason": "preflight_failed",
                        "detail": str(exc)[:400],
                    },
                ),
            )
        enabled = False
        structured: Any = None
        try:
            structured = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            structured = None
        if isinstance(structured, dict):
            enabled = bool(
                structured.get("enabled")
                or structured.get("runtimeEnabled")
                or structured.get("runtime_enabled")
            )
        if status_code == 200 and enabled:
            return None
        return ModuleResult(
            module_id=self.ctx.module_id,
            operation=str(op.get("name") or "unknown"),
            status="FAILED",
            error=ExternalFailureCode.NOT_AVAILABLE.value,
            output=normalize_capability_parts(
                summary="agent runtime not enabled",
                structured_data=structured if isinstance(structured, dict) else None,
                error={
                    "code": ExternalFailureCode.NOT_AVAILABLE.value,
                    "reason": "agent_runtime_disabled",
                    "http_status": status_code,
                },
            ),
        )
