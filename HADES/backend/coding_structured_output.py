"""Hardened structured-output parser for Coding Agent model responses.

Accepts pure JSON, fenced JSON, or one top-level JSON object embedded in prose.
Never executes content. Never uses eval. Returns structured diagnostics.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ParseKind = Literal[
    "ok",
    "no_model_response",
    "malformed_response",
    "schema_invalid",
    "stale_hash",
    "empty_edits",
    "timeout",
    "cancelled",
    "provider_error",
    "truncated",
    "retry_failed",
]

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*([\s\S]*?)```", re.M)
_ALLOWED_ACTIONS = frozenset({"create", "replace", "patch_lines", "unified_diff", "rename"})


@dataclass(slots=True)
class StructuredParseResult:
    kind: ParseKind
    payload: dict[str, Any] | None = None
    edits_raw: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    excerpt: str | None = None
    retry_recommended: bool = False

    @property
    def ok(self) -> bool:
        return self.kind == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "error": self.error,
            "edit_count": len(self.edits_raw),
            "diagnostics": dict(self.diagnostics),
            "excerpt": self.excerpt,
            "retry_recommended": self.retry_recommended,
        }


def _sanitize_excerpt(text: str, *, limit: int = 400) -> str:
    cleaned = (text or "").replace("\x00", "")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _extract_json_candidates(text: str) -> list[str]:
    """Return candidate JSON object strings in preference order (not dangerously permissive)."""
    raw = (text or "").strip()
    if not raw:
        return []
    candidates: list[str] = []

    # 1. Fenced blocks first (most intentional).
    for match in _FENCE_RE.finditer(raw):
        body = (match.group(1) or "").strip()
        if body.startswith("{") and body not in candidates:
            candidates.append(body)

    # 2. Whole text if it looks like a JSON object.
    if raw.startswith("{") and raw.endswith("}"):
        if raw not in candidates:
            candidates.append(raw)

    # 3. Locate balanced top-level objects (skip nested-only / array-only).
    # Prefer the largest object that contains an "edits" key when multiple exist.
    objs: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(raw):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    objs.append(raw[start : i + 1])
                    start = -1

    # Prefer objects that mention "edits"; then larger objects.
    objs_sorted = sorted(
        objs,
        key=lambda s: (1 if '"edits"' in s or "'edits'" in s else 0, len(s)),
        reverse=True,
    )
    for obj in objs_sorted:
        if obj not in candidates:
            candidates.append(obj)

    return candidates


def _looks_truncated(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.count("{") > raw.count("}"):
        return True
    if raw.count("[") > raw.count("]"):
        return True
    if raw.startswith("{") and not raw.endswith("}"):
        return True
    if "```" in raw and raw.count("```") == 1:
        return True
    # Ends mid-string or mid-key
    if re.search(r'[:,{]\s*"[^"]*$', raw):
        return True
    return False


def extract_json_object(text: str) -> tuple[dict[str, Any] | None, StructuredParseResult]:
    """Extract one JSON object from model text; return diagnostics on failure."""
    raw = text if isinstance(text, str) else ""
    excerpt = _sanitize_excerpt(raw)
    if not raw.strip():
        return None, StructuredParseResult(
            kind="no_model_response",
            error="empty_model_response",
            excerpt=excerpt,
            retry_recommended=False,
        )

    truncated = _looks_truncated(raw)
    candidates = _extract_json_candidates(raw)
    if not candidates:
        return None, StructuredParseResult(
            kind="truncated" if truncated else "malformed_response",
            error="no_json_object_found",
            excerpt=excerpt,
            diagnostics={"truncated_signal": truncated},
            retry_recommended=True,
        )

    last_err: str | None = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_err = f"json_decode:{exc}"
            continue
        if not isinstance(parsed, dict):
            last_err = "top_level_not_object"
            continue
        return parsed, StructuredParseResult(
            kind="ok",
            payload=parsed,
            excerpt=excerpt,
            diagnostics={"candidate_count": len(candidates)},
        )

    kind: ParseKind = "truncated" if truncated else "malformed_response"
    return None, StructuredParseResult(
        kind=kind,
        error=last_err or "json_parse_failed",
        excerpt=excerpt,
        diagnostics={"candidate_count": len(candidates), "truncated_signal": truncated},
        retry_recommended=True,
    )


def validate_edits_schema(
    payload: dict[str, Any],
    *,
    known_hashes: dict[str, str] | None = None,
) -> StructuredParseResult:
    """Validate {\"edits\":[...]} schema without constructing FileEdit yet."""
    known = known_hashes or {}
    if not isinstance(payload, dict):
        return StructuredParseResult(
            kind="schema_invalid",
            error="payload_not_object",
            retry_recommended=True,
        )
    raw_edits = payload.get("edits")
    if raw_edits is None:
        return StructuredParseResult(
            kind="schema_invalid",
            error="edits_key_missing",
            payload=payload,
            retry_recommended=True,
        )
    if not isinstance(raw_edits, list):
        return StructuredParseResult(
            kind="schema_invalid",
            error="edits_not_list",
            payload=payload,
            retry_recommended=True,
        )
    if not raw_edits:
        return StructuredParseResult(
            kind="empty_edits",
            error="edits_empty",
            payload=payload,
            edits_raw=[],
            retry_recommended=False,
        )

    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw_edits):
        if not isinstance(item, dict):
            return StructuredParseResult(
                kind="schema_invalid",
                error=f"edit[{index}]_not_object",
                payload=payload,
                retry_recommended=True,
            )
        path = str(item.get("path") or "").strip()
        action = str(item.get("action") or "replace").strip().lower()
        if action not in _ALLOWED_ACTIONS:
            return StructuredParseResult(
                kind="schema_invalid",
                error=f"edit[{index}]_bad_action:{action}",
                payload=payload,
                retry_recommended=True,
            )
        if action == "rename":
            from_path = item.get("from_path") or item.get("old_path")
            if not path or not from_path:
                return StructuredParseResult(
                    kind="schema_invalid",
                    error=f"edit[{index}]_rename_incomplete",
                    payload=payload,
                    retry_recommended=True,
                )
            cleaned.append(
                {
                    "path": path,
                    "action": "rename",
                    "from_path": str(from_path),
                    "base_hash": str(item.get("base_hash") or "") or None,
                }
            )
            continue
        content = item.get("content")
        if not path or content is None:
            return StructuredParseResult(
                kind="schema_invalid",
                error=f"edit[{index}]_incomplete",
                payload=payload,
                retry_recommended=True,
            )
        expected_hash = item.get("base_hash") or item.get("content_hash")
        if expected_hash and path in known and known[path] != expected_hash:
            return StructuredParseResult(
                kind="stale_hash",
                error=f"edit[{index}]_stale_hash:{path}",
                payload=payload,
                retry_recommended=False,
                diagnostics={"path": path, "expected": expected_hash, "actual": known[path]},
            )
        if action == "patch_lines":
            if item.get("start_line") is None or item.get("end_line") is None:
                return StructuredParseResult(
                    kind="schema_invalid",
                    error=f"edit[{index}]_patch_lines_missing_range",
                    payload=payload,
                    retry_recommended=True,
                )
        entry = {
            "path": path,
            "action": action,
            "content": str(content),
            "old_content": str(item["old_content"]) if item.get("old_content") is not None else None,
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
            "base_hash": str(expected_hash) if expected_hash else None,
            "from_path": str(item["from_path"]) if item.get("from_path") else None,
        }
        cleaned.append(entry)

    return StructuredParseResult(
        kind="ok",
        payload=payload,
        edits_raw=cleaned,
        diagnostics={"edit_count": len(cleaned)},
    )


