export type HostStateName =
  | "STOPPED"
  | "PREFLIGHT"
  | "STARTING"
  | "RUNNING"
  | "DEGRADED"
  | "STOPPING"
  | "FAILED"
  | "ATTACHED_EXTERNAL";

export type OwnershipKind = "NONE" | "OWNED" | "EXTERNAL";

export interface PreflightCheck {
  id: string;
  status: string;
  detail: string;
  remediation: string;
}

export interface HostSnapshot {
  state: HostStateName | string;
  ownership: OwnershipKind;
  safeModeArmed: boolean;
  safeModeActive: boolean;
  pid: number | null;
  exitCode: number | null;
  cleanShutdown: boolean | null;
  message: string;
  apiBase: string | null;
  frontendUrl: string | null;
  version: string;
  installRoot: string;
  preflight: {
    ok: boolean;
    checks: PreflightCheck[];
    host: string;
    port: number;
    pythonVersion: string | null;
    nativeStatus: string | null;
    workersExpected: boolean;
    envCreated: boolean;
  };
  startedAt: string | null;
  pythonVersion: string | null;
  supervisorHealth: string | null;
  workersExpected: boolean;
  exitWhenStopped: boolean;
}

export interface ConsoleLine {
  seq: number;
  at: string;
  source: string;
  level: string;
  stream: string;
  text: string;
  pid?: number | null;
}

export interface ControlGate {
  enabled: boolean;
  reason: string;
}
