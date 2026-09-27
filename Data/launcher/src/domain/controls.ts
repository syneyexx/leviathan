import type { ControlGate, HostSnapshot } from "../types/host";

const OWNED_LIVE = new Set(["STARTING", "RUNNING", "DEGRADED"]);

export function controlGates(host: HostSnapshot, frontendReachable: boolean | null): Record<string, ControlGate> {
  const state = host.state;
  const owned = host.ownership === "OWNED";
  const external = host.ownership === "EXTERNAL" || state === "ATTACHED_EXTERNAL";
  const starting = state === "STARTING" || state === "PREFLIGHT" || state === "STOPPING";
  return {
    start: {
      enabled: !external && !starting && state !== "RUNNING" && state !== "DEGRADED",
      reason: external
        ? "An external instance is already attached. Start will not create a second control plane."
        : starting
          ? `Start is unavailable while the host is ${state}.`
          : state === "RUNNING" || state === "DEGRADED"
            ? "Leviathan is already running under this host."
            : "Start the canonical leviathan.py process.",
    },
    stop: {
      enabled: owned && (OWNED_LIVE.has(state) || (state === "FAILED" && host.pid != null)),
      reason: external
        ? "Stop is disabled for an external instance."
        : owned
          ? "Request a graceful shutdown of the owned process tree."
          : "This host does not own a backend process.",
    },
    restart: {
      enabled: owned && (state === "RUNNING" || state === "DEGRADED" || state === "FAILED"),
      reason: external
        ? "Restart is disabled while attached to an external instance."
        : "Graceful stop, verified stop, then a fresh preflight and start.",
    },
    safeMode: {
      enabled: !starting,
      reason: host.safeModeActive
        ? "Safe Mode is active for the owned process. It is a process-local API-only profile."
        : "Arm Safe Mode for the next start. This does not rewrite .env.",
    },
    frontend: {
      enabled: Boolean(host.frontendUrl) && frontendReachable === true,
      reason:
        frontendReachable === true
          ? "Open the configured loopback frontend in the system browser."
          : frontendReachable === false
            ? "The configured frontend URL is not reachable."
            : "Frontend reachability is UNMEASURED until /api/health responds.",
    },
    emergency: {
      enabled: owned && host.pid != null && state !== "STOPPED",
      reason: external
        ? "Emergency shutdown cannot target an external instance."
        : owned
          ? "Force-terminate only the process tree owned by this host."
          : "No owned process tree is available.",
    },
  };
}

export function hostStatusLabel(host: HostSnapshot): { title: string; detail: string } {
  switch (host.state) {
    case "RUNNING":
      return { title: "Backend Host Active", detail: host.safeModeActive ? "SAFE MODE" : "Owned runtime is healthy" };
    case "DEGRADED":
      return { title: "Backend Host Degraded", detail: host.message };
    case "STARTING":
    case "PREFLIGHT":
      return { title: "Backend Host Starting", detail: host.message };
    case "STOPPING":
      return { title: "Backend Host Stopping", detail: host.message };
    case "FAILED":
      return { title: "Backend Host Failed", detail: host.message };
    case "ATTACHED_EXTERNAL":
      return { title: "External Instance", detail: "Monitoring only. Destructive controls are guarded." };
    default:
      return { title: "Backend Host Stopped", detail: host.message || "No owned backend process." };
  }
}