def parse_coding_edits_response(
    content: Any,
    *,
    known_hashes: dict[str, str] | None = None,
    invoke_meta: dict[str, Any] | None = None,
) -> StructuredParseResult:
    """Full parse+validate pipeline for Coding model edit responses."""
    meta = invoke_meta or {}
    note = str(meta.get("note") or "")
    if "lm_invoke_cancelled" in note or meta.get("outcome") == "cancelled":
        return StructuredParseResult(
            kind="cancelled",
            error=note or "lm_invoke_cancelled",
            diagnostics=dict(meta),
            retry_recommended=False,
        )
    if "lm_invoke_timeout" in note:
        return StructuredParseResult(
            kind="timeout",
            error=note,
            diagnostics=dict(meta),
            retry_recommended=False,
        )
    if "lm_invoke_failed" in note:
        return StructuredParseResult(
            kind="provider_error",
            error=note,
            diagnostics=dict(meta),
            retry_recommended=False,
        )
    if content is None:
        return StructuredParseResult(
            kind="no_model_response",
            error="null_content",
            diagnostics=dict(meta),
            retry_recommended=False,
        )

    text = content if isinstance(content, str) else str(content)
    # Detect finish_reason truncation when provided via meta.
    finish = str(meta.get("finish_reason") or meta.get("finishReason") or "").lower()
    if finish in {"length", "max_tokens", "truncated"}:
        return StructuredParseResult(
            kind="truncated",
            error=f"finish_reason:{finish}",
            excerpt=_sanitize_excerpt(text),
            diagnostics=dict(meta),
            retry_recommended=True,
        )

    obj, extract_result = extract_json_object(text)
    if obj is None:
        return extract_result

    validated = validate_edits_schema(obj, known_hashes=known_hashes)
    validated.excerpt = extract_result.excerpt or validated.excerpt
    validated.diagnostics = {
        **extract_result.diagnostics,
        **validated.diagnostics,
        **{k: v for k, v in meta.items() if k in {"worker_ownership", "cancel_signaled", "note"}},
    }
    return validated


