#!/usr/bin/env python3
"""Optional local OpenAI-compatible chat (LM Studio). Fail closed; never hardcode a model id."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")


def chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    base_url: str = "",
    api_key: str = "",
    timeout: float = 60.0,
    max_tokens: int = 1200,
    temperature: float = 0.2,
) -> dict[str, Any]:
    model_id = str(model or "").strip()
    if not model_id:
        return {"ok": False, "error": "model_required", "hint": "Pass a dynamic LM Studio / OpenAI-compatible model id."}
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = api_key or os.environ.get("OPENAI_API_KEY") or "lm-studio"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        return {"ok": False, "error": f"http_{exc.code}", "detail": detail, "url": url}
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "error": "endpoint_unavailable",
            "detail": str(exc.reason or exc),
            "url": url,
            "hint": "Start LM Studio local server or pass a reachable OpenAI-compatible base_url. Internet is optional.",
        }
    except TimeoutError:
        return {"ok": False, "error": "timeout", "url": url}
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json", "url": url}

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return {"ok": False, "error": "empty_completion", "raw": data}
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = str((message or {}).get("content") or "")
    if not content.strip():
        return {"ok": False, "error": "empty_content", "raw": data}
    return {
        "ok": True,
        "model": model_id,
        "base_url": url.rsplit("/chat/completions", 1)[0],
        "content": content,
        "usage": data.get("usage") if isinstance(data, dict) else None,
    }
