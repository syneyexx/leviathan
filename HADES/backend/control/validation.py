"""Typed validation and unlimited handling for control-plane settings."""

from __future__ import annotations

from typing import Any

from .types import SettingDefinition, SettingType


class SettingValidationError(ValueError):
    def __init__(self, setting_id: str, message: str) -> None:
        self.setting_id = setting_id
        super().__init__(f"{setting_id}: {message}")


def is_unlimited(value: Any) -> bool:
    return value is None


def validate_value(definition: SettingDefinition, value: Any) -> Any:
    """Validate and coerce a setting value. ``None`` means unlimited when allowed."""
    sid = definition.id

    if value is None:
        if definition.allow_unlimited or definition.type == SettingType.NULLABLE_INTEGER:
            return None
        if definition.type in {SettingType.STRING, SettingType.OBJECT, SettingType.STRING_LIST}:
            # empty defaults handled below
            pass
        else:
            raise SettingValidationError(sid, "null/unlimited is not allowed for this setting")

    st = definition.type

    if st in {SettingType.INTEGER, SettingType.NULLABLE_INTEGER, SettingType.DURATION_SECONDS, SettingType.BYTES, SettingType.TOKENS}:
        if value is None:
            return None
        if isinstance(value, bool):
            raise SettingValidationError(sid, "boolean is not a valid integer")
        if isinstance(value, float):
            if value != value or value in {float("inf"), float("-inf")}:
                raise SettingValidationError(sid, "non-finite float is not a valid integer")
            if not value.is_integer():
                raise SettingValidationError(sid, f"expected whole integer, got {value!r}")
        if isinstance(value, str) and ("." in value or "e" in value.lower()):
            try:
                as_float = float(value)
            except ValueError:
                as_float = None
            if as_float is not None and not as_float.is_integer():
                raise SettingValidationError(sid, f"expected whole integer, got {value!r}")
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise SettingValidationError(sid, f"expected integer, got {value!r}") from exc
        if definition.min is not None and coerced < definition.min:
            raise SettingValidationError(sid, f"must be >= {definition.min}")
        # Soft max: only enforce when overrideable is False; otherwise treat as guidance.
        if definition.max is not None and not definition.overrideable and coerced > definition.max:
            raise SettingValidationError(sid, f"must be <= {definition.max}")
        if definition.max is not None and definition.overrideable and coerced > definition.max:
            # Still allow but do not reject — caller may warn. Enforce only hard safety floors.
            pass
        return coerced

    if st == SettingType.FLOAT:
        try:
            coerced_f = float(value)
        except (TypeError, ValueError) as exc:
            raise SettingValidationError(sid, f"expected float, got {value!r}") from exc
        if coerced_f != coerced_f or coerced_f in {float("inf"), float("-inf")}:
            raise SettingValidationError(sid, "non-finite float is not allowed")
        if definition.min is not None and coerced_f < definition.min:
            raise SettingValidationError(sid, f"must be >= {definition.min}")
        if definition.max is not None and coerced_f > definition.max:
            raise SettingValidationError(sid, f"must be <= {definition.max}")
        return coerced_f

    if st == SettingType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false", "1", "0", "yes", "no"}:
            return value.lower() in {"true", "1", "yes"}
        raise SettingValidationError(sid, f"expected boolean, got {value!r}")

    if st == SettingType.ENUM:
        text = str(value)
        if definition.enum_values and text not in definition.enum_values:
            mapped = None
            if definition.storage_key == "reasoning_profile":
                try:
                    from reasoning.mode_policy import try_canonicalize_enum

                    mapped = try_canonicalize_enum(definition.storage_key, text)
                except Exception:
                    mapped = None
            if mapped and mapped in definition.enum_values:
                text = mapped
            else:
                raise SettingValidationError(sid, f"must be one of {definition.enum_values}")
        return text

    if st == SettingType.STRING:
        return str(value)

    if st == SettingType.STRING_LIST:
        if value is None:
            return []
        if not isinstance(value, list):
            raise SettingValidationError(sid, "expected string list")
        return [str(item) for item in value]

    if st == SettingType.OBJECT:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise SettingValidationError(sid, "expected object")
        return dict(value)

    raise SettingValidationError(sid, f"unsupported type {st}")



