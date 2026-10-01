"""Canonical server-side ingestion format capability matrix."""

from __future__ import annotations

from typing import Any

from Data.modules.documents.ocr_backend import probe_document_ai_readiness

from .archives.rar_safe import probe_rar_tool
from .settings import SourceIngestionSettings


def build_format_capabilities(settings: SourceIngestionSettings | None = None) -> dict[str, Any]:
    cfg = settings or SourceIngestionSettings()
    ocr = probe_document_ai_readiness()
    pdf_ocr = {
        "supported": ocr.state.value == "AVAILABLE",
        "readiness": ocr.public_dict(),
    }
    rar_probe = probe_rar_tool()
    rar_enabled = bool(cfg.allow_rar)
    rar_ready = rar_enabled and bool(rar_probe.get("available"))
    if not rar_enabled:
        rar_reason = "RAR disabled for this deployment"
    elif not rar_probe.get("available"):
        rar_reason = str(rar_probe.get("reason") or "RAR extraction backend missing")
    else:
        rar_reason = None
    return {
        "formats": {
            ".txt": {"supported": True, "kind": "plain_text"},
            ".md": {"supported": True, "kind": "plain_text"},
            ".pdf": {"supported": True, "kind": "document", "ocr": pdf_ocr},
            ".docx": {"supported": True, "kind": "office"},
            ".xlsx": {"supported": True, "kind": "office"},
            ".pptx": {"supported": True, "kind": "office"},
            ".zip": {"supported": True, "kind": "archive"},
            ".tar": {"supported": True, "kind": "archive"},
            ".gz": {"supported": True, "kind": "archive"},
            ".7z": {
                "supported": bool(cfg.allow_7z),
                "intentionally_unsupported": not cfg.allow_7z,
                "reason": "7z disabled for this build" if not cfg.allow_7z else None,
            },
            ".rar": {
                "supported": rar_ready,
                "enabled": rar_enabled,
                "intentionally_unsupported": not rar_enabled,
                "reason": rar_reason,
                "tool": rar_probe.get("tool"),
                "kind": "archive",
            },
            ".png": {"supported": True, "kind": "image", "ocr": pdf_ocr},
            ".jpg": {"supported": True, "kind": "image", "ocr": pdf_ocr},
            ".jpeg": {"supported": True, "kind": "image", "ocr": pdf_ocr},
            ".tif": {"supported": True, "kind": "image", "ocr": pdf_ocr},
            ".tiff": {"supported": True, "kind": "image", "ocr": pdf_ocr},
            ".parquet": {"supported": True, "kind": "dataset_route"},
            ".jsonl": {"supported": True, "kind": "dataset_or_structured"},
            ".ndjson": {"supported": True, "kind": "dataset_or_structured"},
        },
        "ocr_readiness": ocr.public_dict(),
        "archive": {
            "max_member_count": cfg.max_member_count,
            "max_member_bytes": cfg.max_member_bytes,
            "max_total_uncompressed_bytes": cfg.max_total_uncompressed_bytes,
            "max_nested_archive_depth": cfg.max_nested_archive_depth,
            "rar": rar_probe,
        },
    }
