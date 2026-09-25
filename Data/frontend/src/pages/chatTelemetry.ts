import type {
  AssistantAgentDelegationTelemetry,
  AssistantToolCallTelemetry,
  AssistantTurnTelemetry,
  AssistantWebSourceTelemetry,
  ChatResponse,
  CognitionRunStatus,
} from "../types/api";

/** Derive real turn telemetry from a ChatResponse — never invent values. */
export function deriveAssistantTelemetry(data: ChatResponse): AssistantTurnTelemetry {
  const fromPayload = data.assistant_telemetry;
  const cog = (data.cognition && typeof data.cognition === "object"
    ? data.cognition
    : null) as CognitionRunStatus | null;

  if (fromPayload && typeof fromPayload === "object") {
    return {
      ...fromPayload,
      model: fromPayload.model ?? data.model ?? null,
      knowledge_hits:
        fromPayload.knowledge_hits ?? data.knowledge_sources?.length ?? 0,
      memory_hits:
        fromPayload.memory_hits ?? data.memory_sources?.length ?? 0,
      tool_calls: mergeToolCalls(fromPayload.tool_calls, cog?.tool_calls, fromPayload.tools_invoked),
      agent_delegations: mergeDelegations(
        fromPayload.agent_delegations,
        cog?.agent_delegations,
        fromPayload.agents,
        fromPayload.gi_specialists,
      ),
      web_sources: mergeWebSources(fromPayload.web_sources, cog?.web_sources),
      context_used: fromPayload.context_used ?? fromPayload.context_tokens ?? cog?.context_used ?? null,
      behavior_version:
        fromPayload.behavior_version ?? cog?.behavior_profile_version ?? null,
      truth: {
        telemetry_is_backend_backed: true,
        no_fabricated_brain_percent: true,
        no_hidden_cot: true,
        no_mock_tools_or_agents: true,
        ...(fromPayload.truth || {}),
      },
    };
  }

  const hits = cog?.retrieval_hits || {};
  const tools = list(cog?.tools_invoked);
  const agents = list(cog?.active_agents).filter(Boolean) as string[];
  const gi = list(cog?.gi_specialists);
  const behavior = data.behavior && typeof data.behavior === "object" ? data.behavior : null;

  return {
    model: data.model ?? null,
    behavior_hash:
      (cog?.behavior_hash as string | null | undefined) ??
      (typeof behavior?.settings_hash === "string" ? behavior.settings_hash : null) ??
      (typeof behavior?.hash === "string" ? behavior.hash : null),
    behavior_profile_id:
      (cog?.behavior_profile_id as string | null | undefined) ??
      (typeof behavior?.profile_id === "string" ? behavior.profile_id : null) ??
      (typeof behavior?.id === "string" ? behavior.id : null),
    behavior_version:
      cog?.behavior_profile_version ??
      (typeof behavior?.version === "string" ? behavior.version : null),
    context_budget: cog?.context_budget ?? null,
    context_used: cog?.context_used ?? null,
    context_tokens: cog?.context_used ?? cog?.context_budget ?? null,
    brain_hits: numberOr(hits.brain, hits.knowledge, data.knowledge_sources?.length),
    knowledge_hits: numberOr(hits.knowledge, data.knowledge_sources?.length),
    memory_hits: numberOr(hits.memory, data.memory_sources?.length),
    evidence_hits: numberOr(hits.evidence, 0),
    tools_invoked: tools,
    tool_calls: mergeToolCalls(undefined, cog?.tool_calls, tools),
    agents,
    agent_delegations: mergeDelegations(undefined, cog?.agent_delegations, agents, gi),
    gi_specialists: gi,
    web_sources: mergeWebSources(undefined, cog?.web_sources),
    verification_mode: cog?.verification_mode ?? null,
    verification_passed: cog?.verification_passed ?? null,
    factuality: cog?.factuality ?? null,
    execution_class: cog?.execution_class ?? null,
    cognition_mode: cog?.mode ?? null,
    cognition_status: cog?.status ?? null,
    latency_ms: cog?.latency_ms ?? null,
    usage: cog?.usage ?? null,
    budgets: cog?.budgets ?? null,
    web_used: tools.some((t) => t === "web.search" || t === "web.fetch"),
    truth: {
      telemetry_is_backend_backed: true,
      no_fabricated_brain_percent: true,
      no_hidden_cot: true,
      no_mock_tools_or_agents: true,
    },
  };
}

