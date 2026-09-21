"""Secret detection / redaction for logs, manifests, and API responses."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"hf_[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")


def looks_like_secret(text: str) -> bool:
    return any(pat.search(text) for pat in _SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(0)[: m.start(2) - m.start(0)] + "[REDACTED]") if m.lastindex and m.lastindex >= 2 else "[REDACTED]", out)
    return out


def scan_pii_flags(text: str) -> list[dict[str, Any]]:
    """Return detection flags (not proof) for obvious PII/secret patterns."""
    findings: list[dict[str, Any]] = []
    for label, pattern in (
        ("secret_like", _SECRET_PATTERNS[0]),
        ("bearer_token", _SECRET_PATTERNS[1]),
        ("openai_key_like", _SECRET_PATTERNS[2]),
        ("hf_token_like", _SECRET_PATTERNS[3]),
        ("private_key_pem", _SECRET_PATTERNS[4]),
        ("email", _EMAIL),
        ("phone", _PHONE),
        ("ipv4", _IPV4),
    ):
        for match in pattern.finditer(text):
            findings.append(
                {
                    "kind": label,
                    "start": match.start(),
                    "end": match.end(),
                    "preview": text[match.start() : min(match.end(), match.start() + 24)] + ("…" if match.end() - match.start() > 24 else ""),
                    "note": "Detection is a flag, not proof",
                }
            )
    return findings
