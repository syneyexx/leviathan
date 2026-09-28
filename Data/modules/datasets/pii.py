"""PII / secret scanning for dataset content (flags, not proof)."""

from __future__ import annotations

from typing import Any, Iterable

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
            # Redact any mirrored sample text in findings
            item = {**finding, "recordId": record.id}
            if "sample" in item and isinstance(item["sample"], str):
                item["sample"] = redact_secrets(item["sample"])
            if "match" in item and isinstance(item["match"], str):
                item["match"] = redact_secrets(item["match"])
            findings.append(item)
    return findings


def scan_records_pii(
    records: Iterable[CanonicalRecord],
    *,
    max_findings: int = 100,
    max_records: int | None = None,
) -> dict[str, Any]:
    """Scan an iterable of records — does not require a complete corpus list."""
    findings: list[dict[str, Any]] = []
    records_with = 0
    record_count = 0
    total_finding_count = 0
    capped = False
    for rec in records:
        if max_records is not None and record_count >= max_records:
            capped = True
            break
        record_count += 1
        hit = scan_record_pii(rec)
        if hit:
            records_with += 1
            total_finding_count += len(hit)
            for item in hit:
                if len(findings) < max_findings:
                    findings.append(item)
    evidence = "SAMPLED" if capped else "EXACT"
    return {
        "recordCount": record_count,
        "recordsWithFindings": records_with,
        "findingCount": total_finding_count,
        "findings": findings,
        "truncated": total_finding_count > len(findings) or capped,
        "evidenceClass": evidence,
        "note": "Detections are flags, not proof of PII",
        "truth": {
            "evidenceClass": evidence,
            "fullScanIsDatasetWorker": True,
            "missingScanIsNotClean": True,
        },
    }


def redact_text(text: str) -> str:
    return redact_secrets(text)
