"""Validate canonical dataset records."""

from __future__ import annotations

from typing import Any, Iterable

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
    records: Iterable[CanonicalRecord],
    *,
    max_issues: int = 200,
) -> dict[str, Any]:
    """Validate records incrementally — works for lists or streaming iterables.

    ``errorCount`` / ``warningCount`` are true totals even when the issue sample
    is truncated at ``max_issues``.
    """
    all_issues: list[dict[str, Any]] = []
    empty = 0
    row_count = 0
    error_count = 0
    warning_count = 0
    for idx, rec in enumerate(records):
        row_count += 1
        issues = validate_record(rec, index=idx)
        if any(i.get("code") == "empty_content" for i in issues):
            empty += 1
        for issue in issues:
            if issue.get("severity") == "warning":
                warning_count += 1
            else:
                error_count += 1
            if len(all_issues) < max_issues:
                all_issues.append(issue)
    truncated = (error_count + warning_count) > len(all_issues)
    return {
        "valid": error_count == 0,
        "rowCount": row_count,
        "errorCount": error_count,
        "warningCount": warning_count,
        "emptyContentCount": empty,
        "issues": all_issues,
        "issuesTruncated": truncated,
        "truncated": truncated,
    }
