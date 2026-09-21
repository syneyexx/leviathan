"""Conversation Markdown export with secret redaction (HADES-10 Phase 7)."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)\bauthorization\s*:\s*\S+(?:\s+\S+)?"),
    re.compile(r"(?i)\b(api[_-]?key|password|secret|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}"),
)


def redact_secrets(text: str) -> str:
    out = str(text or "")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def export_conversation_markdown(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    runs: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> str:
    title = str(conversation.get("title") or conversation.get("id") or "conversation")
    lines = [
        f"# {title}",
        "",
        f"- conversation_id: `{conversation.get('id')}`",
        f"- updated_at: {conversation.get('updated_at') or '—'}",
        "",
        "## Turns",
        "",
    ]
    for message in messages:
        role = str(message.get("role") or "unknown")
        content = redact_secrets(str(message.get("content") or ""))
        mid = message.get("id")
        lines.append(f"### {role}" + (f" (`{mid}`)" if mid else ""))
        lines.append("")
        lines.append(content or "_(leeg)_")
        lines.append("")
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        citations = meta.get("citations") or meta.get("sources")
        if citations:
            lines.append("Citations:")
            lines.append("")
            lines.append(redact_secrets(str(citations))[:2_000])
            lines.append("")
    if runs:
        lines.extend(["## Run outcomes", ""])
        for run in runs:
            lines.append(
                f"- `{run.get('run_type')}` `{run.get('run_id')}` → {run.get('status')}"
                + (f" — {run.get('title')}" if run.get("title") else "")
            )
        lines.append("")
    if artifacts:
        lines.extend(["## Artifacts", ""])
        for art in artifacts:
            lines.append(
                f"- {art.get('name') or art.get('id')} ({art.get('mime_type') or art.get('type') or 'artifact'})"
            )
        lines.append("")
    lines.append("_Exported by HADES. Credentials and secret headers are redacted._")
    lines.append("")
    return "\n".join(lines)
