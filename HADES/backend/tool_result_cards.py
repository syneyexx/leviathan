"""Structured tool result cards — normalize tool observations for UI rendering."""

from __future__ import annotations

import json
from typing import Any


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def build_tool_result_card(observation: dict[str, Any]) -> dict[str, Any]:
    """Turn a tool log row into a UI-friendly card without inventing success."""
    name = str(observation.get("tool_name") or observation.get("plugin_id") or "tool")
    status = str(observation.get("status") or observation.get("result_status") or "unknown")
    error = observation.get("error")
    output = observation.get("output") or observation.get("stdout") or observation.get("result")
    parsed = _as_dict(output) if not isinstance(output, dict) else output

    card_type = "log"
    rows: list[dict[str, str]] = []
    diff_text = None
    table: list[list[str]] | None = None

    if isinstance(parsed, dict):
        if "diff" in parsed or "patch" in parsed:
            card_type = "diff"
            diff_text = str(parsed.get("diff") or parsed.get("patch") or "")[:12_000]
        elif "rows" in parsed and isinstance(parsed["rows"], list):
            card_type = "table"
            table = [[str(cell) for cell in row] for row in parsed["rows"][:50] if isinstance(row, (list, tuple))]
        elif "documents" in parsed and isinstance(parsed["documents"], list):
            card_type = "table"
            docs = parsed["documents"][:40]
            table = [["name", "uri", "status"]] + [
                [
                    str(doc.get("name") or doc.get("title") or ""),
                    str(doc.get("uri") or doc.get("url") or ""),
                    str(doc.get("status") or "ok"),
                ]
                for doc in docs
                if isinstance(doc, dict)
            ]
        else:
            card_type = "json"
            for key, value in list(parsed.items())[:24]:
                rows.append({"key": str(key), "value": json.dumps(value, ensure_ascii=False)[:500] if not isinstance(value, str) else value[:500]})

    summary = str(error or observation.get("summary") or "")[:500]
    if not summary and isinstance(output, str):
        summary = output[:400]
    elif not summary and parsed:
        summary = f"{name}: gestructureerd resultaat ({card_type})"

    return {
        "tool_name": name,
        "plugin_id": observation.get("plugin_id"),
        "call_id": observation.get("call_id"),
        "status": status,
        "card_type": card_type,
        "summary": summary,
        "error": error,
        "rows": rows,
        "table": table,
        "diff": diff_text,
        "raw_preview": (json.dumps(output, ensure_ascii=False)[:2_000] if not isinstance(output, str) else output[:2_000]) if output is not None else None,
        "honest": True,
    }


def build_tool_result_cards(observations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [build_tool_result_card(item) for item in (observations or []) if isinstance(item, dict)]
