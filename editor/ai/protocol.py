"""Versioned Editor Context Protocol and Editor Result Protocol."""

from __future__ import annotations

from typing import Any

CONTEXT_PROTOCOL = "leviathan.editor-context"
RESULT_PROTOCOL = "leviathan.editor-result"
CONTEXT_VERSION = 1
RESULT_VERSION = 1

MAX_INSTRUCTION_CHARS = 8_000
MAX_CONTEXT_JSON_CHARS = 400_000
MAX_SNAPSHOT_DATA_URL_CHARS = 1_200_000
MAX_VARIANTS = 4
MAX_SURROUNDINGS = 12
MAX_TOKENS = 48
MAX_PALETTE = 16

STYLE_SOURCES = frozenset(
    {
        "current_page",
        "selected_element",
        "page_and_selection",
        "custom",
    }
)

PLACEMENTS = frozenset(
    {
        "cover",
        "contain",
        "fill",
        "original",
        "background",
        "inline",
        "icon",
    }
)


def _is_nonempty_str(value: Any, *, max_len: int = 512) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= max_len


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def validate_context(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and normalize an Editor Context Protocol envelope.

    Returns (normalized, error). On error normalized is None.
    """
    if not isinstance(payload, dict):
        return None, "context must be an object"

    protocol = payload.get("protocol", CONTEXT_PROTOCOL)
    if protocol != CONTEXT_PROTOCOL:
        return None, f"unsupported protocol: {protocol}"

    version = payload.get("version", CONTEXT_VERSION)
    if version != CONTEXT_VERSION:
        return None, f"unsupported context version: {version}"

    request = payload.get("request")
    if not isinstance(request, dict):
        return None, "request is required"

    task = request.get("task")
    if not isinstance(task, str) or not task.strip():
        return None, "request.task is required"

    instruction = request.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        return None, "request.instruction is required"
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        return None, "instruction too long"

    request_id = request.get("id")
    if request_id is not None and not _is_nonempty_str(request_id, max_len=128):
        return None, "request.id invalid"

    page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
    selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else {}
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    surroundings = payload.get("surroundings") if isinstance(payload.get("surroundings"), dict) else {}
    asset = payload.get("asset") if isinstance(payload.get("asset"), dict) else {}
    visual = payload.get("visualContext") if isinstance(payload.get("visualContext"), dict) else {}
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}

    style_source = style.get("source", "page_and_selection")
    if style_source not in STYLE_SOURCES:
        return None, f"invalid style.source: {style_source}"

    placement = output.get("placement", "cover")
    if placement not in PLACEMENTS:
        return None, f"invalid output.placement: {placement}"

    width = _num(output.get("width"))
    height = _num(output.get("height"))
    if width is not None and (width <= 0 or width > 8192):
        return None, "invalid output.width"
    if height is not None and (height <= 0 or height > 8192):
        return None, "invalid output.height"

    variants = output.get("variants", 1)
    if not isinstance(variants, int) or variants < 1 or variants > MAX_VARIANTS:
        return None, f"variants must be 1..{MAX_VARIANTS}"

    # Bounds check on visual refs (data URLs or token refs)
    for key in ("pageSnapshot", "selectionSnapshot", "regionSnapshot"):
        snap = visual.get(key)
        if snap is None:
            continue
        if isinstance(snap, str):
            if len(snap) > MAX_SNAPSHOT_DATA_URL_CHARS:
                return None, f"visualContext.{key} too large"
        elif isinstance(snap, dict):
            data = snap.get("dataUrl") or snap.get("ref") or ""
            if isinstance(data, str) and len(data) > MAX_SNAPSHOT_DATA_URL_CHARS:
                return None, f"visualContext.{key} too large"
        else:
            return None, f"visualContext.{key} invalid"

    keys = selection.get("keys")
    if keys is not None and not isinstance(keys, list):
        return None, "selection.keys must be a list"
    if isinstance(keys, list) and len(keys) > 64:
        return None, "selection.keys too many"

    primary = selection.get("primary")
    if primary is not None and not isinstance(primary, str):
        return None, "selection.primary must be a string"

    normalized = {
        "protocol": CONTEXT_PROTOCOL,
        "version": CONTEXT_VERSION,
        "request": {
            "id": str(request_id).strip() if request_id else None,
            "task": task.strip(),
            "instruction": instruction.strip(),
            "createdAt": request.get("createdAt"),
        },
        "page": {
            "id": page.get("id"),
            "route": page.get("route"),
            "kind": page.get("kind"),
            "mode": page.get("mode"),
            "viewport": page.get("viewport") if isinstance(page.get("viewport"), dict) else {},
        },
        "selection": {
            "keys": [str(k) for k in (keys or [])][:64],
            "primary": str(primary) if primary else None,
            "count": int(selection.get("count") or (len(keys) if keys else 0)),
            "role": selection.get("role"),
            "tag": selection.get("tag"),
            "bounds": selection.get("bounds") if isinstance(selection.get("bounds"), dict) else {},
            "aspectRatio": _num(selection.get("aspectRatio")),
            "computedSummary": selection.get("computedSummary")
            if isinstance(selection.get("computedSummary"), dict)
            else {},
        },
        "style": {
            "source": style_source,
            "theme": style.get("theme"),
            "tags": list(style.get("tags") or [])[:32] if isinstance(style.get("tags"), list) else [],
            "tokens": _bounded_dict(style.get("tokens"), MAX_TOKENS),
            "typography": style.get("typography") if isinstance(style.get("typography"), dict) else {},
            "palette": list(style.get("palette") or [])[:MAX_PALETTE]
            if isinstance(style.get("palette"), list)
            else [],
            "effects": style.get("effects") if isinstance(style.get("effects"), dict) else {},
            "spacing": style.get("spacing") if isinstance(style.get("spacing"), dict) else {},
            "styleSummary": str(style.get("styleSummary") or "")[:2000],
            "customInstruction": str(style.get("customInstruction") or "")[:2000],
        },
        "surroundings": {
            "parent": surroundings.get("parent") if isinstance(surroundings.get("parent"), dict) else None,
            "siblings": list(surroundings.get("siblings") or [])[:MAX_SURROUNDINGS]
            if isinstance(surroundings.get("siblings"), list)
            else [],
            "nearby": list(surroundings.get("nearby") or [])[:MAX_SURROUNDINGS]
            if isinstance(surroundings.get("nearby"), list)
            else [],
        },
        "asset": {
            "current": asset.get("current"),
            "references": list(asset.get("references") or [])[:8]
            if isinstance(asset.get("references"), list)
            else [],
        },
        "visualContext": {
            "pageSnapshot": visual.get("pageSnapshot"),
            "selectionSnapshot": visual.get("selectionSnapshot"),
            "regionSnapshot": visual.get("regionSnapshot"),
            "included": list(visual.get("included") or [])
            if isinstance(visual.get("included"), list)
            else [],
            "degraded": bool(visual.get("degraded")),
            "degradeReason": visual.get("degradeReason"),
        },
        "output": {
            "kind": output.get("kind") or "asset",
            "placement": placement,
            "width": int(width) if width else None,
            "height": int(height) if height else None,
            "aspectRatio": _num(output.get("aspectRatio")),
            "variants": variants,
        },
        "policy": {
            "previewOnly": bool(policy.get("previewOnly", True)),
            "requireExplicitAccept": bool(policy.get("requireExplicitAccept", True)),
            "allowDirectSourceRewrite": bool(policy.get("allowDirectSourceRewrite", False)),
            "allowAssetPersistenceBeforeAccept": bool(policy.get("allowAssetPersistenceBeforeAccept", False)),
        },
        "options": payload.get("options") if isinstance(payload.get("options"), dict) else {},
        "targetFingerprint": payload.get("targetFingerprint")
        if isinstance(payload.get("targetFingerprint"), dict)
        else {},
    }
    return normalized, None


def _bounded_dict(value: Any, limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(value.items()):
        if i >= limit:
            break
        key = str(k)[:128]
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v if not isinstance(v, str) else v[:512]
        else:
            out[key] = str(v)[:512]
    return out


def make_result(
    *,
    request_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol": RESULT_PROTOCOL,
        "version": RESULT_VERSION,
        "requestId": request_id,
        "status": status,
        "result": result,
        "provider": provider or {},
        "diagnostics": diagnostics or {},
    }
    if error:
        payload["error"] = error
    return payload


def make_error_result(
    request_id: str,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return make_result(
        request_id=request_id,
        status="error",
        result={"kind": "error"},
        provider=provider,
        diagnostics=diagnostics,
        error={"code": code, "message": message, "details": details or {}},
    )
