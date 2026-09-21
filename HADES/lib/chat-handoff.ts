/** One-shot Dashboard → Chat/Coding handoff (sessionStorage). */

export const PENDING_CHAT_DRAFT_KEY = "hades-pending-chat-draft";
export const PENDING_CHAT_HANDOFF_KEY = "hades-pending-chat-handoff";
export const PENDING_CODING_GOAL_KEY = "hades-pending-coding-goal";
export const PENDING_CODING_OMNI_KEY = "hades-pending-coding-omniroute";

export type DashboardRouteId = "lokaal" | "omniroute" | "auto";
export type ResolvedDashboardRoute = "lokaal" | "omniroute";

export type ChatHandoffPayload = {
  draft?: string;
  autoSend?: boolean;
  route?: DashboardRouteId;
  resolvedRoute?: ResolvedDashboardRoute;
  conversationId?: string;
};

export function writePendingChatDraft(draft: string): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(PENDING_CHAT_DRAFT_KEY, draft);
}

export function writeChatHandoff(payload: ChatHandoffPayload): void {
  if (typeof sessionStorage === "undefined") return;
  if (payload.draft != null) {
    sessionStorage.setItem(PENDING_CHAT_DRAFT_KEY, payload.draft);
  }
  sessionStorage.setItem(PENDING_CHAT_HANDOFF_KEY, JSON.stringify(payload));
}

/** Consume one-shot chat handoff. Safe to call once after conversation load. */
export function consumeChatHandoff(): ChatHandoffPayload | null {
  if (typeof sessionStorage === "undefined") return null;
  const rawMeta = sessionStorage.getItem(PENDING_CHAT_HANDOFF_KEY);
  const draft = sessionStorage.getItem(PENDING_CHAT_DRAFT_KEY);
  sessionStorage.removeItem(PENDING_CHAT_HANDOFF_KEY);
  sessionStorage.removeItem(PENDING_CHAT_DRAFT_KEY);
  if (!rawMeta && draft == null) return null;
  if (!rawMeta) return { draft: draft || "", autoSend: false };
  try {
    const parsed = JSON.parse(rawMeta) as ChatHandoffPayload;
    return {
      ...parsed,
      draft: parsed.draft ?? draft ?? "",
    };
  } catch {
    return { draft: draft || "", autoSend: false };
  }
}

export function writeCodingHandoff(goal: string, useOmniroute: boolean): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(PENDING_CODING_GOAL_KEY, goal);
  sessionStorage.setItem(PENDING_CODING_OMNI_KEY, useOmniroute ? "1" : "0");
}

export function consumeCodingHandoff(): { goal: string; useOmniroute: boolean } | null {
  if (typeof sessionStorage === "undefined") return null;
  const goal = sessionStorage.getItem(PENDING_CODING_GOAL_KEY);
  const omni = sessionStorage.getItem(PENDING_CODING_OMNI_KEY);
  sessionStorage.removeItem(PENDING_CODING_GOAL_KEY);
  sessionStorage.removeItem(PENDING_CODING_OMNI_KEY);
  if (goal == null) return null;
  return { goal, useOmniroute: omni === "1" };
}

export function resolveDashboardRoute(opts: {
  selected: DashboardRouteId;
  omniUsable: boolean;
  lmConnected: boolean;
}): ResolvedDashboardRoute {
  if (opts.selected === "lokaal") return "lokaal";
  if (opts.selected === "omniroute") {
    if (!opts.omniUsable) {
      throw new Error("OmniRoute is niet beschikbaar.");
    }
    return "omniroute";
  }
  // Auto: prefer local when LM is connected; otherwise OmniRoute when usable.
  if (opts.lmConnected) return "lokaal";
  if (opts.omniUsable) return "omniroute";
  return "lokaal";
}
