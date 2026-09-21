"""Tool-boundary prompt-injection defenses (G11).

Sanitize/reject tool arguments that look like permission-escalation or
prompt-injection payloads. Deterministic; never delegates to an LLM.
"""

from __future__ import annotations

import re
from typing import Any


INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I)),
    ("system_override", re.compile(r"\bSYSTEM\s*:", re.I)),
    ("grant_admin", re.compile(r"grant[_\s-]?admin\s*=\s*true", re.I)),
    ("permission_escalate", re.compile(r"(escalate|bypass)\s+(permission|policy|sandbox|allowlist)", re.I)),
    ("jailbreak", re.compile(r"\b(dan\s+mode|developer\s+mode\s+enabled|jailbreak)\b", re.I)),
    ("exfil_secret", re.compile(r"(exfiltrat(?:e|ion|ing)?|dump)\s+(secret|credential|api[_-]?key|password|token)", re.I)),
    ("disable_safety", re.compile(r"disable\s+(safety|guardrail|sandbox|permission)", re.I)),
)

# Keys that must never carry free-form escalation instructions into tool calls.
SENSITIVE_ARG_KEYS = frozenset(
    {
        "system",
        "system_prompt",
        "instructions",
        "policy_override",
        "permissions",
        "grant",
        "grants",
        "capability",
        "capabilities",
        "sudo",
        "admin",
    }
)


def _scan_text(text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for code, pattern in INJECTION_PATTERNS:
        if pattern.search(text or ""):
            hits.append({"code": code, "snippet": (text or "")[:120]})
    return hits


def _walk(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_s = str(key)
            child_path = f"{path}.{key_s}" if path else key_s
            if key_s.lower() in SENSITIVE_ARG_KEYS and isinstance(child, (str, dict, list)):
                # Sensitive keys with non-empty content are treated as escalation attempts.
                if child not in (None, "", [], {}):
                    findings.append(
                        {
                            "code": "sensitive_arg_key",
                            "path": child_path,
                            "message": f"Tool arg key '{key_s}' is not allowed at tool boundary",
                        }
                    )
            findings.extend(_walk(child, path=child_path))
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            findings.extend(_walk(child, path=f"{path}[{idx}]"))
    elif isinstance(value, str):
        for hit in _scan_text(value):
            findings.append({**hit, "path": path or "$", "message": f"Injection pattern '{hit['code']}' in tool args"})
    return findings


def inspect_tool_args(args: Any) -> dict[str, Any]:
    findings = _walk(args)
    return {
        "ok": len(findings) == 0,
        "finding_count": len(findings),
        "findings": findings,
        "defense": "tool_boundary_injection_v1",
    }


def sanitize_tool_args(args: Any) -> dict[str, Any]:
    """Return cleaned args with injection-bearing strings stripped / sensitive keys dropped."""

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, child in value.items():
                if str(key).lower() in SENSITIVE_ARG_KEYS:
                    continue
                out[str(key)] = _clean(child)
            return out
        if isinstance(value, list):
            return [_clean(v) for v in value]
        if isinstance(value, str):
            cleaned = value
            for _code, pattern in INJECTION_PATTERNS:
                cleaned = pattern.sub("[blocked]", cleaned)
            # Drop lines that still look like system overrides after partial scrub.
            lines = [
                line
                for line in cleaned.splitlines()
                if not any(m in line.lower() for m in ("grant_admin", "ignore previous", "system:"))
            ]
            return "\n".join(lines).strip()
        return value

    inspection = inspect_tool_args(args)
    cleaned = _clean(args)
    post = inspect_tool_args(cleaned)
    return {
        "ok": post["ok"],
        "rejected": not inspection["ok"] and not post["ok"],
        "sanitized": cleaned,
        "original_findings": inspection["findings"],
        "remaining_findings": post["findings"],
        "defense": "tool_boundary_injection_v1",
    }


def enforce_tool_args(args: Any, *, mode: str = "reject") -> dict[str, Any]:
    """Reject or sanitize tool args at the boundary.

    mode=reject — block when any finding present (fail closed).
    mode=sanitize — scrub and allow only if scrub clears findings.
    """
    mode_n = (mode or "reject").strip().lower()
    inspection = inspect_tool_args(args)
    if inspection["ok"]:
        return {
            "allowed": True,
            "mode": mode_n,
            "args": args,
            "findings": [],
            "reason": "clean",
        }
    if mode_n == "sanitize":
        scrubbed = sanitize_tool_args(args)
        if scrubbed["ok"]:
            return {
                "allowed": True,
                "mode": mode_n,
                "args": scrubbed["sanitized"],
                "findings": scrubbed["original_findings"],
                "reason": "sanitized",
            }
        return {
            "allowed": False,
            "mode": mode_n,
            "args": None,
            "findings": scrubbed["remaining_findings"],
            "reason": "sanitize_incomplete",
        }
    return {
        "allowed": False,
        "mode": "reject",
        "args": None,
        "findings": inspection["findings"],
        "reason": "injection_rejected",
    }
