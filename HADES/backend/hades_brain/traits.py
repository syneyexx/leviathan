"""Capability traits used for routing reasons — not vendor names."""

from __future__ import annotations

from typing import Any, Final, Iterable

TRAIT_NAMES: Final[tuple[str, ...]] = (
    "executable",
    "retrievable",
    "delegatable",
    "stateful",
    "networked",
    "side_effecting",
    "long_running",
    "deterministic",
    "requires_auth",
    "requires_local_resource",
)

# Namespaced future extensions are allowed; unknown traits stay explicit.
KIND_DEFAULT_TRAITS: Final[dict[str, tuple[str, ...]]] = {
    "skill": ("retrievable",),
    "knowledge": ("retrievable",),
    "tool": ("executable",),
    "tool_provider": ("executable",),
    "mcp_provider": ("executable", "networked"),
    "agent": ("delegatable", "executable"),
    "service": ("stateful", "long_running", "executable"),
    "workflow": ("executable", "long_running"),
    "resource": ("retrievable", "requires_local_resource"),
}


def normalize_traits(values: Any) -> list[str]:
    raw: Iterable[Any]
    if isinstance(values, str):
        raw = [item.strip() for item in values.split(",") if item.strip()]
    elif isinstance(values, (list, tuple, set)):
        raw = values
    else:
        raw = []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip().lower().replace(" ", "_")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def infer_traits(
    *,
    kind: str,
    side_effect_class: str = "none",
    extras: dict[str, Any] | None = None,
    declared: Any = None,
) -> list[str]:
    traits = normalize_traits(declared)
    for item in KIND_DEFAULT_TRAITS.get(kind, ()):
        if item not in traits:
            traits.append(item)
    extras = extras or {}
    if side_effect_class not in {"", "none"} and "side_effecting" not in traits:
        traits.append("side_effecting")
    if extras.get("requires_auth") or extras.get("auth_required"):
        if "requires_auth" not in traits:
            traits.append("requires_auth")
    if extras.get("deterministic") or extras.get("domain_truth") == "deterministic":
        if "deterministic" not in traits:
            traits.append("deterministic")
    if extras.get("networked") or extras.get("requires_network"):
        if "networked" not in traits:
            traits.append("networked")
    return traits
