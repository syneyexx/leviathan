"""Documents module — structured extraction with provenance."""

from .extraction import (
    DocumentExtraction,
    ExtractedValue,
    ProvenanceSpan,
    extract_document,
    validate_numeric_values,
)

__all__ = [
    "DocumentExtraction",
    "ExtractedValue",
    "ProvenanceSpan",
    "extract_document",
    "validate_numeric_values",
]
