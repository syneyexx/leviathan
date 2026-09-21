#!/usr/bin/env python3
"""Local-first LLM route table for HADES. Extra providers are optional and fail cleanly.

Discovers OpenAI-compatible ``/models`` inventories at runtime. Does not hardcode
provider counts or model catalogs. Completions never log API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import lm_client
except ImportError:
    lm_client = None  # type: ignore

LOCAL = os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")

SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "token",
        "secret",
        "password",
        "credential",
        "access_key",
    }
)
_SECRET_TEXT_RE = re.compile(r"(?i)(\bsk-[A-Za-z0-9_-]{8,}\b|\bbearer\s+\S+)")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).strip().lower().replace("-", "_")
            if lowered in SECRET_KEYS or lowered.endswith("_api_key") or lowered.endswith("_token"):
                out[key] = "***"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if _looks_like_secret(value):
            return "***"
        return _SECRET_TEXT_RE.sub("***", value)
    return value


def _looks_like_secret(text: str) -> bool:
    raw = text.strip()
    if len(raw) < 12:
        return False
    prefixes = ("sk-", "sk_live", "sk_test", "Bearer ", "bearer ")
    return raw.startswith(prefixes) or raw.lower().startswith("bearer ")


def _extra_urls() -> list[str]:
    raw = os.environ.get("HADES_EXTRA_LLM_BASE_URLS") or ""
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def _is_local_url(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _probe(base_url: str, timeout: float = 3.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/models"
    try:
        import urllib.request

        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        rows = data.get("data") if isinstance(data, dict) else None
        models: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for item in rows:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                meta: dict[str, Any] = {"id": str(item.get("id"))}
                for key in ("max_model_len", "context_length", "max_context_length", "context_window", "owned_by"):
                    if item.get(key) is not None:
                        meta[key] = item[key]
                caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else None
                if caps:
                    meta["capabilities"] = {
                        k: caps[k]
                        for k in ("tools", "structured_output", "json", "streaming")
                        if k in caps
                    }
                models.append(meta)
        return {
            "ok": True,
            "base_url": base_url,
            "local": _is_local_url(base_url),
            "models": models,
            "count": len(models),
        }
    except Exception as exc:  # noqa: BLE001 — probe must never raise into PluginManager as a crash
        return {
            "ok": False,
            "base_url": base_url,
            "local": _is_local_url(base_url),
            "error": "unreachable",
            "detail": str(exc),
        }


def list_routes() -> dict[str, Any]:
    local = _probe(LOCAL)
    extras = [_probe(url) for url in _extra_urls()]
    return {
        "ok": True,
        "local": local,
        "extra": extras,
        "note": "Default route is local LM Studio. Extra URLs come from HADES_EXTRA_LLM_BASE_URLS only.",
        "inventory_source": "runtime_discovery",
    }


def _flatten_candidates(routes: dict[str, Any], *, allow_remote: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in [routes.get("local"), *(routes.get("extra") or [])]:
        if not isinstance(row, dict) or not row.get("ok"):
            continue
        local = bool(row.get("local"))
        if not local and not allow_remote:
            continue
        base_url = str(row.get("base_url") or "")
        for item in row.get("models") or []:
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
                    "model_id": model_id,
                    "base_url": base_url,
                    "local": local,
                    "provider": str(meta.get("owned_by") or ("local" if local else "extra")),
                    "metadata": meta,
                }
            )
    return out


def select_route(
    routes: dict[str, Any] | None = None,
    *,
    requirements: dict[str, Any] | None = None,
    explicit_model: str = "",
) -> dict[str, Any]:
    """Deterministic route pick from discovered inventory. No LLM call."""
    req = requirements if isinstance(requirements, dict) else {}
    allow_remote = bool(req.get("allow_remote"))
    discovered = routes or list_routes()
    candidates = _flatten_candidates(discovered, allow_remote=allow_remote)
    if explicit_model:
        match = next((row for row in candidates if row["model_id"] == explicit_model), None)
        if match:
            return {"ok": True, "routing_mode": "selected", **match}
        return {
            "ok": False,
            "error": "no_eligible_route",
            "detail": "explicit_model_not_in_inventory",
            "model": explicit_model,
        }
    if not candidates:
        return {"ok": False, "error": "no_eligible_route"}
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
            return {"ok": True, "routing_mode": "auto", **scored[0][1]}
    return {"ok": True, "routing_mode": "auto", **local_first[0]}


def complete(prompt: str, model: str, base_url: str, api_key: str) -> dict[str, Any]:
    if lm_client is None:
        return {"ok": False, "error": "lm_client_missing"}
    result = lm_client.chat(
        [{"role": "user", "content": prompt}],
        model=model,
        base_url=base_url or LOCAL,
        api_key=api_key,
        timeout=90.0,
        max_tokens=1200,
    )
    return redact(result if not result.get("ok") else {
        "ok": True,
        "model": model,
        "base_url": result.get("base_url"),
        "content": result.get("content"),
        "usage": result.get("usage"),
    })


def chat(
    *,
    messages: list[dict[str, Any]] | None = None,
    model: str = "",
    base_url: str = "",
    payload_file: str = "",
    requirements: dict[str, Any] | None = None,
    max_tokens: int = 2500,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if payload_file:
        path = Path(payload_file)
        if not path.is_file():
            return {"ok": False, "error": "payload_file_not_found"}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": "payload_file_invalid", "detail": str(exc)}
        if not isinstance(loaded, dict):
            return {"ok": False, "error": "payload_file_invalid"}
        payload = loaded
    if messages is None:
        raw = payload.get("messages")
        messages = raw if isinstance(raw, list) else None
    if not messages:
        return {"ok": False, "error": "messages_required"}
    model_id = str(model or payload.get("model") or "").strip()
    target_url = str(base_url or payload.get("base_url") or "").strip()
    req = requirements if isinstance(requirements, dict) else payload.get("requirements")
    if not isinstance(req, dict):
        req = {}
    max_tokens = int(payload.get("max_tokens") or max_tokens)
    temperature = float(payload.get("temperature") if payload.get("temperature") is not None else temperature)
    timeout = float(payload.get("timeout") or timeout)
    selection = select_route(requirements=req, explicit_model=model_id) if (not target_url or not model_id) else {
        "ok": True,
        "routing_mode": "selected",
        "model_id": model_id,
        "base_url": target_url or LOCAL,
        "local": _is_local_url(target_url or LOCAL),
        "provider": "explicit",
    }
    if not selection.get("ok"):
        return redact(selection)
    if lm_client is None:
        return {"ok": False, "error": "lm_client_missing"}
    # Keys come from the environment / existing provider config — never from job state.
    result = lm_client.chat(
        messages,
        model=str(selection.get("model_id") or model_id),
        base_url=str(selection.get("base_url") or target_url or LOCAL),
        api_key="",
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if not result.get("ok"):
        return redact({**result, "routing": {k: selection.get(k) for k in ("routing_mode", "model_id", "base_url", "local", "provider")}})
    return redact(
        {
            "ok": True,
            "model": result.get("model"),
            "base_url": result.get("base_url"),
            "content": result.get("content"),
            "usage": result.get("usage"),
            "routing_mode": selection.get("routing_mode"),
            "provider": selection.get("provider"),
            "local": selection.get("local"),
            "openai_compatible": True,
            "streaming": False,
        }
    )


def doctor() -> dict[str, Any]:
    routes = list_routes()
    local_ok = bool(routes["local"].get("ok"))
    extra_ok = sum(1 for row in routes.get("extra") or [] if row.get("ok"))
    return {
        "ok": True,
        "python": sys.executable,
        "local_reachable": local_ok,
        "extra_configured": _extra_urls(),
        "extra_reachable": extra_ok,
        "notes": [
            "Offline-first: local LM Studio is the default.",
            "Internet providers are never required.",
            "Inventory is discovered at runtime; it is not a hardcoded catalog.",
        ],
        "local": routes["local"],
        "extra_count": len(routes.get("extra") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES OmniRoute-lite")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("list_routes")
    c = sub.add_parser("complete")
    c.add_argument("--prompt", required=True)
    c.add_argument("--model", required=True)
    c.add_argument("--base-url", default="")
    c.add_argument("--api-key", default="")
    chat_p = sub.add_parser("chat")
    chat_p.add_argument("--payload-file", default="")
    chat_p.add_argument("--model", default="")
    chat_p.add_argument("--base-url", default="")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "list_routes":
        payload = list_routes()
    elif args.cmd == "chat":
        payload = chat(payload_file=args.payload_file, model=args.model, base_url=args.base_url)
    else:
        payload = complete(args.prompt, args.model, args.base_url, args.api_key)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd in {"complete", "chat"}:
        return 0 if payload.get("ok") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
