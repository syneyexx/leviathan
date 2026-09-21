"""Deterministic / hybrid runtimes for specialist agents.

These wrap existing HADES spines (Research, Evidence/Graph, PluginManager,
Trading, Voice) so Work/Tasks steps can complete without inventing a second
parallel system. Returning None from try_run_agent_step means fall through
to the normal model+tools path.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse


URL_RE = re.compile(r"https?://[^\s\]\)\"'<>]+", re.I)


def _ingest_result_verified(result: Any) -> bool:
    """True only when ingest did not report verification failure."""
    if not isinstance(result, dict) or not result:
        return False
    status = str(result.get("status") or "")
    if status == "verification_failed":
        return False
    persistence = result.get("persistence")
    if isinstance(persistence, dict) and persistence.get("verification_passed") is False:
        return False
    return True


@dataclass(slots=True)
class AgentStepResult:
    agent_id: str
    output: str
    mode: str  # deterministic | hybrid | blocked | degraded
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentRuntimeDeps:
    settings: dict[str, Any]
    web_research: Any | None = None
    knowledge: Any | None = None
    plugin_manager: Any | None = None
    shortlist_tools: Callable[..., list[dict[str, Any]]] | None = None
    paper_trading: Any | None = None
    trading_bot: Any | None = None
    platform_db: Any | None = None
    gen2: Any | None = None
    event: Callable[[str, str], None] | None = None
    prior_outputs: list[dict[str, Any]] = field(default_factory=list)
    step_title: str = ""


def _emit(deps: AgentRuntimeDeps, level: str, message: str) -> None:
    if deps.event:
        try:
            deps.event(level, message)
        except Exception:
            pass


def _network_policy(deps: AgentRuntimeDeps) -> str:
    return str(deps.settings.get("network_policy") or "block").strip().lower()


def _extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;")


def _extract_query(instruction: str) -> str:
    text = (instruction or "").strip()
    for prefix in ("zoek", "search", "scout", "verken", "crawl", "harvest"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :].strip(" :-\t")
            break
    return text[:500]


async def run_web_scout(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult:
    agent_id = "web_scout"
    if _network_policy(deps) != "allow":
        return AgentStepResult(
            agent_id=agent_id,
            output=(
                "Web Scout geblokkeerd: network_policy is niet 'allow'. "
                "Geen externe fetch uitgevoerd; lokale Knowledge blijft leidend."
            ),
            mode="blocked",
            ok=False,
            error="network_policy_blocked",
            metadata={"network_policy": _network_policy(deps)},
        )
    if deps.web_research is None:
        return AgentStepResult(
            agent_id=agent_id,
            output="Web Scout gedegradeerd: WebResearchService niet beschikbaar.",
            mode="degraded",
            ok=False,
            error="web_research_unavailable",
        )

    url = _extract_url(instruction)
    query = _extract_query(instruction)
    refs: list[str] = []
    findings: list[str] = []
    failures = 0
    try:
        if url:
            _emit(deps, "info", f"Web Scout fetcht {url}")
            result = await deps.web_research.ingest_url(url, False)
            if not isinstance(result, dict) or not result:
                return AgentStepResult(
                    agent_id=agent_id,
                    output=f"Web Scout mislukt: lege ingest voor {url}.",
                    mode="deterministic",
                    ok=False,
                    error="empty_ingest",
                    metadata={"url": url},
                )
            source_id = str(result.get("source_id") or result.get("id") or "")
            if not source_id:
                return AgentStepResult(
                    agent_id=agent_id,
                    output=f"Web Scout mislukt: ingest zonder source_id voor {url}.",
                    mode="deterministic",
                    ok=False,
                    error="ingest_missing_source_id",
                    metadata={"url": url, "result_keys": sorted(result.keys())},
                )
            if not _ingest_result_verified(result):
                return AgentStepResult(
                    agent_id=agent_id,
                    output=f"Web Scout mislukt: ingest niet geverifieerd voor {url}.",
                    mode="deterministic",
                    ok=False,
                    error="ingest_unverified",
                    metadata={"url": url, "status": result.get("status")},
                )
            refs.append(source_id)
            findings.append(f"Geïngest: {url} → source_id={source_id}")
        else:
            _emit(deps, "info", f"Web Scout discover: {query[:80]}")
            urls = await deps.web_research.discover_duckduckgo(query or instruction, 4)
            if not urls:
                return AgentStepResult(
                    agent_id=agent_id,
                    output=f"Geen webresultaten voor query '{query or instruction}'.",
                    mode="deterministic",
                    ok=False,
                    error="no_discover_results",
                    metadata={"query": query, "urls": []},
                )
            for found in urls[:3]:
                try:
                    ingested = await deps.web_research.ingest_url(found, False)
                    source_id = str((ingested or {}).get("source_id") or (ingested or {}).get("id") or "")
                    if not source_id:
                        failures += 1
                        findings.append(f"{found} → failed: empty_or_missing_source_id")
                        continue
                    if not _ingest_result_verified(ingested):
                        failures += 1
                        findings.append(f"{found} → failed: ingest_unverified")
                        continue
                    refs.append(source_id)
                    findings.append(f"{found} → ok source_id={source_id}")
                except Exception as exc:
                    failures += 1
                    findings.append(f"{found} → failed: {exc}")
            if not refs:
                return AgentStepResult(
                    agent_id=agent_id,
                    output="Web Scout mislukt: geen succesvolle ingest.\n" + "\n".join(findings),
                    mode="deterministic",
                    ok=False,
                    error="all_ingests_failed",
                    metadata={"query": query, "failures": failures},
                )
        output = "Web Scout voltooid.\n" + "\n".join(findings)
        return AgentStepResult(
            agent_id=agent_id,
            output=output,
            mode="deterministic",
            evidence_refs=refs,
            metadata={"query": query, "url": url, "failures": failures},
            ok=True,
        )
    except Exception as exc:
        err = str(exc).lower()
        degraded = any(token in err for token in ("robots", "network", "timeout", "connection", "dns", "refused"))
        return AgentStepResult(
            agent_id=agent_id,
            output=f"Web Scout mislukt: {exc}",
            mode="degraded" if degraded else "deterministic",
            ok=False,
            error=str(exc),
        )


def run_evidence_auditor(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult:
    agent_id = "evidence_auditor"
    entity = None
    lower = (instruction or "").lower()
    for marker in ("entity:", "entiteit:", "symbol:", "ticker:"):
        if marker in lower:
            entity = instruction[lower.index(marker) + len(marker) :].strip().split()[0]
            break
    if not entity:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{1,40}", instruction or "")
        entity = tokens[0] if tokens else None

    contradictions: list[dict[str, Any]] = []
    knowledge_hits: list[dict[str, Any]] = []
    if deps.gen2 is not None:
        try:
            contradictions = list(deps.gen2.find_contradictions(entity) or [])
        except Exception as exc:
            _emit(deps, "warning", f"Evidence Auditor: contradiction scan failed: {exc}")
    if deps.platform_db is not None and instruction:
        try:
            knowledge_hits = list(deps.platform_db.search_knowledge(instruction, limit=6) or [])
        except Exception as exc:
            _emit(deps, "warning", f"Evidence Auditor: knowledge search failed: {exc}")
    elif deps.knowledge is not None and instruction:
        try:
            search = getattr(deps.knowledge, "search", None)
            if callable(search):
                raw = search(instruction, limit=6)
                if isinstance(raw, dict):
                    knowledge_hits = list(raw.get("matches") or raw.get("chunks") or [])
                elif isinstance(raw, list):
                    knowledge_hits = raw
        except Exception as exc:
            _emit(deps, "warning", f"Evidence Auditor: knowledge search failed: {exc}")

    # When an entity is named, only count hits that actually mention it (no false pass on unrelated lexical noise).
    if entity:
        entity_l = entity.lower()
        filtered: list[dict[str, Any]] = []
        for item in knowledge_hits:
            blob = " ".join(
                str(item.get(key) or "")
                for key in ("title", "heading", "content", "snippet", "uri", "source_id", "id")
            ).lower()
            if entity_l in blob:
                filtered.append(item)
        knowledge_hits = filtered

    unsupported: list[str] = []
    if not contradictions and not knowledge_hits:
        unsupported.append("Geen contradiction-edges of knowledge-hits gevonden voor deze scope.")

    missing = [] if knowledge_hits or contradictions else ["Geen steunende passages in lokale store."]
    report = {
        "entity": entity,
        "contradictions": contradictions[:20],
        "knowledge_hit_count": len(knowledge_hits),
        "knowledge_sample": [
            {
                "title": item.get("title") or item.get("heading") or "",
                "source_id": item.get("source_id") or item.get("id"),
                "snippet": str(item.get("content") or item.get("snippet") or "")[:240],
            }
            for item in knowledge_hits[:5]
        ],
        "unsupported_claims": unsupported,
        "missing_evidence": missing,
        "mode": "deterministic_local_audit",
        "passed": bool(knowledge_hits or contradictions) and not unsupported,
    }
    refs = [
        str(item.get("source_id") or item.get("id") or "")
        for item in knowledge_hits
        if item.get("source_id") or item.get("id")
    ]
    # Provenance IDs must be non-empty when present; never claim pass without support.
    refs = [r for r in refs if r]
    passed = bool(report["passed"]) and (bool(refs) or bool(contradictions))
    report["passed"] = passed
    return AgentStepResult(
        agent_id=agent_id,
        output=json.dumps(report, ensure_ascii=False, indent=2),
        mode="deterministic",
        evidence_refs=refs,
        metadata={"entity": entity, "contradiction_count": len(contradictions), "passed": passed},
        ok=passed,
        error=None if passed else "insufficient_evidence",
    )


def _list_installed_plugins(deps: AgentRuntimeDeps) -> list[dict[str, Any]]:
    if deps.platform_db is None:
        return []
    # Do not swallow DB errors as "no plugins" — that becomes a false-empty resolve.
    return list(deps.platform_db.list_plugins() or [])


def _plugin_tools(deps: AgentRuntimeDeps, plugin_id: str) -> list[dict[str, Any]]:
    if deps.platform_db is None:
        return []
    try:
        return list(deps.platform_db.plugin_tools(plugin_id) or [])
    except TypeError:
        return [t for t in (deps.platform_db.plugin_tools() or []) if str(t.get("plugin_id")) == plugin_id]


def _match_plugin(plugins: list[dict[str, Any]], hint: str) -> dict[str, Any] | None:
    hint_l = (hint or "").strip().lower()
    if not hint_l:
        return None
    for plugin in plugins:
        candidates = [
            str(plugin.get("id") or ""),
            str(plugin.get("name") or ""),
            str((plugin.get("manifest") or {}).get("name") or ""),
            str((plugin.get("manifest") or {}).get("id") or ""),
        ]
        for cand in candidates:
            if cand and (cand.lower() == hint_l or hint_l in cand.lower() or cand.lower() in hint_l):
                return plugin
    return None


def _extract_plugin_hint(instruction: str) -> str | None:
    from reasoning.work_intents import extract_plugin_name_hint

    return extract_plugin_name_hint(instruction)


def run_tool_orchestrator(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult | None:
    """Deterministic plugin registry resolve + health.

    Invoke/execute is not handled here (F-02): inventing tool arguments or forging
    user approval would report false success. Returning ``None`` falls through to
    the model + tool-engine path that validates schemas and HITL.
    """
    agent_id = "tool_orchestrator"
    lower = (instruction or "").lower()
    title_l = (deps.step_title or "").lower()
    combined = f"{title_l}\n{lower}"

    wants_resolve = any(
        tok in combined
        for tok in (
            "resolve",
            "zoek",
            "locate",
            "registry",
            "installed",
            "bestaande",
            "geinstalleerde",
            "geïnstalleerde",
            "vind",
        )
    )
    wants_health = any(
        tok in combined
        for tok in (
            "health",
            "availability",
            "beschikbaar",
            "uitvoerbaar",
            "ready",
            "health check",
            "plugin health",
        )
    )
    wants_invoke = any(
        tok in combined
        for tok in (
            "invoke",
            "voer uit",
            "execute",
            "run tool",
            "call tool",
            "run plugin",
            "plugin uitvoeren",
            "echo",
        )
    )
    # Resolve/health-only steps should not also invoke unless explicitly asked.
    if wants_health and not wants_invoke:
        wants_resolve = True
    if wants_resolve and not wants_invoke:
        wants_invoke = False
    elif wants_invoke:
        wants_resolve = True  # execute implies resolve first

    # F-02: never invent arguments or forge user approval for side-effect tools.
    if wants_invoke:
        return None

    plugins = _list_installed_plugins(deps)
    hint = _extract_plugin_hint(instruction) or _extract_plugin_hint(deps.step_title)
    # When instruction prose mentions "plugin registry" etc., prefer a clearer step title.
    if hint and deps.step_title:
        title_hint = _extract_plugin_hint(deps.step_title)
        if title_hint and hint.lower() in {"registry", "workflow", "local", "manager", "runtime"}:
            hint = title_hint
    matched = _match_plugin(plugins, hint or "") if hint else None
    if matched is None and deps.prior_outputs:
        # Prefer plugin_id from prior resolve step.
        for prior in reversed(deps.prior_outputs):
            raw = str(prior.get("output") or "")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                pid = str(parsed.get("plugin_id") or (parsed.get("plugin") or {}).get("id") or "")
                if pid:
                    matched = _match_plugin(plugins, pid) or next(
                        (p for p in plugins if str(p.get("id")) == pid),
                        None,
                    )
                    if matched:
                        break

    if deps.shortlist_tools is None and deps.plugin_manager is None and not plugins:
        return AgentStepResult(
            agent_id=agent_id,
            output="Tool Orchestrator gedegradeerd: shortlist_tools/plugin_manager niet beschikbaar.",
            mode="degraded",
            ok=False,
            error="shortlist_unavailable",
        )

    tools: list[dict[str, Any]] = []
    if deps.shortlist_tools is not None:
        try:
            tools = list(deps.shortlist_tools(instruction, limit=12) or [])
        except TypeError:
            tools = list(deps.shortlist_tools(instruction) or [])
        except Exception as exc:
            return AgentStepResult(
                agent_id=agent_id,
                output=f"Tool Orchestrator shortlist mislukt: {exc}",
                mode="deterministic",
                ok=False,
                error=str(exc),
            )

    # Prefer tools belonging to the matched plugin.
    if matched:
        plugin_tools = _plugin_tools(deps, str(matched.get("id") or ""))
        if plugin_tools:
            tools = plugin_tools + [t for t in tools if str(t.get("plugin_id")) == str(matched.get("id"))]

    denied = {str(x).lower() for x in (deps.settings.get("denied_tools") or [])}
    network = _network_policy(deps)
    eligible: list[dict[str, Any]] = []
    for t in tools:
        plugin_id = str(t.get("plugin_id") or t.get("plugin") or "")
        tool_name = str(t.get("name") or t.get("tool_name") or t.get("id") or "")
        status = str(t.get("status") or t.get("health") or "")
        key = f"{plugin_id}:{tool_name}".lower()
        if key in denied or tool_name.lower() in denied or plugin_id.lower() in denied:
            continue
        if status.lower() in {"blocked", "denied", "disabled"}:
            continue
        perms = [str(p).lower() for p in (t.get("permissions") or t.get("required_permissions") or [])]
        if "network" in perms and network == "block":
            continue
        if matched and plugin_id and plugin_id != str(matched.get("id")):
            continue
        eligible.append(t)

    if wants_resolve and hint and matched is None:
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "resolved": False,
                    "plugin_hint": hint,
                    "error": "plugin_not_found",
                    "installed_plugins": [
                        {"id": p.get("id"), "name": p.get("name"), "status": p.get("status")}
                        for p in plugins[:20]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="deterministic",
            ok=False,
            error="plugin_not_found",
            metadata={"plugin_hint": hint},
        )

    if wants_resolve and not wants_health:
        plugin_id = str((matched or {}).get("id") or "")
        plugin_tools = _plugin_tools(deps, plugin_id) if plugin_id else eligible
        payload = {
            "resolved": True,
            "plugin_id": plugin_id,
            "plugin": {
                "id": (matched or {}).get("id"),
                "name": (matched or {}).get("name"),
                "status": (matched or {}).get("status"),
                "enabled": (matched or {}).get("enabled"),
            },
            "tools": [
                {
                    "plugin_id": t.get("plugin_id") or plugin_id,
                    "tool": t.get("name") or t.get("tool_name") or t.get("id"),
                    "status": t.get("status") or t.get("health"),
                }
                for t in (plugin_tools or eligible)[:12]
            ],
            "note": "Deterministic registry resolve; no plugin created.",
            "llm_budget_consumed": False,
        }
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            mode="deterministic",
            ok=True,
            evidence_refs=[plugin_id] if plugin_id else [],
            metadata={"plugin_id": plugin_id, "phase": "resolve", "llm_budget_consumed": False},
        )

    if wants_health:
        plugin_id = str((matched or {}).get("id") or "")
        status = str((matched or {}).get("status") or "").lower()
        enabled = bool((matched or {}).get("enabled", True))
        plugin_tools = _plugin_tools(deps, plugin_id) if plugin_id else eligible
        ready_tools = [
            t
            for t in (plugin_tools or eligible)
            if str(t.get("status") or t.get("health") or "ready").lower()
            not in {"blocked", "denied", "disabled", "error"}
        ]
        healthy = (
            bool(matched)
            and enabled
            and status in {"", "ready", "ok", "healthy", "enabled"}
            and bool(ready_tools or plugin_tools is not None)
        )
        payload = {
            "health": "ok" if healthy else "unavailable",
            "available": healthy,
            "executable": healthy,
            "plugin_id": plugin_id,
            "plugin": {
                "id": (matched or {}).get("id"),
                "name": (matched or {}).get("name"),
                "status": (matched or {}).get("status"),
                "enabled": enabled,
            },
            "tools": [
                {
                    "plugin_id": t.get("plugin_id") or plugin_id,
                    "tool": t.get("name") or t.get("tool_name") or t.get("id"),
                    "status": t.get("status") or t.get("health"),
                }
                for t in (plugin_tools or eligible)[:12]
            ],
            "note": "Deterministic plugin health/availability check; no LLM.",
            "llm_budget_consumed": False,
        }
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            mode="deterministic",
            ok=healthy,
            error=None if healthy else "plugin_unavailable",
            evidence_refs=[plugin_id] if plugin_id else [],
            metadata={"plugin_id": plugin_id, "phase": "health", "llm_budget_consumed": False},
        )

    plan = {
        "instruction": instruction[:500],
        "plugin_id": (matched or {}).get("id"),
        "eligible_tools": [
            {
                "plugin_id": t.get("plugin_id") or t.get("plugin"),
                "tool": t.get("name") or t.get("tool_name") or t.get("id"),
                "status": t.get("status") or t.get("health"),
                "autonomous": t.get("autonomous_allowed", t.get("autonomous")),
            }
            for t in eligible[:12]
        ],
        "policy": {
            "note": "Invoke uses model+tool-engine (schema + HITL); resolve/health stay deterministic.",
            "network_policy": network,
            "subprocess_policy": deps.settings.get("subprocess_policy"),
        },
        "llm_budget_consumed": False,
        "next_action": "select_and_invoke_via_tool_engine" if eligible else "no_eligible_tools",
    }
    return AgentStepResult(
        agent_id=agent_id,
        output=json.dumps(plan, ensure_ascii=False, indent=2),
        mode="deterministic",
        ok=True,
        tool_log=[],
        metadata={"tool_count": len(eligible), "plugin_id": (matched or {}).get("id"), "llm_budget_consumed": False},
        evidence_refs=[str((matched or {}).get("id") or "")] if matched else [],
    )


def _articles_from_prior(prior_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for prior in prior_outputs:
        raw = str(prior.get("output") or "")
        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        candidates: list[Any] = []
        if isinstance(parsed, dict):
            for key in ("articles", "items", "results", "knowledge_items", "data"):
                val = parsed.get(key)
                if isinstance(val, list):
                    candidates.extend(val)
            invoke = parsed.get("invoke") or parsed.get("tool_output") or {}
            if isinstance(invoke, dict):
                for key in ("articles", "items", "results", "stdout", "output"):
                    val = invoke.get(key)
                    if isinstance(val, list):
                        candidates.extend(val)
                    elif isinstance(val, str) and val.strip():
                        candidates.append({"title": "plugin_output", "content": val})
                result = invoke.get("result")
                if isinstance(result, list):
                    candidates.extend(result)
                elif isinstance(result, dict):
                    nested_list = False
                    for key in ("articles", "items", "results", "data"):
                        nested = result.get(key)
                        if isinstance(nested, list):
                            candidates.extend(nested)
                            nested_list = True
                    if not nested_list:
                        candidates.append(result)
        if not candidates and raw.strip():
            candidates.append({"title": prior.get("title") or "prior_output", "content": raw[:20_000]})
        for item in candidates:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or item.get("headline") or "item")
                content = str(
                    item.get("content")
                    or item.get("body")
                    or item.get("summary")
                    or item.get("text")
                    or json.dumps(item, ensure_ascii=False)
                )
                articles.append(
                    {
                        "title": title[:200],
                        "content": content[:50_000],
                        "uri": str(item.get("uri") or item.get("url") or item.get("link") or ""),
                        "provenance": str(prior.get("step_key") or prior.get("agent_id") or "plugin"),
                    }
                )
            elif isinstance(item, str) and item.strip():
                articles.append(
                    {
                        "title": "item",
                        "content": item[:50_000],
                        "uri": "",
                        "provenance": str(prior.get("step_key") or prior.get("agent_id") or "plugin"),
                    }
                )
    return articles


def run_knowledge_builder(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult:
    """Convert prior tool output into KnowledgeItems and optionally persist+verify."""
    agent_id = "knowledge_builder"
    lower = f"{deps.step_title}\n{instruction}".lower()
    # Guardrail: never accept plugin registry/lookup/execute responsibilities.
    if any(
        tok in lower
        for tok in (
            "resolve existing",
            "zoek de bestaande",
            "plugin registry",
            "installed plugin",
            "voer newsfeeder",
            "execute newsfeeder",
            "invoke plugin",
        )
    ) and not any(tok in lower for tok in ("knowledge", "kennis", "persist", "opslaan", "convert", "omzetten")):
        return AgentStepResult(
            agent_id=agent_id,
            output=(
                "Knowledge Builder weigert plugin lookup/execute. "
                "Gebruik tool_orchestrator voor registry/runtime."
            ),
            mode="blocked",
            ok=False,
            error="wrong_specialist_for_plugin_lookup",
        )

    wants_persist = any(
        tok in lower
        for tok in ("persist", "opslaan", "sla op", "bewaar", "repository", "db insert", "sqlite commit")
    )
    wants_verify = any(
        tok in lower
        for tok in ("verify", "readback", "read back", "verify persistence", "controleer persistence")
    )

    if wants_verify and not wants_persist:
        verified_rows: list[dict[str, Any]] = []
        for prior in deps.prior_outputs:
            raw = str(prior.get("output") or "")
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            for row in parsed.get("persisted") or []:
                if not isinstance(row, dict):
                    continue
                source_id = str(row.get("source_id") or "")
                verified = bool(row.get("verified"))
                chunk_count = int(row.get("chunks") or 0)
                if deps.platform_db is not None and source_id:
                    try:
                        source = deps.platform_db.get_knowledge_source(source_id)
                        chunks = (
                            deps.platform_db.list_knowledge_chunks(source_id, limit=5)
                            if hasattr(deps.platform_db, "list_knowledge_chunks")
                            else []
                        )
                        verified = bool(source) and bool(chunks or chunk_count)
                        chunk_count = len(chunks) if chunks else chunk_count
                    except Exception:
                        verified = False
                verified_rows.append(
                    {
                        "source_id": source_id,
                        "verified": verified,
                        "chunks": chunk_count,
                    }
                )
        ok = bool(verified_rows) and all(row.get("verified") for row in verified_rows)
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "phase": "verify_persistence",
                    "persisted": verified_rows,
                    "verified": ok,
                    "llm_budget_consumed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="deterministic",
            ok=ok,
            error=None if ok else "persistence_not_verified",
            metadata={"phase": "verify_persistence", "llm_budget_consumed": False},
            evidence_refs=[str(row.get("source_id")) for row in verified_rows if row.get("source_id")],
        )

    articles = _articles_from_prior(deps.prior_outputs)
    if not articles:
        # Allow instruction-embedded JSON payload as fallback.
        try:
            embedded = json.loads(instruction)
            if isinstance(embedded, dict):
                articles = _articles_from_prior([{"output": json.dumps(embedded), "title": "instruction"}])
            elif isinstance(embedded, list):
                articles = _articles_from_prior(
                    [{"output": json.dumps({"articles": embedded}), "title": "instruction"}]
                )
        except Exception:
            pass
    if not articles:
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {"knowledge_items": [], "error": "no_prior_plugin_output", "llm_budget_consumed": False},
                ensure_ascii=False,
                indent=2,
            ),
            mode="deterministic",
            ok=False,
            error="no_prior_plugin_output",
        )

    knowledge_items = [
        {
            "title": item["title"],
            "content": item["content"],
            "uri": item.get("uri") or f"plugin://knowledge/{index}",
            "provenance": item.get("provenance"),
        }
        for index, item in enumerate(articles[:50])
    ]

    # Convert-only step returns items; persist/verify steps write or read back.
    convert_only = (not wants_persist and not wants_verify) and any(
        tok in lower for tok in ("convert", "omzetten", "knowledgeitems", "knowledge items", "normaliseer", "samenvat", "normalize")
    )
    if convert_only:
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "knowledge_items": knowledge_items,
                    "persisted": False,
                    "phase": "convert",
                    "llm_budget_consumed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="deterministic",
            ok=True,
            metadata={"item_count": len(knowledge_items), "phase": "convert", "llm_budget_consumed": False},
        )

    if deps.knowledge is None or not hasattr(deps.knowledge, "ingest_text"):
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "knowledge_items": knowledge_items,
                    "error": "knowledge_service_unavailable",
                    "llm_budget_consumed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="degraded",
            ok=False,
            error="knowledge_service_unavailable",
        )

    persisted: list[dict[str, Any]] = []
    for index, item in enumerate(knowledge_items):
        uri = item.get("uri") or f"plugin://knowledge/{index}"
        try:
            result = deps.knowledge.ingest_text(
                title=str(item.get("title") or f"Knowledge item {index + 1}"),
                text=str(item.get("content") or ""),
                source_type="plugin_output",
                uri=str(uri),
                metadata={"provenance": item.get("provenance"), "role": "knowledge"},
            )
            source_id = str(result.get("id") or result.get("source_id") or "")
            # Deterministic readback verification — never ignore ingest verification_failed.
            verified = False
            chunk_count = int(result.get("chunks") or 0)
            if not _ingest_result_verified(result):
                verified = False
            elif deps.platform_db is not None and source_id:
                try:
                    source = deps.platform_db.get_knowledge_source(source_id)
                    chunks = deps.platform_db.list_knowledge_chunks(source_id, limit=5) if hasattr(deps.platform_db, "list_knowledge_chunks") else []
                    verified = bool(source) and (chunk_count > 0 or bool(chunks))
                    if chunks and not chunk_count:
                        chunk_count = len(chunks)
                except Exception:
                    verified = bool(source_id) and chunk_count > 0
            else:
                verified = bool(source_id) and chunk_count > 0
            persisted.append(
                {
                    "source_id": source_id,
                    "title": item.get("title"),
                    "chunks": chunk_count,
                    "verified": verified,
                    "uri": uri,
                    "status": result.get("status"),
                }
            )
        except Exception as exc:
            persisted.append({"title": item.get("title"), "error": str(exc), "verified": False})

    ok = bool(persisted) and all(row.get("verified") for row in persisted)
    return AgentStepResult(
        agent_id=agent_id,
        output=json.dumps(
            {
                "knowledge_items": knowledge_items,
                "persisted": persisted,
                "phase": "persist" if wants_persist and not wants_verify else "persist_verify",
                "ok": ok,
                "llm_budget_consumed": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        mode="deterministic",
        ok=ok,
        error=None if ok else "persist_or_verify_failed",
        evidence_refs=[str(row.get("source_id")) for row in persisted if row.get("source_id")],
        metadata={
            "item_count": len(knowledge_items),
            "persisted_count": len(persisted),
            "llm_budget_consumed": False,
        },
    )


def run_trading_specialist(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult:
    agent_id = "trading_specialist"
    if deps.paper_trading is None:
        return AgentStepResult(
            agent_id=agent_id,
            output="Trading Specialist gedegradeerd: PaperTradingService niet beschikbaar.",
            mode="degraded",
            ok=False,
            error="paper_trading_unavailable",
        )
    # Hard guard: no live broker symbols/APIs are wired into this specialist.
    live_markers = ("live broker", "real money", "binance live", "broker api", "live trading")
    if any(marker in (instruction or "").lower() for marker in live_markers):
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "mode": "PAPER_ONLY",
                    "blocked": True,
                    "reason": "Live broker routing bestaat niet in HADES; verzoek geweigerd.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="blocked",
            ok=False,
            error="live_broker_not_implemented",
        )

    state = deps.paper_trading.state()
    settings = state.get("settings") or {}
    if not settings.get("enabled"):
        summary = {
            "mode": "PAPER_ONLY",
            "enabled": False,
            "note": "Paper trading is uitgeschakeld. Geen live broker-pad bestaat in HADES.",
            "instruction": instruction[:300],
        }
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(summary, ensure_ascii=False, indent=2),
            mode="degraded",
            ok=False,
            error="paper_trading_disabled",
            metadata={"paper_enabled": False},
        )

    if settings.get("kill_switch"):
        return AgentStepResult(
            agent_id=agent_id,
            output=json.dumps(
                {
                    "mode": "PAPER_ONLY",
                    "kill_switch": True,
                    "note": "Kill switch actief: geen nieuwe PAPER-orders; status mag wel gelezen worden.",
                    "wallets": state.get("wallets") or [],
                    "open_positions": len(state.get("positions") or []),
                },
                ensure_ascii=False,
                indent=2,
            ),
            mode="blocked",
            ok=False,
            error="kill_switch_armed",
            metadata={"paper_enabled": True, "kill_switch": True},
        )

    bot_info: dict[str, Any] = {}
    if deps.trading_bot is not None:
        try:
            list_strategies = getattr(deps.trading_bot, "list_strategies", None)
            if callable(list_strategies):
                bot_info["strategies"] = list_strategies()[:10]
            dashboard = getattr(deps.trading_bot, "dashboard", None)
            if callable(dashboard):
                bot_info["dashboard"] = dashboard()
        except Exception as exc:
            bot_info["error"] = str(exc)

    summary = {
        "mode": "PAPER_ONLY",
        "wallets": state.get("wallets") or [],
        "open_positions": len(state.get("positions") or []),
        "recent_orders": (state.get("orders") or [])[:5],
        "kill_switch": bool(settings.get("kill_switch")),
        "bot": bot_info,
        "instruction": instruction[:400],
        "note": "Geen echte orders; uitsluitend lokale PAPER-simulatie.",
        "live_broker": False,
    }
    return AgentStepResult(
        agent_id=agent_id,
        output=json.dumps(summary, ensure_ascii=False, indent=2),
        mode="deterministic",
        ok=True,
        metadata={"paper_enabled": True, "positions": len(state.get("positions") or []), "live_broker": False},
    )


def run_voice_specialist(instruction: str, deps: AgentRuntimeDeps) -> AgentStepResult:
    agent_id = "voice_specialist"
    from voice_tasks import transcript_to_task

    lower = (instruction or "").lower()
    wants_status = any(k in lower for k in ("status", "doctor", "health", "setup", "installatie"))
    if wants_status:
        try:
            from voice.install import doctor

            report = doctor(deps.settings)
            ready = bool(report.get("ready"))
            # Never claim voice ready when ASR/TTS are not operational; no cloud fallback.
            if report.get("cloud_fallback") or report.get("allow_cloud"):
                return AgentStepResult(
                    agent_id=agent_id,
                    output=json.dumps(
                        {"doctor": report, "mode": "voice_host_status", "cloud_fallback": "blocked"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    mode="blocked",
                    ok=False,
                    error="cloud_fallback_forbidden",
                    metadata={"kind": "doctor", "ready": False},
                )
            return AgentStepResult(
                agent_id=agent_id,
                output=json.dumps(
                    {
                        "doctor": report,
                        "mode": "voice_host_status",
                        "voice_ready": ready,
                        "cloud_fallback": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                mode="deterministic" if ready else "degraded",
                ok=ready,
                error=None if ready else "voice_providers_not_ready",
                metadata={"kind": "doctor", "ready": ready},
            )
        except Exception as exc:
            return AgentStepResult(
                agent_id=agent_id,
                output=f"Voice doctor niet beschikbaar: {exc}",
                mode="degraded",
                ok=False,
                error=str(exc),
            )

    # Default: treat instruction as transcript → structured task proposal (local only).
    draft = transcript_to_task(instruction, default_agent="auto")
    return AgentStepResult(
        agent_id=agent_id,
        output=json.dumps(
            {
                "task_draft": draft,
                "mode": "transcript_to_task",
                "cloud_fallback": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        mode="deterministic",
        ok=True,
        metadata={"kind": "transcript_to_task", "agent": draft.get("agent")},
        evidence_refs=[],
    )


HANDLERS: dict[str, Any] = {
    "web_scout": run_web_scout,
    "evidence_auditor": run_evidence_auditor,
    "tool_orchestrator": run_tool_orchestrator,
    "knowledge_builder": run_knowledge_builder,
    "trading_specialist": run_trading_specialist,
    "voice_specialist": run_voice_specialist,
}


async def try_run_agent_step(
    agent_id: str,
    instruction: str,
    *,
    deps: AgentRuntimeDeps,
) -> AgentStepResult | None:
    """Execute a specialist runtime when one exists. Async-safe for web_scout.

    Handlers may return ``None`` to fall through to the model+tool-engine path
    (used when a deterministic path would otherwise invent arguments/approvals).
    Sync specialists run via ``asyncio.to_thread`` so they never block the loop (F-05).
    """
    import asyncio

    handler = HANDLERS.get(agent_id)
    if handler is None:
        return None
    if agent_id == "web_scout":
        return await run_web_scout(instruction, deps)
    # Sync handler — offload so plugin/knowledge I/O cannot stall the event loop.
    result = await asyncio.to_thread(handler, instruction, deps)
    if result is None:
        return None
    if hasattr(result, "__await__"):
        return await result
    return result



