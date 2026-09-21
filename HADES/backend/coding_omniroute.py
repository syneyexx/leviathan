"""Optional OmniRoute backend for HADES Coding model calls.

This module does not replace LM Studio or intercept Chat/Trading/Media.
When ``use_omniroute`` is false, callers must not construct this wrapper.

Routing is deterministic (task metadata + discovered inventory). The coding
prompt never receives the OmniRoute catalog. Completions reuse OpenAI-compatible
``LmStudioClient`` against a selected discovered route after PluginManager
eligibility checks.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from approvals import redact_secrets
from plugin_registry_cache import registry_generation
from plugin_runtime_v2 import eligible_for_autonomous, eligible_for_manual


PLUGIN_ID = "omniroute"

STATUS_PLUGIN_MISSING = "plugin_missing"
STATUS_PLUGIN_DISABLED = "plugin_disabled"
STATUS_PLUGIN_NOT_READY = "plugin_not_ready"
STATUS_UNREACHABLE = "omniroute_unreachable"
STATUS_NO_ELIGIBLE_ROUTE = "no_eligible_route"
STATUS_AUTH = "authentication_required"
STATUS_RATE_LIMITED = "provider_rate_limited"
STATUS_PROVIDER_FAILED = "provider_failed"
STATUS_COMPLETION_FAILED = "completion_failed"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_READY = "ready"

_ROLE: ContextVar[str] = ContextVar("hades_coding_omniroute_role", default="coding_editor")

SPECIALIST_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "coding_investigator": {
        "large_context": True,
        "coding_strength": "high",
        "reasoning_strength": "medium",
        "prefer_low_latency": False,
        "independence": False,
    },
    "coding_planner": {
        "large_context": True,
        "coding_strength": "high",
        "reasoning_strength": "high",
        "prefer_low_latency": False,
        "independence": False,
    },
    "coding_editor": {
        "large_context": False,
        "coding_strength": "very_high",
        "reasoning_strength": "medium",
        "prefer_low_latency": False,
        "independence": False,
    },
    "coding_debugger": {
        "large_context": False,
        "coding_strength": "high",
        "reasoning_strength": "high",
        "prefer_low_latency": False,
        "independence": False,
    },
    "coding_test_engineer": {
        "large_context": False,
        "coding_strength": "medium",
        "reasoning_strength": "medium",
        "prefer_low_latency": True,
        "independence": False,
    },
    "coding_final_reviewer": {
        "large_context": False,
        "coding_strength": "high",
        "reasoning_strength": "high",
        "prefer_low_latency": False,
        "independence": True,
    },
    "coding_security_reviewer": {
        "large_context": False,
        "coding_strength": "high",
        "reasoning_strength": "high",
        "prefer_low_latency": False,
        "independence": True,
    },
    "coding_api_reviewer": {
        "large_context": False,
        "coding_strength": "high",
        "reasoning_strength": "high",
        "prefer_low_latency": False,
        "independence": True,
    },
}

STATUS_LABELS = {
    STATUS_PLUGIN_MISSING: "OmniRoute plugin not installed",
    STATUS_PLUGIN_DISABLED: "Enable OmniRoute in Plugins",
    STATUS_PLUGIN_NOT_READY: "OmniRoute is not Ready",
    STATUS_UNREACHABLE: "OmniRoute unreachable",
    STATUS_NO_ELIGIBLE_ROUTE: "No eligible OmniRoute model",
    STATUS_AUTH: "OmniRoute authentication required",
    STATUS_RATE_LIMITED: "OmniRoute provider rate limited",
    STATUS_PROVIDER_FAILED: "OmniRoute provider failed",
    STATUS_COMPLETION_FAILED: "OmniRoute completion failed",
    STATUS_TIMEOUT: "OmniRoute timed out",
    STATUS_CANCELLED: "Coding job cancelled",
    STATUS_READY: "OmniRoute ready",
}


def _resolve_setting(setting_id: str, default: Any) -> Any:
    try:
        from control.service import resolve_setting

        return resolve_setting(setting_id, default=default)
    except Exception:
        return default


INVENTORY_CACHE_TTL_DEFAULT_SECONDS = 30.0
INVENTORY_CACHE_TTL_FLOOR_SECONDS = 5.0
INVENTORY_CACHE_TTL_CEILING_SECONDS = 300.0
_SECRET_TEXT_RE = re.compile(r"(?i)(\bsk-[A-Za-z0-9_-]{8,}\b|\bbearer\s+\S+)")


def _inventory_ttl_seconds() -> float:
    raw = _resolve_setting("coding.omniroute.inventory_cache_ttl_seconds", INVENTORY_CACHE_TTL_DEFAULT_SECONDS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = INVENTORY_CACHE_TTL_DEFAULT_SECONDS
    return max(INVENTORY_CACHE_TTL_FLOOR_SECONDS, min(INVENTORY_CACHE_TTL_CEILING_SECONDS, value))


def _scrub_secret_text(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_TEXT_RE.sub("***", value)
    return value


def allow_omniroute_fallback() -> bool:
    return bool(_resolve_setting("coding.omniroute.allow_fallback", True))


def omniroute_enabled_by_default() -> bool:
    return bool(_resolve_setting("coding.omniroute.enabled_by_default", False))


def allow_remote_routes(settings: dict[str, Any] | None = None) -> bool:
    cfg = settings if isinstance(settings, dict) else {}
    if "allow_cloud_model_fallback" in cfg:
        return bool(cfg.get("allow_cloud_model_fallback"))
    return bool(_resolve_setting("models.allow_cloud_fallback", False))


@contextmanager
def coding_role_scope(role: str):
    token = _ROLE.set(str(role or "coding_editor"))
    try:
        yield
    finally:
        _ROLE.reset(token)


def current_coding_role() -> str:
    return str(_ROLE.get() or "coding_editor")


def _normalize_model_id(model: str | None) -> str | None:
    text = str(model or "").strip()
    if not text or text.lower() in {"local", "default", "auto"}:
        return None
    return text


def requirements_for_specialist(specialist: str | None = None) -> dict[str, Any]:
    role = str(specialist or current_coding_role() or "coding_editor")
    base = dict(SPECIALIST_REQUIREMENTS.get(role) or SPECIALIST_REQUIREMENTS["coding_editor"])
    base["specialist"] = role
    base["allow_remote"] = allow_remote_routes()
    return base


def is_local_url(base_url: str) -> bool:
    host = (urlparse(str(base_url or "")).hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def public_routing_snapshot(data: dict[str, Any] | None) -> dict[str, Any]:
    """Bounded, secret-free routing metadata for job state / UI / events."""
    raw = redact_secrets(dict(data or {}))
    allowed = {
        "omniroute_requested",
        "omniroute_available",
        "omniroute_used",
        "fallback_used",
        "fallback_reason",
        "routing_mode",
        "selected_model",
        "selected_provider",
        "local_or_remote",
        "status_code",
        "status_label",
        "reason",
        "extra_routing_llm_calls",
        "catalog_injected_into_prompt",
        "cache_hit",
        "reported_by_omniroute",
    }
    out = {key: _scrub_secret_text(raw.get(key)) for key in allowed if key in raw}
    out.setdefault("extra_routing_llm_calls", 0)
    out.setdefault("catalog_injected_into_prompt", False)
    return out


@dataclass(slots=True)
class OmniRouteAvailability:
    installed: bool = False
    enabled: bool = False
    ready: bool = False
    usable: bool = False
    status_code: str = STATUS_PLUGIN_MISSING
    status_label: str = STATUS_LABELS[STATUS_PLUGIN_MISSING]
    reason: str = STATUS_LABELS[STATUS_PLUGIN_MISSING]
    trust: str | None = None
    health: str | None = None
    failure_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _InventoryCache:
    payload: dict[str, Any] | None = None
    expires_at: float = 0.0
    generation: int = -1
    lock: threading.RLock = field(default_factory=threading.RLock)


_INVENTORY = _InventoryCache()


def clear_omniroute_inventory_cache() -> None:
    with _INVENTORY.lock:
        _INVENTORY.payload = None
        _INVENTORY.expires_at = 0.0
        _INVENTORY.generation = -1


class OmniRouteCodingProvider:
    """Discovery, health, routing and execution for optional Coding OmniRoute."""

    def __init__(
        self,
        *,
        plugin_lookup: Callable[[str], dict[str, Any] | None],
        plugin_tools: Callable[[str], list[dict[str, Any]]] | None = None,
        invoke: Callable[..., dict[str, Any]] | None = None,
        complete_fn: Callable[..., dict[str, Any]] | None = None,
        settings: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], float] | None = None,
        generation: Callable[[], int] | None = None,
        policy_settings: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._lookup = plugin_lookup
        self._tools = plugin_tools or (lambda _pid: [])
        self._invoke = invoke
        self._complete_fn = complete_fn
        self._settings = settings or (lambda: {})
        self._now = now or time.monotonic
        self._generation = generation or registry_generation
        self._policy_settings = policy_settings
        self.discovery_calls = 0
        self.completion_calls = 0
        self.fallback_calls = 0
        self.routing_llm_calls = 0

    def availability(self) -> OmniRouteAvailability:
        plugin = self._lookup(PLUGIN_ID)
        if not plugin:
            return OmniRouteAvailability()
        enabled = bool(plugin.get("enabled"))
        status = str(plugin.get("status") or "").strip().lower()
        ready = status == "ready"
        failure = plugin.get("failure_state")
        trust = plugin.get("trust")
        health = plugin.get("health")
        tools = self._tools(PLUGIN_ID) or []
        chat_tool = next(
            (
                item
                for item in tools
                if str(item.get("name")) in {"chat", "complete", "list_routes"} and item.get("enabled", True)
            ),
            None,
        )
        eligible, why = eligible_for_manual(plugin)
        if eligible and chat_tool:
            auto_ok, auto_why = eligible_for_autonomous(plugin, chat_tool)
            if not auto_ok:
                eligible, why = False, auto_why
        if not enabled:
            code = STATUS_PLUGIN_DISABLED
            reason = STATUS_LABELS[code]
        elif not ready or failure:
            code = STATUS_PLUGIN_NOT_READY
            reason = why if why and why != "ok" else f"status={status or 'unknown'}"
            if failure:
                reason = f"failure_state={failure}"
        elif not chat_tool:
            code = STATUS_PLUGIN_NOT_READY
            reason = "omniroute_tools_not_registered"
        elif not eligible:
            code = STATUS_PLUGIN_NOT_READY
            reason = why
        else:
            code = STATUS_READY
            reason = STATUS_LABELS[code]
        usable = code == STATUS_READY
        return OmniRouteAvailability(
            installed=True,
            enabled=enabled,
            ready=ready and not failure,
            usable=usable,
            status_code=code,
            status_label=STATUS_LABELS.get(code, code),
            reason=reason,
            trust=str(trust) if trust is not None else None,
            health=str(health) if health is not None else None,
            failure_state=str(failure) if failure else None,
        )

    def _parse_invoke_json(self, result: dict[str, Any]) -> dict[str, Any]:
        stdout = str(result.get("stdout") or result.get("output") or "")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            start = stdout.find("{")
            end = stdout.rfind("}")
            if start >= 0 and end > start:
                try:
                    payload = json.loads(stdout[start : end + 1])
                except json.JSONDecodeError:
                    payload = {}
            else:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if result.get("status") not in {None, "completed", "succeeded", "success", "ok"} and not payload.get("ok"):
            payload.setdefault("ok", False)
            payload.setdefault("error", result.get("error") or STATUS_UNREACHABLE)
        return redact_secrets(payload)

    def discover(self, *, force: bool = False) -> dict[str, Any]:
        gen = int(self._generation())
        ttl = _inventory_ttl_seconds()
        with _INVENTORY.lock:
            fresh = (
                not force
                and _INVENTORY.payload is not None
                and _INVENTORY.generation == gen
                and self._now() < _INVENTORY.expires_at
            )
            if fresh:
                cached = dict(_INVENTORY.payload or {})
                cached["_cache_hit"] = True
                return cached
        self.discovery_calls += 1
        if self._invoke is None:
            payload = {"ok": False, "error": STATUS_UNREACHABLE, "detail": "invoke_unavailable"}
        else:
            try:
                raw = self._invoke(
                    PLUGIN_ID,
                    "list_routes",
                    {},
                    invocation_type="autonomous",
                    approved_by_user=False,
                )
                payload = self._parse_invoke_json(raw if isinstance(raw, dict) else {})
            except Exception as exc:  # noqa: BLE001 — discovery must fail honestly, not crash coding
                payload = {"ok": False, "error": STATUS_UNREACHABLE, "detail": str(exc)[:400]}
        payload["_cache_hit"] = False
        healthy = bool(payload.get("ok"))
        with _INVENTORY.lock:
            _INVENTORY.payload = dict(payload)
            _INVENTORY.generation = gen
            # Failures are not retained as healthy — zero TTL, next call re-probes.
            _INVENTORY.expires_at = self._now() + (ttl if healthy else 0.0)
        return payload

    def select_route(
        self,
        *,
        requirements: dict[str, Any] | None = None,
        explicit_model: str | None = None,
        inventory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = dict(requirements or requirements_for_specialist())
        allow_remote = bool(req.get("allow_remote")) if "allow_remote" in req else allow_remote_routes(self._settings())
        req["allow_remote"] = allow_remote
        routes = inventory if isinstance(inventory, dict) else self.discover()
        if not routes.get("ok") and not (routes.get("local") or routes.get("extra")):
            return {"ok": False, "error": routes.get("error") or STATUS_UNREACHABLE}

        def _rows() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for block in [routes.get("local"), *(routes.get("extra") or [])]:
                if not isinstance(block, dict) or not block.get("ok"):
                    continue
                base_url = str(block.get("base_url") or "")
                local = bool(block.get("local")) if "local" in block else is_local_url(base_url)
                if not local and not allow_remote:
                    continue
                for item in block.get("models") or []:
                    if isinstance(item, str):
                        model_id = item
                        meta: dict[str, Any] = {}
                    elif isinstance(item, dict):
                        model_id = str(item.get("id") or "")
                        meta = {k: v for k, v in item.items() if k != "id"}
                    else:
                        continue
                    if not model_id:
                        continue
                    out.append(
                        {
                            "ok": True,
                            "model_id": model_id,
                            "base_url": base_url,
                            "local": local,
                            "provider": str(meta.get("owned_by") or ("local" if local else "extra")),
                            "routing_mode": "auto",
                            "metadata": meta,
                            "reported_by_omniroute": True,
                        }
                    )
            return out

        candidates = _rows()
        explicit = _normalize_model_id(explicit_model)
        if explicit:
            match = next((row for row in candidates if row["model_id"] == explicit), None)
            if match:
                match["routing_mode"] = "selected"
                return match
            return {"ok": False, "error": STATUS_NO_ELIGIBLE_ROUTE, "detail": "explicit_model_not_in_inventory"}
        if not candidates:
            return {"ok": False, "error": STATUS_NO_ELIGIBLE_ROUTE}
        local_first = [row for row in candidates if row.get("local")] or candidates
        if req.get("large_context"):
            scored: list[tuple[int, dict[str, Any]]] = []
            for row in local_first:
                meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                ctx = None
                for key in ("context_length", "max_model_len", "max_context_length", "context_window"):
                    if meta.get(key) is not None:
                        try:
                            ctx = int(meta[key])
                        except (TypeError, ValueError):
                            ctx = None
                        break
                if ctx is not None:
                    scored.append((ctx, row))
            if scored:
                scored.sort(key=lambda item: item[0], reverse=True)
                return scored[0][1]
        return local_first[0]

    def _api_key_for_url(self, base_url: str) -> str:
        settings = self._settings() or {}
        if is_local_url(base_url):
            return str(settings.get("lm_studio_api_key") or os.environ.get("HADES_LM_STUDIO_API_KEY") or os.environ.get("OPENAI_API_KEY") or "lm-studio")
        return str(os.environ.get("OPENAI_API_KEY") or settings.get("lm_studio_api_key") or "lm-studio")

    async def _default_complete(self, openai_payload: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        """OpenAI-compatible POST /chat/completions against a discovered route.

        Async httpx so Coding Task cancellation can unwind an in-flight request.
        Streaming is not used on this path — coding awaits a full completion object.
        """
        import httpx

        base_url = str(selection.get("base_url") or "").rstrip("/")
        model_id = str(selection.get("model_id") or openai_payload.get("model") or "").strip()
        if not base_url or not model_id:
            return {"ok": False, "error": STATUS_NO_ELIGIBLE_ROUTE}
        timeout = float((self._settings() or {}).get("request_timeout_seconds") or 120)
        url = base_url + "/chat/completions"
        body = {
            "model": model_id,
            "messages": openai_payload.get("messages") or [],
            "temperature": openai_payload.get("temperature", 0),
            "max_tokens": openai_payload.get("max_tokens", 2500),
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key_for_url(base_url)}",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
                raw = response.text or ""
                code = int(response.status_code)
                if code in {401, 403}:
                    return {
                        "ok": False,
                        "error": STATUS_AUTH,
                        "http_status": code,
                        "detail": _scrub_secret_text(raw[:400]),
                    }
                if code == 429:
                    return {
                        "ok": False,
                        "error": STATUS_RATE_LIMITED,
                        "http_status": code,
                        "detail": _scrub_secret_text(raw[:400]),
                    }
                if code >= 500:
                    return {
                        "ok": False,
                        "error": STATUS_PROVIDER_FAILED,
                        "http_status": code,
                        "detail": _scrub_secret_text(raw[:400]),
                    }
                if code >= 400:
                    return {
                        "ok": False,
                        "error": STATUS_COMPLETION_FAILED,
                        "http_status": code,
                        "detail": _scrub_secret_text(raw[:400]),
                    }
                try:
                    data = response.json() if raw.strip() else {}
                except ValueError:
                    return {"ok": False, "error": STATUS_COMPLETION_FAILED, "detail": "invalid_json"}
        except httpx.TimeoutException:
            return {"ok": False, "error": STATUS_TIMEOUT}
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as exc:
            return {"ok": False, "error": STATUS_UNREACHABLE, "detail": _scrub_secret_text(str(exc)[:400])}
        if not isinstance(data, dict) or not data.get("choices"):
            return {"ok": False, "error": STATUS_COMPLETION_FAILED, "detail": "empty_completion"}
        reported = str(data.get("model") or model_id)
        return {"ok": True, "response": data, "model": reported if reported else model_id}

    async def complete(
        self,
        openai_payload: dict[str, Any],
        *,
        requirements: dict[str, Any] | None = None,
        explicit_model: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if callable(cancel_check) and cancel_check():
            return {"ok": False, "error": STATUS_CANCELLED}
        availability = self.availability()
        if not availability.usable:
            return {
                "ok": False,
                "error": availability.status_code,
                "detail": availability.reason,
                "availability": availability.to_dict(),
            }
        inventory = self.discover()
        selection = self.select_route(
            requirements=requirements,
            explicit_model=_normalize_model_id(explicit_model) or _normalize_model_id(str(openai_payload.get("model") or "")),
            inventory=inventory,
        )
        if not selection.get("ok"):
            return {
                "ok": False,
                "error": selection.get("error") or STATUS_NO_ELIGIBLE_ROUTE,
                "detail": selection.get("detail"),
                "cache_hit": bool(inventory.get("_cache_hit")),
            }
        if callable(cancel_check) and cancel_check():
            return {"ok": False, "error": STATUS_CANCELLED}
        self.completion_calls += 1
        runner = self._complete_fn or self._default_complete
        result = runner(openai_payload, selection)
        if inspect.isawaitable(result):
            result = await result
        if not result.get("ok"):
            clear_omniroute_inventory_cache()
        snapshot = public_routing_snapshot(
            {
                "omniroute_requested": True,
                "omniroute_available": True,
                "omniroute_used": bool(result.get("ok")),
                "fallback_used": False,
                "routing_mode": selection.get("routing_mode"),
                "selected_model": result.get("model") or selection.get("model_id"),
                "selected_provider": selection.get("provider"),
                "local_or_remote": "local" if selection.get("local") else "remote",
                "status_code": None if result.get("ok") else result.get("error"),
                "reason": None if result.get("ok") else result.get("detail") or result.get("error"),
                "cache_hit": bool(inventory.get("_cache_hit")),
                "reported_by_omniroute": bool(selection.get("reported_by_omniroute", True)),
                "extra_routing_llm_calls": 0,
                "catalog_injected_into_prompt": False,
            }
        )
        return {**result, "selection": {k: selection.get(k) for k in ("model_id", "base_url", "local", "provider", "routing_mode")}, "snapshot": snapshot}

    def prompt_catalog_delta(self, openai_payload: dict[str, Any]) -> dict[str, Any]:
        """Prove routing does not inject inventory into the model prompt."""
        messages = openai_payload.get("messages") if isinstance(openai_payload, dict) else None
        serialized = json.dumps(messages if isinstance(messages, list) else openai_payload, ensure_ascii=False)
        return {
            "prompt_chars": len(serialized),
            "catalog_injected_into_prompt": False,
            "extra_routing_llm_calls": self.routing_llm_calls,
            "token_count_mode": "serialized_prompt_chars",
        }


def provider_from_plugin_manager(plugin_manager: Any, *, settings: Callable[[], dict[str, Any]] | None = None) -> OmniRouteCodingProvider:
    db = getattr(plugin_manager, "db", None)

    def lookup(plugin_id: str) -> dict[str, Any] | None:
        if db is None:
            return None
        return db.get_plugin(plugin_id)

    def tools(plugin_id: str) -> list[dict[str, Any]]:
        if db is None:
            return []
        return list(db.plugin_tools(plugin_id) or [])

    def invoke(plugin_id: str, tool_name: str, input_data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return plugin_manager.invoke(plugin_id, tool_name, input_data, **kwargs)

    return OmniRouteCodingProvider(
        plugin_lookup=lookup,
        plugin_tools=tools,
        invoke=invoke,
        settings=settings,
    )


class OmniRouteCodingChat:
    """chat_fn wrapper used only when a coding run requested OmniRoute."""

    def __init__(
        self,
        fallback_chat_fn: Any,
        provider: OmniRouteCodingProvider,
        *,
        allow_fallback: bool = True,
        explicit_model: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_snapshot: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._fallback = fallback_chat_fn
        self.provider = provider
        self.allow_fallback = allow_fallback
        self.explicit_model = explicit_model
        self.cancel_check = cancel_check
        self.on_snapshot = on_snapshot
        self.last_snapshot: dict[str, Any] = public_routing_snapshot(
            {
                "omniroute_requested": True,
                "omniroute_available": False,
                "omniroute_used": False,
                "fallback_used": False,
                "extra_routing_llm_calls": 0,
                "catalog_injected_into_prompt": False,
            }
        )
        self.fallback_calls = 0

    def _emit(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        safe = public_routing_snapshot(snapshot)
        self.last_snapshot = safe
        if callable(self.on_snapshot):
            self.on_snapshot(safe)
        return safe

    def _fallback_result(self, openai_payload: dict[str, Any], *, reason: str) -> Any:
        if not self.allow_fallback or not callable(self._fallback):
            self._emit(
                {
                    "omniroute_requested": True,
                    "omniroute_available": reason not in {STATUS_PLUGIN_MISSING, STATUS_PLUGIN_DISABLED, STATUS_PLUGIN_NOT_READY},
                    "omniroute_used": False,
                    "fallback_used": False,
                    "fallback_reason": reason,
                    "status_code": reason,
                    "status_label": STATUS_LABELS.get(reason, reason),
                    "reason": STATUS_LABELS.get(reason, reason),
                }
            )
            raise RuntimeError(reason)
        self.fallback_calls += 1
        self.provider.fallback_calls += 1
        self._emit(
            {
                "omniroute_requested": True,
                "omniroute_available": reason not in {STATUS_PLUGIN_MISSING},
                "omniroute_used": False,
                "fallback_used": True,
                "fallback_reason": reason,
                "status_code": reason,
                "status_label": STATUS_LABELS.get(reason, reason),
                "reason": STATUS_LABELS.get(reason, reason),
            }
        )
        return self._fallback(openai_payload)

    async def chat(self, payload: dict[str, Any]) -> Any:
        if callable(self.cancel_check) and self.cancel_check():
            self._emit({"omniroute_requested": True, "omniroute_used": False, "status_code": STATUS_CANCELLED, "fallback_used": False})
            raise RuntimeError(STATUS_CANCELLED)
        openai_payload = dict(payload or {})
        openai_payload.pop("_hades_coding_role", None)
        result = await self.provider.complete(
            openai_payload,
            requirements=requirements_for_specialist(),
            explicit_model=_normalize_model_id(self.explicit_model) or _normalize_model_id(str(openai_payload.get("model") or "")),
            cancel_check=self.cancel_check,
        )
        if result.get("ok"):
            snap = dict(result.get("snapshot") or {})
            snap["omniroute_used"] = True
            snap["fallback_used"] = False
            self._emit(snap)
            return result.get("response")
        reason = str(result.get("error") or STATUS_COMPLETION_FAILED)
        # Cancellation: never fall back to a fresh untracked LM call.
        if reason == STATUS_CANCELLED or (callable(self.cancel_check) and self.cancel_check()):
            self._emit({"omniroute_requested": True, "omniroute_used": False, "status_code": STATUS_CANCELLED, "fallback_used": False})
            raise RuntimeError(STATUS_CANCELLED)
        fallback = self._fallback_result(openai_payload, reason=reason)
        if hasattr(fallback, "__await__"):
            return await fallback
        return fallback

    def _sync_chat(self, payload: dict[str, Any]) -> Any:
        """Legacy sync surface — routes through Coding model runtime (no nested asyncio.run)."""
        from coding_model_runtime import invoke_coding_model

        async def _coro() -> Any:
            return await self.chat(payload)

        outcome = invoke_coding_model(_coro, phase="omniroute_sync")
        if outcome.kind == "cancelled":
            raise RuntimeError(STATUS_CANCELLED)
        if outcome.kind == "timeout":
            raise TimeoutError("omniroute_sync_timeout")
        if outcome.kind == "error":
            raise RuntimeError(outcome.error or "omniroute_sync_error")
        return outcome.response

    def __call__(self, first: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(first, list):
            payload = {
                "messages": first,
                "model": kwargs.get("model") or self.explicit_model,
                "temperature": kwargs.get("temperature", 0),
                "max_tokens": kwargs.get("max_tokens", 2500),
            }
            return self._sync_chat(payload)
        return self.chat(first)


def wrap_coding_chat_fn(
    fallback_chat_fn: Any,
    *,
    use_omniroute: bool,
    plugin_manager: Any | None,
    settings: Callable[[], dict[str, Any]] | None = None,
    explicit_model: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_snapshot: Callable[[dict[str, Any]], None] | None = None,
    allow_fallback: bool | None = None,
    provider: OmniRouteCodingProvider | None = None,
) -> Any:
    """Return fallback unchanged when OmniRoute is off."""
    if not use_omniroute:
        return fallback_chat_fn
    resolved = provider
    if resolved is None:
        if plugin_manager is None:
            resolved = OmniRouteCodingProvider(plugin_lookup=lambda _pid: None, settings=settings)
        else:
            resolved = provider_from_plugin_manager(plugin_manager, settings=settings)
    fallback_ok = allow_omniroute_fallback() if allow_fallback is None else bool(allow_fallback)
    return OmniRouteCodingChat(
        fallback_chat_fn,
        resolved,
        allow_fallback=fallback_ok,
        explicit_model=explicit_model,
        cancel_check=cancel_check,
        on_snapshot=on_snapshot,
    )


def availability_from_plugin_manager(plugin_manager: Any | None) -> dict[str, Any]:
    if plugin_manager is None:
        return OmniRouteAvailability().to_dict()
    return provider_from_plugin_manager(plugin_manager).availability().to_dict()
