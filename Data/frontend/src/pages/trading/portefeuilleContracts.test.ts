import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const deskDrawerPath = resolve(__dirname, "workspaces/tradingDesk/TradingDeskDrawers.tsx");
const deskHookPath = resolve(__dirname, "workspaces/tradingDesk/useTradingDeskData.ts");
const agentPagePath = resolve(__dirname, "agentOverview/AgentOverviewPage.tsx");
const clientPath = resolve(__dirname, "../../api/client.ts");
const typesPath = resolve(__dirname, "../../types/api.ts");

describe("Portefeuille capabilities absorbed by Agent Overzicht", () => {
  const drawers = readFileSync(deskDrawerPath, "utf8");
  const hook = readFileSync(deskHookPath, "utf8");
  const agentPage = readFileSync(agentPagePath, "utf8");
  const client = readFileSync(clientPath, "utf8");
  const types = readFileSync(typesPath, "utf8");

  it("Agent Overzicht opens portfolio advanced controls (no separate page route)", () => {
    expect(agentPage).toContain("CreatePortfolioDrawer");
    expect(agentPage).toContain("AdvancedDrawer");
    expect(agentPage).toContain('section === "portfolio"');
    expect(agentPage).not.toContain("PortefeuillePage");
  });

  it("wires real portfolio API methods instead of hardcoded screenshot equity", () => {
    expect(client).toContain("portfolioDashboard");
    expect(client).toContain("createPortfolio");
    expect(client).toContain("closeSelectedPortfolioPositions");
    expect(hook).toContain("createPortfolio");
    expect(hook).toContain("exportPortfolio");
    expect(hook).toContain("rebalancePreview");
    expect(drawers).not.toContain("1428351");
    expect(drawers).not.toContain("1,428,351");
  });

  it("declares typed dashboard models", () => {
    expect(types).toContain("export type PaperPortfolio");
    expect(types).toContain("export type PortfolioDashboard");
    expect(types).toContain("export type PortfolioRecommendation");
  });

  it("exposes create / lifecycle / rebalance / export controls via desk drawers", () => {
    expect(drawers).toContain("Create wallet");
    expect(drawers).toMatch(/PAPER|paper/);
    expect(hook).toContain("lifecycle");
    expect(hook).toContain("saveAllocations");
    expect(hook).toContain("exportPortfolio");
  });
});
