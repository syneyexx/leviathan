"""PII / secret scanning for dataset content (flags, not proof)."""

from __future__ import annotations

from typing import Any

from Data.modules.common.secrets import redact_secrets, scan_pii_flags

from .types import CanonicalRecord


def scan_record_pii(record: CanonicalRecord) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    texts = [record.text or ""]
    if record.messages:
        for msg in record.messages:
            content = msg.get("content") or msg.get("text") or ""
            if isinstance(content, str):
                texts.append(content)
    for text in texts:
        for finding in scan_pii_flags(text):
            findings.append({**finding, "recordId": record.id})
    return findings


def scan_records_pii(
    records: list[CanonicalRecord],
    *,
    max_findings: int = 100,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    records_with = 0
    for rec in records:
        hit = scan_record_pii(rec)
        if hit:
            records_with += 1
            for item in hit:
                if len(findings) < max_findings:
                    findings.append(item)
    return {
        "recordCount": len(records),
        "recordsWithFindings": records_with,
        "findingCount": len(findings),
        "findings": findings,
        "truncated": records_with > 0 and len(findings) >= max_findings,
        "note": "Detections are flags, not proof of PII",
    }


def redact_text(text: str) -> str:
    return redact_secrets(text)
