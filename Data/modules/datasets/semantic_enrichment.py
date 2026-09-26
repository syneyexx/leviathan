"""Optional model-assisted semantic enrichment + job orchestration helpers.

Deterministic profiling always works. Model assistance is advisory and optional.
Chain-of-thought / reasoning traces are never persisted.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .semantic_engine import apply_operator_precedence, build_deterministic_profile
from .semantic_profiler import BoundedDatasetEvidence, BoundedDatasetProfiler, ProfilerLimits
from .semantic_types import (
    GENERATOR_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    DatasetCategory,
    DatasetSemanticProfile,
    DisplayNameSource,
    SemanticValidationError,
    sanitize_utf8_text,
    validate_category,
    validate_confidence,
    validate_display_name,
    validate_optional_category,
    validate_tags,
)


class ModelStatus:
    NOT_REQUESTED = "NOT_REQUESTED"
    UNAVAILABLE = "UNAVAILABLE"
    OK = "OK"
    FAILED = "FAILED"
    STUB = "STUB"


def build_idempotency_key(
    dataset_id: str,
    version_id: str | None,
    content_hash: str | None,
    schema_version: int = SEMANTIC_SCHEMA_VERSION,
    generator_version: str = GENERATOR_VERSION,
) -> str:
    """Stable key for enrich_metadata jobs / cache identity."""
    payload = "|".join(
        [
            str(dataset_id or "").strip(),
            str(version_id or "").strip(),
            str(content_hash or "").strip(),
            str(int(schema_version)),
            str(generator_version or "").strip(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"enrich_metadata:{digest}"


def merge_operator_overrides(
    profile: DatasetSemanticProfile | Mapping[str, Any],
    overrides: Mapping[str, Any] | None,
) -> DatasetSemanticProfile:
    """Apply operator overrides onto an existing or dict profile."""
    if isinstance(profile, DatasetSemanticProfile):
        base = profile
    else:
        base = DatasetSemanticProfile.from_dict(dict(profile))
    return apply_operator_precedence(base, overrides)


def validate_model_semantic_output(raw: Any) -> dict[str, Any]:
    """Strict structured validation of model-assisted semantic suggestions.

    Rejects free-form / tool-call / chain-of-thought payloads.
    """
    if not isinstance(raw, dict):
        raise SemanticValidationError("model output must be an object", code="model_output_type")
    banned = {
        "chain_of_thought",
        "chainOfThought",
        "reasoning",
        "reasoning_trace",
        "reasoningTrace",
        "tool_calls",
        "toolCalls",
        "function_call",
        "functionCall",
    }
    for key in banned:
        if key in raw:
            raise SemanticValidationError(
                f"model output must not include {key}",
                code="model_output_forbidden_field",
            )

    display_name = validate_display_name(raw.get("displayName") or raw.get("display_name") or "")
    primary = validate_category(
        raw.get("primaryCategory") or raw.get("primary_category"),
        field_name="primary_category",
    )
    secondary = validate_optional_category(
        raw.get("secondaryCategory") if "secondaryCategory" in raw else raw.get("secondary_category")
    )
    tags = validate_tags(raw.get("tags") or [])
    confidence = validate_confidence(raw.get("confidence") if raw.get("confidence") is not None else 0.5)
    summary = sanitize_utf8_text(raw.get("summary") or "", field_name="summary", max_len=2000)
    subjects_raw = raw.get("subjects") or []
    if subjects_raw is not None and not isinstance(subjects_raw, list):
        raise SemanticValidationError("subjects must be a list", code="model_subjects")
    subjects = [sanitize_utf8_text(s, field_name="subject", max_len=128) for s in list(subjects_raw)[:32]]
    subjects = [s for s in subjects if s]

    category_path = raw.get("categoryPath") or raw.get("category_path") or [primary.value]
    if not isinstance(category_path, list):
        raise SemanticValidationError("categoryPath must be a list", code="model_category_path")
    path = [sanitize_utf8_text(p, field_name="category_path", max_len=64).upper().replace(" ", "_") for p in category_path[:8]]
    path = [p for p in path if p]
    if not path:
        path = [primary.value]

    return {
        "displayName": display_name,
        "primaryCategory": primary.value,
        "secondaryCategory": secondary.value if secondary else None,
        "categoryPath": path,
        "tags": tags,
        "subjects": subjects,
        "summary": summary,
        "confidence": confidence,
        "reviewRequired": bool(raw.get("reviewRequired") if "reviewRequired" in raw else raw.get("review_required", False)),
    }


def apply_model_suggestion(
    base: DatasetSemanticProfile,
    model_raw: Any,
    *,
    model_status: str = ModelStatus.OK,
    model_provenance: Mapping[str, Any] | None = None,
) -> DatasetSemanticProfile:
    """Merge validated model suggestion without overriding OPERATOR fields."""
    suggestion = validate_model_semantic_output(model_raw)
    data = base.to_dict()
    overrides = dict(base.operator_overrides or {})

    # Never overwrite operator-owned fields.
    if data.get("displayNameSource") != DisplayNameSource.OPERATOR.value and "displayName" not in overrides:
        data["displayName"] = suggestion["displayName"]
        data["displayNameSource"] = DisplayNameSource.SEMANTIC_MODEL.value
    if "primaryCategory" not in overrides:
        data["primaryCategory"] = suggestion["primaryCategory"]
        data["categoryPath"] = suggestion["categoryPath"]
        data["secondaryCategory"] = suggestion["secondaryCategory"]
    if "tags" not in overrides:
        data["tags"] = suggestion["tags"]
    if "summary" not in overrides and suggestion.get("summary"):
        data["summary"] = suggestion["summary"]
    data["subjects"] = suggestion.get("subjects") or data.get("subjects") or []
    data["confidence"] = max(float(data.get("confidence") or 0), float(suggestion["confidence"]))
    data["reviewRequired"] = bool(suggestion.get("reviewRequired"))
    data["classificationMethod"] = "MODEL_ASSISTED"
    data["modelStatus"] = model_status
    prov = dict(model_provenance or {})
    for banned in ("chain_of_thought", "chainOfThought", "reasoning_trace", "reasoningTrace"):
        prov.pop(banned, None)
    data["modelProvenance"] = {
        **prov,
        "advisory": True,
        "validated": True,
    }
    # Re-apply operator locks.
    profile = DatasetSemanticProfile.from_dict(data)
    return apply_operator_precedence(profile, overrides)


class StubSemanticModel:
    """Deterministic fake model for tests — no network, no tools."""

    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self.response = dict(response or {})

    def suggest(self, evidence: BoundedDatasetEvidence) -> dict[str, Any]:
        if self.response:
            return dict(self.response)
        # Minimal structured suggestion derived from evidence (still advisory).
        name = evidence.filename or evidence.dataset_id
        return {
            "displayName": str(name)[:160],
            "primaryCategory": DatasetCategory.GENERAL.value,
            "secondaryCategory": None,
            "categoryPath": [DatasetCategory.GENERAL.value],
            "tags": ["stub"],
            "subjects": [],
            "summary": "Stub model suggestion",
            "confidence": 0.4,
            "reviewRequired": True,
        }


def enrich_from_evidence(
    evidence: BoundedDatasetEvidence,
    *,
    model: Any | None = None,
    prefer_model: bool = False,
) -> DatasetSemanticProfile:
    """Run deterministic enrichment; optionally merge model suggestion."""
    profile = build_deterministic_profile(evidence)
    if model is None:
        if prefer_model:
            data = profile.to_dict()
            data["modelStatus"] = ModelStatus.UNAVAILABLE
            data["modelProvenance"] = {"reason": "model_unavailable", "advisory": True}
            return DatasetSemanticProfile.from_dict(data)
        return profile

    try:
        if hasattr(model, "suggest"):
            raw = model.suggest(evidence)
        elif callable(model):
            raw = model(evidence)
        else:
            raise TypeError("model must be callable or expose suggest()")
        status = ModelStatus.STUB if isinstance(model, StubSemanticModel) else ModelStatus.OK
        return apply_model_suggestion(
            profile,
            raw,
            model_status=status,
            model_provenance={"modelClass": type(model).__name__},
        )
    except Exception as exc:  # noqa: BLE001 — model is optional
        data = profile.to_dict()
        data["modelStatus"] = ModelStatus.FAILED if model is not None else ModelStatus.UNAVAILABLE
        data["modelProvenance"] = {
            "error": str(exc)[:500],
            "advisory": True,
        }
        return DatasetSemanticProfile.from_dict(data)


def run_deterministic_enrichment_job(
    *,
    profiler: BoundedDatasetProfiler | None = None,
    evidence: BoundedDatasetEvidence | None = None,
    profile_kwargs: Mapping[str, Any] | None = None,
) -> DatasetSemanticProfile:
    """Helper used by DatasetService enrich_metadata handler."""
    if evidence is None:
        if not profile_kwargs:
            raise SemanticValidationError("evidence or profile_kwargs required", code="enrich_missing_input")
        profiler = profiler or BoundedDatasetProfiler(ProfilerLimits())
        evidence = profiler.profile(**dict(profile_kwargs))
    return enrich_from_evidence(evidence, model=None, prefer_model=False)


def profile_to_metadata_patch(profile: DatasetSemanticProfile) -> dict[str, Any]:
    """Fields to merge into dataset.metadata without removing unrelated keys."""
    pub = profile.public_dict()
    return {
        "semanticProfile": pub,
        "displayName": pub["displayName"],
        "displayNameSource": pub["displayNameSource"],
        "primaryCategory": pub["primaryCategory"],
        "secondaryCategory": pub.get("secondaryCategory"),
        "semanticTags": list(pub.get("tags") or []),
        "semanticReviewRequired": bool(pub.get("reviewRequired")),
    }
