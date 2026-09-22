"""OmniRoute Editor Gateway — validate → resolve → execute → normalize."""

from __future__ import annotations

import base64
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .actions import validate_actions
from .protocol import (
    make_error_result,
    make_result,
    validate_context,
)
from .providers.base import ProviderRequest
from .providers.registry import ProviderRegistry
from .tasks import get_task, list_tasks, resolve_task_id
from .temp_assets import TempAssetStore

# Magic-byte validation reused from server when available
try:
    from validate_image_helper import validate_image_bytes  # type: ignore
except Exception:
    validate_image_bytes = None  # set by server wiring

_gateway: "OmniRouteEditorGateway | None" = None
_gateway_lock = threading.Lock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


class OmniRouteEditorGateway:
    def __init__(self, temp_root: Path, *, validate_image=None) -> None:
        self.registry = ProviderRegistry()
        self.temp = TempAssetStore(temp_root)
        self.validate_image = validate_image
        self._lock = threading.RLock()
        self._active: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self.default_timeout = float(os.environ.get("LEVIATHAN_EDITOR_AI_TIMEOUT_SECONDS") or "90")

    def capabilities(self) -> dict[str, Any]:
        self.registry.reload()
        report = self.registry.capability_report()
        report["tasks"] = list_tasks()
        if _truthy("LEVIATHAN_EDITOR_AI_DISABLED"):
            report["available"] = False
            report["aiEnabled"] = False
            report["disabledReason"] = "LEVIATHAN_EDITOR_AI_DISABLED"
        return report

    def cancel(self, request_id: str) -> dict[str, Any]:
        with self._lock:
            ev = self._cancel_events.get(request_id)
            rec = self._active.get(request_id)
            if ev:
                ev.set()
            if rec:
                rec["status"] = "cancel_requested"
            # Honest: provider may not support true cancellation
            return {
                "ok": True,
                "requestId": request_id,
                "cancelled": bool(ev),
                "providerCancelSupported": False,
                "notes": "Client abandons request; in-flight provider work may still complete and will be ignored if cancelled",
            }

    def cleanup_preview(self, *, request_id: str | None = None, asset_id: str | None = None) -> dict[str, Any]:
        removed = 0
        if asset_id:
            removed += 1 if self.temp.delete(asset_id) else 0
        if request_id:
            removed += self.temp.cleanup_request(request_id)
        removed += self.temp.cleanup_expired()
        return {"ok": True, "removed": removed}

    def handle(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Process generate request. Returns (http_status, body). Never mutates content files."""
        started = time.time()
        if _truthy("LEVIATHAN_EDITOR_AI_DISABLED"):
            rid = str(payload.get("requestId") or uuid.uuid4().hex)
            return 503, make_error_result(
                rid,
                code="ai_disabled",
                message="Studio AI is disabled by configuration",
            )

        self.registry.reload()
        self.temp.cleanup_expired()

        # Accept either full context envelope or legacy shallow body
        context_raw = payload.get("context") if isinstance(payload.get("context"), dict) else payload
        # Lift top-level instruction/task into request if needed
        if "request" not in context_raw:
            context_raw = {
                **context_raw,
                "request": {
                    "id": payload.get("requestId") or payload.get("id"),
                    "task": payload.get("task") or "generate_image",
                    "instruction": payload.get("instruction") or "",
                    "createdAt": payload.get("createdAt"),
                },
            }
        elif payload.get("instruction") and not (context_raw.get("request") or {}).get("instruction"):
            req = dict(context_raw.get("request") or {})
            req["instruction"] = payload["instruction"]
            context_raw = {**context_raw, "request": req}

        context, err = validate_context(context_raw)
        if err or context is None:
            rid = str(payload.get("requestId") or uuid.uuid4().hex)
            return 400, make_error_result(rid, code="invalid_context", message=err or "invalid context")

        task_id = resolve_task_id(context["request"]["task"])
        if not task_id:
            rid = context["request"]["id"] or uuid.uuid4().hex
            return 400, make_error_result(rid, code="invalid_task", message=f"Unknown task: {context['request']['task']}")

        task = get_task(task_id)
        assert task is not None
        context["request"]["task"] = task_id

        request_id = context["request"]["id"] or uuid.uuid4().hex
        context["request"]["id"] = request_id

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[request_id] = cancel_event
            self._active[request_id] = {"status": "running", "task": task_id, "started": started}

        try:
            provider_req = ProviderRequest(
                request_id=request_id,
                task=task_id,
                capability=task.capability,
                instruction=context["request"]["instruction"],
                context=context,
                width=context["output"].get("width"),
                height=context["output"].get("height"),
                variants=int(context["output"].get("variants") or 1),
                timeout_seconds=self.default_timeout,
                cancel_event=cancel_event,
            )
            result, routing = self.registry.execute(provider_req)

            if cancel_event.is_set():
                return 499, make_error_result(
                    request_id,
                    code="cancelled",
                    message="Request cancelled",
                    diagnostics={"durationMs": int((time.time() - started) * 1000), "routing": routing},
                )

            if not result.ok:
                code = result.error_code or "provider_failed"
                http = 501 if code in {"no-provider", "unsupported_capability"} else 502
                if code == "provider_timeout":
                    http = 504
                if code == "provider_auth":
                    http = 502
                return http, make_error_result(
                    request_id,
                    code=code,
                    message=result.error_message or "Provider failed",
                    provider={
                        "id": routing.get("providerId"),
                        "model": result.model,
                        "isMock": routing.get("isMock"),
                    },
                    diagnostics={
                        "durationMs": int((time.time() - started) * 1000),
                        "routing": routing,
                        "capability": task.capability,
                    },
                )

            # Persist asset variants to temp store; strip huge base64 from response where possible
            normalized = result.to_payload()
            if normalized.get("kind") in {"asset_preview", "asset_variants"}:
                stored_variants = []
                for variant in result.variants:
                    stored = self._store_variant(request_id, variant, task_id=task_id)
                    if stored is None:
                        return 502, make_error_result(
                            request_id,
                            code="invalid_image",
                            message="Generated result failed validation",
                            diagnostics={"routing": routing},
                        )
                    stored_variants.append(stored)
                normalized["variants"] = stored_variants
                if stored_variants:
                    normalized["variant"] = stored_variants[0]

            if normalized.get("kind") == "action_preview":
                actions, action_err = validate_actions(result.actions)
                if action_err:
                    return 502, make_error_result(
                        request_id,
                        code="invalid_actions",
                        message=action_err,
                        diagnostics={"routing": routing},
                    )
                normalized["actions"] = actions

            provider_meta = {
                "id": routing.get("providerId"),
                "model": result.model,
                "isMock": bool(routing.get("isMock") or result.diagnostics.get("mock")),
                "label": "Studio Dev Mock" if routing.get("isMock") else None,
            }

            body = make_result(
                request_id=request_id,
                status="success",
                result=normalized,
                provider=provider_meta,
                diagnostics={
                    "durationMs": int((time.time() - started) * 1000),
                    "routing": routing,
                    "capability": task.capability,
                    "task": task_id,
                    "degradedContext": result.degraded_context,
                    "degradeReason": result.degrade_reason,
                    "previewOnly": True,
                    "documentMutated": False,
                    "requestedSize": result.requested_size,
                    "generatedSize": result.generated_size,
                    "targetFingerprint": context.get("targetFingerprint") or {},
                },
            )
            return 200, body
        finally:
            with self._lock:
                self._active.pop(request_id, None)
                self._cancel_events.pop(request_id, None)

    def _store_variant(self, request_id: str, variant: dict[str, Any], *, task_id: str) -> dict[str, Any] | None:
        b64 = variant.get("bytesBase64")
        if not isinstance(b64, str) or not b64:
            return None
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            return None
        mime = str(variant.get("mime") or "image/png")
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }.get(mime, ".png")
        if self.validate_image:
            try:
                raw = self.validate_image(ext, raw)
            except ValueError:
                return None
        else:
            if ext == ".png" and not raw.startswith(b"\x89PNG"):
                return None
            if ext in {".jpg", ".jpeg"} and not raw.startswith(b"\xff\xd8"):
                return None
            if ext == ".webp" and not (raw[0:4] == b"RIFF" and raw[8:12] == b"WEBP"):
                return None

        stored = self.temp.put(
            raw,
            ext=ext,
            mime=mime,
            meta={
                "requestId": request_id,
                "task": task_id,
                "variantId": variant.get("id"),
                "isMock": bool(variant.get("isMock")),
                "width": variant.get("width"),
                "height": variant.get("height"),
            },
        )
        return {
            "id": variant.get("id") or stored["id"],
            "tempId": stored["id"],
            "url": stored["url"],
            "ref": stored["ref"],
            "mime": mime,
            "width": variant.get("width"),
            "height": variant.get("height"),
            "label": variant.get("label"),
            "isMock": bool(variant.get("isMock")),
            "bytes": stored["bytes"],
        }

    def get_preview_bytes(self, asset_id: str) -> tuple[bytes, dict[str, Any]] | None:
        return self.temp.get(asset_id)

    def accept_to_upload_bytes(self, asset_id: str) -> tuple[bytes, str, str] | None:
        """Return (bytes, ext, mime) for promoting a temp preview into permanent upload."""
        got = self.temp.get(asset_id)
        if not got:
            return None
        raw, record = got
        return raw, record.get("ext") or ".png", record.get("mime") or "image/png"


def get_gateway(temp_root: Path | None = None, *, validate_image=None) -> OmniRouteEditorGateway:
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            root = temp_root or Path(__file__).resolve().parent.parent / ".studio-ai-temp"
            _gateway = OmniRouteEditorGateway(root, validate_image=validate_image)
        elif validate_image and _gateway.validate_image is None:
            _gateway.validate_image = validate_image
        return _gateway


def reset_gateway_for_tests() -> None:
    global _gateway
    with _gateway_lock:
        _gateway = None
