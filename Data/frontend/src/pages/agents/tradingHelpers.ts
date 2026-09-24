import type { TradeOrchestra, TradingDecision, TradingMandate } from "../../types/api";

/** UI labels (Dutch) for the readiness ladder. A5/live never exists. */
export const AUTONOMY_LABELS: Record<string, string> = {
  A0: "A0 · Gym",
  A1: "A1 · Validatie",
  A2: "A2 · Sealed run",
  A3: "A3 · Schaduw-paper",
  A4: "A4 · Autonoom paper",
};

export const TRADING_MISSION_KINDS = [
  { kind: "deliberation_round", label: "Deliberatieronde" },
  { kind: "news_digest", label: "Nieuwsdigest" },
  { kind: "post_mortem", label: "Post-mortem" },
] as const;

export const STAGE_LABELS: Record<string, string> = {
  proposal: "Voorstel",
  critique: "Kritiek",
  risk_decision: "Risicobesluit",
  order_intent: "Paper-intent",
  fill: "Fill",
  post_mortem: "Post-mortem",
  digest: "Nieuwsdigest",
};

export function autonomyLabel(level: string | null | undefined): string {
  const key = String(level || "").toUpperCase();
  return AUTONOMY_LABELS[key] ?? (key ? key : "UNMEASURED");
}

/** Readiness is rendered exactly as the backend reports it; never inferred client-side. */
export function readinessLabel(orchestra: Pick<TradeOrchestra, "readiness">): string {
  const state = String(orchestra.readiness?.state || "UNMEASURED");
  return state === "MEASURED" ? "Gemeten" : "UNMEASURED";
}

export function readinessReason(orchestra: Pick<TradeOrchestra, "readiness">): string {
  return String(orchestra.readiness?.reason || "");
}

/** Paper capital is a mandate limit, never a PnL claim. */
export function paperCapitalLabel(mandate: Pick<TradingMandate, "paperCapital">): string {
  const value = Number(mandate.paperCapital);
  if (!Number.isFinite(value)) return "—";
  return `${value.toLocaleString("nl-NL", { maximumFractionDigits: 0 })} (paper)`;
}

/** PnL is only shown when the backend has fill records; otherwise UNMEASURED. */
export function paperPnlLabel(stats: TradeOrchestra["decisionStats"] | null | undefined): string {
  const fills = Number(stats?.byStage?.fill ?? 0);
  return fills > 0 ? "zie beslissingen (fills)" : "UNMEASURED (geen fills)";
}

export function liveTradingLabel(orchestra: Pick<TradeOrchestra, "truth" | "mandate">): string {
  const truth = String(orchestra.truth?.live_trading ?? "");
  if (truth === "BLOCKED" && orchestra.mandate?.cannotEnableLive === true) return "Geblokkeerd";
  return "ONBEKEND";
}

export function universeLabel(mandate: Pick<TradingMandate, "universe">): string {
  const list = Array.isArray(mandate.universe) ? mandate.universe : [];
  return list.length ? list.join(", ") : "— (leeg: geen deliberatie mogelijk)";
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function decisionOneLiner(decision: TradingDecision): string {
  const p = decision.payload ?? {};
  switch (decision.stage) {
    case "proposal":
      return `${String(p.instrument ?? "?")} · ${String(p.direction ?? "?")} · conf ${fmtNum(p.confidence)} · ${String(p.source ?? "")}`;
    case "critique":
      return `${String(p.verdict ?? "?")} · Δconf ${fmtNum(p.confidenceAdjustment)} · ${String(p.source ?? "")}`;
    case "risk_decision":
      return `${p.allowed ? "TOEGESTAAN" : "GEWEIGERD"} · ${String(p.side ?? "")} ${fmtNum(p.sizedQty)} · ${String(p.reason ?? "")}`;
    case "order_intent":
      return `${String(p.side ?? "HOLD")} ${fmtNum(p.qty)} ${String(p.instrument ?? "")} · ${String(p.status ?? "")} · venue ${String(p.venue ?? "paper")}`;
    case "digest":
      return p.signalId
        ? `${String(p.direction ?? "")} ${String(p.eventType ?? "")} → ${(p.instruments as string[] | undefined)?.join(",") ?? ""}`
        : String(p.status ?? "");
    case "post_mortem":
      return String(p.claim ?? p.status ?? "");
    default:
      return JSON.stringify(p).slice(0, 120);
  }
}

function fmtNum(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

export function parseUniverse(text: string): string[] {
  return text
    .split(/[,\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}
