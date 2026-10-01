import { describe, expect, it } from "vitest";
import { TRADING_LEGACY_REDIRECTS, resolveTradingRedirect } from "./workspaces/workspaceConfig";

describe("TradingLegacyRedirect map", () => {
  it("redirects former four workspaces into the three-page IA", () => {
    expect(resolveTradingRedirect("/trading/command-hub")).toBe("/trading/agents");
    expect(resolveTradingRedirect("/trading/trading-desk")).toBe("/trading/live-agents");
    expect(resolveTradingRedirect("/trading/strategy-lab")).toBe("/trading/research");
    expect(resolveTradingRedirect("/trading/market-data")).toContain("/trading/research");
  });

  it("preserves section/drawer query intent for legacy deep links", () => {
    expect(TRADING_LEGACY_REDIRECTS["/trading/portefeuille"]).toContain("section=portfolio");
    expect(TRADING_LEGACY_REDIRECTS["/trading/control-room"]).toContain("drawer=control-room");
    expect(TRADING_LEGACY_REDIRECTS["/trading/broker"]).toContain("section=broker-boundary");
    expect(TRADING_LEGACY_REDIRECTS["/trading/marktdata"]).toContain("section=market-data");
    expect(TRADING_LEGACY_REDIRECTS["/trading/onderzoek"]).toContain("section=research-command");
  });
});
