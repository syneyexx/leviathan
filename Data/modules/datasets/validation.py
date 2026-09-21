"""Validate canonical dataset records."""

from __future__ import annotations

from typing import Any

from .types import CanonicalRecord


def validate_record(record: CanonicalRecord, *, index: int = 0) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not record.id or not str(record.id).strip():
        issues.append({"index": index, "field": "id", "code": "missing_id", "message": "id is required"})
    has_text = bool(record.text and str(record.text).strip())
    has_messages = bool(record.messages)
    if not has_text and not has_messages:
        issues.append(
            {
                "index": index,
                "field": "text",
                "code": "empty_content",
                "message": "record needs text or messages",
            }
        )
    if record.messages is not None:
        if not isinstance(record.messages, list):
            issues.append(
                {
                    "index": index,
                    "field": "messages",
                    "code": "invalid_messages",
                    "message": "messages must be a list",
                }
            )
        else:
            for mi, msg in enumerate(record.messages):
                if not isinstance(msg, dict):
                    issues.append(
                        {
                            "index": index,
                            "field": f"messages[{mi}]",
                            "code": "invalid_message",
                            "message": "each message must be an object",
                        }
                    )
                    continue
                if "content" not in msg and "text" not in msg:
                    issues.append(
                        {
                            "index": index,
                            "field": f"messages[{mi}]",
                            "code": "message_missing_content",
                            "message": "message needs content or text",
                        }
                    )
    if record.split is not None and record.split not in {"train", "validation", "val", "test", "dev"}:
        issues.append(
            {
                "index": index,
                "field": "split",
                "code": "unknown_split",
                "message": f"unexpected split label: {record.split}",
                "severity": "warning",
            }
        )
    return issues


def validate_records(
    records: list[CanonicalRecord],
    *,
    max_issues: int = 200,
) -> dict[str, Any]:
    all_issues: list[dict[str, Any]] = []
    empty = 0
    for idx, rec in enumerate(records):
        issues = validate_record(rec, index=idx)
        if any(i.get("code") == "empty_content" for i in issues):
            empty += 1
        for issue in issues:
            if len(all_issues) < max_issues:
                all_issues.append(issue)
    errors = [i for i in all_issues if i.get("severity") != "warning"]
    warnings = [i for i in all_issues if i.get("severity") == "warning"]
    # Also count truncated
    truncated = len(records) > 0 and len(all_issues) >= max_issues
    valid = len(errors) == 0
    return {
        "valid": valid,
        "rowCount": len(records),
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "emptyContentCount": empty,
        "issues": all_issues,
        "truncated": truncated,
    }
