#!/usr/bin/env python3
"""Local-first LLM route table for HADES. Extra providers are optional and fail cleanly."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import lm_client
except ImportError:
    lm_client = None  # type: ignore

LOCAL = os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")


def _extra_urls() -> list[str]:
    raw = os.environ.get("HADES_EXTRA_LLM_BASE_URLS") or ""
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def _probe(base_url: str, timeout: float = 3.0) -> dict:
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        models = [str(item.get("id")) for item in data.get("data") or [] if isinstance(item, dict) and item.get("id")]
        return {"ok": True, "base_url": base_url, "models": models[:50], "count": len(models)}
    except Exception as exc:  # noqa: BLE001 — probe must never raise into PluginManager as a crash
        return {"ok": False, "base_url": base_url, "error": "unreachable", "detail": str(exc)}


def list_routes() -> dict:
    rows = [_probe(LOCAL)]
    extras = []
    for url in _extra_urls():
        extras.append(_probe(url))
    return {
        "ok": True,
        "local": rows[0],
        "extra": extras,
        "note": "Default route is local LM Studio. Extra URLs come from HADES_EXTRA_LLM_BASE_URLS only — this is not a 352-provider cloud gateway.",
    }


def complete(prompt: str, model: str, base_url: str, api_key: str) -> dict:
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
    if not result.get("ok"):
        return result
    return {"ok": True, "model": model, "base_url": result.get("base_url"), "content": result.get("content")}


def doctor() -> dict:
    routes = list_routes()
    local_ok = bool(routes["local"].get("ok"))
    return {
        "ok": True,
        "python": sys.executable,
        "local_reachable": local_ok,
        "extra_configured": _extra_urls(),
        "notes": [
            "Offline-first: local LM Studio is the default.",
            "Internet providers are never required.",
        ],
        "local": routes["local"],
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
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "list_routes":
        payload = list_routes()
    else:
        payload = complete(args.prompt, args.model, args.base_url, args.api_key)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd == "complete":
        return 0 if payload.get("ok") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
