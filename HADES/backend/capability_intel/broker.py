"""HADES Capability Broker — discovery + controlled execution bridge.

The model-facing surface is ``hades.capabilities.search|inspect|invoke``.
Plugins and MCP remain optional extras indexed in the CapabilityRegistry;
they are never permanent first-party Chat tool schemas.

Execution always re-checks live registry/plugin/MCP/policy/trust/approval
state. Model-supplied security metadata is ignored.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from plugin_runtime_v2 import build_capability_contract, eligible_for_autonomous, evaluate_global_side_effect_policies
from reasoning.tool_registry import validate_against_schema

from .availability import (
    APPROVAL_REQUIRED,
    AVAILABLE,
    DISABLED,
    MCP_DISCONNECTED,
    NOT_AUTONOMOUS,
    UNREGISTERED,
    evaluate_availability,
)
from .contracts import CanonicalCapability, RankedCandidate
from .ids import (
    capability_id_for_record,
    capability_id_for_tool,
    legacy_aliases,
    make_capability_id,
    parse_capability_id,
)
from .planner import plan_requirements
from .ranking import rank_capabilities
from .registry import CapabilityRegistry, get_registry

InvokeFn = Callable[..., dict[str, Any]]
ApprovalFn = Callable[..., dict[str, Any]]
PermissionOk = Callable[[dict[str, Any], dict[str, Any]], bool]


@dataclass
class BrokerIndexEntry:
    capability_id: str
    provider: str
    provider_id: str
    action: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    side_effect_class: str = "none"
    cost_class: str = "cheap"
    latency_class: str = "fast"
    plugin_id: str = ""
    tool_name: str = ""
    labels: list[str] = field(default_factory=list)
    record: CanonicalCapability | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityBroker:
    """Central discovery + invoke bridge over CapabilityRegistry + live providers."""

    MAX_SEARCH = 20
    DEFAULT_SEARCH = 5

    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
        tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
        invoke_fn: InvokeFn | None = None,
        approval_fn: ApprovalFn | None = None,
        permission_ok: PermissionOk | None = None,
        mcp_connected: Callable[[str], bool] | None = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.plugins_by_id = dict(plugins_by_id or {})
        self.tools_by_key = dict(tools_by_key or {})
        self.settings = dict(settings or {})
        self.invoke_fn = invoke_fn
        self.approval_fn = approval_fn
        self.permission_ok = permission_ok
        self.mcp_connected = mcp_connected
        self._index: dict[str, BrokerIndexEntry] = {}
        self._alias_to_id: dict[str, str] = {}
        self._generation = 0
        self.rebuild_index()

    # --- lifecycle ---------------------------------------------------------

    def set_live_state(
        self,
        *,
        plugins_by_id: dict[str, dict[str, Any]] | None = None,
        tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        if plugins_by_id is not None:
            self.plugins_by_id = dict(plugins_by_id)
        if tools_by_key is not None:
            self.tools_by_key = dict(tools_by_key)
        if settings is not None:
            self.settings = dict(settings)
        self.rebuild_index()

    def refresh_from_plugins(
        self,
        plugins: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        """Index installed plugins/tools into the registry + broker index."""
        self.plugins_by_id = {str(p.get("id")): p for p in plugins if p.get("id")}
        self.tools_by_key = {
            (str(t.get("plugin_id")), str(t.get("name"))): t
            for t in tools
            if t.get("plugin_id") and t.get("name")
        }
        for plugin in plugins:
            pid = str(plugin.get("id") or "")
            if not pid:
                continue
            plugin_tools = [t for t in tools if str(t.get("plugin_id")) == pid]
            try:
                self.registry.refresh_plugin(plugin, tools=plugin_tools)
            except Exception:
                # Fail soft for one bad package — keep indexing others.
                pass
        self.rebuild_index()
        return len(self._index)

    def on_plugin_removed(self, plugin_id: str) -> None:
        self.registry.drop_plugin(plugin_id)
        self.plugins_by_id.pop(plugin_id, None)
        self.tools_by_key = {k: v for k, v in self.tools_by_key.items() if k[0] != plugin_id}
        self.rebuild_index()

    def rebuild_index(self) -> None:
        index: dict[str, BrokerIndexEntry] = {}
        aliases: dict[str, str] = {}

        # Live tool rows are authoritative for execution identity.
        for (plugin_id, tool_name), tool in self.tools_by_key.items():
            plugin = self.plugins_by_id.get(plugin_id)
            if plugin is None:
                plugin = {"id": plugin_id, "name": plugin_id, "enabled": True, "status": "ready"}
            cap_id = capability_id_for_tool(plugin, tool, plugin_id=plugin_id)
            provider = cap_id.split(":", 1)[0]
            provider_id = cap_id.split(":")[1] if ":" in cap_id else plugin_id
            contract = build_capability_contract(plugin, tool)
            labels = []
            if isinstance(plugin.get("labels"), list):
                labels.extend(str(x) for x in plugin["labels"] if x)
            manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
            if isinstance(manifest.get("labels"), list):
                labels.extend(str(x) for x in manifest["labels"] if x)
            entry = BrokerIndexEntry(
                capability_id=cap_id,
                provider=provider,
                provider_id=provider_id,
                action=tool_name,
                name=str(tool.get("name") or tool_name),
                description=str(tool.get("description") or plugin.get("description") or ""),
                input_schema=dict(tool.get("input_schema") or {}),
                effects=list(contract.get("effects") or []),
                side_effect_class=str(contract.get("side_effect_class") or "none"),
                cost_class=str(contract.get("cost_class") or "cheap"),
                latency_class=str(contract.get("latency_class") or "fast"),
                plugin_id=plugin_id,
                tool_name=tool_name,
                labels=labels,
                metadata={
                    "plugin_name": str(plugin.get("name") or plugin_id),
                    "autonomous_manifest": bool(
                        (manifest.get("autonomous") if "autonomous" in manifest else plugin.get("autonomous", True))
                    ),
                },
            )
            index[cap_id] = entry
            for alias in legacy_aliases(cap_id):
                aliases[alias.lower()] = cap_id
            aliases[f"{plugin_id}:{tool_name}".lower()] = cap_id
            aliases[tool_name.lower()] = aliases.get(tool_name.lower()) or cap_id

        # Registry records enrich descriptions / ranking when present.
        for record in self.registry.all():
            if record.kind != "tool":
                continue
            cap_id = capability_id_for_record(record)
            entry = index.get(cap_id)
            if entry is None and record.plugin_id and record.name:
                # Registry-only (e.g. after refresh before live tools wired).
                plugin = self.plugins_by_id.get(str(record.plugin_id)) or {
                    "id": record.plugin_id,
                    "name": record.plugin_id,
                }
                tool = self.tools_by_key.get((str(record.plugin_id), str(record.name))) or {
                    "plugin_id": record.plugin_id,
                    "name": record.name,
                    "description": record.description,
                    "input_schema": record.input_contract,
                }
                cap_id = capability_id_for_tool(plugin, tool)
                if cap_id not in index:
                    parsed = parse_capability_id(cap_id)
                    index[cap_id] = BrokerIndexEntry(
                        capability_id=cap_id,
                        provider=parsed[0] if parsed else "plugin",
                        provider_id=parsed[1] if parsed else str(record.plugin_id),
                        action=parsed[2] if parsed else str(record.name),
                        name=record.name,
                        description=record.description,
                        input_schema=dict(record.input_contract or {}),
                        effects=list(record.effects or []),
                        side_effect_class=str(record.side_effect_class or "none"),
                        cost_class=str(record.cost_class or "cheap"),
                        latency_class=str(record.latency_class or "fast"),
                        plugin_id=str(record.plugin_id or ""),
                        tool_name=str(record.name),
                        record=record,
                    )
                    entry = index[cap_id]
            if entry is not None:
                entry.record = record
                if record.description and len(record.description) > len(entry.description):
                    entry.description = record.description
                if record.input_contract and not entry.input_schema:
                    entry.input_schema = dict(record.input_contract)
                for alias in legacy_aliases(cap_id) + [record.canonical_id]:
                    aliases[str(alias).lower()] = entry.capability_id

        self._index = index
        self._alias_to_id = aliases
        self._generation += 1

    # --- resolve -----------------------------------------------------------

    def resolve(self, capability_id: str) -> BrokerIndexEntry | None:
        raw = str(capability_id or "").strip()
        if not raw:
            return None
        if raw in self._index:
            return self._index[raw]
        mapped = self._alias_to_id.get(raw.lower())
        if mapped and mapped in self._index:
            return self._index[mapped]
        parsed = parse_capability_id(raw)
        if parsed:
            provider, provider_id, action = parsed
            # Try mcp:provider_id reconstitutions.
            candidates = [raw]
            if provider == "mcp":
                candidates.append(make_capability_id("mcp", provider_id, action))
                candidates.append(f"mcp:{provider_id}:{action}")
            for cand in candidates:
                if cand in self._index:
                    return self._index[cand]
                mapped = self._alias_to_id.get(cand.lower())
                if mapped and mapped in self._index:
                    return self._index[mapped]
            # Direct plugin/tool lookup.
            for plugin_key in (provider_id, f"mcp:{provider_id}", f"plugin:{provider_id}"):
                tool = self.tools_by_key.get((plugin_key, action))
                if tool:
                    plugin = self.plugins_by_id.get(plugin_key) or {"id": plugin_key}
                    cap = capability_id_for_tool(plugin, tool, plugin_id=plugin_key)
                    return self._index.get(cap) or BrokerIndexEntry(
                        capability_id=cap,
                        provider=provider,
                        provider_id=provider_id,
                        action=action,
                        name=action,
                        description=str(tool.get("description") or ""),
                        input_schema=dict(tool.get("input_schema") or {}),
                        plugin_id=plugin_key,
                        tool_name=action,
                    )
        return None

    def list_ids(self) -> list[str]:
        return sorted(self._index.keys())

    def count(self) -> int:
        return len(self._index)

    # --- availability ------------------------------------------------------

    def _mcp_is_connected(self, plugin_id: str) -> bool | None:
        if self.mcp_connected is None:
            return None
        try:
            return bool(self.mcp_connected(plugin_id))
        except Exception:
            return False

    def availability_for(self, entry: BrokerIndexEntry) -> dict[str, Any]:
        plugin = self.plugins_by_id.get(entry.plugin_id)
        tool = self.tools_by_key.get((entry.plugin_id, entry.tool_name))
        mcp_state = None
        if entry.provider == "mcp":
            mcp_state = self._mcp_is_connected(entry.plugin_id)
        return evaluate_availability(
            plugin=plugin,
            tool=tool,
            settings=self.settings,
            provider=entry.provider,
            mcp_connected=mcp_state,
        )

    # --- search / inspect --------------------------------------------------

    def search(self, query: str, *, limit: int | None = None) -> dict[str, Any]:
        """Discovery only — does not grant execution rights."""
        cap = max(1, min(self.MAX_SEARCH, int(limit if limit is not None else self.DEFAULT_SEARCH)))
        # Build ephemeral CanonicalCapability list from the broker index for ranking.
        records: list[CanonicalCapability] = []
        for entry in self._index.values():
            if entry.record is not None:
                rec = entry.record
                # Ensure public id is searchable via aliases.
                if entry.capability_id not in rec.aliases:
                    rec.aliases = list(rec.aliases) + [entry.capability_id, entry.plugin_id, entry.tool_name]
                records.append(rec)
            else:
                records.append(
                    CanonicalCapability(
                        canonical_id=entry.capability_id,
                        kind="tool",
                        name=entry.name,
                        description=entry.description,
                        provider_id=entry.provider_id,
                        plugin_id=entry.plugin_id or None,
                        source=entry.provider,
                        domains=[],
                        intents=[],
                        aliases=[entry.capability_id, entry.plugin_id, entry.tool_name, *entry.labels],
                        input_contract=dict(entry.input_schema),
                        effects=list(entry.effects),
                        side_effect_class=entry.side_effect_class,  # type: ignore[arg-type]
                        cost_class=entry.cost_class,  # type: ignore[arg-type]
                        latency_class=entry.latency_class,  # type: ignore[arg-type]
                        extras={"capability_id": entry.capability_id},
                    )
                )
        plan = plan_requirements(query)
        decision = rank_capabilities(query, records, plan=plan, limit=max(cap * 4, 12))
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ranked in decision.selected + decision.rejected:
            entry = self._entry_for_ranked(ranked)
            if entry is None or entry.capability_id in seen:
                continue
            seen.add(entry.capability_id)
            avail = self.availability_for(entry)
            matches.append(
                {
                    "capability_id": entry.capability_id,
                    "provider": entry.provider,
                    "provider_id": entry.provider_id,
                    "name": entry.name,
                    "description": entry.description[:500],
                    "effects": list(entry.effects),
                    "available": bool(avail.get("available")),
                    "availability_reason": avail.get("reason"),
                    "availability_detail": avail.get("detail"),
                    "autonomous": bool(avail.get("autonomous")),
                    "score": round(float(ranked.score), 4),
                    "reasons": list(ranked.reasons)[:8],
                }
            )
            if len(matches) >= cap:
                break
        return {
            "query": query,
            "matches": matches,
            "total_indexed": len(self._index),
            "limit": cap,
            "generation": self._generation,
        }

    def _entry_for_ranked(self, ranked: RankedCandidate) -> BrokerIndexEntry | None:
        cap = ranked.capability
        for key in (capability_id_for_record(cap), cap.canonical_id, f"{cap.plugin_id}:{cap.name}"):
            hit = self.resolve(str(key))
            if hit:
                return hit
        if cap.plugin_id and cap.name:
            return self.resolve(capability_id_for_tool({"id": cap.plugin_id}, {"name": cap.name}))
        return None

    def inspect(self, capability_id: str) -> dict[str, Any]:
        entry = self.resolve(capability_id)
        if entry is None:
            return {
                "capability_id": capability_id,
                "found": False,
                "available": False,
                "availability_reason": UNREGISTERED,
                "error": "Capability is not registered.",
            }
        avail = self.availability_for(entry)
        plugin = self.plugins_by_id.get(entry.plugin_id) or {}
        return {
            "capability_id": entry.capability_id,
            "found": True,
            "provider": entry.provider,
            "provider_id": entry.provider_id,
            "action": entry.action,
            "name": entry.name,
            "description": entry.description,
            "input_schema": entry.input_schema,
            "effects": list(entry.effects),
            "side_effect_class": entry.side_effect_class,
            "cost_class": entry.cost_class,
            "latency_class": entry.latency_class,
            "plugin_id": entry.plugin_id,
            "tool_name": entry.tool_name,
            "labels": list(entry.labels),
            "available": bool(avail.get("available")),
            "availability_reason": avail.get("reason"),
            "availability_detail": avail.get("detail"),
            "autonomous": bool(avail.get("autonomous")),
            "executable": bool(avail.get("executable")),
            "policy": avail.get("policy"),
            "trust": plugin.get("trust"),
            "enabled": plugin.get("enabled"),
            "health": plugin.get("health") or plugin.get("status"),
            "plugin_name": plugin.get("name") or entry.metadata.get("plugin_name"),
        }

    # --- invoke ------------------------------------------------------------

    def invoke(
        self,
        capability_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        approved_by_user: bool = False,
        approved_network: bool = False,
        approved_file_read: bool = False,
        approved_file_write: bool = False,
        approved_subprocess: bool = False,
        approvals: dict[str, bool] | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve + authorize + execute. Model metadata is never trusted."""
        started = time.perf_counter()
        # Explicitly ignore model-supplied security fields.
        _ = model_metadata
        args = dict(arguments or {}) if isinstance(arguments, dict) else {}
        # Strip forged security keys if the model stuffed them into arguments.
        for forged in (
            "autonomous",
            "trust",
            "effects",
            "approved",
            "permissions",
            "side_effect_class",
            "approved_by_user",
            "approved_network",
            "approved_file_read",
            "approved_file_write",
            "approved_subprocess",
            "approvals",
        ):
            args.pop(forged, None)

        entry = self.resolve(capability_id)
        if entry is None:
            return self._result(
                status="blocked",
                reason_code=UNREGISTERED,
                error=f"Unregistered capability_id={capability_id!r}",
                capability_id=capability_id,
                started=started,
            )

        plugin = self.plugins_by_id.get(entry.plugin_id)
        tool = self.tools_by_key.get((entry.plugin_id, entry.tool_name))
        if plugin is None or tool is None:
            return self._result(
                status="blocked",
                reason_code=UNREGISTERED,
                error="Capability provider/tool row missing at invoke time.",
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
            )

        if entry.provider == "mcp":
            connected = self._mcp_is_connected(entry.plugin_id)
            if connected is False:
                return self._result(
                    status="blocked",
                    reason_code=MCP_DISCONNECTED,
                    error="MCP server is disconnected.",
                    capability_id=entry.capability_id,
                    started=started,
                    provider=entry.provider,
                    plugin_id=entry.plugin_id,
                    tool_name=entry.tool_name,
                )

        if not bool(plugin.get("enabled", True)):
            return self._result(
                status="blocked",
                reason_code=DISABLED,
                error="Plugin is disabled.",
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
            )

        schema_errors = validate_against_schema(args, tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else entry.input_schema)
        if schema_errors:
            return self._result(
                status="blocked",
                reason_code="invalid_arguments",
                error="Argument schema validation failed: " + "; ".join(schema_errors[:8]),
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
                schema_errors=schema_errors,
            )

        if self.permission_ok is not None:
            try:
                if not self.permission_ok(plugin, tool):
                    return self._result(
                        status="blocked",
                        reason_code="permission_denied",
                        error="Permission check denied.",
                        capability_id=entry.capability_id,
                        started=started,
                        provider=entry.provider,
                        plugin_id=entry.plugin_id,
                        tool_name=entry.tool_name,
                    )
            except Exception as exc:
                return self._result(
                    status="blocked",
                    reason_code="permission_denied",
                    error=f"Permission check failed: {exc}",
                    capability_id=entry.capability_id,
                    started=started,
                    provider=entry.provider,
                    plugin_id=entry.plugin_id,
                    tool_name=entry.tool_name,
                )

        contract = build_capability_contract(plugin, tool)
        # Effects come only from registry/contract — never from the model.
        # Approved restricted invokes use manual invocation_type so ask policies
        # can proceed after explicit per-kind approval (never silent autonomous ask→allow).
        # approved_by_user alone is not ask authority (F-03).
        from plugin_runtime_v2 import normalize_capability_approvals

        kind_approvals = normalize_capability_approvals(
            approvals,
            approved_network=approved_network,
            approved_file_read=approved_file_read,
            approved_file_write=approved_file_write,
            approved_subprocess=approved_subprocess,
        )
        # Promote to manual only when per-kind flags are present.
        # Bare approved_by_user is audit-only and must not satisfy ask (F-03).
        invocation_type = "manual" if any(kind_approvals.values()) else "autonomous"
        policy = evaluate_global_side_effect_policies(
            contract=contract,
            settings=self.settings,
            invocation_type=invocation_type,
            approved_by_user=bool(approved_by_user),
            approvals=kind_approvals,
        )
        if not policy.get("allowed"):
            reason = str(policy.get("reason") or "policy_block")
            if policy.get("requires_approval") or "ask" in reason.lower() or "approval" in reason.lower():
                if self.approval_fn is not None and not approved_by_user:
                    try:
                        approval = self.approval_fn(
                            plugin_id=entry.plugin_id,
                            tool_name=entry.tool_name,
                            arguments=args,
                            expected_effect=f"Capability {entry.capability_id}",
                            schema_version="1",
                            scope={
                                "invocation_type": "autonomous",
                                "capability_id": entry.capability_id,
                                "provider": entry.provider,
                                "effects": list(contract.get("effects") or []),
                            },
                        )
                    except Exception as exc:
                        approval = {"error": str(exc)}
                    return self._result(
                        status="approval_required",
                        reason_code=APPROVAL_REQUIRED,
                        error=reason,
                        capability_id=entry.capability_id,
                        started=started,
                        provider=entry.provider,
                        plugin_id=entry.plugin_id,
                        tool_name=entry.tool_name,
                        effects=list(contract.get("effects") or []),
                        approval=approval if isinstance(approval, dict) else {"raw": approval},
                        policy=policy,
                    )
                return self._result(
                    status="approval_required",
                    reason_code=APPROVAL_REQUIRED,
                    error=reason,
                    capability_id=entry.capability_id,
                    started=started,
                    provider=entry.provider,
                    plugin_id=entry.plugin_id,
                    tool_name=entry.tool_name,
                    effects=list(contract.get("effects") or []),
                    policy=policy,
                )
            return self._result(
                status="blocked",
                reason_code=str(policy.get("reason_code") or reason),
                error=reason,
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
                effects=list(contract.get("effects") or []),
                policy=policy,
            )

        ok, autonomy_reason = eligible_for_autonomous(plugin, tool)
        if not ok and not approved_by_user and not any(kind_approvals.values()):
            lower = autonomy_reason.lower()
            if "autonomous" in lower:
                if self.approval_fn is not None:
                    try:
                        approval = self.approval_fn(
                            plugin_id=entry.plugin_id,
                            tool_name=entry.tool_name,
                            arguments=args,
                            expected_effect=f"Restricted capability {entry.capability_id}",
                            schema_version="1",
                            scope={
                                "invocation_type": "manual",
                                "capability_id": entry.capability_id,
                                "provider": entry.provider,
                                "effects": list(contract.get("effects") or []),
                            },
                        )
                    except Exception as exc:
                        approval = {"error": str(exc)}
                    return self._result(
                        status="approval_required",
                        reason_code=APPROVAL_REQUIRED,
                        error=autonomy_reason,
                        capability_id=entry.capability_id,
                        started=started,
                        provider=entry.provider,
                        plugin_id=entry.plugin_id,
                        tool_name=entry.tool_name,
                        effects=list(contract.get("effects") or []),
                        approval=approval if isinstance(approval, dict) else {"raw": approval},
                    )
                return self._result(
                    status="approval_required",
                    reason_code=NOT_AUTONOMOUS,
                    error=autonomy_reason,
                    capability_id=entry.capability_id,
                    started=started,
                    provider=entry.provider,
                    plugin_id=entry.plugin_id,
                    tool_name=entry.tool_name,
                    effects=list(contract.get("effects") or []),
                )
            return self._result(
                status="blocked",
                reason_code=autonomy_reason,
                error=autonomy_reason,
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
            )

        if self.invoke_fn is None:
            return self._result(
                status="failed",
                reason_code="executor_unavailable",
                error="No provider executor is wired to the capability broker.",
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
            )

        try:
            raw = self.invoke_fn(
                entry.plugin_id,
                entry.tool_name,
                args,
                approved_by_user=bool(approved_by_user),
                invocation_type=invocation_type,
                approved_network=kind_approvals["network"],
                approved_file_read=kind_approvals["file_read"],
                approved_file_write=kind_approvals["file_write"],
                approved_subprocess=kind_approvals["subprocess"],
                approvals=kind_approvals,
            )
        except TypeError:
            try:
                raw = self.invoke_fn(
                    entry.plugin_id,
                    entry.tool_name,
                    args,
                    approved_by_user=bool(approved_by_user),
                    invocation_type=invocation_type,
                )
            except TypeError:
                try:
                    raw = self.invoke_fn(entry.plugin_id, entry.tool_name, args)
                except Exception as exc:
                    return self._result(
                        status="failed",
                        reason_code="provider_failure",
                        error=f"Provider execution failed: {exc}",
                        capability_id=entry.capability_id,
                        started=started,
                        provider=entry.provider,
                        plugin_id=entry.plugin_id,
                        tool_name=entry.tool_name,
                        effects=list(contract.get("effects") or []),
                    )
            except Exception as exc:
                return self._result(
                    status="failed",
                    reason_code="provider_failure",
                    error=f"Provider execution failed: {exc}",
                    capability_id=entry.capability_id,
                    started=started,
                    provider=entry.provider,
                    plugin_id=entry.plugin_id,
                    tool_name=entry.tool_name,
                    effects=list(contract.get("effects") or []),
                )
        except Exception as exc:
            return self._result(
                status="failed",
                reason_code="provider_failure",
                error=f"Provider execution failed: {exc}",
                capability_id=entry.capability_id,
                started=started,
                provider=entry.provider,
                plugin_id=entry.plugin_id,
                tool_name=entry.tool_name,
                effects=list(contract.get("effects") or []),
            )

        status = str((raw or {}).get("status") or "completed")
        return {
            **(raw if isinstance(raw, dict) else {"output": raw}),
            "capability_id": entry.capability_id,
            "provider": entry.provider,
            "provider_id": entry.provider_id,
            "plugin_id": entry.plugin_id,
            "tool_name": entry.tool_name,
            "effects": list(contract.get("effects") or []),
            "broker": True,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "status": status,
            "execution_status": status,
        }

    def _result(
        self,
        *,
        status: str,
        reason_code: str,
        error: str,
        capability_id: str,
        started: float,
        provider: str | None = None,
        plugin_id: str | None = None,
        tool_name: str | None = None,
        effects: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = {
            "status": status,
            "execution_status": status,
            "reason_code": reason_code,
            "error": error,
            "capability_id": capability_id,
            "provider": provider,
            "plugin_id": plugin_id,
            "tool_name": tool_name,
            "effects": effects or [],
            "broker": True,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "output": json.dumps(
                {"status": status, "reason_code": reason_code, "error": error, "capability_id": capability_id},
                ensure_ascii=False,
            ),
        }
        payload.update(extra)
        return payload

    def prefetch_hints(self, query: str, *, limit: int = 3) -> list[str]:
        """Compact text hints for Chat context — never full schemas."""
        page = self.search(query, limit=limit)
        hints: list[str] = []
        for match in page.get("matches") or []:
            name = str(match.get("name") or match.get("capability_id"))
            desc = str(match.get("description") or "")[:80]
            avail = match.get("availability_reason") or ""
            suffix = ""
            if avail and avail != AVAILABLE:
                suffix = f" ({avail})"
            hints.append(f"- {name} — {desc}{suffix}".strip())
        return hints


_BROKER: CapabilityBroker | None = None


def get_broker(**kwargs: Any) -> CapabilityBroker:
    global _BROKER
    if _BROKER is None:
        _BROKER = CapabilityBroker(**kwargs)
    elif kwargs:
        if "plugins_by_id" in kwargs or "tools_by_key" in kwargs or "settings" in kwargs:
            _BROKER.set_live_state(
                plugins_by_id=kwargs.get("plugins_by_id"),
                tools_by_key=kwargs.get("tools_by_key"),
                settings=kwargs.get("settings"),
            )
        if "invoke_fn" in kwargs and kwargs["invoke_fn"] is not None:
            _BROKER.invoke_fn = kwargs["invoke_fn"]
        if "approval_fn" in kwargs and kwargs["approval_fn"] is not None:
            _BROKER.approval_fn = kwargs["approval_fn"]
        if "permission_ok" in kwargs and kwargs["permission_ok"] is not None:
            _BROKER.permission_ok = kwargs["permission_ok"]
        if "mcp_connected" in kwargs and kwargs["mcp_connected"] is not None:
            _BROKER.mcp_connected = kwargs["mcp_connected"]
        if "registry" in kwargs and kwargs["registry"] is not None:
            _BROKER.registry = kwargs["registry"]
    return _BROKER


def reset_broker() -> None:
    global _BROKER
    _BROKER = None
