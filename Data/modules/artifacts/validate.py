"""Artifact reopen + structural validation (Round 7).

"File created" is not sufficient — reopen the artifact and validate structure
and relevant content where feasible.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .store import ArtifactStore, sha256_bytes
from .types import ArtifactRecord


def reopen_artifact(store: ArtifactStore, artifact_id: str) -> dict[str, Any]:
    record = store.get(artifact_id)
    if record is None:
        raise KeyError(artifact_id)
    path = Path(record.path)
    if not path.is_file():
        return {
            "artifact_id": artifact_id,
            "ok": False,
            "error": "artifact file missing on disk",
            "truth": {"file_created_is_not_validation": True},
        }
    data = path.read_bytes()
    hash_ok = sha256_bytes(data) == record.content_hash
    structural = validate_artifact_bytes(
        data,
        artifact_type=record.artifact_type,
        filename=path.name,
        metadata=record.metadata,
    )
    status = "validated" if hash_ok and structural["ok"] else (
        "hash_mismatch" if not hash_ok else "structure_invalid"
    )
    # Persist verification status
    with store.connect() as conn:
        conn.execute(
            "UPDATE artifacts SET verification_status = ? WHERE artifact_id = ?",
            (status, artifact_id),
        )
    return {
        "artifact_id": artifact_id,
        "ok": hash_ok and structural["ok"],
        "hash_ok": hash_ok,
        "verification_status": status,
        "structure": structural,
        "size_bytes": len(data),
        "producer": record.producer,
        "artifact_type": record.artifact_type,
        "truth": {
            "file_created_is_not_validation": True,
            "reopened_and_validated": True,
            "unverified_is_not_passed": status != "validated",
        },
    }


def validate_artifact_bytes(
    data: bytes,
    *,
    artifact_type: str,
    filename: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate structure/content of generated documents/spreadsheets/etc."""
    name = filename.lower()
    meta = metadata or {}
    checks: list[dict[str, Any]] = []

    def add(name_: str, ok: bool, detail: str) -> None:
        checks.append({"check": name_, "ok": ok, "detail": detail})

    if name.endswith(".json") or artifact_type in {"json", "structured_json"}:
        try:
            parsed = json.loads(data.decode("utf-8"))
            add("json_parse", True, type(parsed).__name__)
            if isinstance(parsed, dict) and meta.get("required_keys"):
                missing = [k for k in meta["required_keys"] if k not in parsed]
                add("required_keys", not missing, f"missing={missing}")
        except Exception as exc:  # noqa: BLE001
            add("json_parse", False, str(exc))
    elif name.endswith(".csv") or artifact_type in {"csv", "spreadsheet", "table"}:
        try:
            text = data.decode("utf-8")
            rows = list(csv.reader(io.StringIO(text)))
            add("csv_parse", True, f"rows={len(rows)}")
            add("non_empty", len(rows) > 0, f"rows={len(rows)}")
            if rows:
                add("has_header_or_data", len(rows[0]) > 0, f"cols={len(rows[0])}")
        except Exception as exc:  # noqa: BLE001
            add("csv_parse", False, str(exc))
    elif name.endswith((".html", ".htm")) or artifact_type in {"html", "document", "presentation"}:
        text = data.decode("utf-8", errors="replace")
        add("has_html_tag", "<" in text and ">" in text, "markup present")
        if meta.get("must_contain"):
            needle = str(meta["must_contain"])
            add("must_contain", needle in text, needle)
    elif name.endswith(".md") or artifact_type == "markdown":
        text = data.decode("utf-8", errors="replace")
        add("non_empty", bool(text.strip()), f"chars={len(text)}")
    elif name.endswith(".svg") or artifact_type in {"browser_screenshot", "image_svg"}:
        text = data.decode("utf-8", errors="replace")
        add("svg_root", "<svg" in text.lower(), "svg")
    elif name.endswith(".xlsx") or artifact_type == "spreadsheet_xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            add("xlsx_zip", True, f"entries={len(names)}")
            add("has_workbook", any("workbook" in n for n in names), "workbook.xml")
        except Exception as exc:  # noqa: BLE001
            add("xlsx_zip", False, str(exc))
    elif name.endswith(".pdf") or artifact_type == "pdf":
        add("pdf_header", data[:5] == b"%PDF-", "header")
    else:
        add("bytes_present", len(data) > 0, f"size={len(data)}")
        add("type_specific_unmeasured", True, "no structural validator for this type")

    ok = all(c["ok"] for c in checks) if checks else False
    return {
        "ok": ok,
        "checks": checks,
        "truth": {"structure_and_content_validated": ok},
    }


def validate_record(record: ArtifactRecord) -> dict[str, Any]:
    data = Path(record.path).read_bytes()
    return validate_artifact_bytes(
        data,
        artifact_type=record.artifact_type,
        filename=Path(record.path).name,
        metadata=record.metadata,
    )
