import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AgentFleetSummary, HealthResponse } from "../types/api";

export type ShellSystemState = "online" | "degraded" | "offline" | "unknown";

export type ShellStatus = {
  systemState: ShellSystemState;
  systemLabel: string;
  agentsActive: number | null;
  agentsLabel: string;
  llmAvailable: boolean | null;
  llmLabel: string;
  approvalsPending: number | null;
  jobsQueued: number | null;
  health: HealthResponse | null;
  fleet: AgentFleetSummary | null;
  error: string | null;
};

function resolveSystemState(health: HealthResponse | null, errored: boolean): ShellSystemState {
  if (errored || health == null) return "offline";
  if (!health.ok) return "degraded";
  const llmOk = health.llm?.available !== false;
  const dbOk = !health.database || health.database === "ok" || health.database === "ready";
  if (!llmOk || !dbOk) return "degraded";
  return "online";
}

function resolveAgentsActive(fleet: AgentFleetSummary | null, health: HealthResponse | null): number | null {
  if (fleet) {
    if (typeof fleet.active === "number") return fleet.active;
    if (typeof fleet.busy === "number") return fleet.busy;
    if (typeof fleet.agentCount === "number") return fleet.agentCount;
    if (typeof fleet.agents === "number") return fleet.agents;
  }
  if (health?.agents?.enabled === false) return 0;
  return null;
}

/**
 * Live shell chrome status — health + agent fleet summary.
 * Never invents green/online state when the backend is unreachable.
 */
export function useShellStatus(opts?: { enabled?: boolean; intervalMs?: number }): ShellStatus {
  const enabled = opts?.enabled ?? true;
  const intervalMs = opts?.intervalMs ?? 8_000;
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [fleet, setFleet] = useState<AgentFleetSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const pull = useCallback(async () => {
    if (inFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    inFlight.current = true;
    try {
      const [healthRes, fleetRes] = await Promise.allSettled([
        api.health(),
        api.getAgentFleetSummary(),
      ]);
      if (!mounted.current) return;

      let nextHealth: HealthResponse | null = null;
      let nextFleet: AgentFleetSummary | null = null;
      const errors: string[] = [];

      if (healthRes.status === "fulfilled") {
        nextHealth = healthRes.value;
      } else {
        errors.push(healthRes.reason instanceof Error ? healthRes.reason.message : "Health unavailable");
      }

      if (fleetRes.status === "fulfilled") {
        nextFleet = fleetRes.value.summary;
      } else {
        errors.push(fleetRes.reason instanceof Error ? fleetRes.reason.message : "Agents unavailable");
      }

      setHealth(nextHealth);
      setFleet(nextFleet);
      setError(errors.length && !nextHealth ? errors[0] : null);
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return;
    void pull();
    const id = window.setInterval(() => {
      void pull();
    }, intervalMs);
    const onVis = () => {
      if (document.visibilityState === "visible") void pull();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [enabled, intervalMs, pull]);

  const systemState = resolveSystemState(health, Boolean(error) && health == null);
  const agentsActive = resolveAgentsActive(fleet, health);
  const llmAvailable = health ? Boolean(health.llm?.available) : null;
  const approvalsPending = health?.approvals?.pending ?? null;
  const jobsQueued = health?.jobs?.queued ?? null;

  const systemLabel =
    systemState === "online"
      ? "Systems Online"
      : systemState === "degraded"
        ? "Systems Degraded"
        : systemState === "offline"
          ? "Systems Offline"
          : "Systems Unknown";

  const agentsLabel =
    agentsActive == null
      ? health?.agents?.enabled === false
        ? "Agents Disabled"
        : "Agents —"
      : `${agentsActive} Agent${agentsActive === 1 ? "" : "s"} Active`;

  const llmLabel =
    llmAvailable == null
      ? "LLM —"
      : llmAvailable
        ? health?.llm?.model
          ? `LLM ${health.llm.model}`
          : "LLM Ready"
        : "LLM Offline";

  return {
    systemState,
    systemLabel,
    agentsActive,
    agentsLabel,
    llmAvailable,
    llmLabel,
    approvalsPending,
    jobsQueued,
    health,
    fleet,
    error,
  };
}
