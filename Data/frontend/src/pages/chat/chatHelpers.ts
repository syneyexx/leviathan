/**
 * Chat conversation date grouping — Dutch locale labels.
 */

import type { Conversation } from "../../types/api";

export type ConversationGroupId = "today" | "yesterday" | "week" | "older";

export type ConversationGroup = {
  id: ConversationGroupId;
  label: string;
  items: Conversation[];
};

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function groupConversationsByDate(
  conversations: Conversation[],
  now: Date = new Date(),
): ConversationGroup[] {
  const today = startOfDay(now);
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;

  const buckets: Record<ConversationGroupId, Conversation[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };

  for (const item of conversations) {
    const ts = Date.parse(item.updated_at || item.created_at);
    if (!Number.isFinite(ts)) {
      buckets.older.push(item);
      continue;
    }
    const day = startOfDay(new Date(ts));
    if (day >= today) buckets.today.push(item);
    else if (day >= yesterday) buckets.yesterday.push(item);
    else if (day >= weekAgo) buckets.week.push(item);
    else buckets.older.push(item);
  }

  const labels: Record<ConversationGroupId, string> = {
    today: "Vandaag",
    yesterday: "Gisteren",
    week: "Vorige 7 dagen",
    older: "Ouder",
  };

  return (["today", "yesterday", "week", "older"] as const)
    .filter((id) => buckets[id].length > 0)
    .map((id) => ({ id, label: labels[id], items: buckets[id] }));
}

export function formatConversationTime(value: string | null | undefined, now = new Date()): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const day = startOfDay(date);
  const today = startOfDay(now);
  const time = date.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  if (day >= today) return time;
  if (day >= today - 86_400_000) return time;
  // Within the last 7 days: weekday + time (e.g. "zo 19:34")
  if (day >= today - 7 * 86_400_000) {
    const weekday = date.toLocaleDateString("nl-NL", { weekday: "short" });
    return `${weekday} ${time}`;
  }
  return date.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

export function formatMessageTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
}

/** Format parameter counts for model cards (e.g. 14B). */
export function formatModelParams(n: number | null | undefined): string | null {
  if (n == null || !Number.isFinite(n) || n <= 0) return null;
  if (n >= 1e9) {
    const v = n / 1e9;
    return `${Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)}B`;
  }
  if (n >= 1e6) {
    const v = n / 1e6;
    return `${Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)}B`;
  }
  if (n >= 1e3) {
    const v = n / 1e3;
    return `${Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)}K`;
  }
  return String(n);
}

/** @deprecated Prefer formatModelParams — kept as a thin alias. */
export function formatParamCount(n: number | null | undefined): string | null {
  return formatModelParams(n);
}

export function formatTokenCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "UNMEASURED";
  if (n >= 1000) {
    const k = n / 1000;
    return `${k >= 10 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}K tokens`;
  }
  return `${Math.round(n)} tokens`;
}

export type CapabilityKind = "web" | "rag" | "python" | "data" | "vision" | "other";

export function classifyCapability(cap: {
  id: string;
  name?: string;
  description?: string;
}): CapabilityKind {
  const blob = `${cap.id} ${cap.name ?? ""} ${cap.description ?? ""}`.toLowerCase();
  if (/(vision|image|multimodal|vlm)/.test(blob)) return "vision";
  if (/(web|search|browser|http)/.test(blob)) return "web";
  if (/(rag|knowledge|retriev|embed)/.test(blob)) return "rag";
  if (/(python|code|interpreter|coding|sandbox)/.test(blob)) return "python";
  if (/(data|sql|analy|csv|dataset)/.test(blob)) return "data";
  return "other";
}

export function isCapabilityActive(cap: {
  enabled?: boolean;
  available?: boolean;
}): boolean {
  if (cap.available === false) return false;
  if (cap.enabled === false) return false;
  return true;
}
