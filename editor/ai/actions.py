"""Allowlisted structured editor actions from AI results.

Treat model output as untrusted. Validate before any apply path.
"""

from __future__ import annotations

from typing import Any

ALLOWED_ACTIONS = frozenset(
    {
        "replace_asset",
        "set_image_source",
        "set_text",
        "update_style_properties",
        "insert_node",
        "insert_component",
        "remove_node",
        "reorder_node",
        "set_attributes",
        "update_component_props",
    }
)

ALLOWED_STYLE_PROPS = frozenset(
    {
        "width",
        "height",
        "min-width",
        "min-height",
        "max-width",
        "max-height",
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "margin",
        "margin-top",
        "margin-right",
        "margin-bottom",
        "margin-left",
        "gap",
        "row-gap",
        "column-gap",
        "align-items",
        "justify-content",
        "align-self",
        "justify-self",
        "flex-direction",
        "flex-wrap",
        "flex",
        "flex-grow",
        "flex-shrink",
        "grid-template-columns",
        "grid-template-rows",
        "border-radius",
        "background",
        "background-color",
        "background-image",
        "color",
        "font-family",
        "font-size",
        "font-weight",
        "line-height",
        "letter-spacing",
        "text-align",
        "opacity",
        "object-fit",
        "box-shadow",
        "border",
        "border-color",
        "border-width",
        "display",
        "position",
        "top",
        "left",
        "right",
        "bottom",
        "z-index",
        "overflow",
    }
)

FORBIDDEN_VALUE_MARKERS = (
    "javascript:",
    "expression(",
    "@import",
    "url(file:",
    "<script",
    "data:text/html",
)

MAX_ACTIONS = 32
MAX_ATTR_KEYS = 24


def validate_actions(actions: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if actions is None:
        return [], None
    if not isinstance(actions, list):
        return None, "actions must be a list"
    if len(actions) > MAX_ACTIONS:
        return None, f"too many actions (max {MAX_ACTIONS})"

    out: list[dict[str, Any]] = []
    for i, raw in enumerate(actions):
        if not isinstance(raw, dict):
            return None, f"action[{i}] must be an object"
        op = raw.get("type") or raw.get("operation")
        if op not in ALLOWED_ACTIONS:
            return None, f"action[{i}] unknown operation: {op}"
        target = raw.get("target")
        if target is not None and not isinstance(target, str):
            return None, f"action[{i}] target must be a string"
        if isinstance(target, str) and (not target.strip() or len(target) > 256):
            return None, f"action[{i}] invalid target"

        args = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
        changes = raw.get("changes") if isinstance(raw.get("changes"), dict) else args.get("changes")

        if op == "update_style_properties":
            if not isinstance(changes, dict) or not changes:
                return None, f"action[{i}] changes required"
            cleaned: dict[str, str] = {}
            for prop, value in changes.items():
                prop_s = str(prop).strip().lower()
                if prop_s not in ALLOWED_STYLE_PROPS:
                    return None, f"action[{i}] style property not allowed: {prop_s}"
                val_s = str(value)
                low = val_s.lower()
                if any(m in low for m in FORBIDDEN_VALUE_MARKERS):
                    return None, f"action[{i}] unsafe style value"
                if len(val_s) > 512:
                    return None, f"action[{i}] style value too long"
                cleaned[prop_s] = val_s
            out.append(
                {
                    "type": op,
                    "target": str(target) if target else None,
                    "changes": cleaned,
                    "preconditions": raw.get("preconditions")
                    if isinstance(raw.get("preconditions"), dict)
                    else {},
                }
            )
            continue

        if op in {"set_text", "set_image_source", "replace_asset"}:
            value = raw.get("value", args.get("value") or args.get("text") or args.get("url"))
            if not isinstance(value, str) or not value.strip():
                return None, f"action[{i}] value required"
            if len(value) > 50_000:
                return None, f"action[{i}] value too long"
            if op != "set_text":
                low = value.lower()
                if any(m in low for m in FORBIDDEN_VALUE_MARKERS) or low.startswith("file:"):
                    return None, f"action[{i}] unsafe asset url"
            out.append(
                {
                    "type": op,
                    "target": str(target) if target else None,
                    "value": value,
                    "preconditions": raw.get("preconditions")
                    if isinstance(raw.get("preconditions"), dict)
                    else {},
                }
            )
            continue

        if op == "set_attributes":
            attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else args.get("attributes")
            if not isinstance(attrs, dict) or not attrs:
                return None, f"action[{i}] attributes required"
            cleaned_attrs: dict[str, str] = {}
            for k, v in list(attrs.items())[:MAX_ATTR_KEYS]:
                key = str(k).strip().lower()
                if key.startswith("on") or key in {"srcdoc"}:
                    return None, f"action[{i}] forbidden attribute"
                val = str(v)
                if any(m in val.lower() for m in FORBIDDEN_VALUE_MARKERS):
                    return None, f"action[{i}] unsafe attribute value"
                cleaned_attrs[key] = val[:1024]
            out.append({"type": op, "target": str(target) if target else None, "attributes": cleaned_attrs})
            continue

        # Structural ops: validated shape only; apply layer enforces shell rules
        out.append(
            {
                "type": op,
                "target": str(target) if target else None,
                "arguments": {k: v for k, v in args.items() if k in {"parent", "index", "componentId", "props", "node"}},
                "preconditions": raw.get("preconditions") if isinstance(raw.get("preconditions"), dict) else {},
            }
        )

    return out, None
