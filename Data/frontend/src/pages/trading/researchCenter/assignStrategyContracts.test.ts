import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pagePath = resolve(__dirname, "ResearchCenterPage.tsx");
const viewPath = resolve(__dirname, "ResearchCenterView.tsx");
const deployDrawerPath = resolve(__dirname, "../workspaces/tradingDesk/TradingDeskDrawers.tsx");

describe("Research Centrum strategy → agent assignment", () => {
  const page = readFileSync(pagePath, "utf8");
  const view = readFileSync(viewPath, "utf8");
  const drawer = readFileSync(deployDrawerPath, "utf8");

  it("wires Toewijzen aan agent to DeployPaperDrawer (not a bare Link)", () => {
    expect(view).toContain("onAssignToAgent");
    expect(view).toContain("Toewijzen aan agent");
    expect(view).not.toMatch(/Toewijzen aan agent[\s\S]{0,80}to=\{`\/trading\/agents/);
    expect(page).toContain("DeployPaperDrawer");
    expect(page).toContain("showAssign");
    expect(page).toContain("initialStrategyId");
    expect(page).toContain("/trading/live-agents");
  });

  it("DeployPaperDrawer persists assignment provenance via qualificationRefs", () => {
    expect(drawer).toContain("qualificationRefs");
    expect(drawer).toContain("assignedVia");
    expect(drawer).toContain("createPaperDeployment");
    expect(drawer).toContain("paperOnly");
    expect(drawer).toContain("LIVE MONEY blijft BLOCKED");
  });

  it("does not claim live-money execution on assign", () => {
    expect(drawer).toContain("PAPER");
    expect(drawer.toLowerCase()).not.toMatch(/live money.*enabled|live trading.*enabled/);
  });
});
