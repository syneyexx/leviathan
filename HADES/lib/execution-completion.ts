export type CompletionKind = "incomplete" | "unverified" | "ok";

export type CompletionAssessment = {
  kind: CompletionKind;
  message: string;
  criticBlocked?: boolean;
};

const INCOMPLETE_STATUSES = new Set(["partial", "failed", "cancelled", "blocked"]);

export function isIncompleteStatus(status?: string | null): boolean {
  if (!status) return false;
  return INCOMPLETE_STATUSES.has(status.toLowerCase());
}

export function verificationWasExpected(input: {
  route?: Record<string, unknown> | null;
  executed_route?: Record<string, unknown> | null;
  reasoning_profile?: string | null;
}): boolean {
  if (input.route?.require_verification === true) return true;
  const notes = Array.isArray(input.executed_route?.notes)
    ? (input.executed_route?.notes as string[])
    : [];
  if (notes.some((note) => note.startsWith("verification:"))) return true;
  return false;
}

export function criticBlockedCompletion(notes?: string[] | null): boolean {
  return (notes || []).some((note) => /^verification:failed/i.test(String(note)));
}

export function checklistHasUnmet(checklist?: Array<Record<string, unknown>> | null): boolean {
  return (checklist || []).some((row) => row && row.met === false);
}

export function assessChatCompletion(input: {
  status?: string | null;
  verification_called?: boolean;
  route?: Record<string, unknown> | null;
  executed_route?: Record<string, unknown> | null;
  reasoning_profile?: string | null;
  verification_notes?: string[] | null;
  acceptance_checklist?: Array<Record<string, unknown>> | null;
}): CompletionAssessment | null {
  const status = String(input.status || "").toLowerCase();
  const notes = [
    ...(Array.isArray(input.verification_notes) ? input.verification_notes : []),
    ...(Array.isArray(input.executed_route?.notes) ? (input.executed_route?.notes as string[]) : []),
  ];
  const unmetChecklist = checklistHasUnmet(input.acceptance_checklist);
  if (
    criticBlockedCompletion(notes)
    || unmetChecklist
    || (status === "partial" && notes.some((n) => n.startsWith("verification:failed")))
  ) {
    return {
      kind: "incomplete",
      message: unmetChecklist
        ? "Acceptatiecriteria niet gehaald — voltooiing geblokkeerd"
        : "Critic blokkeerde voltooiing — zie verificatienotities",
      criticBlocked: true,
    };
  }
  if (isIncompleteStatus(status)) {
    return {
      kind: "incomplete",
      message: "Niet voltooid — zie tools/verificatie/fout",
    };
  }
  if (
    status === "completed"
    && verificationWasExpected(input)
    && !input.verification_called
  ) {
    return {
      kind: "unverified",
      message: "Voltooid zonder verificatie — controleer tools en acceptatiecriteria",
    };
  }
  return null;
}

export function assessTaskCompletion(input: {
  status?: string | null;
  error?: string | null;
  checkpointPhase?: string | null;
  acceptance_checklist?: Array<Record<string, unknown>> | null;
}): CompletionAssessment | null {
  const status = String(input.status || "").toLowerCase();
  const unmet = checklistHasUnmet(input.acceptance_checklist);
  if (status === "failed" || status === "cancelled" || unmet) {
    const critic = String(input.checkpointPhase || "").includes("verification_failed") || unmet;
    return {
      kind: "incomplete",
      message: critic
        ? unmet
          ? "Acceptatiecriteria niet gehaald — checkpoint behouden voor hervatten"
          : "Critic blokkeerde voltooiing — checkpoint behouden voor hervatten"
        : "Niet voltooid — zie tools/verificatie/fout",
      criticBlocked: critic,
    };
  }
  return null;
}

export function mentionsSelfCorrection(text: string): boolean {
  const lower = text.toLowerCase();
  return /\b(replan|herplan|retry|opnieuw uitvoer|herstel|self-correct|correctie)\b/.test(lower);
}

export function selfCorrectionNotes(notes?: string[] | null): string[] {
  return (notes || []).filter((note) => /replan|herplan|correct|retry|verification:failed/i.test(String(note)));
}
