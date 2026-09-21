"""Normalize adapter payloads + plugin/tool rows into CanonicalCapability records."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from plugin_runtime_v2 import build_capability_contract, normalize_isolation, normalize_trust

from .adapters.base import default_registry
from .adapters.native import native_capabilities
from .contracts import (
    AdaptationResult,
    AgentContract,
    CanonicalCapability,
    UnsupportedMapping,
    UsageMetadata,
    content_hash,
)
from .taxonomy import CONTRACT_VERSION, NATIVE_PROVIDER_ID, is_capability_kind, normalize_kind


def _slug(*parts: str) -> str:
    cleaned = [str(part or "").strip().lower().replace(" ", "-") for part in parts if str(part or "").strip()]
    return ":".join(cleaned)


def _listify(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _domains_from_text(*texts: str) -> list[str]:
    hay = " ".join(texts).lower()
    found: list[str] = []
    mapping = (
        ("python", "software.python"),
        ("javascript", "software.javascript"),
        ("typescript", "software.javascript"),
        ("debug", "debugging"),
        ("concurren", "software.concurrency"),
        ("deadlock", "software.concurrency"),
        ("async", "software.concurrency"),
        ("race", "software.concurrency"),
        ("repositor", "software.repository"),
        ("git", "software.git"),
        ("test", "software.test"),
        ("research", "research"),
        ("osint", "osint"),
        ("mcp", "mcp"),
        ("markdown", "documents.conversion"),
        ("pdf", "documents.conversion"),
        ("document", "documents.conversion"),
        ("convert", "documents.conversion"),
        ("browser", "browser.automation"),
        ("puppeteer", "browser.automation"),
        ("screenshot", "browser.automation"),
        ("chromium", "browser.automation"),
    )
    for token, domain in mapping:
        if token in hay and domain not in found:
            found.append(domain)
    return found


def _intents_from_text(*texts: str) -> list[str]:
    hay = " ".join(texts).lower()
    found: list[str] = []
    mapping = (
        ("diagnos", "diagnose_bug"),
        ("repair", "repair_bug"),
        ("fix", "repair_bug"),
        ("search", "inspect_code"),
        ("inspect", "inspect_code"),
        ("edit", "code.modify"),
        ("patch", "code.modify"),
        ("test", "tests.execute"),
        ("verif", "result.verify"),
        ("research", "research"),
        ("convert", "document.convert"),
        ("markdown", "document.convert"),
        ("pdf", "document.convert"),
        ("screenshot", "browser.screenshot"),
        ("navigate", "browser.navigate"),
        ("browser", "browser.navigate"),
    )
    for token, intent in mapping:
        if token in hay and intent not in found:
            found.append(intent)
    return found


def _hash_file(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()[:256_000]
    except Exception:
        return ""
    return hashlib.sha256(data).hexdigest()


def normalize_raw_capability(
    raw: dict[str, Any],
    *,
    plugin: dict[str, Any] | None,
    adapter_id: str,
    root: Path | None = None,
    tool_row: dict[str, Any] | None = None,
) -> CanonicalCapability | None:
    kind = normalize_kind(raw.get("kind"))
    if kind is None:
        return None
    plugin_id = str((plugin or {}).get("id") or "")
    ident = str(raw.get("id") or raw.get("name") or "").strip()
    if not ident:
        return None
    canonical_id = _slug(plugin_id or raw.get("provider_id") or NATIVE_PROVIDER_ID, kind, ident)
    contract = {}
    if tool_row is not None or raw.get("tool"):
        contract = build_capability_contract(plugin, tool_row or raw.get("tool"))
    elif plugin:
        contract = build_capability_contract(plugin, None)
    description = str(raw.get("description") or "")
    name = str(raw.get("name") or ident)
    domains = _listify(raw.get("domains")) or _domains_from_text(name, description, ident)
    intents = _listify(raw.get("intents")) or _intents_from_text(name, description, ident)
    specialties = _listify(raw.get("specialties"))
    if specialties:
        for item in specialties:
            if item not in domains:
                domains.append(item)
    content_ref = str(raw.get("content_ref") or "")
    file_hash = _hash_file(root, content_ref) if root and content_ref else ""
    extras: dict[str, Any] = {}
    if kind == "agent":
        extras["agent"] = AgentContract(
            canonical_id=canonical_id,
            specialties=specialties or domains,
            accepts=_listify(raw.get("accepts")),
            produces=_listify(raw.get("produces")),
            required_context=_listify(raw.get("required_context")),
            allowed_capabilities=_listify(raw.get("allowed_tools") or raw.get("allowed_capabilities")),
            executable=bool(raw.get("executable", not raw.get("persona_only", False))),
            persona_only=bool(raw.get("persona_only", False)),
        ).to_dict()
    if raw.get("persona_only"):
        extras["persona_only"] = True
    usage = UsageMetadata.from_mapping(raw.get("usage") or raw)
    health = str((plugin or {}).get("health") or raw.get("health") or "unknown")
    enabled = bool((plugin or {}).get("enabled", True))
    status = str((plugin or {}).get("status") or "ready")
    available = enabled and status == "ready" and health not in {"unhealthy", "needs_attention"}
    record = CanonicalCapability(
        canonical_id=canonical_id,
        kind=kind,
        name=name,
        description=description,
        provider_id=plugin_id or str(raw.get("provider_id") or NATIVE_PROVIDER_ID),
        plugin_id=plugin_id or None,
        source=str(raw.get("from") or adapter_id or "plugin"),
        version=str((plugin or {}).get("version") or raw.get("version") or ""),
        domains=domains,
        intents=intents,
        aliases=_listify(raw.get("aliases")) + ([ident] if ident != name else []),
        input_contract=dict(raw.get("input_contract") or raw.get("input_schema") or {}),
        output_contract=dict(raw.get("output_contract") or raw.get("output_schema") or {}),
        effects=_listify(raw.get("effects") or contract.get("effects")),
        side_effect_class=str(raw.get("side_effect_class") or contract.get("side_effect_class") or ("none" if kind in {"skill", "knowledge", "resource"} else "process")),
        cost_class=str(raw.get("cost_class") or contract.get("cost_class") or ("cheap" if kind in {"skill", "knowledge"} else "moderate")),
        latency_class=str(raw.get("latency_class") or contract.get("latency_class") or "fast"),
        trust_requirements=normalize_trust((plugin or {}).get("trust") or raw.get("trust_requirements") or "untrusted"),
        permissions=_listify((plugin or {}).get("permissions") or raw.get("permissions")),
        isolation=normalize_isolation((plugin or {}).get("isolation") or raw.get("isolation")),
        health="available" if available else ("needs_setup" if status != "ready" else "unknown"),
        availability=available,
        prerequisites=_listify(raw.get("prerequisites") or raw.get("requires")),
        required_resources=_listify(raw.get("required_resources")),
        failure_modes=_listify(raw.get("failure_modes") or contract.get("failure_modes")),
        agent_affinity=_listify(raw.get("agent_affinity")),
        preferred_followups=_listify(raw.get("preferred_followups") or usage.preferred_followups),
        produces=_listify(raw.get("produces") or usage.produces),
        usage=usage,
        content_ref=content_ref,
        content_hash=file_hash or content_hash({"id": ident, "kind": kind, "description": description}),
        adapter_id=adapter_id,
        contract_version=CONTRACT_VERSION,
        extras=extras,
    )
    try:
        from hades_brain.traits import infer_traits

        record.extras["traits"] = infer_traits(
            kind=kind,
            side_effect_class=str(record.side_effect_class),
            extras=record.extras,
            declared=raw.get("traits"),
        )
    except Exception:
        pass
    # Skills/knowledge are never side-effecting merely because a plugin has subprocess tools.
    if kind in {"skill", "knowledge", "resource"}:
        record.effects = []
        record.side_effect_class = "none"
        record.cost_class = "cheap"
    return record


def adapt_package(
    root: Path | None,
    *,
    plugin: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    include_native: bool = False,
) -> AdaptationResult:
    """Run format detection → adapters → HADES normalization."""
    result = AdaptationResult()
    base = Path(root) if root else Path(".")
    plugin = plugin or {}
    manifest = manifest or (plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {})
    registry = default_registry()
    parsed = registry.parse_applicable(base, plugin=plugin, manifest=manifest) if root else []
    seen: set[str] = set()
    tool_by_name = {str(item.get("name")): item for item in (tools or []) if isinstance(item, dict)}
    for adapter_id, payload in parsed:
        result.adapters_used.append(adapter_id)
        if payload.get("error"):
            result.warnings.append(f"{adapter_id}: {payload['error']}")
            continue
        for raw in payload.get("capabilities") or []:
            if not isinstance(raw, dict):
                continue
            claimed = str(raw.get("kind") or "")
            if claimed and not is_capability_kind(claimed):
                result.unsupported.append(
                    UnsupportedMapping(
                        path=str(raw.get("content_ref") or raw.get("id") or ""),
                        claimed_kind=claimed,
                        reason="Unknown capability kind; not forced into an incorrect type.",
                        adapter_id=adapter_id,
                    )
                )
                continue
            tool_row = tool_by_name.get(str(raw.get("name") or raw.get("id") or ""))
            record = normalize_raw_capability(raw, plugin=plugin, adapter_id=adapter_id, root=base if root else None, tool_row=tool_row)
            if record is None or record.canonical_id in seen:
                continue
            seen.add(record.canonical_id)
            result.capabilities.append(record)
        for item in payload.get("unsupported") or []:
            if isinstance(item, dict):
                result.unsupported.append(
                    UnsupportedMapping(
                        path=str(item.get("path") or ""),
                        claimed_kind=str(item.get("claimed_kind") or "unknown"),
                        reason=str(item.get("reason") or "unsupported"),
                        adapter_id=str(item.get("adapter_id") or adapter_id),
                    )
                )
    if include_native:
        for record in native_capabilities():
            if record.canonical_id not in seen:
                result.capabilities.append(record)
                seen.add(record.canonical_id)
    return result


def normalize_legacy_plugin(plugin: dict[str, Any], tools: list[dict[str, Any]] | None = None) -> AdaptationResult:
    """Back-compat: plugin_type=tool + tools[] → executable tool capabilities."""
    root = Path(str(plugin.get("local_path") or "."))
    return adapt_package(root if root.exists() else None, plugin=plugin, tools=tools or plugin.get("tools") or [])
