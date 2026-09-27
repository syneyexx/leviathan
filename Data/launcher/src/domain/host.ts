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
  };
}

export const FIXTURE_MODE =
  import.meta.env.MODE === "fixture" && import.meta.env.VITE_LEVIATHAN_VISUAL_FIXTURE === "1";
