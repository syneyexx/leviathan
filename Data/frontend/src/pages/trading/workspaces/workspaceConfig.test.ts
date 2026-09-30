import { describe, expect, it } from "vitest";
import {
  TRADING_LEGACY_REDIRECTS,
  TRADING_WORKSPACES,
  getTradingWorkspace,
  resolveWorkspaceSurface,
} from "./workspaceConfig";

describe("Trading Center WAVE 1 workspace config", () => {
  it("exposes exactly four workspaces", () => {
    expect(TRADING_WORKSPACES).toHaveLength(4);
    expect(TRADING_WORKSPACES.map((w) => w.id)).toEqual([
      "command_hub",
      "strategy_lab",
      "trading_desk",
      "market_data",
    ]);
  });

  it("keeps unique routes under /trading/*", () => {
    const routes = TRADING_WORKSPACES.map((w) => w.route);
    expect(new Set(routes).size).toBe(4);
    expect(routes.every((r) => r.startsWith("/trading/"))).toBe(true);
  });

  it("maps every legacy trading route into a workspace surface", () => {
    const legacy = [
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
    for (const path of legacy) {
      expect(TRADING_LEGACY_REDIRECTS[path]).toBeTruthy();
      expect(TRADING_LEGACY_REDIRECTS[path].startsWith("/trading/")).toBe(true);
    }
  });

  it("resolves surface query with workspace default fallback", () => {
    const hub = getTradingWorkspace("command_hub");
    expect(resolveWorkspaceSurface(hub, null).id).toBe("overview");
    const lab = getTradingWorkspace("strategy_lab");
    expect(resolveWorkspaceSurface(lab, null).id).toBe("lab");
    expect(resolveWorkspaceSurface(lab, "simulation").id).toBe("simulation");
    expect(resolveWorkspaceSurface(lab, "missing").id).toBe("lab");
  });

  it("tags surfaces with progressive disclosure levels", () => {
    for (const ws of TRADING_WORKSPACES) {
      expect(ws.surfaces.length).toBeGreaterThan(0);
      expect(ws.surfaces.every((s) => ["PRIMARY", "SECONDARY", "ADVANCED"].includes(s.level))).toBe(
        true,
      );
    }
  });
});