function mergeToolCalls(
  primary?: AssistantToolCallTelemetry[] | null,
  secondary?: AssistantToolCallTelemetry[] | null,
  fallbackIds?: string[] | null,
): AssistantToolCallTelemetry[] {
  const rows = [...(primary || []), ...(secondary || [])];
  if (rows.length) {
    const seen = new Set<string>();
    return rows.filter((row) => {
      const key = `${row.capability_id}:${row.receipt_id || row.status}`;
      if (!row.capability_id || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  return list(fallbackIds).map((id) => ({
    capability_id: id,
    status: "INVOKED",
    success: null,
    duration_ms: null,
    receipt_id: null,
  }));
}

function mergeDelegations(
  primary?: AssistantAgentDelegationTelemetry[] | null,
  secondary?: AssistantAgentDelegationTelemetry[] | null,
  agents?: string[] | null,
  gi?: string[] | null,
): AssistantAgentDelegationTelemetry[] {
  const rows = [...(primary || []), ...(secondary || [])];
  if (rows.length) {
    const seen = new Set<string>();
    return rows.filter((row) => {
      const key = `${row.agent_kind}:${row.status}`;
      if (!row.agent_kind || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  return Array.from(new Set([...(agents || []), ...(gi || [])])).map((id) => ({
    agent_kind: id,
    status: "SELECTED",
    success: null,
    summary: null,
  }));
}

function mergeWebSources(
  primary?: AssistantWebSourceTelemetry[] | null,
  secondary?: AssistantWebSourceTelemetry[] | null,
): AssistantWebSourceTelemetry[] {
  return [...(primary || []), ...(secondary || [])].slice(0, 20);
}

function list(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "")).filter(Boolean);
}

function numberOr(...candidates: Array<number | null | undefined>): number {
  for (const c of candidates) {
    if (typeof c === "number" && Number.isFinite(c)) return c;
  }
  return 0;
}

export type DiagnosticStripItem = { label: string; value: string };

/** Optional factual self-diagnostic strip — measured fields only. */
export function buildDiagnosticStrip(tel: AssistantTurnTelemetry | null): DiagnosticStripItem[] {
  if (!tel) return [];
  const items: DiagnosticStripItem[] = [];
  if (tel.execution_class) items.push({ label: "mode", value: String(tel.execution_class) });
  else if (tel.cognition_mode) items.push({ label: "mode", value: String(tel.cognition_mode) });
  if (tel.model) items.push({ label: "model", value: String(tel.model) });
  items.push({
    label: "brain",
    value: `${tel.brain_hits ?? 0} hit${(tel.brain_hits ?? 0) === 1 ? "" : "s"}`,
  });
  const webCount = tel.web_sources?.length ?? 0;
  items.push({
    label: "web",
    value: webCount ? `${webCount} source${webCount === 1 ? "" : "s"}` : tel.web_used ? "used" : "idle",
  });
  const tools = tel.tool_calls?.length ?? tel.tools_invoked?.length ?? 0;
  items.push({ label: "tools", value: tools ? String(tools) : "none" });
  const agents =
    (tel.agent_delegations?.length ?? 0) ||
    (tel.agents?.length ?? 0) + (tel.gi_specialists?.length ?? 0);
  items.push({ label: "agents", value: agents ? String(agents) : "none" });
  if (tel.verification_mode || tel.verification_passed != null) {
    const mode = tel.verification_mode || "check";
    const pass =
      tel.verification_passed === true
        ? "pass"
        : tel.verification_passed === false
          ? "fail"
          : "pending";
    items.push({ label: "verification", value: `${mode}/${pass}` });
  }
  if (tel.context_budget != null || tel.context_used != null || tel.context_tokens != null) {
    items.push({
      label: "context",
      value: `${tel.context_used ?? tel.context_tokens ?? "—"}/${tel.context_budget ?? "—"}`,
    });
  }
  if (tel.latency_ms != null) {
    items.push({ label: "latency", value: `${Math.round(tel.latency_ms)}ms` });
  }
  if (tel.behavior_version) {
    items.push({ label: "behavior", value: `v${tel.behavior_version}` });
  } else if (tel.behavior_hash) {
    items.push({ label: "behavior", value: String(tel.behavior_hash).slice(0, 10) });
  }
  return items;
}
