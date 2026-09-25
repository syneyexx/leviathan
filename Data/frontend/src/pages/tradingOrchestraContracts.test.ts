import { describe, expect, it } from "vitest";
import type { TradeOrchestra, TradingDecision } from "../types/api";
import { AGENT_KINDS } from "./agents/helpers";
import {
  autonomyLabel,
  decisionOneLiner,
  liveTradingLabel,
  paperCapitalLabel,
  paperPnlLabel,
  parseUniverse,
  readinessLabel,
  universeLabel,
} from "./agents/tradingHelpers";
import { MAIN_MENU } from "../navigation/menu";

function orchestra(partial: Partial<TradeOrchestra> = {}): TradeOrchestra {
  return {
    orchestraId: "agent_x",
    name: "Desk",
    description: "",
    enabled: true,
    archived: false,
    health: "idle",
    role: "trade_orchestra",
    mandate: {
      universe: ["BTCUSD"],
      paperCapital: 50000,
      maxGrossExposurePct: 100,
      maxSymbolExposurePct: 25,
      perTradeRiskPct: 1,
      maxOrdersPerDay: 20,
      maxDrawdownPct: 20,
      allowedOrderTypes: ["MARKET"],
      allowedFamilies: ["equity", "crypto_spot"],
      autonomyLevel: "A0",
      readinessCeiling: "A4",
      decisionCadence: "daily_close",
      maxModelCallsPerMission: 24,
      maxTokensPerMission: 24000,
      cannotEnableLive: true,
    },
    mandateFingerprint: "abc",
    readiness: { state: "UNMEASURED", reason: "no sealed evaluation recorded" },
    autonomyLevel: "A0",
    decisionStats: { byStage: {}, total: 0, riskRejections: 0, lastDecisionAt: null },
    lastMissionId: null,
    lastRunAt: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    memberAgentIds: [],
    truth: { paper_only: true, live_trading: "BLOCKED" },
    ...partial,
  };
}

describe("G66 — trading cards render only backend truth", () => {
  it("exposes the trading agent kind in the editor kinds", () => {
    expect(AGENT_KINDS).toContain("trading");
  });

  it("renders UNMEASURED readiness as-is and never infers MEASURED", () => {
    expect(readinessLabel(orchestra())).toBe("UNMEASURED");
    expect(readinessLabel(orchestra({ readiness: { state: "MEASURED" } }))).toBe("Gemeten");
    expect(readinessLabel(orchestra({ decisionStats: { byStage: { fill: 3 }, total: 3, riskRejections: 0, lastDecisionAt: null } }))).toBe(
      "UNMEASURED",
    );
  });

  it("never shows a PnL number without fill records and labels paper capital as paper", () => {
    expect(paperPnlLabel(orchestra().decisionStats)).toBe("UNMEASURED (geen fills)");
    expect(paperPnlLabel({ byStage: { fill: 2 }, total: 2, riskRejections: 0, lastDecisionAt: null })).toContain("fills");
    expect(paperCapitalLabel(orchestra().mandate)).toContain("(paper)");
    expect(paperCapitalLabel({ paperCapital: Number.NaN })).toBe("—");
  });

  it("only reports live trading as blocked when backend truth AND mandate agree", () => {
    expect(liveTradingLabel(orchestra())).toBe("Geblokkeerd");
    expect(liveTradingLabel(orchestra({ truth: {} }))).toBe("ONBEKEND");
  });

  it("has no live autonomy level and falls back to UNMEASURED", () => {
    expect(autonomyLabel("A4")).toBe("A4 · Autonoom paper");
    expect(autonomyLabel("A5")).toBe("A5");
    expect(autonomyLabel("")).toBe("UNMEASURED");
    expect(Object.keys(autonomyLabel).length).toBe(0);
  });

  it("formats decisions from payload fields only", () => {
    const risk: TradingDecision = {
      decisionId: "d1",
      orchestraId: "o",
      missionId: null,
      agentId: "a",
      role: "risk_officer",
      stage: "risk_decision",
      asOf: "2024-01-01T00:00:00+00:00",
      payload: { allowed: false, side: "HOLD", sizedQty: 0, reason: "max orders/day" },
      parentDecisionId: null,
      modelId: null,
      promptArtifactId: null,
      outputArtifactId: null,
      mandateFingerprint: "abc",
      createdAt: "2024-01-01T00:00:00+00:00",
    };
    expect(decisionOneLiner(risk)).toContain("GEWEIGERD");
    expect(decisionOneLiner(risk)).toContain("max orders/day");
    expect(decisionOneLiner({ ...risk, stage: "order_intent", payload: { side: "BUY", qty: 1.5, instrument: "BTCUSD", status: "recorded_not_routed" } })).toContain(
      "recorded_not_routed",
    );
  });

  it("parses universes and labels empty ones truthfully", () => {
    expect(parseUniverse("btcusd, ethusd  solusd")).toEqual(["BTCUSD", "ETHUSD", "SOLUSD"]);
    expect(universeLabel({ universe: [] })).toContain("leeg");
  });

  it("registers the Onderzoek page under TradingCenter", () => {
    const trading = MAIN_MENU.find((m) => m.id === "trading");
    expect(trading?.submenu?.some((s) => s.to === "/trading/onderzoek")).toBe(true);
  });
});
