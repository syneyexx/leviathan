/**
 * Truthful mutation outcome contract for Datasets workspace.
 * Callers must not toast "success" for blocked / noop / failed outcomes.
 */

export type MutationOutcome =
  | { kind: "completed"; message: string }
  | { kind: "started"; message: string; jobId?: string }
  | { kind: "blocked"; message: string }
  | { kind: "cancelled"; message: string }
  | { kind: "failed"; message: string }
  | { kind: "noop"; message?: string }
  | { kind: "partial"; message: string; succeeded: number; failed: number };

export type MutationToastKind = "success" | "info" | "warn" | "error" | "none";

/** Map outcome → toast severity. Only completed/started/partial-with-successes are success. */
export function mutationToastKind(outcome: MutationOutcome): MutationToastKind {
  switch (outcome.kind) {
    case "completed":
    case "started":
      return "success";
    case "partial":
      return outcome.succeeded > 0 ? "success" : "error";
    case "blocked":
    case "noop":
      return "info";
    case "cancelled":
      return "warn";
    case "failed":
      return "error";
    default:
      return "none";
  }
}

export function mutationToastMessage(outcome: MutationOutcome): string | null {
  if (outcome.kind === "noop" && !outcome.message) return null;
  return outcome.message ?? null;
}

/** Whether the UI should treat this as an operator-visible success toast. */
export function isSuccessOutcome(outcome: MutationOutcome): boolean {
  return mutationToastKind(outcome) === "success";
}

export function outcomeFromBulk(result: {
  succeeded: number;
  failed: number;
  message: string;
}): MutationOutcome {
  if (result.succeeded === 0 && result.failed === 0) {
    return { kind: "noop", message: result.message };
  }
  if (result.failed === 0) {
    return { kind: "started", message: result.message };
  }
  if (result.succeeded === 0) {
    return { kind: "failed", message: result.message };
  }
  return {
    kind: "partial",
    message: result.message,
    succeeded: result.succeeded,
    failed: result.failed,
  };
}

export function startedJob(message: string, jobId?: string): MutationOutcome {
  return { kind: "started", message, jobId };
}

export function completed(message: string): MutationOutcome {
  return { kind: "completed", message };
}

export function blocked(message: string): MutationOutcome {
  return { kind: "blocked", message };
}

export function failed(message: string): MutationOutcome {
  return { kind: "failed", message };
}

export function noop(message?: string): MutationOutcome {
  return { kind: "noop", message };
}
