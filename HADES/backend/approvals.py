"""Durable approval and user-input requests with atomic decisions and resume."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from database import new_id, utc_now

REQUEST_KINDS = frozenset({"tool_approval", "user_input"})
REQUEST_STATUSES = frozenset({"pending", "approved", "rejected", "expired", "cancelled"})
POLICY_OUTCOMES = frozenset({"allow", "approval_required", "block"})


def _ttl(setting_id: str, fallback: int) -> int:
    try:
        from control.service import resolve_setting

        value = resolve_setting(setting_id, default=fallback)
        return int(fallback if value is None else value)
    except Exception:
        return fallback


def arguments_fingerprint(arguments: dict[str, Any] | None, *, tool_name: str, schema_version: str, scope: dict[str, Any] | None) -> str:
    payload = {
        "tool_name": tool_name,
        "schema_version": schema_version,
        "arguments": arguments or {},
        "scope": scope or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _secret_key_name(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    exact = {
        "password",
        "token",
        "api_key",
        "apikey",
        "secret",
        "authorization",
        "auth",
        "cookie",
        "auth_header",
        "private_key",
        "secret_key",
    }
    if normalized in exact:
        return True
    if normalized.startswith("authorization_"):
        return True
    suffixes = (
        "_password",
        "_token",
        "_api_key",
        "_apikey",
        "_secret",
        "_private_key",
        "_secret_key",
        "_secret_access_key",
        "_credential",
        "_credentials",
        "_cookie",
    )
    return any(normalized.endswith(suffix) for suffix in suffixes)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _secret_key_name(key):
                out[key] = "***"
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


class ApprovalService:
    def __init__(self, db: Any, inbox: Any | None = None) -> None:
        self.db = db
        self.inbox = inbox

    def create_tool_approval(
        self,
        *,
        plugin_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        expected_effect: str,
        schema_version: str = "1",
        scope: dict[str, Any] | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        conversation_id: str | None = None,
        step_id: str | None = None,
        plan_version: int | None = None,
        project_id: str | None = None,
        expires_in_seconds: int | None = None,
        destination_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        if expires_in_seconds is None:
            expires_in_seconds = _ttl("approvals.default_ttl_seconds", 3600)
        fingerprint = arguments_fingerprint(arguments, tool_name=tool_name, schema_version=schema_version, scope=scope)
        expires_at = (datetime.now(UTC) + timedelta(seconds=max(60, expires_in_seconds))).isoformat(timespec="seconds")
        record = {
            "id": new_id("apr"),
            "kind": "tool_approval",
            "status": "pending",
            "policy_outcome": "approval_required",
            "plugin_id": plugin_id,
            "tool_name": tool_name,
            "arguments_json": arguments,
            "arguments_hash": fingerprint,
            "schema_version": schema_version,
            "scope_json": scope or {},
            "expected_effect": expected_effect,
            "destination_paths": destination_paths or [],
            "run_id": run_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "step_id": step_id,
            "plan_version": plan_version,
            "project_id": project_id,
            "resume_token": new_id("resume"),
            "checkpoint_json": {
                "phase": "waiting_for_input",
                "kind": "tool_approval",
                "tool_name": tool_name,
                "plugin_id": plugin_id,
            },
            "expires_at": expires_at,
            "decision_at": None,
            "decision_note": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        saved = self.db.insert_approval_request(record)
        if self.inbox is not None:
            self.inbox.create(
                kind="approval_required",
                title=f"Goedkeuring vereist: {tool_name}",
                body=expected_effect,
                ref_type="approval_request",
                ref_id=saved["id"],
                project_id=project_id,
                task_id=task_id,
                conversation_id=conversation_id,
            )
        return self.public_view(saved)

    def create_user_input(
        self,
        *,
        prompt: str,
        run_id: str | None = None,
        task_id: str | None = None,
        conversation_id: str | None = None,
        step_id: str | None = None,
        plan_version: int | None = None,
        project_id: str | None = None,
        expires_in_seconds: int | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if expires_in_seconds is None:
            expires_in_seconds = _ttl("approvals.extended_ttl_seconds", 7200)
        expires_at = (datetime.now(UTC) + timedelta(seconds=max(60, expires_in_seconds))).isoformat(timespec="seconds")
        record = {
            "id": new_id("apr"),
            "kind": "user_input",
            "status": "pending",
            "policy_outcome": "approval_required",
            "plugin_id": None,
            "tool_name": None,
            "arguments_json": {"fields": fields or [], "prompt": prompt},
            "arguments_hash": arguments_fingerprint({"prompt": prompt}, tool_name="user_input", schema_version="1", scope={}),
            "schema_version": "1",
            "scope_json": {},
            "expected_effect": prompt,
            "destination_paths": [],
            "run_id": run_id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "step_id": step_id,
            "plan_version": plan_version,
            "project_id": project_id,
            "resume_token": new_id("resume"),
            "checkpoint_json": {"phase": "waiting_for_input", "kind": "user_input"},
            "expires_at": expires_at,
            "decision_at": None,
            "decision_note": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        saved = self.db.insert_approval_request(record)
        if self.inbox is not None:
            self.inbox.create(
                kind="needs_input",
                title="Aanvullende informatie gevraagd",
                body=prompt,
                ref_type="approval_request",
                ref_id=saved["id"],
                project_id=project_id,
                task_id=task_id,
                conversation_id=conversation_id,
            )
        return self.public_view(saved)

    def public_view(self, item: dict[str, Any]) -> dict[str, Any]:
        view = dict(item)
        args = view.get("arguments_json") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        view["arguments_json"] = redact_secrets(args)
        view["arguments_preview"] = view["arguments_json"]
        expires = view.get("expires_at")
        timed_out = False
        if view.get("status") == "pending" and expires:
            try:
                timed_out = str(expires) < utc_now()
            except Exception:
                timed_out = False
        view["timed_out"] = timed_out
        # Never imply timeout auto-allowed; pending remains pending.
        view["auto_allowed"] = False
        return view

    def list_pending(self, *, task_id: str | None = None, conversation_id: str | None = None) -> list[dict[str, Any]]:
        # Do not auto-expire pending approvals on read — timeout remains pending.
        items = self.db.list_approval_requests(status="pending", task_id=task_id, conversation_id=conversation_id)
        return [self.public_view(item) for item in items]

    def get(self, request_id: str) -> dict[str, Any] | None:
        item = self.db.get_approval_request(request_id)
        return self.public_view(item) if item else None

    def expire_due(self) -> int:
        """Kept for compatibility; pending approvals are not auto-closed on timeout."""
        return self.db.expire_approval_requests(utc_now())

    def decide(
        self,
        request_id: str,
        *,
        approve: bool,
        note: str = "",
        response_payload: dict[str, Any] | None = None,
        current_permissions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically decide a pending request. Double-submit returns the same decision."""
        current = self.db.get_approval_request(request_id)
        if not current:
            raise KeyError(request_id)
        if current["status"] in {"approved", "rejected"}:
            return self.public_view(current)
        if current["status"] == "expired":
            raise PermissionError("Aanvraag is verlopen.")
        if current["status"] != "pending":
            raise PermissionError(f"Aanvraag is niet beslisbaar (status={current['status']}).")

        if approve and current["kind"] == "tool_approval":
            # Re-check that approved arguments still match the bound fingerprint.
            args = current.get("arguments_json") or {}
            if isinstance(args, str):
                args = json.loads(args)
            expected = arguments_fingerprint(
                args,
                tool_name=str(current.get("tool_name") or ""),
                schema_version=str(current.get("schema_version") or "1"),
                scope=current.get("scope_json") if isinstance(current.get("scope_json"), dict) else {},
            )
            if expected != current.get("arguments_hash"):
                raise PermissionError("Argumenten komen niet meer overeen met de gebonden goedkeuring.")
            if current_permissions:
                # Caller may pass live policies; block always wins.
                for key, value in current_permissions.items():
                    if str(value).lower() == "block":
                        raise PermissionError(f"Huidig beleid blokkeert uitvoering ({key}=block).")

        status = "approved" if approve else "rejected"
        updated = self.db.decide_approval_request(
            request_id,
            status=status,
            decision_note=note,
            response_payload=response_payload or {},
            decision_at=utc_now(),
        )
        if not updated:
            # Lost the race; return whatever is stored now.
            latest = self.db.get_approval_request(request_id)
            if not latest:
                raise KeyError(request_id)
            return self.public_view(latest)
        if self.inbox is not None:
            self.inbox.mark_refs_read("approval_request", request_id)
            if status == "rejected":
                self.inbox.create(
                    kind="approval_rejected",
                    title=f"Aanvraag afgewezen: {current.get('tool_name') or current.get('kind')}",
                    body=note or "Aanvraag afgewezen.",
                    ref_type="approval_request",
                    ref_id=request_id,
                    task_id=current.get("task_id"),
                    conversation_id=current.get("conversation_id"),
                    project_id=current.get("project_id"),
                )
        return self.public_view(updated)

    def assert_reusable(self, request_id: str, *, tool_name: str, arguments: dict[str, Any], schema_version: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        item = self.db.get_approval_request(request_id)
        if not item:
            raise KeyError(request_id)
        if item["status"] != "approved":
            raise PermissionError("Goedkeuring is niet actief.")
        expires = item.get("expires_at")
        if expires and expires < utc_now():
            self.db.expire_approval_requests(utc_now())
            raise PermissionError("Goedkeuring is verlopen.")
        fingerprint = arguments_fingerprint(arguments, tool_name=tool_name, schema_version=schema_version, scope=scope)
        if fingerprint != item.get("arguments_hash") or tool_name != item.get("tool_name"):
            raise PermissionError("Gewijzigde argumenten of tool vereisen een nieuwe beoordeling.")
        return item
