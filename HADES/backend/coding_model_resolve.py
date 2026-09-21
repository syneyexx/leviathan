"""Deterministic Coding model resolution.

Never silently substitute "local" unless that id exists in provider inventory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(slots=True)
class ResolvedCodingModel:
    model_id: str | None
    provider: str
    source: str
    usable: bool
    blocker: str | None = None
    inventory_checked: bool = False
    requested_model_id: str | None = None
    omniroute: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "source": self.source,
            "usable": self.usable,
            "blocker": self.blocker,
            "inventory_checked": self.inventory_checked,
            "requested_model_id": self.requested_model_id,
            "omniroute": self.omniroute,
            "details": dict(self.details),
        }


def _inventory_ids(inventory: Iterable[Any] | None) -> set[str]:
    ids: set[str] = set()
    for item in inventory or []:
        if isinstance(item, str):
            if item.strip():
                ids.add(item.strip())
            continue
        if isinstance(item, dict):
            for key in ("id", "model_id", "name"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    ids.add(val.strip())
                    break
    return ids


def resolve_coding_model(
    *,
    explicit_model_id: str | None = None,
    active_model_id: str | None = None,
    profile_model_id: str | None = None,
    inventory: Iterable[Any] | None = None,
    use_omniroute: bool = False,
    omniroute_usable: bool | None = None,
    allow_local_alias: bool = False,
) -> ResolvedCodingModel:
    """Resolve the model id that Coding must request.

    Priority (OmniRoute off):
      explicit → active → profile
    OmniRoute on: retain routing semantics; still record explicit preference.
    """
    requested = (explicit_model_id or "").strip() or None
    active = (active_model_id or "").strip() or None
    profile = (profile_model_id or "").strip() or None
    inv = _inventory_ids(inventory)
    inventory_checked = inventory is not None

    if use_omniroute:
        if omniroute_usable is False:
            # Fall through to local resolution when OmniRoute not usable.
            pass
        else:
            # OmniRoute owns routing; still pass through preferred model if any.
            preferred = requested or active or profile
            return ResolvedCodingModel(
                model_id=preferred,
                provider="omniroute",
                source="omniroute" if preferred is None else "omniroute+explicit",
                usable=True,
                inventory_checked=inventory_checked,
                requested_model_id=requested,
                omniroute=True,
                details={"preferred_model_id": preferred},
            )

    candidates = [
        ("explicit", requested),
        ("active", active),
        ("profile", profile),
    ]
    for source, mid in candidates:
        if not mid:
            continue
        if mid == "local" and not allow_local_alias:
            if inventory_checked and "local" not in inv:
                continue
            if not inventory_checked:
                # Without inventory, refuse opaque "local" alias — treat as missing.
                continue
        if inventory_checked and inv and mid not in inv:
            # Soft skip: try next candidate; record mismatch.
            continue
        return ResolvedCodingModel(
            model_id=mid,
            provider="lm_studio",
            source=source,
            usable=True,
            inventory_checked=inventory_checked,
            requested_model_id=requested,
            omniroute=False,
        )

    # If inventory empty/unavailable but we have an explicit non-"local" id, trust it.
    for source, mid in candidates:
        if mid and mid != "local":
            return ResolvedCodingModel(
                model_id=mid,
                provider="lm_studio",
                source=f"{source}_unverified",
                usable=True,
                inventory_checked=inventory_checked,
                requested_model_id=requested,
                omniroute=False,
                details={"inventory_empty_or_unavailable": True},
            )

    return ResolvedCodingModel(
        model_id=None,
        provider="lm_studio",
        source="none",
        usable=False,
        blocker="model_unavailable",
        inventory_checked=inventory_checked,
        requested_model_id=requested,
        omniroute=False,
    )


def resolve_coding_model_from_runtime(
    *,
    explicit_model_id: str | None = None,
    use_omniroute: bool = False,
    runtime_values: dict[str, Any] | None = None,
    list_models: Callable[[], Any] | None = None,
    active_profile: Callable[[], Any] | None = None,
) -> ResolvedCodingModel:
    """Backend helper: resolve using runtime settings / profile / LM inventory."""
    values = dict(runtime_values or {})
    active = None
    profile = None
    if callable(active_profile):
        try:
            prof = active_profile() or {}
            if isinstance(prof, dict):
                profile = prof.get("model_id")
                active = prof.get("model_id")
        except Exception:
            pass
    active = values.get("active_model") or values.get("model_id") or active
    inventory = None
    if callable(list_models):
        try:
            raw = list_models()
            if isinstance(raw, dict):
                inventory = raw.get("data") or raw.get("models") or []
            elif isinstance(raw, list):
                inventory = raw
        except Exception:
            inventory = None
    omni_usable = None
    if use_omniroute:
        omni_usable = True  # caller may refine
    return resolve_coding_model(
        explicit_model_id=explicit_model_id,
        active_model_id=str(active) if active else None,
        profile_model_id=str(profile) if profile else None,
        inventory=inventory,
        use_omniroute=use_omniroute,
        omniroute_usable=omni_usable,
    )


def coding_lm_timeout_seconds(default: float = 180.0) -> float:
    """Coding-specific LM timeout with sane upper bound."""
    try:
        from control.service import resolve_setting

        raw = resolve_setting("coding.lm_timeout_seconds", default=default)
        value = float(raw)
    except Exception:
        value = float(default)
    # Bounds: 30s .. 900s
    return max(30.0, min(900.0, value))


def coding_lm_max_tokens(default: int = 8192) -> int:
    """Output token budget for Coding edit generation (not a silent 2500)."""
    try:
        from control.service import resolve_setting

        raw = resolve_setting("coding.lm_max_tokens", default=default)
        value = int(raw)
    except Exception:
        value = int(default)
    return max(1024, min(32_768, value))