def format_schema_repair_prompt(*, validation_error: str, previous_excerpt: str | None = None) -> str:
    """Ask only for corrected structured output — one bounded retry."""
    excerpt = _sanitize_excerpt(previous_excerpt or "", limit=300)
    return (
        "Your previous reply was not valid structured Coding edits JSON.\n"
        f"Validation error: {validation_error}\n"
        "Reply with ONLY a JSON object (no markdown fences required, but allowed):\n"
        '{"edits":[{"path":"rel/path","action":"unified_diff|patch_lines|create|rename|replace",'
        '"content":"...","base_hash":"...","start_line":N,"end_line":M}]}\n'
        "Prefer unified_diff or patch_lines for existing files. Do not echo large old_content.\n"
        "Do not include explanations outside the JSON object.\n"
        + (f"Previous excerpt:\n{excerpt}\n" if excerpt else "")
    )


def message_content_from_chat_response(response: Any) -> tuple[str, dict[str, Any]]:
    """Extract assistant text + finish metadata from OpenAI-compatible chat response."""
    meta: dict[str, Any] = {}
    if response is None:
        return "", meta
    if isinstance(response, str):
        return response, meta
    if not isinstance(response, dict):
        return str(getattr(response, "content", response) or ""), meta
    choices = response.get("choices") or []
    if not choices:
        return "", meta
    choice0 = choices[0] if isinstance(choices[0], dict) else {}
    finish = choice0.get("finish_reason") or choice0.get("finishReason")
    if finish:
        meta["finish_reason"] = finish
    message = choice0.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = choice0.get("text") or ""
    return str(content or ""), meta


# Preferred edit-contract instructions for model prompts.
CODING_EDIT_CONTRACT_PROMPT = """You are the HADES coding agent.
Return ONLY a JSON object with an "edits" array.

Edit action preference (strongest first):
1. unified_diff — normal modifications to existing files (preferred)
2. patch_lines — precise bounded line-range changes (start_line/end_line inclusive, 1-based)
3. create — new files only
4. rename — path moves (from_path + path)
5. replace — ONLY for genuinely small files where full rewrite is safer than a diff

Rules:
- Bind each edit to base_hash from the provided file hashes when modifying existing files.
- Do NOT echo large old_content; base_hash provides stale-write protection.
- Do not remove, skip, or weaken tests.
- Paths must be repo-relative using forward slashes.
- Keep edits minimal and focused on the goal.

Schema example:
{"edits":[{"path":"src/app.py","action":"unified_diff","content":"--- a/src/app.py\\n+++ b/src/app.py\\n@@ ...","base_hash":"..."}]}
"""
