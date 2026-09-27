import type { BridgeState, ControlGate, HostSnapshot } from "../types/host";

const OWNED_LIVE = new Set(["STARTING", "RUNNING", "DEGRADED"]);

export function controlGates(
  host: HostSnapshot,
  frontendReachable: boolean | null,
  bridge: BridgeState = "READY",
): Record<string, ControlGate> {
  const state = host.state;
  const owned = host.ownership === "OWNED";
  const external = host.ownership === "EXTERNAL" || state === "ATTACHED_EXTERNAL";
  const starting = state === "STARTING" || state === "PREFLIGHT" || state === "STOPPING";
  const linked = bridge === "READY";
  const bridgeReason =
    bridge === "FAILED"
      ? "HOST BRIDGE FAILURE. Start stays disabled until the Tauri host shell answers."
      : "Host bridge is connecting. Operator commands are not live yet.";
  return {
    start: {
      enabled: linked && !external && !starting && state !== "RUNNING" && state !== "DEGRADED",
      reason: !linked
        ? bridgeReason
        : external
          ? "An external instance is already attached. Start will not create a second control plane."
          : starting
            ? `Start is unavailable while the host is ${state}.`
            : state === "RUNNING" || state === "DEGRADED"
              ? "Leviathan is already running under this host."
              : "Start the canonical leviathan.py process.",
    },
    stop: {
      enabled: linked && owned && (OWNED_LIVE.has(state) || (state === "FAILED" && host.pid != null)),
      reason: !linked
        ? bridgeReason
        : external
          ? "Stop is disabled for an external instance."
          : owned
            ? "Request a graceful shutdown of the owned process tree."
            : "This host does not own a backend process.",
    },
    restart: {
      enabled: linked && owned && (state === "RUNNING" || state === "DEGRADED" || state === "FAILED"),
      reason: !linked
        ? bridgeReason
        : external
          ? "Restart is disabled while attached to an external instance."
          : "Graceful stop, verified stop, then a fresh preflight and start.",
    },
    safeMode: {
      enabled: linked && !starting,
      reason: !linked
        ? bridgeReason
        : host.safeModeActive
          ? "Safe Mode is active for the owned process. It is a process-local API-only profile."
          : "Arm Safe Mode for the next start. This does not rewrite .env.",
    },
    frontend: {
      enabled: linked && Boolean(host.frontendUrl) && frontendReachable === true,
      reason: !linked
        ? bridgeReason
        : frontendReachable === true
          ? "Open the configured loopback frontend in the system browser."
          : frontendReachable === false
            ? "The configured frontend URL is not reachable."
            : "Frontend reachability is UNMEASURED until /api/health responds.",
    },
    emergency: {
      enabled: linked && owned && host.pid != null && state !== "STOPPED",
      reason: !linked
        ? bridgeReason
        : external
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
