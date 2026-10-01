import { describe, expect, it } from "vitest";
import {
  TRADING_LEGACY_REDIRECTS,
  TRADING_WORKSPACES,
  getTradingWorkspace,
  resolveTradingRedirect,
  resolveWorkspaceSurface,
} from "./workspaceConfig";

describe("Trading Center 3-page workspace config", () => {
  it("exposes exactly three primary workspaces", () => {
    expect(TRADING_WORKSPACES).toHaveLength(3);
    expect(TRADING_WORKSPACES.map((w) => w.id)).toEqual([
      "agent_overview",
      "live_agents",
      "research_center",
    ]);
  });

  it("keeps unique canonical routes under /trading/*", () => {
    const routes = TRADING_WORKSPACES.map((w) => w.route);
    expect(new Set(routes).size).toBe(3);
    expect(routes).toEqual(["/trading/agents", "/trading/live-agents", "/trading/research"]);
  });

  it("maps former four workspaces and legacy nine routes", () => {
    const required = [
      "/trading/command-hub",
      "/trading/trading-desk",
      "/trading/strategy-lab",
      "/trading/market-data",
      "/trading/simulatie",
      "/trading/strategieen",
      "/trading/marktdata",
      "/trading/portefeuille",
      "/trading/paper",
      "/trading/broker",
      "/trading/onderzoek",
      "/trading/lab",
      "/trading/control-room",
    ];
    for (const path of required) {
      expect(TRADING_LEGACY_REDIRECTS[path]).toBeTruthy();
      expect(TRADING_LEGACY_REDIRECTS[path].startsWith("/trading/")).toBe(true);
    }
    expect(resolveTradingRedirect("/trading/command-hub")).toBe("/trading/agents");
    expect(resolveTradingRedirect("/trading/trading-desk")).toBe("/trading/live-agents");
    expect(resolveTradingRedirect("/trading/strategy-lab")).toBe("/trading/research");
    expect(resolveTradingRedirect("/trading/market-data")).toBe(
      "/trading/research?section=market-data",
    );
    expect(resolveTradingRedirect("/trading/portefeuille")).toBe(
      "/trading/agents?section=portfolio",
    );
    expect(resolveTradingRedirect("/trading/control-room")).toBe(
      "/trading/agents?drawer=control-room",
    );
  });

  it("resolves surface query with workspace default fallback", () => {
    const agents = getTradingWorkspace("agent_overview");
    expect(resolveWorkspaceSurface(agents, null).id).toBe("overview");
    const live = getTradingWorkspace("live_agents");
    expect(resolveWorkspaceSurface(live, "missing").id).toBe("live");
    const research = getTradingWorkspace("research_center");
    expect(resolveWorkspaceSurface(research, null).id).toBe("research");
  });

  it("keeps exactly one PRIMARY surface per native workspace", () => {
    for (const ws of TRADING_WORKSPACES) {
      expect(ws.surfaces).toHaveLength(1);
      expect(ws.surfaces[0]?.level).toBe("PRIMARY");
    }
  });
});
