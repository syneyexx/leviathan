"""Typed contracts for dataset semantic profiling and catalog enrichment.

Stage 2 Dataset Intelligence — schema contracts only (no I/O).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


SEMANTIC_SCHEMA_VERSION = 1
GENERATOR_VERSION = "1.0.0"

MAX_DISPLAY_NAME_LEN = 160
MAX_SUMMARY_LEN = 2000
MAX_TAGS = 32
MAX_TAG_LEN = 64
MAX_SUBJECTS = 32
MAX_SUBJECT_LEN = 128
MAX_EVIDENCE_LEN = 4000
MAX_CATEGORY_PATH = 8
MAX_CATEGORY_PATH_SEG_LEN = 64

_CONTROL_CHAR_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DisplayNameSource(str, Enum):
    OPERATOR = "OPERATOR"
    SEMANTIC_MODEL = "SEMANTIC_MODEL"
    DETERMINISTIC = "DETERMINISTIC"
    SOURCE_METADATA = "SOURCE_METADATA"
    SOURCE_FILENAME = "SOURCE_FILENAME"
    FALLBACK = "FALLBACK"


class DatasetCategory(str, Enum):
    ANIMALS_BIOLOGY = "ANIMALS_BIOLOGY"
    FINANCE_TRADING = "FINANCE_TRADING"
    CRYPTO_BLOCKCHAIN = "CRYPTO_BLOCKCHAIN"
    BUSINESS_ECONOMICS = "BUSINESS_ECONOMICS"
    SCIENCE_ENGINEERING = "SCIENCE_ENGINEERING"
    TECHNOLOGY_SOFTWARE = "TECHNOLOGY_SOFTWARE"
    RESEARCH_PUBLICATIONS = "RESEARCH_PUBLICATIONS"
    HEALTH_MEDICINE = "HEALTH_MEDICINE"
    LAW_REGULATION = "LAW_REGULATION"
    HISTORY_CULTURE = "HISTORY_CULTURE"
    GEOGRAPHY_ENVIRONMENT = "GEOGRAPHY_ENVIRONMENT"
    EDUCATION_LANGUAGE = "EDUCATION_LANGUAGE"
    NEWS_MEDIA = "NEWS_MEDIA"
    GENERAL = "GENERAL"
    OTHER = "OTHER"
    UNCATEGORIZED = "UNCATEGORIZED"


CATEGORY_LABELS: dict[DatasetCategory, dict[str, str]] = {
    DatasetCategory.ANIMALS_BIOLOGY: {
        "en": "Animals & Biology",
        "nl": "Dieren & Biologie",
    },
    DatasetCategory.FINANCE_TRADING: {
        "en": "Finance & Trading",
        "nl": "Financiën & Trading",
    },
    DatasetCategory.CRYPTO_BLOCKCHAIN: {
        "en": "Crypto & Blockchain",
        "nl": "Crypto & Blockchain",
    },
    DatasetCategory.BUSINESS_ECONOMICS: {
        "en": "Business & Economics",
        "nl": "Business & Economie",
    },
    DatasetCategory.SCIENCE_ENGINEERING: {
        "en": "Science & Engineering",
        "nl": "Wetenschap & Techniek",
    },
    DatasetCategory.TECHNOLOGY_SOFTWARE: {
        "en": "Technology & Software",
        "nl": "Technologie & Software",
    },
    DatasetCategory.RESEARCH_PUBLICATIONS: {
        "en": "Research & Publications",
        "nl": "Onderzoek & Publicaties",
    },
    DatasetCategory.HEALTH_MEDICINE: {
        "en": "Health & Medicine",
        "nl": "Gezondheid & Geneeskunde",
    },
    DatasetCategory.LAW_REGULATION: {
        "en": "Law & Regulation",
        "nl": "Recht & Regulering",
    },
    DatasetCategory.HISTORY_CULTURE: {
        "en": "History & Culture",
        "nl": "Geschiedenis & Cultuur",
    },
    DatasetCategory.GEOGRAPHY_ENVIRONMENT: {
        "en": "Geography & Environment",
        "nl": "Geografie & Milieu",
    },
    DatasetCategory.EDUCATION_LANGUAGE: {
        "en": "Education & Language",
        "nl": "Onderwijs & Taal",
    },
    DatasetCategory.NEWS_MEDIA: {
        "en": "News & Media",
        "nl": "Nieuws & Media",
    },
    DatasetCategory.GENERAL: {
        "en": "General",
        "nl": "Algemeen",
    },
    DatasetCategory.OTHER: {
        "en": "Other",
        "nl": "Overig",
    },
    DatasetCategory.UNCATEGORIZED: {
        "en": "Uncategorized",
        "nl": "Ongecategoriseerd",
    },
}

ALLOWED_CATEGORIES = frozenset(c.value for c in DatasetCategory)


class SemanticValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "semantic_invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sanitize_utf8_text(value: Any, *, field_name: str, max_len: int | None = None) -> str:
    """Normalize to UTF-8 text and strip control characters (except newline/tab)."""
    if value is None:
        text = ""
    elif isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHAR_RX.sub("", text)
    text = text.strip()
    if max_len is not None and len(text) > max_len:
        raise SemanticValidationError(
            f"{field_name} exceeds max length {max_len}",
            code="semantic_field_too_long",
        )
    return text


def validate_display_name(name: str) -> str:
    text = sanitize_utf8_text(name, field_name="display_name", max_len=MAX_DISPLAY_NAME_LEN)
    if not text:
        raise SemanticValidationError("display_name is required", code="semantic_display_name")
    return text


def validate_category(value: Any, *, field_name: str = "category") -> DatasetCategory:
    raw = sanitize_utf8_text(value, field_name=field_name, max_len=64).upper().replace(" ", "_")
    if raw not in ALLOWED_CATEGORIES:
        raise SemanticValidationError(
            f"invalid {field_name}: {value!r}",
            code="semantic_category",
        )
    return DatasetCategory(raw)


def validate_optional_category(value: Any, *, field_name: str = "secondary_category") -> DatasetCategory | None:
    if value is None or value == "":
        return None
    return validate_category(value, field_name=field_name)


def validate_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError) as exc:
        raise SemanticValidationError("confidence must be a number", code="semantic_confidence") from exc
    if conf < 0.0 or conf > 1.0:
        raise SemanticValidationError("confidence must be in [0, 1]", code="semantic_confidence")
    return conf


def validate_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, (list, tuple)):
        raise SemanticValidationError("tags must be a list", code="semantic_tags")
    if len(tags) > MAX_TAGS:
        raise SemanticValidationError(f"tags exceed max count {MAX_TAGS}", code="semantic_tags")
    out: list[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = sanitize_utf8_text(item, field_name="tag", max_len=MAX_TAG_LEN)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def validate_subjects(subjects: Any) -> list[str]:
    if subjects is None:
        return []
    if not isinstance(subjects, (list, tuple)):
        raise SemanticValidationError("subjects must be a list", code="semantic_subjects")
    if len(subjects) > MAX_SUBJECTS:
        raise SemanticValidationError(
            f"subjects exceed max count {MAX_SUBJECTS}",
            code="semantic_subjects",
        )
    out: list[str] = []
    for item in subjects:
        subj = sanitize_utf8_text(item, field_name="subject", max_len=MAX_SUBJECT_LEN)
        if subj:
            out.append(subj)
    return out


def validate_category_path(path: Any) -> list[str]:
    if path is None:
        return []
    if not isinstance(path, (list, tuple)):
        raise SemanticValidationError("category_path must be a list", code="semantic_category_path")
    if len(path) > MAX_CATEGORY_PATH:
        raise SemanticValidationError(
            f"category_path exceeds max segments {MAX_CATEGORY_PATH}",
            code="semantic_category_path",
        )
    out: list[str] = []
    for seg in path:
        text = sanitize_utf8_text(seg, field_name="category_path", max_len=MAX_CATEGORY_PATH_SEG_LEN)
        if text:
            out.append(text.upper().replace(" ", "_"))
    return out


def _parse_display_name_source(value: Any) -> DisplayNameSource:
    raw = sanitize_utf8_text(value or DisplayNameSource.FALLBACK.value, field_name="display_name_source")
    try:
        return DisplayNameSource(raw.upper())
    except ValueError as exc:
        raise SemanticValidationError(
            f"invalid display_name_source: {value!r}",
            code="semantic_display_name_source",
        ) from exc


@dataclass
class DatasetSemanticProfile:
    """Governed semantic enrichment profile for a dataset version."""

    display_name: str
    display_name_source: DisplayNameSource
    primary_category: DatasetCategory
    schema_version: int = SEMANTIC_SCHEMA_VERSION
    summary: str = ""
    secondary_category: DatasetCategory | None = None
    category_path: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    language: str | None = None
    confidence: float = 0.0
    review_required: bool = False
    classification_method: str = "DETERMINISTIC"
    evidence_summary: str = ""
    source_dataset_id: str | None = None
    source_version_id: str | None = None
    source_content_hash: str | None = None
    generated_at: str | None = None
    generator_version: str = GENERATOR_VERSION
    model_status: str = "NOT_REQUESTED"
    model_provenance: dict[str, Any] = field(default_factory=dict)
    operator_overrides: dict[str, Any] = field(default_factory=dict)
    truth: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if int(self.schema_version) != SEMANTIC_SCHEMA_VERSION:
            raise SemanticValidationError(
                f"unsupported semantic schema_version={self.schema_version}",
                code="semantic_schema",
            )
        self.display_name = validate_display_name(self.display_name)
        if isinstance(self.display_name_source, DisplayNameSource):
            pass
        else:
            self.display_name_source = _parse_display_name_source(self.display_name_source)
        if isinstance(self.primary_category, DatasetCategory):
            pass
        else:
            self.primary_category = validate_category(self.primary_category, field_name="primary_category")
        if self.secondary_category is not None and not isinstance(self.secondary_category, DatasetCategory):
            self.secondary_category = validate_optional_category(self.secondary_category)
        elif isinstance(self.secondary_category, DatasetCategory):
            pass
        self.summary = sanitize_utf8_text(self.summary, field_name="summary", max_len=MAX_SUMMARY_LEN)
        self.category_path = validate_category_path(self.category_path)
        self.tags = validate_tags(self.tags)
        self.subjects = validate_subjects(self.subjects)
        self.confidence = validate_confidence(self.confidence)
        self.evidence_summary = sanitize_utf8_text(
            self.evidence_summary,
            field_name="evidence_summary",
            max_len=MAX_EVIDENCE_LEN,
        )
        if self.language is not None:
            lang = sanitize_utf8_text(self.language, field_name="language", max_len=32)
            self.language = lang or None
        if not isinstance(self.model_provenance, dict):
            raise SemanticValidationError("model_provenance must be an object", code="semantic_provenance")
        if not isinstance(self.operator_overrides, dict):
            raise SemanticValidationError("operator_overrides must be an object", code="semantic_overrides")
        if not isinstance(self.truth, dict):
            raise SemanticValidationError("truth must be an object", code="semantic_truth")
        # Never store chain-of-thought blobs.
        for banned in ("chain_of_thought", "chainOfThought", "reasoning_trace", "reasoningTrace"):
            self.model_provenance.pop(banned, None)
            self.truth.pop(banned, None)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schemaVersion": int(self.schema_version),
            "displayName": self.display_name,
            "displayNameSource": self.display_name_source.value,
            "summary": self.summary,
            "primaryCategory": self.primary_category.value,
            "secondaryCategory": self.secondary_category.value if self.secondary_category else None,
            "categoryPath": list(self.category_path),
            "tags": list(self.tags),
            "subjects": list(self.subjects),
            "language": self.language,
            "confidence": float(self.confidence),
            "reviewRequired": bool(self.review_required),
            "classificationMethod": str(self.classification_method),
            "evidenceSummary": self.evidence_summary,
            "sourceDatasetId": self.source_dataset_id,
            "sourceVersionId": self.source_version_id,
            "sourceContentHash": self.source_content_hash,
            "generatedAt": self.generated_at or _utc_now_iso(),
            "generatorVersion": self.generator_version or GENERATOR_VERSION,
            "modelStatus": str(self.model_status),
            "modelProvenance": dict(self.model_provenance),
            "operatorOverrides": dict(self.operator_overrides),
            "truth": {
                "semanticProfileIsDerived": True,
                "datasetStoreIsCanonical": True,
                "tradingClassificationIsRoutingAuthority": True,
                "modelAssistedIsAdvisory": True,
                "operatorOverridesWin": True,
                "noChainOfThoughtStored": True,
                **dict(self.truth),
            },
        }

    def public_dict(self) -> dict[str, Any]:
        """API-safe view (same contract as to_dict; no secrets/embeddings)."""
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DatasetSemanticProfile":
        if not isinstance(data, dict):
            raise SemanticValidationError("semantic profile must be an object", code="semantic_invalid")
        primary = data.get("primaryCategory") or data.get("primary_category")
        secondary = data.get("secondaryCategory") if "secondaryCategory" in data else data.get("secondary_category")
        source = data.get("displayNameSource") or data.get("display_name_source")
        return cls(
            schema_version=int(data.get("schemaVersion") or data.get("schema_version") or SEMANTIC_SCHEMA_VERSION),
            display_name=str(data.get("displayName") or data.get("display_name") or ""),
            display_name_source=_parse_display_name_source(source),
            summary=str(data.get("summary") or ""),
            primary_category=validate_category(primary, field_name="primary_category"),
            secondary_category=validate_optional_category(secondary),
            category_path=list(data.get("categoryPath") or data.get("category_path") or []),
            tags=list(data.get("tags") or []),
            subjects=list(data.get("subjects") or []),
            language=data.get("language"),
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 0.0),
            review_required=bool(data.get("reviewRequired") if "reviewRequired" in data else data.get("review_required")),
            classification_method=str(
                data.get("classificationMethod") or data.get("classification_method") or "DETERMINISTIC"
            ),
            evidence_summary=str(data.get("evidenceSummary") or data.get("evidence_summary") or ""),
            source_dataset_id=_opt_str(data.get("sourceDatasetId") or data.get("source_dataset_id")),
            source_version_id=_opt_str(data.get("sourceVersionId") or data.get("source_version_id")),
            source_content_hash=_opt_str(data.get("sourceContentHash") or data.get("source_content_hash")),
            generated_at=_opt_str(data.get("generatedAt") or data.get("generated_at")),
            generator_version=str(data.get("generatorVersion") or data.get("generator_version") or GENERATOR_VERSION),
            model_status=str(data.get("modelStatus") or data.get("model_status") or "NOT_REQUESTED"),
            model_provenance=dict(data.get("modelProvenance") or data.get("model_provenance") or {})
            if isinstance(data.get("modelProvenance") or data.get("model_provenance") or {}, dict)
            else {},
            operator_overrides=dict(data.get("operatorOverrides") or data.get("operator_overrides") or {})
            if isinstance(data.get("operatorOverrides") or data.get("operator_overrides") or {}, dict)
            else {},
            truth=dict(data.get("truth") or {}) if isinstance(data.get("truth"), dict) else {},
        )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def category_label(category: DatasetCategory | str, *, lang: str = "en") -> str:
    cat = category if isinstance(category, DatasetCategory) else validate_category(category)
    labels = CATEGORY_LABELS.get(cat) or {}
    return str(labels.get(lang) or labels.get("en") or cat.value)
