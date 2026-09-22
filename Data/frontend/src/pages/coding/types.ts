import type {
  CodingMission,
  CodingSessionStatus,
} from "../../types/api";

export type { CodingMission, CodingSessionStatus };
export type {
  CodingStatusResponse,
  CodingSession,
  CodingSessionDetail,
  CodingStep,
  CodingPatch,
  CodingVerification,
  CodingNeuroSnapshot,
} from "../../types/api";

export type CodingWorkspaceEntry = {
  path: string;
  type: "file" | "dir";
  size?: number;
  mark?: "M" | "A" | null;
};

export const MISSION_CHIPS: Array<{ mission: CodingMission; label: string; seed: string }> = [
  {
    mission: "SCAFFOLD",
    label: "Scaffold project",
    seed: "Scaffold a minimal project structure with tests and a README.",
  },
  {
    mission: "REVIEW",
    label: "Review diff",
    seed: "Review the current workspace changes and critique risky edits.",
  },
  {
    mission: "TEST",
    label: "Write tests",
    seed: "Write and run tests for the code related to this goal.",
  },
  {
    mission: "FIX",
    label: "Fix bug",
    seed: "Reproduce the bug, patch the failing code, and re-run tests.",
  },
];

export function codingEmptySessionsCopy(count: number): string | null {
  return count === 0 ? "NO CODING SESSIONS" : null;
}

export function statusPillClass(status: CodingSessionStatus | null | undefined): string {
  if (!status) return "is-idle";
  if (status === "RUNNING") return "";
  if (status === "WAITING_APPROVAL") return "is-wait";
  if (status === "FAILED" || status === "CANCELLED" || status === "DISABLED") return "is-fail";
  return "is-idle";
}

export function statusPillLabel(status: CodingSessionStatus | null | undefined): string {
  if (!status) return "Agent Idle";
  if (status === "RUNNING") return "Agent Running";
  if (status === "WAITING_APPROVAL") return "Awaiting Approval";
  if (status === "COMPLETED") return "Completed";
  if (status === "UNVERIFIED") return "Unverified";
  if (status === "FAILED") return "Failed";
  if (status === "CANCELLED") return "Cancelled";
  if (status === "DISABLED") return "Disabled";
  return status;
}
