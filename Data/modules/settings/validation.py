"""Validation helpers for Settings Control Plane mutations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .catalog import CATALOG_BY_KEY
from .types import SettingDefinition, SettingType, SettingsError

_SAFE_COMMAND = re.compile(r"^[A-Za-z0-9._\\/-]+$")


def coerce_value(definition: SettingDefinition, raw: Any) -> Any:
    """Coerce and validate a single setting value."""
    if definition.value_type == SettingType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise SettingsError("INVALID_TYPE", f"{definition.key} expects a boolean", http_status=422)

    if definition.value_type == SettingType.INTEGER:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsError(
                "INVALID_TYPE", f"{definition.key} expects an integer", http_status=422
            ) from exc
        _check_bounds(definition, value)
        return value

    if definition.value_type == SettingType.FLOAT:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsError(
                "INVALID_TYPE", f"{definition.key} expects a number", http_status=422
            ) from exc
        _check_bounds(definition, value)
        return value

    if definition.value_type == SettingType.STRING_LIST:
        if isinstance(raw, str):
            items = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, (list, tuple)):
            items = [str(part).strip() for part in raw if str(part).strip()]
        else:
            raise SettingsError(
                "INVALID_TYPE",
                f"{definition.key} expects a comma-separated string or list",
                http_status=422,
            )
        if definition.key == "coding.command_allowlist":
            for item in items:
                if not _SAFE_COMMAND.match(item) or " " in item or ".." in item:
                    raise SettingsError(
                        "INVALID_ALLOWLIST",
                        f"Unsafe command allowlist entry: {item!r}",
                        http_status=422,
                    )
        return tuple(items)

    if definition.value_type == SettingType.ENUM:
        text = None if raw is None else str(raw).strip()
        if text == "":
            text = None
        if text is None and None not in definition.enum_values and "" not in definition.enum_values:
            # allow empty optional enums only when default is None
            if definition.default is None:
                return None
        if text not in definition.enum_values:
            raise SettingsError(
                "INVALID_ENUM",
                f"{definition.key} must be one of {list(definition.enum_values)}",
                http_status=422,
            )
        return text

    if definition.value_type in {SettingType.STRING, SettingType.PATH, SettingType.SECRET, SettingType.URL}:
        if raw is None:
            return None if definition.default is None else ""
        text = str(raw).strip()
        if definition.value_type == SettingType.URL and text:
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise SettingsError(
                    "INVALID_URL",
                    f"{definition.key} must be an http(s) URL",
                    http_status=422,
                )
        if definition.value_type == SettingType.PATH and text:
            # Reject null bytes; allow Windows drive letters.
            if "\x00" in text:
                raise SettingsError("INVALID_PATH", f"{definition.key} contains NUL", http_status=422)
            # Soft normalization for relative paths — absolute resolution is config-owned.
            _ = Path(text)
        if definition.value_type != SettingType.SECRET and text == "" and definition.default is None:
            return None
        return text

    raise SettingsError("INVALID_TYPE", f"Unsupported type for {definition.key}", http_status=422)


def _check_bounds(definition: SettingDefinition, value: float | int) -> None:
    if definition.min_value is not None and value < definition.min_value:
        raise SettingsError(
            "OUT_OF_RANGE",
            f"{definition.key} must be >= {definition.min_value}",
            http_status=422,
        )
    if definition.max_value is not None and value > definition.max_value:
        raise SettingsError(
            "OUT_OF_RANGE",
            f"{definition.key} must be <= {definition.max_value}",
            http_status=422,
        )


def validate_feature_hierarchy(desired: dict[str, Any]) -> None:
    """Enforce parent/child feature invariants against a desired map of catalog values."""

    def flag(key: str) -> bool:
        return bool(desired.get(key, CATALOG_BY_KEY[key].default if key in CATALOG_BY_KEY else False))

    checks = [
        ("features.chat_sse", ("features.chat_streaming",)),
        ("features.module_manager_subprocess", ("features.module_manager_enabled",)),
        ("features.coding_enabled", ("features.agents_enabled",)),
        ("features.mcp_stdio", ("features.mcp_enabled",)),
        ("features.mcp_http", ("features.mcp_enabled",)),
        ("features.mcp_auto_expand_modules", ("features.mcp_enabled",)),
        ("features.deep_recall", ("features.rag_v3",)),
        ("features.why_library", ("features.rag_v3",)),
        ("features.cognition_shadow", ("features.cognition_enabled",)),
        ("features.cognition_iterative_loop", ("features.cognition_enabled",)),
        ("features.cognition_belief_state", ("features.cognition_enabled",)),
        ("features.cognition_neuro", ("features.cognition_enabled", "features.neuro_enabled")),
        ("features.cognition_adaptive_depth", ("features.cognition_enabled",)),
        ("features.cognition_delegation", ("features.cognition_enabled",)),
        ("features.cognition_experience_learning", ("features.cognition_enabled",)),
        ("features.neuro_associative_memory", ("features.neuro_enabled",)),
        ("features.neuro_process_critic", ("features.neuro_enabled",)),
        ("features.neuro_residual_injection", ("features.neuro_enabled",)),
        ("features.neuro_cortex", ("features.neuro_enabled",)),
        ("features.neuro_memory_tiers", ("features.neuro_enabled",)),
        ("features.neuro_residual_orchestrator", ("features.neuro_enabled",)),
        ("features.neuro_cortex_blocks", ("features.neuro_enabled", "features.neuro_cortex")),
        ("features.neuro_contrastive_training", ("features.neuro_enabled",)),
        ("features.neuro_soak_long", ("features.neuro_enabled",)),
        ("features.neuro_training_real_worker", ("features.neuro_enabled",)),
        ("features.residual_production", ("features.neuro_enabled", "features.neuro_residual_injection")),
    ]
    for child, parents in checks:
        if not flag(child):
            continue
        for parent in parents:
            if not flag(parent):
                raise SettingsError(
                    "FEATURE_DEPENDENCY",
                    f"{child} requires {parent}=true",
                    http_status=422,
                )

    if flag("features.mcp_enabled") and not flag("features.mcp_stdio") and not flag("features.mcp_http"):
        raise SettingsError(
            "FEATURE_DEPENDENCY",
            "features.mcp_enabled requires mcp_stdio and/or mcp_http",
            http_status=422,
        )

    chunk_max = desired.get("knowledge.chunk_max_chars")
    chunk_overlap = desired.get("knowledge.chunk_overlap")
    if chunk_max is not None and chunk_overlap is not None:
        if int(chunk_overlap) >= int(chunk_max):
            raise SettingsError(
                "INVALID_RANGE",
                "knowledge.chunk_overlap must be < knowledge.chunk_max_chars",
                http_status=422,
            )

    rerank_candidates = desired.get("knowledge.rerank_candidate_count")
    rerank_final = desired.get("knowledge.rerank_final_count")
    if rerank_candidates is not None and rerank_final is not None:
        if int(rerank_final) > int(rerank_candidates):
            raise SettingsError(
                "INVALID_RANGE",
                "knowledge.rerank_final_count must be <= knowledge.rerank_candidate_count",
                http_status=422,
            )

    if flag("chaos.enabled") and desired.get("runtime.loopback_only") is False:
        raise SettingsError(
            "SECURITY_POLICY",
            "chaos.enabled is refused when runtime.loopback_only is false",
            http_status=403,
        )
