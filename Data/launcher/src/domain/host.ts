import type { HostSnapshot } from "../types/host";

export function stoppedSnapshot(): HostSnapshot {
  return {
    state: "STOPPED",
    ownership: "NONE",
    safeModeArmed: false,
    safeModeActive: false,
    pid: null,
    exitCode: null,
    cleanShutdown: null,
    message: "Backend host is stopped.",
    apiBase: null,
    frontendUrl: null,
    version: "0.1.0",
    installRoot: "",
    preflight: {
      ok: false,
      checks: [],
      host: "127.0.0.1",
      port: 8765,
      pythonVersion: null,
      nativeStatus: null,
      workersExpected: true,
      envCreated: false,
    },
    startedAt: null,
    pythonVersion: null,
    supervisorHealth: null,
    workersExpected: true,
    exitWhenStopped: false,
    systemReadiness: "UNMEASURED",
  };
}

export const FIXTURE_MODE =
  import.meta.env.MODE === "fixture" && import.meta.env.VITE_LEVIATHAN_VISUAL_FIXTURE === "1";

export function isHostSnapshot(value: unknown): value is HostSnapshot {
  if (!value || typeof value !== "object") return false;
  const snap = value as Partial<HostSnapshot>;
  return typeof snap.state === "string" && typeof snap.ownership === "string" && typeof snap.message === "string";
}

/** Immediate visible state for operator commands. The invoke result replaces this. */
export function optimisticCommand(host: HostSnapshot, command: string): HostSnapshot | null {
  if (command === "host_start" || command === "host_restart") {
    return { ...host, state: "PREFLIGHT", message: "Running preflight." };
  }
  if (command === "host_stop" || command === "host_emergency" || command === "host_confirm_close") {
    return { ...host, state: "STOPPING", message: "Stopping the owned backend." };
  }
  return null;
}
