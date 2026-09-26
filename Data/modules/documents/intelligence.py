"""Document / multimodal intelligence helpers (W20) — extend documents + context owners.

Vision support must be measured/declared honestly. Text-only models do not become visual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisionCapabilityReport:
    model_id: str
    vision: str  # MEASURED | UNSUPPORTED | UNAVAILABLE | NOT_CONFIGURED | UNMEASURED
    detail: str = ""
    provenance: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "vision": self.vision,
            "detail": self.detail,
            "provenance": self.provenance,
            "truth": {
                "text_only_is_not_visual": self.vision in {"UNSUPPORTED", "UNAVAILABLE", "NOT_CONFIGURED"},
                "unmeasured_is_not_supported": self.vision == "UNMEASURED",
            },
        }


def declare_vision_capability(
    *,
    model_id: str,
    supports_vision: bool | None,
    probed: bool = False,
    detail: str = "",
) -> VisionCapabilityReport:
    if supports_vision is True and probed:
        status = "MEASURED"
    elif supports_vision is False and probed:
        status = "UNSUPPORTED"
    elif supports_vision is False:
        status = "UNSUPPORTED"
    elif not probed:
        status = "UNMEASURED"
    else:
        status = "UNMEASURED"
    return VisionCapabilityReport(
        model_id=model_id,
        vision=status,
        detail=detail or ("vision declared" if supports_vision else "no vision"),
        provenance="capability_probe" if probed else "unprobed_declaration",
    )


@dataclass
class DocumentStructure:
    """Extraction structure with page/section/table/figure refs for Knowledge ingest."""

    source_path: str
    pages: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    ocr_confidence: float | None = None
    ocr_status: str = "UNMEASURED"
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "pages": list(self.pages),
            "tables": list(self.tables),
            "figures": list(self.figures),
            "ocr_confidence": self.ocr_confidence,
            "ocr_status": self.ocr_status,
            "text_chars": len(self.text),
            "metadata": dict(self.metadata),
            "truth": {
                "retains_source_refs": True,
                "ocr_confidence_labelled": True,
                "not_independent_multimodal_runtime": True,
            },
        }


def structure_from_extraction(
    *,
    source_path: str,
    text: str,
    pages: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
    figures: list[dict[str, Any]] | None = None,
    ocr_confidence: float | None = None,
) -> DocumentStructure:
    ocr_status = "UNMEASURED"
    if ocr_confidence is not None:
        ocr_status = "MEASURED" if 0.0 <= float(ocr_confidence) <= 1.0 else "UNMEASURED"
    return DocumentStructure(
        source_path=source_path,
        pages=list(pages or []),
        tables=list(tables or []),
        figures=list(figures or []),
        ocr_confidence=ocr_confidence,
        ocr_status=ocr_status,
        text=text or "",
    )


def multimodal_eval_families() -> list[dict[str, Any]]:
    return [
        {"family": "chart_comprehension", "status": "FEATURE_GATED"},
        {"family": "document_qa", "status": "FEATURE_GATED"},
        {"family": "table_qa", "status": "FEATURE_GATED"},
        {"family": "screenshot_ui_understanding", "status": "FEATURE_GATED"},
        {"family": "source_page_grounding", "status": "FEATURE_GATED"},
    ]
